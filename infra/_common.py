"""Shared helpers for the infra scripts. Standard library only, so they run before `pip install`
and work the same in PowerShell, macOS and Linux."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
CTX = "kind-heal-demo"          # the ONLY kube context these scripts ever use
IS_WINDOWS = os.name == "nt"
IS_WSL = "microsoft" in platform.release().lower()

if IS_WINDOWS:                   # make ANSI-free output safe on old consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def read_env() -> dict[str, str]:
    """Parse .env (KEY=VALUE lines). Real environment variables win, like python-dotenv."""
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if v})   # exported keys count too (e.g. API keys)
    return values


def set_env_value(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def has(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(*cmd: str, check: bool = True, capture: bool = False, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run a command (argument list, no shell, so quoting is identical on every OS)."""
    return subprocess.run(list(cmd), cwd=ROOT, check=check, text=True, input=stdin,
                          capture_output=capture or stdin is not None)


def out(*cmd: str) -> str:
    try:
        return subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def kubectl(*args: str, **kw) -> subprocess.CompletedProcess:
    return run("kubectl", "--context", CTX, *args, **kw)
