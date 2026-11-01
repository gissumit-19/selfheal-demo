"""HTTP sessions for the LOCAL systems (traffic-api, Jenkins, Argo CD, Airflow on this machine).

They never need a proxy, so proxy settings are ignored (trust_env=False). This matters on corporate
Windows laptops: with a system proxy configured, requests consults the Windows proxy-bypass list on
EVERY request, which does a reverse-DNS lookup (socket.getfqdn) that can take ~2 s. The service probe
then measured p95 > 2000 ms for a service that answers in 8 ms, and the guard refused rebuilds.
GitHub and the model APIs keep using the proxy settings (they may need them)."""
from __future__ import annotations

import requests


def local_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    return s
