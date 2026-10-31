"""Argo CD, through its REST API. Reads an Application's health, sync state and deployment
history; can roll back to an earlier history entry and sync. Rollback needs the app's
automated sync to be OFF (Argo CD refuses a rollback while auto-sync would undo it)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests
import urllib3


class ArgoCD:
    name = "argocd"

    def __init__(self, url: str, app: str, user: str = "", password: str = "", token: str = "", verify_tls: bool = True):
        self.url, self.app_name = url.rstrip("/"), app
        self.http = requests.Session()
        self.http.verify = verify_tls
        if not verify_tls:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        if not token:
            r = self.http.post(f"{self.url}/api/v1/session", json={"username": user, "password": password}, timeout=30)
            r.raise_for_status()
            token = r.json()["token"]
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _req(self, method: str, path: str, **kw) -> requests.Response:
        r = self.http.request(method, f"{self.url}/api/v1{path}", timeout=60, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Argo CD {method} {path}: {r.status_code} {r.text[:300]}")
        return r

    # ---------------- read ----------------
    def app(self) -> dict:
        a = self._req("GET", f"/applications/{self.app_name}").json()
        st = a.get("status", {})
        history = [{"id": h["id"], "revision": h.get("revision", "")[:7], "deployed_at": h.get("deployedAt")}
                   for h in st.get("history", [])][-5:]
        op = st.get("operationState", {})
        return {"app": self.app_name, "health": st.get("health", {}).get("status"),
                "sync": st.get("sync", {}).get("status"), "revision": st.get("sync", {}).get("revision", "")[:7],
                "operation": op.get("phase"), "operation_message": op.get("message", "")[:200],
                "auto_sync": bool(a.get("spec", {}).get("syncPolicy", {}).get("automated")),
                "history": history}

    @staticmethod
    def minutes_since(iso: str | None) -> float:
        if not iso:
            return 1e9
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 60

    # ---------------- actions ----------------
    def rollback(self, history_id: int) -> str:
        self._req("POST", f"/applications/{self.app_name}/rollback",
                  json={"name": self.app_name, "id": history_id, "prune": False})
        return f"{self.app_name} rollback to history id {history_id} started"

    def sync(self, revision: str = "HEAD") -> str:
        self._req("GET", f"/applications/{self.app_name}", params={"refresh": "hard"})   # re-read git now
        self._req("POST", f"/applications/{self.app_name}/sync", json={"name": self.app_name, "revision": revision, "prune": True})
        return f"{self.app_name} sync to {revision} started"

    def wait_settled(self, timeout: int = 300) -> dict:
        deadline = time.time() + timeout
        time.sleep(3)
        while time.time() < deadline:
            a = self.app()
            if a["operation"] in ("Succeeded", "Failed", "Error") and a["health"] in ("Healthy", "Degraded"):
                return a
            time.sleep(5)
        return self.app()
