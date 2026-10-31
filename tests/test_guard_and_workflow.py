"""Offline contract tests: fakes implement the same ports as the real adapters, so the guard and
the workflow are tested without network or model. (The demo itself never uses these fakes.)"""
from __future__ import annotations

from dataclasses import replace

import pytest

from heal import workflow
from heal.config import Settings
from heal.context import Context
from heal.memory import Memory
from heal.policy import guard
from heal.ports import Incident
from heal.redact import redact


class FakeGitHub:
    def __init__(self, files=("README.md",), attempt=1, rerun_result="success"):
        self.files, self.attempt, self.rerun_result, self.reruns, self.issues = list(files), attempt, rerun_result, 0, []

    def run(self, run_id):
        return {"run_id": run_id, "run_attempt": self.attempt, "sha": "abc1234", "status": "completed",
                "conclusion": "failure", "workflow": "ci", "branch": "main", "url": "u"}

    def commit(self, sha):
        return {"sha": sha[:7], "message": "m", "author": "dev", "files": self.files}

    def rerun_failed_jobs(self, run_id):
        self.reruns += 1
        return "rerun requested"

    def wait_for_run(self, run_id, min_attempt, timeout):
        return {"run_attempt": min_attempt, "conclusion": self.rerun_result}

    def open_issue(self, title, body, labels):
        self.issues.append(title)
        return f"opened issue #{len(self.issues)}"


class FakeService:
    def __init__(self, healthy):
        self.healthy = healthy

    def probe(self):
        return {"healthy": self.healthy, "reachable": True, "version": "1.1.0", "error_rate_pct": 0 if self.healthy else 100,
                "p95_ms": 5, "budget": "b"}


class FakeArgo:
    def __init__(self):
        self.hist = [{"id": 1, "revision": "aaaaaaa", "deployed_at": "2099-01-01T00:00:00Z"},
                     {"id": 2, "revision": "bbbbbbb", "deployed_at": "2099-01-01T00:00:00Z"}]

    def app(self):
        return {"revision": "bbbbbbb", "history": self.hist, "health": "Healthy", "sync": "Synced"}

    @staticmethod
    def minutes_since(iso):
        return 5


class FakeJenkins:
    def __init__(self, by="user"):
        self.by = by

    def build(self, n):
        return {"number": n, "params": {"TRIGGERED_BY": self.by}}


class FakeAirflow:
    def run_state(self, r):
        return "failed"


@pytest.fixture
def ctx(tmp_path):
    s = replace(Settings(), runtime_dir=tmp_path, escalation="github_issue", wait_timeout=1)
    return Context(settings=s, memory=Memory(tmp_path), github=FakeGitHub(), service=FakeService(True),
                   argocd=FakeArgo(), jenkins=FakeJenkins(), airflow=FakeAirflow())


def test_unknown_action_denied(ctx):
    assert guard("run_sql", {}, ctx, "k", "s").verdict == "deny"


def test_gha_rerun_docs_only_first_attempt_is_auto(ctx):
    assert guard("gha_rerun_failed_jobs", {"run_id": 1}, ctx, "k", "TimeoutError").verdict == "auto"


def test_gha_rerun_denied_when_commit_changed_code(ctx):
    ctx.github.files = ["service/app.py"]
    d = guard("gha_rerun_failed_jobs", {"run_id": 1}, ctx, "k", "AssertionError test_to_mps")
    assert d.verdict == "deny" and "changed code" in d.reason


def test_gha_rerun_allowed_for_code_change_when_memory_proves_flake(ctx):
    ctx.github.files = ["service/app.py"]
    for i in range(2):
        ctx.memory.add_history("TimeoutError in test_eta_cache_refresh", "github", "gha_rerun_failed_jobs", "resolved", f"i{i}")
    assert guard("gha_rerun_failed_jobs", {"run_id": 1}, ctx, "k", "TimeoutError in test_eta_cache_refresh").verdict == "auto"


def test_gha_rerun_denied_on_second_attempt(ctx):
    ctx.github.attempt = 2
    assert guard("gha_rerun_failed_jobs", {"run_id": 1}, ctx, "k", "s").verdict == "deny"


