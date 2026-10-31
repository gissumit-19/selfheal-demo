"""GitHub Actions, through the GitHub REST API. Reads runs, jobs, logs and commits; can re-run
failed jobs and open issues. Needs a token with `actions: write` and `issues: write`
(the workflow GITHUB_TOKEN, a fine-grained PAT, or `gh auth token`)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests


class GitHubActions:
    name = "github"

    def __init__(self, repo: str, token: str, workflow: str = "ci.yml", api: str = "https://api.github.com"):
        self.repo, self.workflow = repo, workflow
        self.base = f"{api.rstrip('/')}/repos/{repo}"
        self.http = requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                  "X-GitHub-Api-Version": "2022-11-28"})

    def _req(self, method: str, path: str, **kw) -> requests.Response:
        r = self.http.request(method, self.base + path, timeout=30, **kw)
        r.raise_for_status()
        return r

    # ---------------- read ----------------
    def failed_runs(self, since_hours: int = 24) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = self._req("GET", f"/actions/workflows/{self.workflow}/runs",
                         params={"status": "failure", "per_page": 20, "created": f">={since}"}).json()["workflow_runs"]
        return [self._summary(r) for r in runs]

    def run(self, run_id: int) -> dict:
        return self._summary(self._req("GET", f"/actions/runs/{run_id}").json())

    @staticmethod
    def _summary(r: dict) -> dict:
        return {"run_id": r["id"], "workflow": r["name"], "status": r["status"], "conclusion": r["conclusion"],
                "run_attempt": r.get("run_attempt", 1), "branch": r["head_branch"], "sha": r["head_sha"],
                "event": r["event"], "title": r.get("display_title", ""), "created_at": r["created_at"],
                "url": r["html_url"], "actor": (r.get("actor") or {}).get("login", "")}

    def failed_jobs(self, run_id: int) -> list[dict]:
        jobs = self._req("GET", f"/actions/runs/{run_id}/jobs", params={"filter": "latest"}).json()["jobs"]
        return [{"job_id": j["id"], "name": j["name"], "conclusion": j["conclusion"],
                 "failed_steps": [s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"]}
                for j in jobs if j["conclusion"] == "failure"]

    def job_log(self, job_id: int) -> str:
        # 302 to a signed blob URL; requests drops the auth header on the cross-host redirect, as it should.
        return self._req("GET", f"/actions/jobs/{job_id}/logs").text

    def commit(self, sha: str) -> dict:
        c = self._req("GET", f"/commits/{sha}").json()
        return {"sha": sha[:7], "message": c["commit"]["message"].splitlines()[0],
                "author": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
                "files": [f["filename"] for f in c.get("files", [])][:50]}

    # ---------------- actions ----------------
    def rerun_failed_jobs(self, run_id: int) -> str:
        self._req("POST", f"/actions/runs/{run_id}/rerun-failed-jobs")
        return f"re-run of failed jobs requested for run {run_id}"

    def wait_for_run(self, run_id: int, min_attempt: int, timeout: int = 900) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.run(run_id)
            if r["run_attempt"] >= min_attempt and r["status"] == "completed":
                return r
            time.sleep(10)
        return {**self.run(run_id), "conclusion": "timed_out_waiting"}

    def dispatch(self, ref: str = "main", inputs: dict | None = None) -> None:
        self._req("POST", f"/actions/workflows/{self.workflow}/dispatches", json={"ref": ref, "inputs": inputs or {}})

    # ---------------- escalation ----------------
    def open_issue(self, title: str, body: str, labels: list[str]) -> str:
        existing = self._req("GET", "/issues", params={"state": "open", "labels": ",".join(labels), "per_page": 50}).json()
        for i in existing:
            if i["title"] == title:
                self._req("POST", f"/issues/{i['number']}/comments", json={"body": body})
                return f"commented on existing issue #{i['number']}: {i['html_url']}"
        i = self._req("POST", "/issues", json={"title": title, "body": body, "labels": labels}).json()
        return f"opened issue #{i['number']}: {i['html_url']}"
