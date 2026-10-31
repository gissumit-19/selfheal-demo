"""
python -m heal doctor                         check every configured system is reachable
python -m heal scan   [--execute]             find failures in all systems and handle each one
python -m heal watch  [--execute] [--every N] scan forever (a poller / daemon)
python -m heal handle --source S --ref R [--execute]
                                              one incident, e.g. from a pipeline's on-failure step

Without --execute nothing is changed: the agent investigates and shows what the guard would allow.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from heal.config import SETTINGS
from heal.context import build_context


def banner(ctx, execute: bool) -> None:
    up = [n for n in ("github", "jenkins", "argocd", "airflow", "service") if getattr(ctx, n)]
    print("=" * 78)
    print(f"self-healing agent  model={SETTINGS.model}  mode={'EXECUTE' if execute else 'DRY RUN'}")
    print(f"connected: {', '.join(up) or 'nothing'}")
    for n, why in ctx.errors.items():
        print(f"  not connected: {n} ({why})")
    print("=" * 78)


def doctor() -> int:
    ctx = build_context(SETTINGS)
    checks = {
        "github": lambda: f"{len(ctx.github.failed_runs(SETTINGS.lookback_hours))} failed run(s) of {SETTINGS.github_workflow} in {SETTINGS.github_repo}",
        "jenkins": lambda: f"{len(ctx.jenkins.failed_builds(SETTINGS.lookback_hours))} failed build(s) of {SETTINGS.jenkins_job}",
        "argocd": lambda: (lambda a: f"{a['app']}: {a['health']}/{a['sync']} rev {a['revision']}, auto-sync {'ON (rollback will be refused)' if a['auto_sync'] else 'off'}")(ctx.argocd.app()),
        "airflow": lambda: f"{len(ctx.airflow.failed_runs(SETTINGS.lookback_hours))} failed run(s) of {SETTINGS.airflow_dag}",
        "service": lambda: (lambda p: f"{'HEALTHY' if p['healthy'] else 'UNHEALTHY'} {p}")(ctx.service.probe()),
    }
    bad = 0
    for name, fn in checks.items():
        if getattr(ctx, name) is None:
            print(f"  {name:<8} --   {ctx.errors.get(name, 'not requested in HEAL_SOURCES')}")
            continue
        try:
            print(f"  {name:<8} OK   {fn()}")
        except Exception as e:
            bad += 1
            print(f"  {name:<8} FAIL {type(e).__name__}: {e}")
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    print(f"  {'model':<8} {'OK  ' if has_key else '??  '} {SETTINGS.model} "
          f"({'API key set' if has_key else 'no ANTHROPIC_API_KEY; relying on an `ant auth login` profile if any'})")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m heal", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["doctor", "scan", "watch", "handle"])
    ap.add_argument("--execute", action="store_true", help="actually run approved actions and open tickets")
    ap.add_argument("--source", choices=["deploy", "github", "jenkins", "airflow"])
    ap.add_argument("--ref", help="run id / build number / dag_run_id")
    ap.add_argument("--sources", help="comma list, overrides HEAL_SOURCES")
    ap.add_argument("--every", type=int, default=60, help="watch interval, seconds")
    a = ap.parse_args()
    if a.sources:
        SETTINGS.sources = [s.strip() for s in a.sources.split(",")]
    if a.command == "doctor":
        return doctor()

    from heal.agent import LLM
    from heal.detect import detect_all, incident_for
    from heal.workflow import handle

    ctx = build_context(SETTINGS)
    banner(ctx, a.execute)
    llm = LLM(SETTINGS)

    if a.command == "handle":
        if not (a.source and a.ref) and a.source != "deploy":
            ap.error("handle needs --source and --ref")
        inc = incident_for(ctx, a.source, a.ref or "")
        if a.execute and ctx.memory.is_processed(inc.key):
            print(f"{inc.key} was already handled")
            return 0
        outcome = handle(ctx, llm, inc, a.execute)
        return 0 if outcome in ("resolved", "dry_run") else 2

    while True:
        incidents = detect_all(ctx, SETTINGS.sources)
        print(f"\n{len(incidents)} new incident(s)")
        results = [(i.key, handle(ctx, llm, i, a.execute)) for i in incidents]
        if results:
            print("\nSUMMARY")
            for key, outcome in results:
                print(f"  {outcome.upper():<10} {key}")
            print(f"  audit trail: {ctx.memory.audit_path}")
        if a.command == "scan":
            return 0
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
