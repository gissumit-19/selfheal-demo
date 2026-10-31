"""
Cause REAL failures in the real systems, then let the agent handle them.

  python scenarios.py bootstrap    first Argo CD sync of traffic-api 1.0.0, check it is healthy
  python scenarios.py bad-deploy   push a real regression (1.1.0), sync it with Argo CD, then run the
                                   Airflow DAG and the Jenkins smoke build that it breaks
  python scenarios.py flaky        docs-only commit, then GitHub Actions + Jenkins runs with the flaky test on
  python scenarios.py code-bug     push branch demo/units-bug with a real unit-conversion bug (CI fails)
  python scenarios.py reset        restore 1.0.0 on main, sync, delete the demo branch

Each one uses git (in this repo) and the same adapters the agent uses. Nothing is simulated.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from heal.config import SETTINGS
from heal.context import build_context

ROOT = Path(__file__).parent
APP, DEPLOY = ROOT / "service" / "app.py", ROOT / "service" / "deployment.yaml"

GOOD_BULK = """        batch = segment_ids[start:start + batch_size]
        out.extend(lookup_segment(s) for s in batch)"""
BAD_BULK = """        # perf: fetch in fixed-size pages
        out.extend(lookup_segment(segment_ids[start + i]) for i in range(batch_size))"""
GOOD_MPS, BAD_MPS = "return kph / 3.6\n", "return kph / 3.6 / 3.6   # unify units\n"


def git(*args: str) -> str:
    print(f"  $ git {' '.join(args)}")
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{path.name}: expected text not found (already applied? run `python scenarios.py reset`)")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def set_version(v: str) -> None:
    lines = DEPLOY.read_text(encoding="utf-8").splitlines(keepends=True)
    i = next(n for n, l in enumerate(lines) if "name: APP_VERSION" in l)
    lines[i + 1] = lines[i + 1].split("value:")[0] + f'value: "{v}"\n'
    DEPLOY.write_text("".join(lines), encoding="utf-8", newline="\n")


def commit_push(msg: str, branch: str = "main") -> None:
    git("add", "-A", "service", "docs")
    git("commit", "-m", msg)
    git("push", "origin", branch)


def sync_and_wait(ctx) -> None:
    print("  " + ctx.argocd.sync())
    app = ctx.argocd.wait_settled(300)
    print(f"  argo cd: {app['health']}/{app['sync']} rev {app['revision']} ({app['operation']})")
    time.sleep(10)                                   # let the rollout finish
    print(f"  probe: {ctx.service.probe()}")


def main(cmd: str) -> None:
    ctx = build_context(SETTINGS)
    for n, why in ctx.errors.items():
        print(f"  (not connected: {n}: {why})")

    if cmd == "bootstrap":
        sync_and_wait(ctx)
        if ctx.airflow:
            print("  waiting for Airflow to load the DAG ...")
            ctx.airflow.wait_for_dag()
            ctx.airflow.unpause()
            print(f"  airflow: {SETTINGS.airflow_dag} loaded and unpaused")
        if ctx.jenkins:
            print(f"  jenkins: job ok, {len(ctx.jenkins.failed_builds(1))} recent failed build(s)")
        print("\nReady. Next: python -m heal doctor")

    elif cmd == "bad-deploy":
        git("checkout", "main")
        git("pull", "--ff-only", "origin", "main")
        replace(APP, GOOD_BULK, BAD_BULK)
        set_version("1.1.0")
        commit_push("perf: fetch segments in fixed-size pages (traffic-api 1.1.0)")
        print("  waiting 15s so Argo CD sees the new commit ...")
        time.sleep(15)
        sync_and_wait(ctx)
        if ctx.airflow:
            print(f"  airflow: triggered {ctx.airflow.trigger()}")
        if ctx.jenkins:
            ctx.jenkins.trigger({"SCENARIO": "normal", "TRIGGERED_BY": "user"})
            print("  jenkins: triggered traffic-api-ci (normal)")
        print("\nIn ~1 minute the DAG and the Jenkins smoke stage fail. Then: python -m heal scan --execute")

    elif cmd == "flaky":
        git("checkout", "main")
        git("pull", "--ff-only", "origin", "main")
        with (ROOT / "docs" / "CHANGELOG.md").open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"- docs touch-up {time.strftime('%Y-%m-%d %H:%M')}\n")
        commit_push("docs: update changelog")
        time.sleep(5)
        if ctx.github:
            ctx.github.dispatch("main", {"flaky": "true"})
            print("  github: dispatched ci.yml with flaky=true")
        if ctx.jenkins:
            ctx.jenkins.trigger({"SCENARIO": "flaky", "TRIGGERED_BY": "user"})
            print("  jenkins: triggered traffic-api-ci (flaky)")
        print("\nIn ~1-2 minutes both fail on the flaky test. Then: python -m heal scan --execute")

    elif cmd == "code-bug":
        git("checkout", "main")
        git("pull", "--ff-only", "origin", "main")
        git("checkout", "-B", "demo/units-bug")
        replace(APP, GOOD_MPS, BAD_MPS)
        git("add", "service/app.py")
        git("commit", "-m", "refactor: unify speed units")
        git("push", "-f", "-u", "origin", "demo/units-bug")
        git("checkout", "main")
        print("\nCI on demo/units-bug fails on test_to_mps. Then: python -m heal scan --execute  (expect an escalation, not a re-run)")

    elif cmd == "reset":
        git("checkout", "main")
        git("pull", "--ff-only", "origin", "main")
        text = APP.read_text(encoding="utf-8").replace(BAD_BULK, GOOD_BULK).replace(BAD_MPS, GOOD_MPS)
        APP.write_text(text, encoding="utf-8", newline="\n")
        set_version("1.0.0")
        if git("status", "--porcelain", "service"):
            commit_push("fix: restore traffic-api 1.0.0 bulk_get")
        try:
            git("push", "origin", "--delete", "demo/units-bug")
        except subprocess.CalledProcessError:
            pass
        sync_and_wait(ctx)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
