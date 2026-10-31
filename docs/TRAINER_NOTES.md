# Trainer notes

## Before the class
1. **Rehearse the whole thing once on a clean machine** (ideally one Mac and one Windows/WSL laptop): every step of
   `LEARNER_GUIDE.md`, all labs, then `down.sh`. Note your own timings.
2. **Publish the code as a GitHub template repo** (repo Settings > "Template repository"), and share the link. Learners
   then get their own public copy in one click (guide step 3, option A). Never push your `.env`: it is gitignored.
3. **Send the prerequisites a few days early:** step 0 and step 1 of the guide, plus "run `./infra/preflight.sh` and
   send me a screenshot". Most class-time problems are Docker memory, WSL setup and corporate proxies.
4. **Bandwidth:** each learner downloads about 3 GB. On shared Wi-Fi, ask learners to run `./infra/up.sh` the day before.
   Or run `./infra/prepull.sh` at home and keep the stack between days. `down.sh` deletes it, so don't run that until
   the end.
5. **API keys:** learners can use Anthropic **or** OpenAI keys (`LLM_PROVIDER`). Running half the class on each is a
   good discussion: the guard's verdicts are the same whichever model proposes. One key per learner is simplest. If you share one org key, check its rate limits: about 30 learners
   running Lab C at once is about 30 parallel agent loops. Budget about $1 to $3 per learner (see guide step 0).

## Timing plan (about 2 hours)
| | |
|---|---|
| 0:00 | Architecture recap: model proposes, guard decides; runbook.yaml; ports and adapters |
| 0:15 | Steps 5 to 7 (preflight, up, bootstrap, doctor). Have stragglers pair up |
| 0:35 | Lab A: flaky test |
| 0:50 | Lab B: code bug |
| 1:00 | Lab C: bad deploy (approve), then C2 (decline) |
| 1:30 | Lab D: memory and audit; open `runtime/audit.jsonl` together |
| 1:40 | Discussion: adding GitLab/Flux (README "Adding another tool"); what you would put in runbook.yaml at work |

## What is real, what is staged (be upfront with learners)
- **Real:** every API call to GitHub, Jenkins, Argo CD, Airflow and Claude. The deploy, rollback, re-run, rebuild
  and clear. The validation polling. The issues opened in their repos.
- **Staged:** *when* failures happen (`scenarios.py`). The flaky test is deterministic on purpose: slow on attempt 1,
  fast on a re-run, so it behaves the same for everyone.
- **Live models vary.** The agent may sometimes propose `escalate` where the guide expects an action, or vice versa.
  That is a good discussion point: compare its reasoning with the guard's verdict. The guard's verdicts are
  deterministic for the same live state.

## Talking points
- The guard reads facts from the systems themselves: GitHub `run_attempt`, commit files, the live probe, Argo CD
  history, the Airflow run state. It never reads them from the model's text.
- "Cannot verify = not allowed": stop Jenkins (`docker stop heal-demo-jenkins-1`) and re-run a scan. Jenkins actions
  are denied, not guessed.
- Attempt limits come from durable memory **and** the platform's own counters, so a restart can't cause a retry loop.
- Rollback is GitOps-aware: Argo CD rolls back, but git still has the bad commit. The agent opens a follow-up rather
  than rewriting history.
- Prompt injection: logs are treated as untrusted data in the system prompt. Even if the model obeys an injected
  instruction, the guard's allow-list stops it.

## Known limits (as of the first version)
- Approvals are at the terminal (or `AUTO_APPROVE`). Slack/Teams approval is one function in `heal/approval.py`.
- Memory is local SQLite per machine. A team setup would use a shared database.
- Airflow 3 API v2 only. For Airflow 2, swap the base path to `/api/v1` and use basic auth (see the adapter docstring).
