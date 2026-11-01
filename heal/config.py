"""
Settings, read from the environment (and .env). Every system is optional: an adapter is
built only when its settings are present, so the same agent runs in a GitHub Actions job
(GitHub only), on a Jenkins box, or on a laptop that can reach all four systems.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
# An empty line in .env (e.g. `OPENAI_BASE_URL=`) means "not set". Remove those from the environment, otherwise
# the SDKs read the empty string itself (an empty base URL = "Request URL is missing an 'http://' protocol").
for _key, _value in dotenv_values(ROOT / ".env").items():
    if not (_value or "").strip() and os.environ.get(_key, "") == "":
        os.environ.pop(_key, None)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def local_url(name: str, default: str = "") -> str:
    """URLs of the local systems. `localhost` becomes 127.0.0.1: on Windows `localhost` tries IPv6 (::1) first,
    the published ports listen on IPv4 only, and every request then waits ~2 s for the refused IPv6 attempt.
    That made traffic-api look slow (p95 > 2000 ms) and the guard refuse rebuilds."""
    return re.sub(r"//localhost(?=[:/]|$)", "//127.0.0.1", env(name, default))


def _github_token() -> str:
    """GITHUB_TOKEN, or the token of a logged-in `gh` CLI (handy on a laptop)."""
    token = env("GITHUB_TOKEN")
    if token:
        return token
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _provider() -> str:
    chosen = env("LLM_PROVIDER").lower()
    if chosen in ("anthropic", "openai"):
        return chosen
    if env("ANTHROPIC_API_KEY") or env("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    return "openai" if env("OPENAI_API_KEY") else "none"


@dataclass
class Settings:
    sources: list[str] = field(default_factory=lambda: [s.strip() for s in env(
        "HEAL_SOURCES", "deploy,github,jenkins,airflow").split(",") if s.strip()])
    lookback_hours: int = int(env("HEAL_LOOKBACK_HOURS", "24"))
    wait_timeout: int = int(env("HEAL_WAIT_TIMEOUT", "900"))        # seconds to wait when validating a fix
    runtime_dir: Path = Path(env("HEAL_RUNTIME_DIR", str(ROOT / "runtime")))

    # Model: LLM_PROVIDER=anthropic|openai (empty = whichever key is set)
    provider: str = field(default_factory=_provider)
    model: str = env("CLAUDE_MODEL", "claude-opus-5-5")
    effort: str = env("CLAUDE_EFFORT", "medium")
    fallbacks: bool = env("CLAUDE_FALLBACKS", "1") == "1"
    openai_model: str = env("OPENAI_MODEL", "gpt-5.5")
    openai_base_url: str = env("OPENAI_BASE_URL")              # Azure OpenAI / OpenAI-compatible servers
    openai_api_style: str = env("OPENAI_API_STYLE", "responses")   # responses | chat
    openai_reasoning_effort: str = env("OPENAI_REASONING_EFFORT", "medium")   # empty for non-reasoning models

    # GitHub Actions
    github_repo: str = env("GITHUB_REPO")
    github_token: str = field(default_factory=_github_token)
    github_workflow: str = env("GITHUB_WORKFLOW", "ci.yml")
    github_api: str = env("GITHUB_API_URL", "https://api.github.com")

    # Jenkins
    jenkins_url: str = local_url("JENKINS_URL")
    jenkins_user: str = env("JENKINS_USER", "admin")
    jenkins_token: str = env("JENKINS_TOKEN")
    jenkins_job: str = env("JENKINS_JOB", "traffic-api-ci")

    # Argo CD
    argocd_url: str = local_url("ARGOCD_URL")
    argocd_user: str = env("ARGOCD_USER", "admin")
    argocd_password: str = env("ARGOCD_PASSWORD")
    argocd_token: str = env("ARGOCD_TOKEN")
    argocd_app: str = env("ARGOCD_APP", "traffic-api")
    argocd_verify_tls: bool = env("ARGOCD_VERIFY_TLS", "false") == "true"

    # Airflow 3 (REST API v2)
    airflow_url: str = local_url("AIRFLOW_URL")
    airflow_user: str = env("AIRFLOW_USER", "admin")
    airflow_password: str = env("AIRFLOW_PASSWORD")
    airflow_dag: str = env("AIRFLOW_DAG", "traffic_probe_daily")

    # The service the pipelines deliver (deploy monitor + dependency health)
    service_url: str = local_url("SERVICE_URL")
    smoke_p95_ms: float = float(env("SMOKE_P95_MS", "800"))
    smoke_max_error_pct: float = float(env("SMOKE_MAX_ERROR_PCT", "1.0"))

    # Escalation: "github_issue" (needs GitHub settings) or "stdout"
    escalation: str = env("HEAL_ESCALATION", "github_issue")


SETTINGS = Settings()
