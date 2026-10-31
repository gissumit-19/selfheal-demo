# Self-healing CI/CD: a real demo (GitHub Actions, Jenkins, Argo CD, Airflow)

> **Learners:** click **Use this template > Create a new repository** (make it **Public**), clone your copy, and
> follow **[docs/LEARNER_GUIDE.md](docs/LEARNER_GUIDE.md)**. **Trainers:** see [docs/TRAINER_NOTES.md](docs/TRAINER_NOTES.md).
>
> Tested end to end on macOS (Apple Silicon, Docker Desktop) with GPT-5.5 against live GitHub Actions, Jenkins LTS,
> Argo CD (stable) and Airflow 3.3: Labs A, B, C and C2. Claude support uses the same loop. Windows/WSL and Linux follow
> the same steps but have not been rehearsed yet.

This is the real version of the Module 6 labs. Nothing here is mocked. The agent reads and acts on
**live systems** through their REST APIs:

| System | Runs where | What the agent reads | What it can do (only via the guard) |
|---|---|---|---|
| **GitHub Actions** | github.com (your repo) | failed runs, jobs, failed steps, job logs, commits | re-run failed jobs, open issues |
| **Jenkins** | Docker (JCasC, job `traffic-api-ci`) | failed builds, stages, console log, parameters | rebuild with the same parameters |
| **Argo CD** | kind cluster `heal-demo` | app health/sync, revision, deploy history | roll back to the previous history entry |
| **Airflow 3** | Docker (`traffic_probe_daily`) | failed DAG runs, task instances, task logs | clear failed tasks (scheduler re-runs them) |
| **traffic-api** | kind, deployed by Argo CD from your repo | live smoke probe (error rate, p95) | none |

The model is **Claude** (`claude-opus-5-5`, Anthropic SDK) or **OpenAI GPT** (`gpt-5.5`, OpenAI Responses API).
Set one key; `LLM_PROVIDER=anthropic|openai` picks one if you have both. If there is no key, the agent fails. It
never switches to a scripted mock. `OPENAI_API_STYLE=chat` + `OPENAI_BASE_URL` also works with Azure OpenAI and
OpenAI-compatible servers.

**What is still staged:** the *failures* are caused on purpose (`scenarios.py`). Each one happens for
real: a bad commit is pushed and deployed, a test times out, a DAG task gets HTTP 500s. One more thing
is staged: the flaky test is deliberately slow on the first attempt and fast on a re-run, so it fails
the same way in every class.

## How it works

```
detect (all systems) -> recall memory -> investigate (Claude + read-only tools) -> propose ONE action
     -> guard (runbook.yaml allow-list, params, attempt limit, LIVE preconditions) -> approval (medium risk)
     -> execute (one API call) -> validate (poll the real system) -> fixed? learn : back to guard -> escalate
```

- **The model proposes, code decides.** `heal/policy.py` re-checks every precondition against the
  real system: GitHub's own `run_attempt`, the commit's changed files, the live service probe, Argo CD
  history, the Airflow run state. If a system can't be reached, the precondition can't be checked, and
  the action is **denied**.
- **The runbook is data:** `heal/runbook.yaml`. Teams edit YAML, not Python.
- **Cross-system root cause:** the detector order puts the deploy monitor first. A bad deploy is
  rolled back *before* the Jenkins smoke failure and the Airflow failure it caused. When the guard
  then checks those two, the dependency is healthy again, so a rebuild or clear is allowed.
- **Safety:** dry run by default (`--execute` to act). Secrets are redacted and logs are cut to the
  tail before the model sees them. Logs are treated as untrusted data. Attempt limits are per incident.
  Processed incidents are never handled twice. Memory is SQLite (`runtime/heal.db`) and the audit
  trail is `runtime/audit.jsonl`.

## Setup

**Learners: follow [docs/LEARNER_GUIDE.md](docs/LEARNER_GUIDE.md)** (macOS, Linux, Windows/WSL2; step-by-step with
expected output, the labs, troubleshooting). Trainers: [docs/TRAINER_NOTES.md](docs/TRAINER_NOTES.md).

Short version:
```bash
cp .env.example .env                 # ANTHROPIC_API_KEY or OPENAI_API_KEY, GITHUB_REPO, JENKINS_TOKEN
python -m venv .venv                 # macOS/Linux: python3
. .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
gh repo create <you>/selfheal-demo --public --source . --push   # after git init + first commit
python infra/preflight.py                 # checks tools, Docker memory, ports, keys, repo; changes nothing
python infra/up.py                        # kind + Argo CD + Jenkins + Airflow (only the kind-heal-demo context)
python scenarios.py bootstrap && python -m heal doctor
```

