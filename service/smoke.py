"""Post-deploy smoke check, run by Jenkins against the deployed traffic-api.
Same budget the agent's probe uses: error rate <= 1%, p95 <= 800 ms.

    python3 service/smoke.py http://localhost:30080
"""
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:30080").rstrip("/")
ids = [f"seg-{i}" for i in range(120)]
errors, lat, first_error = 0, [], ""
version = json.load(urllib.request.urlopen(f"{url}/healthz", timeout=5)).get("version")
for _ in range(20):
    t = time.perf_counter()
    req = urllib.request.Request(f"{url}/v3/segments/bulk", data=json.dumps({"segment_ids": ids}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except urllib.error.HTTPError as e:
        errors += 1
        first_error = first_error or f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
    except Exception as e:
        errors += 1
        first_error = first_error or str(e)
    lat.append((time.perf_counter() - t) * 1000)
p95 = statistics.quantiles(lat, n=20)[-1]
err = 100 * errors / len(lat)
print(f"traffic-api {version}: error rate {err:.1f}% (budget 1.0%), p95 {p95:.0f} ms (budget 800)")
if err > 1.0 or p95 > 800:
    print(f"SMOKE FAILED: {first_error}")
    sys.exit(1)
print("SMOKE PASSED")
