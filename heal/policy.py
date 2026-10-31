"""
The guard between the model and the platforms. The model PROPOSES; this code DECIDES:

  allow-list     only actions in runbook.yaml exist
  params         every required parameter must be present
  attempt limit  per incident, from durable memory AND the platform's own counters
  preconditions  live checks against the real systems (never the model's word)
  approval       medium-risk actions always wait for a human
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

RUNBOOK: dict = yaml.safe_load((Path(__file__).parent / "runbook.yaml").read_text())["actions"]

CODE_EXT = (".py", ".js", ".ts", ".go", ".java", ".kt", ".rb", ".rs", ".cs", ".groovy", ".scala", ".sh")
CODE_FILES = ("Jenkinsfile", "Dockerfile", "requirements.txt", "package.json", "go.mod", "pom.xml")


@dataclass
class Decision:
    verdict: str      # auto | approval | deny
    reason: str


Check = Callable[..., "tuple[bool, str]"]
CHECKS: dict[str, Check] = {}


def check(name: str):
    def register(fn: Check) -> Check:
        CHECKS[name] = fn
        return fn
    return register


def _need(adapter, name: str):
    if adapter is None:
        raise LookupError(f"{name} is not configured/reachable, so this cannot be verified")
    return adapter


def is_code_change(files: list[str]) -> list[str]:
    return [f for f in files if f.endswith(CODE_EXT) or f.rsplit("/", 1)[-1] in CODE_FILES]


# ---------------------------------------------------------------- checks (live state)
@check("gha_first_attempt")
def _gha_first_attempt(ctx, p, signature, **_):
    run = _need(ctx.github, "GitHub").run(p["run_id"])
    return run["run_attempt"] == 1, f"run {p['run_id']} is on attempt {run['run_attempt']} (GitHub's own counter)"


@check("gha_commit_safe_or_known_flaky")
def _gha_commit_safe(ctx, p, signature, min_resolved_reruns=2, **_):
    gh = _need(ctx.github, "GitHub")
    commit = gh.commit(gh.run(p["run_id"])["sha"])
    code = is_code_change(commit["files"])
    if not code:
        return True, f"commit {commit['sha']} changed no code ({', '.join(commit['files'][:4]) or 'no files'})"
    proven = ctx.memory.resolved_count(signature, "gha_rerun_failed_jobs")
    if proven >= min_resolved_reruns:
        return True, f"commit changed code, but memory shows a re-run fixed '{signature}' {proven}x"
    return False, f"commit {commit['sha']} changed code ({', '.join(code[:4])}); a re-run could hide a real bug"


@check("jenkins_not_agent_rebuild")
def _jenkins_not_agent(ctx, p, signature, **_):
    b = _need(ctx.jenkins, "Jenkins").build(p["build_number"])
    by = b["params"].get("TRIGGERED_BY", "user")
    return by != "heal-agent", f"build #{p['build_number']} was started by {by}"


@check("service_healthy")
def _service_healthy(ctx, p, signature, **_):
    pr = _need(ctx.service, "the service probe").probe()
    return pr["healthy"], _probe_text(pr)


@check("service_unhealthy")
def _service_unhealthy(ctx, p, signature, **_):
    pr = _need(ctx.service, "the service probe").probe()
    return not pr["healthy"], _probe_text(pr)


@check("argocd_target_is_previous")
def _argocd_previous(ctx, p, signature, **_):
    app = _need(ctx.argocd, "Argo CD").app()
    h = app["history"]
    if len(h) < 2:
        return False, "no earlier Argo CD history entry to roll back to"
    prev = h[-2]
    ok = p["history_id"] == prev["id"] and prev["revision"] != app["revision"]
    return ok, f"target history id {p['history_id']} vs previous good id {prev['id']} (rev {prev['revision']}); current rev {app['revision']}"


@check("argocd_recent_deploy")
def _argocd_recent(ctx, p, signature, max_age_minutes=240, **_):
    app = _need(ctx.argocd, "Argo CD").app()
    age = ctx.argocd.minutes_since(app["history"][-1]["deployed_at"]) if app["history"] else 1e9
    return age <= max_age_minutes, f"last sync {age:.0f} min ago (limit {max_age_minutes})"


@check("airflow_run_failed")
def _airflow_failed(ctx, p, signature, **_):
    state = _need(ctx.airflow, "Airflow").run_state(p["dag_run_id"])
    return state == "failed", f"DAG run {p['dag_run_id']} is {state}"


def _probe_text(pr: dict) -> str:
    if not pr.get("reachable", True):
        return pr["detail"]
    return f"service {pr['version']}: errors {pr['error_rate_pct']}%, p95 {pr['p95_ms']} ms ({pr['budget']})"


# ---------------------------------------------------------------- the guard
def guard(action: str, params: dict, ctx, incident_key: str, signature: str) -> Decision:
    if action not in RUNBOOK:
        return Decision("deny", f"'{action}' is not in the runbook allow-list")
    rule = RUNBOOK[action]
    missing = [k for k in rule["params"] if params.get(k) in (None, "")]
    if missing:
        return Decision("deny", f"{rule['id']} missing parameter(s): {', '.join(missing)}")
    tried = ctx.memory.attempts(incident_key, action)
    if tried >= rule["max_attempts"]:
        return Decision("deny", f"{rule['id']} already tried {tried}x for this incident (limit {rule['max_attempts']})")
    reasons = []
    for pre in rule.get("preconditions", []):
        args = {k: v for k, v in pre.items() if k != "check"}
        try:
            ok, why = CHECKS[pre["check"]](ctx, params, signature, **args)
        except Exception as e:                      # cannot verify = not allowed
            return Decision("deny", f"{rule['id']} precondition {pre['check']} could not be checked: {e}")
        if not ok:
            return Decision("deny", f"{rule['id']} precondition failed: {why}")
        reasons.append(why)
    facts = "; ".join(reasons)
    if rule["mode"] == "approval":
        return Decision("approval", f"{rule['id']} is {rule['risk']} risk, needs a human ({facts})")
    return Decision("auto", f"{rule['id']} low risk, preconditions met ({facts})")


def runbook_text() -> str:
    return "\n".join(f"- {name} [{r['id']}, {r['risk']} risk, {r['mode']}, params: {', '.join(r['params'])}]: {r['when']}"
                     for name, r in RUNBOOK.items())
