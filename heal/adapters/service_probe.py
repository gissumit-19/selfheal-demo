"""Black-box probe of the delivered service: the same smoke check a pipeline runs after a
deploy. Real HTTP calls; measures error rate and p95 latency against the budgets."""
from __future__ import annotations

import statistics
import time

import requests

from heal.adapters._http import local_session


class ServiceProbe:
    name = "service"

    def __init__(self, url: str, p95_budget_ms: float = 800, max_error_pct: float = 1.0, requests_per_probe: int = 20):
        self.url, self.p95_budget, self.max_err, self.n = url.rstrip("/"), p95_budget_ms, max_error_pct, requests_per_probe
        self.http = local_session()

    def probe(self) -> dict:
        version, errors, latencies, samples = "unknown", 0, [], []
        try:
            version = self.http.get(f"{self.url}/healthz", timeout=5).json().get("version", "unknown")
        except (requests.RequestException, ValueError) as e:
            return {"healthy": False, "reachable": False, "detail": f"{self.url}/healthz unreachable: {e}"}
        ids = [f"seg-{i}" for i in range(120)]              # same payload the Airflow DAG publishes
        for _ in range(self.n):
            t = time.perf_counter()
            try:
                r = self.http.post(f"{self.url}/v3/segments/bulk", json={"segment_ids": ids}, timeout=5)
                ok = r.status_code == 200
                if not ok and len(samples) < 2:
                    samples.append(f"{r.status_code}: {r.text[:160]}")
            except requests.RequestException as e:
                ok = False
                if len(samples) < 2:
                    samples.append(str(e)[:160])
            latencies.append((time.perf_counter() - t) * 1000)
            errors += not ok
        p95 = statistics.quantiles(latencies, n=20)[-1] if len(latencies) >= 2 else latencies[0]
        err_pct = 100 * errors / self.n
        healthy = err_pct <= self.max_err and p95 <= self.p95_budget
        return {"healthy": healthy, "reachable": True, "version": version, "error_rate_pct": round(err_pct, 1),
                "p95_ms": round(p95), "budget": f"errors <= {self.max_err}%, p95 <= {self.p95_budget:.0f} ms",
                "sample_errors": samples}
