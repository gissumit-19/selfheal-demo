# Learner guide: self-healing CI/CD with real GitHub Actions, Jenkins, Argo CD and Airflow

Total time: about 30 to 45 minutes of setup the first time (most of it downloads), then about 90 minutes of labs.

## 0. What you need

| | |
|---|---|
| Accounts | A **GitHub** account. An **Anthropic API key** (console.anthropic.com) **or** an **OpenAI API key** (platform.openai.com), with credit. |
| Machine | macOS (Intel or Apple Silicon), Linux, or Windows 10/11 with **WSL2**. 16 GB RAM recommended (8 GB minimum), 15 GB free disk. |
| Network | About 3 GB of downloads. Access to github.com, api.anthropic.com, Docker Hub and raw.githubusercontent.com. |
| Cost | The model calls cost roughly **$0.05 to $0.25 per incident** the agent investigates, so about **$1 to $3 for all the labs**. Set `CLAUDE_EFFORT=low` or `OPENAI_REASONING_EFFORT=low` in `.env` to spend less. GitHub Actions minutes are free for public repos. |

Everything runs on your machine except GitHub. Nothing touches any other Kubernetes cluster you have:
the scripts only use the context `kind-heal-demo`.

## 1. Install the tools

You need: Docker, kind, kubectl, git, gh (GitHub CLI), Python 3.11+, curl.

### macOS
1. Install **Docker Desktop** (docker.com/products/docker-desktop) and start it.
   Settings > Resources > Memory: **at least 6 GB**.
2. `brew install kind kubectl gh git python@3.12`

### Windows (use WSL2: every command in this guide runs in the Ubuntu terminal, not PowerShell)
1. In PowerShell as Administrator: `wsl --install -d Ubuntu`, then reboot and open "Ubuntu".
2. Install **Docker Desktop**. Settings > General: "Use the WSL 2 based engine". Settings > Resources > WSL
   integration: enable **Ubuntu**. Settings > Resources > Memory: at least 6 GB.
3. In Ubuntu, follow the Linux steps below (skip installing Docker Engine: Docker Desktop provides it).
4. Keep the project inside the Linux home folder (`~/selfheal-demo`), **not** under `/mnt/c/...`. It is much faster,
   and the scripts keep their line endings.

### Linux (Ubuntu/Debian; also inside WSL)
```bash
sudo apt update && sudo apt install -y git curl python3 python3-venv python3-pip
# Docker Engine (skip on WSL with Docker Desktop): https://docs.docker.com/engine/install/ubuntu/
sudo usermod -aG docker $USER && newgrp docker
# kind
ARCH=$(dpkg --print-architecture)    # amd64 or arm64
curl -Lo kind https://github.com/kubernetes-sigs/kind/releases/latest/download/kind-linux-$ARCH
chmod +x kind && sudo mv kind /usr/local/bin/
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/$ARCH/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
# GitHub CLI: https://github.com/cli/cli/blob/trunk/docs/install_linux.md
```

Check: `docker run --rm hello-world` prints "Hello from Docker!".

## 2. Log in to GitHub

```bash
gh auth login          # GitHub.com > HTTPS > "Login with a web browser"
gh auth setup-git      # lets `git push` use the same login
```

**No gh?** Create a fine-grained token (GitHub > Settings > Developer settings > Fine-grained tokens), limited to
your demo repo, with permissions **Actions: read/write, Contents: read/write, Issues: read/write, Metadata: read**.
Put it in `.env` as `GITHUB_TOKEN`, and use it as the password when `git push` asks.

## 3. Get your own copy of the repo

Each learner needs their **own public repo**. The pipelines run there and Argo CD deploys from it.

**Option A (template, easiest):** open the template link from your trainer, click **Use this template > Create a new
repository**, name it `selfheal-demo`, choose **Public**, then:
```bash
gh repo clone <your-user>/selfheal-demo && cd selfheal-demo
```

**Option B (zip from the trainer):**
```bash
unzip selfheal-real.zip && cd selfheal-real
git init -b main && git add -A && git commit -m "self-healing demo"
gh repo create <your-user>/selfheal-demo --public --source . --push
```

Public is required: Argo CD and Jenkins clone the repo without credentials.

## 4. Configure

