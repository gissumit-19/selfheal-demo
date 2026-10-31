"""Brings up the real systems on this machine. Same command on every OS:

    python infra/up.py

  kind cluster "heal-demo" + Argo CD + the traffic-api Application (GitOps from your GitHub repo)
  Jenkins (JCasC, job traffic-api-ci) and Airflow 3 (DAG traffic_probe_daily) in Docker Compose
Every kubectl call uses --context kind-heal-demo. Your other clusters are never touched.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

from _common import CTX, ENV_FILE, ROOT, has, kubectl, out, read_env, run, set_env_value

ARGO_VERSION = os.getenv("ARGO_VERSION", "stable")


def wait_http(name: str, url: str, auth: tuple[str, str] | None = None, timeout: int = 900) -> None:
    print(f"waiting for {name} ", end="", flush=True)
    headers = {}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
                if r.status == 200:
                    print(" up")
                    return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(5)
    sys.exit(f"\n{name} did not come up in {timeout}s: run `docker compose -f infra/compose.yaml logs` to see why")


def main() -> None:
    for tool, how in [("docker", "Docker Desktop"), ("kind", "kind"), ("kubectl", "kubectl")]:
        if not has(tool):
            sys.exit(f"missing: {tool} (install {how}, see the guide), then run `python infra/preflight.py`")
    if not out("docker", "info", "--format", "{{.ServerVersion}}"):
        sys.exit("Docker is not running: start Docker Desktop")
    if not ENV_FILE.exists():
        sys.exit("copy .env.example to .env and fill it in first")
    env = read_env()
    repo = env.get("GITHUB_REPO", "")
    if not repo or repo.startswith("your-user/"):
        sys.exit("set GITHUB_REPO=<your-user>/selfheal-demo in .env")

    print("==> kind cluster")
    if "heal-demo" not in out("kind", "get", "clusters").split():
        previous = out("kubectl", "config", "current-context")
        run("kind", "create", "cluster", "--config", str(ROOT / "infra" / "kind-config.yaml"))
        if previous and previous != CTX:                  # kind switches the current context; put yours back
            run("kubectl", "config", "use-context", previous, capture=True)
            print(f"(your kubectl context is still '{previous}'; the demo uses --context {CTX})")
    kubectl("get", "nodes")

    print(f"==> Argo CD ({ARGO_VERSION})")
    ns = kubectl("create", "namespace", "argocd", check=False, capture=True)
    if ns.returncode and "AlreadyExists" not in ns.stderr:
        sys.exit(ns.stderr)
    kubectl("apply", "-n", "argocd", "--server-side", "--force-conflicts", "-f",
            f"https://raw.githubusercontent.com/argoproj/argo-cd/{ARGO_VERSION}/manifests/install.yaml", capture=True)
    kubectl("-n", "argocd", "rollout", "status", "deploy/argocd-server", "--timeout=300s")
    patch = {"spec": {"type": "NodePort", "ports": [{"name": "https", "port": 443, "targetPort": 8080, "nodePort": 30443}]}}
    kubectl("-n", "argocd", "patch", "svc", "argocd-server", "--type", "merge", "-p", json.dumps(patch), capture=True)
    for _ in range(30):                                   # the secret appears a few seconds after the server
        b64 = kubectl("-n", "argocd", "get", "secret", "argocd-initial-admin-secret", "-o", "jsonpath={.data.password}",
                      check=False, capture=True).stdout
        if b64:
            set_env_value("ARGOCD_PASSWORD", base64.b64decode(b64).decode())
            break
        time.sleep(5)
    else:
        sys.exit("Argo CD admin secret not found")

    print(f"==> Argo CD Application traffic-api -> github.com/{repo} (path service/)")
    app = (ROOT / "infra" / "argocd-app.yaml").read_text(encoding="utf-8").replace("__GITHUB_REPO__", repo)
    kubectl("apply", "-f", "-", stdin=app)

    print("==> Jenkins + Airflow")
    run("docker", "compose", "-f", str(ROOT / "infra" / "compose.yaml"), "--env-file", str(ENV_FILE), "up", "-d", "--build")
    env = read_env()
    wait_http("Jenkins", f"{env.get('JENKINS_URL', 'http://localhost:8081')}/api/json", ("admin", env.get("JENKINS_TOKEN", "")))
    wait_http("Airflow", f"{env.get('AIRFLOW_URL', 'http://localhost:8082')}/api/v2/monitor/health")

    print(f"""
All systems up:
  Argo CD  https://localhost:30443  (admin / see ARGOCD_PASSWORD in .env)
  Jenkins  {env.get('JENKINS_URL')}  (admin / JENKINS_TOKEN)
  Airflow  {env.get('AIRFLOW_URL')}  (admin / admin)
Next: python scenarios.py bootstrap   (first Argo CD sync of traffic-api)""")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\ncommand failed: {' '.join(e.cmd)}\n{e.stderr or ''}")
