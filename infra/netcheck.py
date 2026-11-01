"""Why does traffic-api look slow from this machine? Measures each step separately. Changes nothing.

    python infra/netcheck.py
"""
from __future__ import annotations

import socket
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402

from heal.adapters._http import local_session  # noqa: E402
from heal.config import SETTINGS  # noqa: E402


def ms(fn, n: int = 5) -> str:
    times = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            fn()
        except Exception as e:
            return f"ERROR {type(e).__name__}: {str(e)[:80]}"
        times.append((time.perf_counter() - t) * 1000)
    return f"{statistics.median(times):7.0f} ms"


url = SETTINGS.service_url or "http://127.0.0.1:30080"
host, port = url.split("//")[1].split("/")[0].rsplit(":", 1)
print(f"agent uses           : {url}   {'(OK)' if '127.0.0.1' in url else '(update to the latest version: should be 127.0.0.1)'}")
print(f"proxy settings seen  : {urllib.request.getproxies() or 'none'}")
if sys.platform == "win32":
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enabled = winreg.QueryValueEx(k, "ProxyEnable")[0]
        print(f"Windows system proxy : {'ON' if enabled else 'off'}")
    except OSError:
        print("Windows system proxy : (not readable)")
print()
print(f"reverse DNS of {host:<9}: {ms(lambda: socket.getfqdn(host), 3)}   (slow here = corporate DNS)")
print(f"TCP connect          : {ms(lambda: socket.create_connection((host, int(port)), 5).close())}")
print(f"requests, OLD way    : {ms(lambda: requests.get(url + '/healthz', timeout=10))}   (reads proxy settings every call)")
s = local_session()
print(f"requests, NEW way    : {ms(lambda: s.get(url + '/healthz', timeout=10))}   (what the agent uses now)")
print(f"probe request (POST) : {ms(lambda: s.post(url + '/v3/segments/bulk', json={'segment_ids': [f'seg-{i}' for i in range(120)]}, timeout=10))}")
print("\nNEW way and probe request under ~100 ms = fixed. If only OLD way is slow, it was the proxy lookup (fixed by the update).")