```bash
cp .env.example .env
```
Edit `.env` and set at least:
- **one** model key: `ANTHROPIC_API_KEY=` **or** `OPENAI_API_KEY=` (with both set, `LLM_PROVIDER=openai` or `anthropic` picks)
- `GITHUB_REPO=<your-user>/selfheal-demo`
- `JENKINS_TOKEN=` any password you like (it becomes the Jenkins admin password)

Then install the Python packages:
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```
Run `. .venv/bin/activate` again in every new terminal.

## 5. Preflight check (changes nothing)

```bash
./infra/preflight.sh
```
It checks tools, Docker memory, free ports, `.env`, the API key (with a free call), your GitHub repo and token, and
the Python packages. Fix every `[FAIL]` line and run it again until it ends with **`Ready: ./infra/up.sh`**.

## 6. Bring up the systems (10 to 20 minutes the first time)

```bash
./infra/up.sh
```
It creates the kind cluster, installs Argo CD, points Argo CD at your repo, and builds and starts Jenkins and Airflow.
The Jenkins image build is the slow part. It ends with:
```
All systems up:
  Argo CD  https://localhost:30443  (admin / see ARGOCD_PASSWORD in .env)
  Jenkins  http://localhost:8081  (admin / JENKINS_TOKEN)
  Airflow  http://localhost:8082  (admin / admin)
```
Your browser warns about Argo CD's self-signed certificate. That is expected: choose "Advanced > Proceed".

## 7. First deploy and connection check

```bash
python scenarios.py bootstrap
python -m heal doctor
```
`doctor` should show **OK** for github, jenkins, argocd, airflow, service (HEALTHY) and the model. Also
open http://localhost:30080/healthz, which should show `{"status": "ok", "version": "1.0.0"}`.

---

## The labs

Each lab: **cause a real failure > watch it in the UIs > run the agent dry > run it for real > discuss.**
`--execute` is the only mode that changes anything. Without it the agent only investigates and reports.

### Lab A: a flaky test (about 15 min)
```bash
python scenarios.py flaky
```
Wait until GitHub (Actions tab, workflow **ci**, the dispatched run) and Jenkins (`traffic-api-ci`) are both red
(1 to 2 minutes). Then:
```bash
python -m heal scan              # dry run
python -m heal scan --execute
```
**Expect:** for both incidents, `[decide] AUTO: ... commit changed no code ...`. The agent re-runs the failed GitHub
jobs and rebuilds Jenkins, waits for them, then shows `FIXED`.
**Discuss:** which facts did the guard check itself? Look for the run attempt counter and the commit's files. Why is
a re-run only "auto" when the commit changed no code?

### Lab B: a real code bug (about 10 min)
```bash
python scenarios.py code-bug
```
Wait for the **ci** run on branch `demo/units-bug` to fail, then `python -m heal scan --execute`.
**Expect:** category `code_bug`, then **escalate**. A GitHub issue labelled `heal-agent` appears in your repo,
addressed to the commit author. Even if the model proposed a re-run, the guard would deny it (`commit changed code`).
**Discuss:** why must a self-healing system never "fix" a real bug by retrying?

### Lab C: a bad deploy that breaks two other pipelines (about 20 min)
```bash
python scenarios.py bad-deploy
```
This pushes traffic-api **1.1.0**. Its unit tests pass, but it has a real paging bug, and Argo CD deploys it. Then the
Airflow DAG and a Jenkins build start. Wait until `publish_traffic_api` (Airflow) and `Smoke: staging traffic-api`
(Jenkins) are red, about 1 minute. Then:
```bash
python -m heal scan --execute
```
**Expect, in this order:**
1. the **deploy** incident: `argocd_rollback` needs **approval**. Type `y`. Argo CD rolls back to 1.0.0, the probe
   confirms it is healthy, and a follow-up issue asks you to revert the bad commit in git.
2. **Jenkins**: usually a rebuild (the service is healthy again), then `FIXED`. Some model runs escalate here instead,
   calling the failure a "code regression". That is safe but conservative. Ask: was Jenkins the *cause* or a *victim*?
3. **Airflow**: clear the failed task (the service is healthy again). The DAG run ends `success`.

Note: GitHub CI is **green** for the bad commit. The unit tests only use a full page of 50 segments, so they miss the
bug, and only the smoke test and the real DAG traffic (120 segments) catch it. That is a good discussion point too.

**Discuss:** why does the deploy incident come first? What would happen to the Airflow incident if it were
handled before the rollback?

### Lab C2: say no (about 10 min)
```bash
python scenarios.py reset
python scenarios.py bad-deploy
```
Wait for the failures, run `python -m heal scan --execute`, and answer **`n`** at the approval prompt.
**Expect:** the deploy incident escalates (`human declined argocd_rollback`). Jenkins escalates because the service is
still broken. For Airflow the model may propose the rollback again, since it is the real fix, and you are asked
again: say `n` again. A rebuild or clear is never allowed while the dependency is unhealthy (`service_healthy` in
`runbook.yaml`). The agent does not work around a human "no". Run `python scenarios.py reset` afterwards.

### Lab D: memory and the audit trail (about 10 min)
Run `python -m heal scan --execute` again: `0 new incident(s)`, because processed incidents are never handled twice.
Then repeat Lab A: `[recall]` now shows the earlier fix. Open `runtime/audit.jsonl`: every proposal, guard verdict,
approval, action and validation is recorded there.

### Lab E (optional): self-healing inside GitHub Actions
In your repo: **Settings > Secrets and variables > Actions**. Add the secret `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
(for OpenAI also the variable `LLM_PROVIDER` = `openai`) and the variable `HEAL_ENABLED` = `true`. Now when **ci** fails, the **heal** workflow runs the agent inside GitHub Actions. Trigger it
with `python scenarios.py flaky` and watch the Actions tab. Turn it off again (`HEAL_ENABLED=false`) before other labs,
or the local agent and the Actions agent will both handle the same GitHub failures.

