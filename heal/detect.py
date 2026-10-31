"""Detectors: turn real failures into incidents. Ordered so that root causes come first: a
bad deploy is handled before the CI and DAG failures it causes, so those see a healthy
dependency by the time the guard checks."""
from __future__ import annotations

from heal.ports import Incident
from heal.redact import tail

PRIORITY = {"deploy": 0, "github": 1, "jenkins": 2, "airflow": 3}


def detect_deploy(ctx) -> list[Incident]:
    if not ctx.service:
        return []
    pr = ctx.service.probe()
    if pr["healthy"]:
        return []
    app = ctx.argocd.app() if ctx.argocd else {}
    rev = app.get("revision", "unknown")
    return [Incident(key=f"deploy:{ctx.settings.argocd_app}:{rev}", source="deploy", ref=rev,
                     title=f"traffic-api {pr.get('version', '?')} breaches smoke budget",
                     evidence=f"probe: {pr}\nargo cd: {app}", facts={"probe": pr, "argocd": app})]


def detect_github(ctx) -> list[Incident]:
    if not ctx.github:
        return []
    out = []
    for r in ctx.github.failed_runs(ctx.settings.lookback_hours):
        jobs = ctx.github.failed_jobs(r["run_id"])
        out.append(Incident(key=f"github:{r['run_id']}:{r['run_attempt']}", source="github", ref=str(r["run_id"]),
                            title=f"GitHub Actions {r['workflow']} failed on {r['branch']} ({r['sha'][:7]})",
                            evidence=f"run: {r}\nfailed jobs: {jobs}", url=r["url"], facts={"run": r, "failed_jobs": jobs}))
    return out


def detect_jenkins(ctx) -> list[Incident]:
    if not ctx.jenkins:
        return []
    out = []
    for b in ctx.jenkins.failed_builds(ctx.settings.lookback_hours):
        out.append(Incident(key=f"jenkins:{ctx.settings.jenkins_job}:{b['number']}", source="jenkins", ref=str(b["number"]),
                            title=f"Jenkins {ctx.settings.jenkins_job} #{b['number']} failed",
                            evidence=f"build: {b}\nconsole tail:\n{tail(ctx.jenkins.console_tail(b['number']), 1500)}",
                            url=b.get("url", ""), facts={"build": b}))
    return out


def detect_airflow(ctx) -> list[Incident]:
    if not ctx.airflow:
        return []
    out = []
    for r in ctx.airflow.failed_runs(ctx.settings.lookback_hours):
        tasks = ctx.airflow.failed_tasks(r["dag_run_id"])
        out.append(Incident(key=f"airflow:{ctx.settings.airflow_dag}:{r['dag_run_id']}", source="airflow", ref=r["dag_run_id"],
                            title=f"Airflow {ctx.settings.airflow_dag} run failed ({', '.join(t['task_id'] for t in tasks)})",
                            evidence=f"run: {r}\nfailed tasks: {tasks}", facts={"run": r, "failed_tasks": tasks}))
    return out


DETECTORS = {"deploy": detect_deploy, "github": detect_github, "jenkins": detect_jenkins, "airflow": detect_airflow}


def detect_all(ctx, sources: list[str]) -> list[Incident]:
    found = []
    for src in sorted(sources, key=lambda s: PRIORITY.get(s, 9)):
        try:
            found += [i for i in DETECTORS[src](ctx) if not ctx.memory.is_processed(i.key)]
        except Exception as e:
            print(f"  ! detector {src} failed: {type(e).__name__}: {e}")
    return found


def incident_for(ctx, source: str, ref: str) -> Incident:
    """One specific incident, e.g. from a pipeline's on-failure hook."""
    if source == "github":
        r = ctx.github.run(int(ref))
        jobs = ctx.github.failed_jobs(r["run_id"])
        return Incident(key=f"github:{r['run_id']}:{r['run_attempt']}", source="github", ref=ref,
                        title=f"GitHub Actions {r['workflow']} failed on {r['branch']} ({r['sha'][:7]})",
                        evidence=f"run: {r}\nfailed jobs: {jobs}", url=r["url"], facts={"run": r, "failed_jobs": jobs})
    if source == "jenkins":
        b = ctx.jenkins.build(int(ref))
        return Incident(key=f"jenkins:{ctx.settings.jenkins_job}:{ref}", source="jenkins", ref=ref,
                        title=f"Jenkins {ctx.settings.jenkins_job} #{ref} failed",
                        evidence=f"build: {b}\nconsole tail:\n{tail(ctx.jenkins.console_tail(int(ref)), 1500)}",
                        url=b.get("url", ""), facts={"build": b})
    if source == "airflow":
        tasks = ctx.airflow.failed_tasks(ref)
        return Incident(key=f"airflow:{ctx.settings.airflow_dag}:{ref}", source="airflow", ref=ref,
                        title=f"Airflow {ctx.settings.airflow_dag} run failed", evidence=f"failed tasks: {tasks}",
                        facts={"failed_tasks": tasks})
    if source == "deploy":
        found = detect_deploy(ctx)
        if not found:
            raise SystemExit("service is healthy: no deploy incident")
        return found[0]
    raise SystemExit(f"unknown source {source}")
