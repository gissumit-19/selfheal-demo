"""Update this copy to the latest version of the lab, in one command. Same on every OS:

    python infra/update.py           (asks before discarding local edits)
    python infra/update.py --yes     (no questions)
    python infra/update.py --no-up   (don't touch the running containers)

It: fetches the latest version from the trainer's repo, resets the files to it (also fixing Windows
line endings), makes your GitHub fork match, installs new Python packages, recreates the containers
only if their setup changed, and runs the preflight check. Your .env, .venv and runtime/ are kept.
"""
from __future__ import annotations

import os
import subprocess
import sys

from _common import ROOT, has, out, run

UPSTREAM = os.getenv("HEAL_UPSTREAM", "https://github.com/pravinmenghani1/selfheal-demo.git")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run("git", *args, check=check, capture=True)


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)          # keep our lines in order with the tools' output
    yes = "--yes" in sys.argv
    if not has("git") or not (ROOT / ".git").exists():
        sys.exit("run this inside your clone of the lab repo (git is needed)")

    print(f"==> fetching the latest version from {UPSTREAM}")
    git("fetch", "--quiet", UPSTREAM, "main")
    new, old = out("git", "rev-parse", "FETCH_HEAD"), out("git", "rev-parse", "HEAD")
    local = [l for l in out("git", "status", "--porcelain").splitlines()
             if not l.endswith(("infra/update.py", "infra/_common.py"))]   # the updater itself, fetched first time
    if new == old and not local:
        print(f"==> files already at the latest version ({new[:7]})")
    else:
        if local:
            print("these local changes will be DISCARDED (your .env, .venv and runtime/ are safe):")
            print("\n".join("   " + l for l in local[:20]))
            if not yes and input("continue? [y/N] ").strip().lower() != "y":
                print("stopped, nothing changed")
                return 1
        git("reset", "--quiet", "--hard", new)
        git("rm", "-r", "-q", "--cached", ".")            # re-check out every file: fixes Windows line endings
        git("reset", "--quiet", "--hard", new)
        print(f"==> files updated: {old[:7]} -> {new[:7]}")

    origin = out("git", "remote", "get-url", "origin")
    if origin and origin.rstrip("/").removesuffix(".git") != UPSTREAM.removesuffix(".git"):
        fork_head = (out("git", "ls-remote", "origin", "refs/heads/main").split() or [""])[0]
        if fork_head != new:
            print(f"==> making your fork match ({origin})")
            push = git("push", "--force", "--quiet", "origin", f"{new}:refs/heads/main", check=False)
            if push.returncode:
                print(f"   could not push to your fork: {push.stderr.strip()[:300]}\n"
                      "   (run `gh auth setup-git` or check your GitHub login, then run this again)")
        else:
            print("==> your fork already matches")
        git("fetch", "--quiet", "origin", check=False)
        git("branch", "--quiet", "--set-upstream-to=origin/main", "main", check=False)

    print("==> installing Python packages")
    run(sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt"))

    if "--no-up" in sys.argv:
        print("==> skipping python infra/up.py (--no-up)")
    elif out("docker", "ps", "-q", "--filter", "name=heal-demo"):
        print("==> applying the update to the running systems (python infra/up.py; only changed containers restart)")
        run(sys.executable, str(ROOT / "infra" / "up.py"), check=False)
    else:
        print("==> systems not running: start them with  python infra/up.py")

    print("\n==> checking everything (python infra/preflight.py)")
    return run(sys.executable, str(ROOT / "infra" / "preflight.py"), check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