### Reset and clean up
```bash
python scenarios.py reset        # back to 1.0.0, between labs
./infra/down.sh                  # at the end: deletes the cluster, containers and volumes
docker system prune -a           # optional: frees the disk space used by the images
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| preflight: `port 8081/8082 is taken` | Change `JENKINS_PORT` + `JENKINS_URL` (or `AIRFLOW_PORT` + `AIRFLOW_URL`) in `.env` to a free port, e.g. 8091. |
| preflight: `port 30080/30443 is taken` | Another kind/minikube cluster is using it. Stop it (`kind get clusters`, `minikube stop`). |
| `up.sh` stuck at "waiting for Jenkins" | `docker logs heal-demo-jenkins-1`. A plugin download error is usually network/proxy related: re-run `./infra/up.sh`. |
| `up.sh` stuck at "waiting for Airflow" | `docker logs heal-demo-airflow-1`. The first start takes 1 to 2 minutes. Docker needs at least 6 GB of memory. |
| `doctor`: argocd FAIL 401 | `ARGOCD_PASSWORD` in `.env` is stale. Re-run `./infra/up.sh` (it rewrites it). |
| `doctor`: service UNHEALTHY / unreachable right after setup | Run `python scenarios.py bootstrap` (the first sync). Check `kubectl --context kind-heal-demo -n traffic get pods`. |
| Argo CD app shows "repository not found" | The repo is private, or `GITHUB_REPO` is wrong. Make it public, then re-run `./infra/up.sh`. |
| Jenkins build fails at "Checkout SCM" | Same as above (Jenkins clones your public repo). |
| `git push` asks for a password | Run `gh auth setup-git`, or paste your fine-grained token as the password. |
| Airflow `publish_traffic_api` fails with "connection refused" | traffic-api is not running: `python scenarios.py bootstrap`. On Linux, Docker must support `host-gateway` (Docker 20.10+). |
| `Error 400 ... fallbacks` from the model | Your account does not support the fallback beta. Set `CLAUDE_FALLBACKS=0` in `.env`. |
| `Error 401` from the model | Wrong or revoked key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). Check with `./infra/preflight.sh`. A key exported in your shell wins over `.env`. |
| OpenAI `400 ... Function tools with reasoning_effort are not supported ... in /v1/chat/completions` | Keep `OPENAI_API_STYLE=responses` (the default). Only use `chat` for servers without the Responses API, and then leave `OPENAI_REASONING_EFFORT` empty. |
| scenario says "expected text not found" | A previous scenario is still applied: `python scenarios.py reset`. |
| Windows: `bad interpreter: /bin/bash^M` | The files got Windows line endings. Work inside WSL (`~/...`) and run `git config --global core.autocrlf input`, then clone again. |
