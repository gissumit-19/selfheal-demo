"""Jenkins, through its JSON REST API. Reads builds, stages (pipeline-stage-view plugin) and
console output; can rebuild with the same parameters. Use an API token (user > Security >
API token); a password also works because we fetch a CSRF crumb for POSTs."""
from __future__ import annotations

import time
from urllib.parse import quote

import requests

from heal.adapters._http import local_session

TREE = "number,result,building,timestamp,duration,url,actions[parameters[name,value],causes[shortDescription]]"


class Jenkins:
    name = "jenkins"

    def __init__(self, url: str, user: str, token: str, job: str):
        self.url, self.job = url.rstrip("/"), job
        self.job_url = f"{self.url}/job/{quote(job)}"
        self.http = local_session()
        self.http.auth = (user, token)
        self._crumb: dict | None = None

    def _get(self, url: str, **kw) -> requests.Response:
        r = self.http.get(url, timeout=30, **kw)
        r.raise_for_status()
        return r

    def _post(self, url: str, **kw) -> requests.Response:
        if self._crumb is None:
            try:
                c = self._get(f"{self.url}/crumbIssuer/api/json").json()
                self._crumb = {c["crumbRequestField"]: c["crumb"]}
            except requests.HTTPError:
                self._crumb = {}                       # CSRF protection off, or API-token auth
        r = self.http.post(url, headers=self._crumb, timeout=30, **kw)
        r.raise_for_status()
        return r

    @staticmethod
    def _summary(b: dict) -> dict:
        params, causes = {}, []
        for a in b.get("actions", []):
            for p in a.get("parameters", []) or []:
                params[p["name"]] = p.get("value")
            causes += [c.get("shortDescription", "") for c in a.get("causes", []) or []]
        return {"number": b["number"], "result": b.get("result"), "building": b.get("building"),
                "started_ms": b.get("timestamp"), "url": b.get("url"), "params": params, "causes": causes}

    # ---------------- read ----------------
    def failed_builds(self, since_hours: int = 24) -> list[dict]:
        builds = self._get(f"{self.job_url}/api/json", params={"tree": f"builds[{TREE}]{{0,20}}"}).json()["builds"]
        cutoff = (time.time() - since_hours * 3600) * 1000
        return [self._summary(b) for b in builds
                if b.get("result") == "FAILURE" and not b.get("building") and b.get("timestamp", 0) >= cutoff]

    def build(self, number: int) -> dict:
        b = self._summary(self._get(f"{self.job_url}/{number}/api/json", params={"tree": TREE}).json())
        try:
            stages = self._get(f"{self.job_url}/{number}/wfapi/describe").json().get("stages", [])
            b["stages"] = [{"name": s["name"], "status": s["status"]} for s in stages]
        except requests.HTTPError:
            b["stages"] = []
        return b

    def console_tail(self, number: int) -> str:
        return self._get(f"{self.job_url}/{number}/consoleText").text

    # ---------------- actions ----------------
    def rebuild(self, number: int) -> int:
        """Start a new build with the same parameters, marked TRIGGERED_BY=heal-agent. Returns its number."""
        params = {**self.build(number)["params"], "TRIGGERED_BY": "heal-agent"}
        r = self._post(f"{self.job_url}/buildWithParameters", params=params)
        queue = r.headers["Location"].rstrip("/")
        for _ in range(120):
            item = self._get(f"{queue}/api/json").json()
            if item.get("executable"):
                return item["executable"]["number"]
            if item.get("cancelled"):
                raise RuntimeError("Jenkins cancelled the queued build")
            time.sleep(2)
        raise TimeoutError("build stayed in the Jenkins queue for 4 minutes")

    def wait_for_build(self, number: int, timeout: int = 900) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            b = self._summary(self._get(f"{self.job_url}/{number}/api/json", params={"tree": TREE}).json())
            if not b["building"] and b["result"]:
                return b
            time.sleep(5)
        return {"number": number, "result": "TIMED_OUT_WAITING"}

    def trigger(self, params: dict) -> None:
        self._post(f"{self.job_url}/buildWithParameters", params=params)
