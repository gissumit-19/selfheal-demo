"""Apache Airflow 3, through the stable REST API (v2). Reads failed DAG runs, task instances
and task logs; can clear failed tasks so the scheduler re-runs them. Auth: a JWT from
POST /auth/token (simple auth manager or FAB). For Airflow 2.x, swap /api/v2 for /api/v1
and use basic auth; the method names stay the same."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests


def _q(s: str) -> str:
    return quote(s, safe="")


class Airflow:
    name = "airflow"

    def __init__(self, url: str, user: str, password: str, dag_id: str):
        self.url, self.dag = url.rstrip("/"), dag_id
        self.http = requests.Session()
        r = self.http.post(f"{self.url}/auth/token", json={"username": user, "password": password}, timeout=30)
        r.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def _req(self, method: str, path: str, **kw) -> requests.Response:
        r = self.http.request(method, f"{self.url}/api/v2/dags/{_q(self.dag)}{path}", timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Airflow {method} {path}: {r.status_code} {r.text[:300]}")
        return r

    # ---------------- read ----------------
    def failed_runs(self, since_hours: int = 24) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        runs = self._req("GET", "/dagRuns", params={"state": "failed", "order_by": "-start_date", "limit": 20,
                                                    "start_date_gte": since}).json()["dag_runs"]
        return [{"dag_run_id": r["dag_run_id"], "state": r["state"], "start_date": r.get("start_date"),
                 "end_date": r.get("end_date"), "run_type": r.get("run_type")} for r in runs]

    def run_state(self, dag_run_id: str) -> str:
        return self._req("GET", f"/dagRuns/{_q(dag_run_id)}").json()["state"]

    def failed_tasks(self, dag_run_id: str) -> list[dict]:
        tis = self._req("GET", f"/dagRuns/{_q(dag_run_id)}/taskInstances").json()["task_instances"]
        return [{"task_id": t["task_id"], "state": t["state"], "try_number": t.get("try_number", 1)}
                for t in tis if t["state"] in ("failed", "upstream_failed")]

    def task_log(self, dag_run_id: str, task_id: str, try_number: int) -> str:
        r = self._req("GET", f"/dagRuns/{_q(dag_run_id)}/taskInstances/{_q(task_id)}/logs/{try_number}",
                      params={"full_content": "true"}, headers={"Accept": "application/json"})
        content = r.json().get("content", "")
        if isinstance(content, list):                     # structured log lines in Airflow 3
            lines = []
            for c in content:
                if isinstance(c, dict):
                    lines.append(" ".join(str(c.get(k, "")) for k in ("timestamp", "level", "event") if c.get(k)))
                    if c.get("error_detail"):
                        lines.append(str(c["error_detail"]))
                else:
                    lines.append(str(c))
            return "\n".join(lines)
        return str(content)

    # ---------------- actions ----------------
    def clear_failed(self, dag_run_id: str) -> str:
        tasks = [t["task_id"] for t in self.failed_tasks(dag_run_id)]
        self._req("POST", "/clearTaskInstances", json={
            "dry_run": False, "dag_run_id": dag_run_id, "task_ids": tasks, "only_failed": True,
            "include_downstream": True, "reset_dag_runs": True})
        return f"cleared {tasks} in {dag_run_id}"

    def wait_for_run(self, dag_run_id: str, timeout: int = 600) -> str:
        deadline = time.time() + timeout
        time.sleep(5)
        while time.time() < deadline:
            state = self.run_state(dag_run_id)
            if state in ("success", "failed"):
                return state
            time.sleep(5)
        return "timed_out_waiting"

    def trigger(self) -> str:
        r = self._req("POST", "/dagRuns", json={"logical_date": None, "conf": {}})
        return r.json()["dag_run_id"]

    def wait_for_dag(self, timeout: int = 180) -> None:
        """A new DAG file takes the dag processor a little while to parse."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.http.get(f"{self.url}/api/v2/dags/{_q(self.dag)}", timeout=30).status_code == 200:
                return
            time.sleep(5)
        raise TimeoutError(f"Airflow has not loaded DAG {self.dag} after {timeout}s: check airflow/dags is mounted")

    def unpause(self) -> None:
        self._req("PATCH", "", json={"is_paused": False})