def test_attempt_limit_from_memory(ctx):
    ctx.memory.record_attempt("k", "gha_rerun_failed_jobs", "done")
    d = guard("gha_rerun_failed_jobs", {"run_id": 1}, ctx, "k", "s")
    assert d.verdict == "deny" and "already tried" in d.reason


def test_missing_param_denied(ctx):
    assert guard("argocd_rollback", {"history_id": None}, ctx, "k", "s").verdict == "deny"


def test_rollback_needs_approval_when_unhealthy_and_target_is_previous(ctx):
    ctx.service.healthy = False
    assert guard("argocd_rollback", {"history_id": 1}, ctx, "k", "s").verdict == "approval"


def test_rollback_denied_to_wrong_revision_or_when_healthy(ctx):
    ctx.service.healthy = False
    assert guard("argocd_rollback", {"history_id": 2}, ctx, "k", "s").verdict == "deny"
    ctx.service.healthy = True
    assert guard("argocd_rollback", {"history_id": 1}, ctx, "k", "s").verdict == "deny"


def test_airflow_clear_denied_while_dependency_unhealthy(ctx):
    ctx.service.healthy = False
    assert guard("airflow_clear_failed", {"dag_run_id": "r"}, ctx, "k", "s").verdict == "deny"
    ctx.service.healthy = True
    assert guard("airflow_clear_failed", {"dag_run_id": "r"}, ctx, "k", "s").verdict == "auto"


def test_jenkins_does_not_rebuild_its_own_rebuild(ctx):
    ctx.jenkins.by = "heal-agent"
    assert guard("jenkins_rebuild", {"build_number": 7}, ctx, "k", "s").verdict == "deny"


def test_unreachable_system_means_deny(ctx):
    ctx.argocd = None
    ctx.service.healthy = False
    d = guard("argocd_rollback", {"history_id": 1}, ctx, "k", "s")
    assert d.verdict == "deny" and "could not be checked" in d.reason


def _rca(action, **params):
    p = {"run_id": None, "build_number": None, "history_id": None, "dag_run_id": None, **params}
    return {"category": "flaky_test", "signature": "TimeoutError in test_eta_cache_refresh", "root_cause": "rc",
            "evidence": "ev", "proposed_action": action, "params": p, "why": "w", "owner": "o", "confidence": "high"}


INC = Incident(key="github:1:1", source="github", ref="1", title="ci failed", evidence="e")


def test_workflow_rerun_resolves_and_learns(ctx, monkeypatch):
    monkeypatch.setattr(workflow, "investigate", lambda *a, **k: _rca("gha_rerun_failed_jobs", run_id=1))
    assert workflow.handle(ctx, None, INC, execute=True) == "resolved"
    assert ctx.github.reruns == 1 and ctx.memory.is_processed(INC.key)
    assert ctx.memory.resolved_count("TimeoutError in test_eta_cache_refresh", "gha_rerun_failed_jobs") == 1


def test_workflow_failed_fix_escalates_after_one_attempt(ctx, monkeypatch):
    ctx.github.rerun_result = "failure"
    monkeypatch.setattr(workflow, "investigate", lambda *a, **k: _rca("gha_rerun_failed_jobs", run_id=1))
    assert workflow.handle(ctx, None, INC, execute=True) == "escalated"
    assert ctx.github.reruns == 1 and len(ctx.github.issues) == 1


def test_dry_run_changes_nothing(ctx, monkeypatch):
    monkeypatch.setattr(workflow, "investigate", lambda *a, **k: _rca("gha_rerun_failed_jobs", run_id=1))
    assert workflow.handle(ctx, None, INC, execute=False) == "dry_run"
    assert ctx.github.reruns == 0 and not ctx.memory.is_processed(INC.key) and not ctx.github.issues


def test_declined_approval_escalates(ctx, monkeypatch):
    ctx.service.healthy = False
    monkeypatch.setenv("AUTO_APPROVE", "no")
    monkeypatch.setattr(workflow, "investigate", lambda *a, **k: _rca("argocd_rollback", history_id=1))
    assert workflow.handle(ctx, None, INC, execute=True) == "escalated"
    assert ctx.github.issues


def test_redaction():
    fake = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
    out = redact(f"token={fake} password: hunter2 Bearer abcdefghijklmnopqrstu")
    assert "ghp_" not in out and "hunter2" not in out and "abcdefghijklmnopqrstu" not in out
