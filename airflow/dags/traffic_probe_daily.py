"""traffic_probe_daily: extract probe segments, then publish them to traffic-api.
publish_traffic_api fails for real whenever the deployed traffic-api is broken."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from airflow.sdk import dag, task

API = os.environ.get("TRAFFIC_API_URL", "http://host.docker.internal:30080")


@dag(schedule=None, start_date=datetime(2026, 1, 1), catchup=False, tags=["heal-demo"])
def traffic_probe_daily():
    @task
    def extract_probes() -> list[str]:
        return [f"seg-{i}" for i in range(120)]

    @task(retries=0)
    def publish_traffic_api(segment_ids: list[str]) -> int:
        req = urllib.request.Request(f"{API}/v3/segments/bulk", data=json.dumps({"segment_ids": segment_ids}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            body = json.load(urllib.request.urlopen(req, timeout=10))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"POST {API}/v3/segments/bulk -> HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")
        print(f"published {len(body['segments'])} segments to traffic-api {body['version']}")
        return len(body["segments"])

    publish_traffic_api(extract_probes())


traffic_probe_daily()