UIs: Argo CD https://localhost:30443 · Jenkins http://localhost:8081 · Airflow http://localhost:8082 ·
traffic-api http://localhost:30080/healthz

## The demos

Run a scenario, wait for the failures to show up in the UIs, then run the agent. Do a dry run first,
then `--execute`.

```bash
python -m heal scan               # dry run: investigates, shows the guard verdicts, changes nothing
python -m heal scan --execute     # acts; asks you before medium-risk actions (AUTO_APPROVE=yes|no for unattended)
```

| Scenario | What really happens | Expected agent outcome |
|---|---|---|
| `python scenarios.py flaky` | docs-only commit; GitHub `ci` (flaky on) and Jenkins (`SCENARIO=flaky`) fail on `test_eta_cache_refresh` TimeoutError | **auto re-run** (RB-GHA-01) and **auto rebuild** (RB-JEN-01). Validated green by polling GitHub/Jenkins. |
| `python scenarios.py code-bug` | branch `demo/units-bug` changes `to_mps()`; `test_to_mps` fails | **escalate** to the commit author. The guard also refuses a re-run, because the commit changed code. Opens a GitHub issue. |
| `python scenarios.py bad-deploy` | pushes 1.1.0 with a real paging bug in `bulk_get`. Unit tests pass, Argo CD deploys it, then every 120-segment request returns HTTP 500. The Airflow `publish_traffic_api` task and the Jenkins smoke stage fail. | 1) deploy incident: **rollback needs approval** (RB-ARGO-01), validated by the live probe, plus a follow-up issue to revert the git commit. 2) Jenkins: **rebuild** (service healthy again). 3) Airflow: **clear failed task**, validated `success`. |
| run `bad-deploy` and answer **n** | same | everything **escalates**. With the dependency still broken, the guard refuses the rebuild and clear: no working around a human "no". |
| run `flaky` and `scan --execute` twice | the second run has nothing new | already-processed incidents are skipped; memory now shows the re-run fixed that signature |

Reset between demos: `python scenarios.py reset`. Tear down everything: `python infra/down.py`.

## Using it in a pipeline

The agent is a CLI, so it fits any CI/CD system:

- **GitHub Actions:** `.github/workflows/heal.yml` runs `python -m heal handle --source github --ref <run id> --execute`
  when `ci` fails. Turn it on with the repo variable `HEAL_ENABLED=true` and the secret `ANTHROPIC_API_KEY`.
  From there only GitHub is reachable, and approvals default to *no*, so only low-risk re-runs happen.
  Everything else becomes an issue.
- **Jenkins / GitLab / anything else:** run `python -m heal watch --execute --every 60` as a small service
  (or a cron `scan`). You can also call `handle --source <s> --ref <id>` from a failure webhook or notification.
- **Approvals:** `heal/approval.py` is one function. Replace it with a Slack or Teams button to approve
  from chat.

## Adding another tool (GitLab CI, Azure DevOps, Flux, Dagster, ...)

1. Write an adapter with the methods in `heal/ports.py` (e.g. `heal/adapters/gitlab.py`). GitLab's
   pipelines/jobs/trace/retry API maps one-to-one onto `CIProvider`.
2. Build it in `heal/context.py` and add read tools in `heal/tools.py` and a detector in `heal/detect.py`.
3. Add its actions to `heal/runbook.yaml`, its preconditions in `heal/policy.py` and its execute and
   validate code in `heal/actions.py`.
4. Add fakes to `tests/test_guard_and_workflow.py`. `pytest tests` runs offline.

## Files

```
heal/                    the agent
  adapters/              github_actions.py  jenkins.py  argocd.py  airflow.py  service_probe.py
  ports.py               the interfaces adapters implement
  runbook.yaml           allowed actions, risk, approval, preconditions
  policy.py              the guard and its live precondition checks
  agent.py               investigation loop (read-only tools, submit_rca); Anthropic or OpenAI backend
  workflow.py            decide -> approve -> execute -> validate -> escalate -> learn
  detect.py, actions.py, tools.py, memory.py, redact.py, approval.py, __main__.py
service/                 traffic-api (app, tests, smoke check, k8s manifests Argo CD deploys)
jenkins/                 Jenkins image, JCasC, Jenkinsfile
airflow/dags/            traffic_probe_daily
infra/                   kind config, Argo CD Application, compose; preflight.py, up.py, down.py, prepull.py (run on any OS)
.github/workflows/       ci.yml (the pipeline), heal.yml (in-pipeline self-healing)
scenarios.py             cause real failures
tests/                   offline contract tests for the guard and workflow
```
