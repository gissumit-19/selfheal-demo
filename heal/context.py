"""Builds the adapters that are configured. A missing system is simply absent: the agent
gets no tools for it and the guard denies any action that needs it."""
from __future__ import annotations

from dataclasses import dataclass, field

from heal.adapters.airflow import Airflow
from heal.adapters.argocd import ArgoCD
from heal.adapters.github_actions import GitHubActions
from heal.adapters.jenkins import Jenkins
from heal.adapters.service_probe import ServiceProbe
from heal.config import Settings
from heal.memory import Memory


@dataclass
class Context:
    settings: Settings
    memory: Memory
    github: GitHubActions | None = None
    jenkins: Jenkins | None = None
    argocd: ArgoCD | None = None
    airflow: Airflow | None = None
    service: ServiceProbe | None = None
    errors: dict = field(default_factory=dict)      # adapter -> why it could not be built


def build_context(s: Settings) -> Context:
    ctx = Context(settings=s, memory=Memory(s.runtime_dir))
    builders = {
        "github": (s.github_repo and s.github_token,
                   lambda: GitHubActions(s.github_repo, s.github_token, s.github_workflow, s.github_api)),
        "jenkins": (s.jenkins_url and s.jenkins_token,
                    lambda: Jenkins(s.jenkins_url, s.jenkins_user, s.jenkins_token, s.jenkins_job)),
        "argocd": (s.argocd_url and (s.argocd_token or s.argocd_password),
                   lambda: ArgoCD(s.argocd_url, s.argocd_app, s.argocd_user, s.argocd_password, s.argocd_token, s.argocd_verify_tls)),
        "airflow": (s.airflow_url and s.airflow_password,
                    lambda: Airflow(s.airflow_url, s.airflow_user, s.airflow_password, s.airflow_dag)),
        "service": (s.service_url,
                    lambda: ServiceProbe(s.service_url, s.smoke_p95_ms, s.smoke_max_error_pct)),
    }
    wanted = set(s.sources) | ({"service", "argocd"} if "deploy" in s.sources else set())
    for name, (configured, build) in builders.items():
        if name not in wanted and not (name == "github" and s.escalation == "github_issue"):
            continue
        if not configured:
            ctx.errors[name] = "not configured"
            continue
        try:
            setattr(ctx, name, build())
        except Exception as e:                       # unreachable system: keep going without it
            ctx.errors[name] = f"{type(e).__name__}: {e}"
    return ctx
