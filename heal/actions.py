"""Each runbook action = one real API call + a real validation that the fix worked."""
from __future__ import annotations

import time


def execute(action: str, p: dict, ctx) -> tuple[str, dict]:
    """Run the action. Returns (result text, state needed to validate it)."""
    if action == "gha_rerun_failed_jobs":
        attempt = ctx.github.run(p["run_id"])["run_attempt"]
        return ctx.github.rerun_failed_jobs(p["run_id"]), {"min_attempt": attempt + 1}
    if action == "jenkins_rebuild":
        n = ctx.jenkins.rebuild(p["build_number"])
        return f"Jenkins rebuild of #{p['build_number']} started as #{n}", {"new_build": n}
    if action == "argocd_rollback":
        return ctx.argocd.rollback(p["history_id"]), {}
    if action == "airflow_clear_failed":
        return ctx.airflow.clear_failed(p["dag_run_id"]), {}
    raise ValueError(f"no executor for {action}")


def validate(action: str, p: dict, state: dict, ctx) -> tuple[bool, str]:
    t = ctx.settings.wait_timeout
    if action == "gha_rerun_failed_jobs":
        r = ctx.github.wait_for_run(p["run_id"], state["min_attempt"], t)
        return r["conclusion"] == "success", f"run {p['run_id']} attempt {r['run_attempt']}: {r['conclusion']}"
    if action == "jenkins_rebuild":
        b = ctx.jenkins.wait_for_build(state["new_build"], t)
        return b["result"] == "SUCCESS", f"Jenkins #{state['new_build']}: {b['result']}"
    if action == "argocd_rollback":
        app = ctx.argocd.wait_settled(min(t, 300))
        for _ in range(12):                         # pods roll; give the probe a minute to see the old version
            pr = ctx.service.probe()
            if pr["healthy"]:
                break
            time.sleep(5)
        return pr["healthy"], (f"Argo CD {app['health']}, deployed rev {app['deployed_revision']} (git main {app['revision']}, "
                               f"{app['sync']}); service {pr.get('version')} "
                               f"errors {pr.get('error_rate_pct')}% p95 {pr.get('p95_ms')} ms")
    if action == "airflow_clear_failed":
        state_ = ctx.airflow.wait_for_run(p["dag_run_id"], t)
        return state_ == "success", f"DAG run {p['dag_run_id']}: {state_}"
    return False, "no validation defined"
