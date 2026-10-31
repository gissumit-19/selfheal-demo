#!/usr/bin/env bash
# Brings up the real systems on this machine:
#   kind cluster "heal-demo" + Argo CD + the traffic-api Application (GitOps from your GitHub repo)
#   Jenkins (JCasC, job traffic-api-ci) and Airflow 3 (DAG traffic_probe_daily) in Docker Compose
# Every kubectl call uses --context kind-heal-demo. Your other clusters are never touched.
set -euo pipefail
cd "$(dirname "$0")/.."
CTX=kind-heal-demo
K="kubectl --context $CTX"
ARGO_VERSION="${ARGO_VERSION:-stable}"

need() { command -v "$1" >/dev/null || { echo "missing: $1 ($2)"; exit 1; }; }
need docker "install Docker Desktop"
need kind "brew install kind"
need kubectl "brew install kubectl"
docker info >/dev/null 2>&1 || { echo "Docker is not running: start Docker Desktop"; exit 1; }
[ -f .env ] || { echo "copy .env.example to .env and fill it in first"; exit 1; }
set -a; . ./.env; set +a
[ -n "${GITHUB_REPO:-}" ] || { echo "set GITHUB_REPO=owner/repo in .env"; exit 1; }

setenv() {  # setenv KEY VALUE: write a value into .env
  if grep -q "^$1=" .env; then sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi
}

echo "==> kind cluster"
kind get clusters | grep -qx heal-demo || kind create cluster --config infra/kind-config.yaml
$K get nodes

echo "==> Argo CD ($ARGO_VERSION)"
$K create namespace argocd --dry-run=client -o yaml | $K apply -f -
$K apply -n argocd --server-side --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/$ARGO_VERSION/manifests/install.yaml" >/dev/null
$K -n argocd rollout status deploy/argocd-server --timeout=300s
$K -n argocd patch svc argocd-server --type merge -p \
  '{"spec":{"type":"NodePort","ports":[{"name":"https","port":443,"targetPort":8080,"nodePort":30443}]}}' >/dev/null
PW=$($K -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)
setenv ARGOCD_PASSWORD "$PW"

echo "==> Argo CD Application traffic-api -> github.com/$GITHUB_REPO (path service/)"
sed "s|__GITHUB_REPO__|$GITHUB_REPO|" infra/argocd-app.yaml | $K apply -f -

echo "==> Jenkins + Airflow"
docker compose -f infra/compose.yaml --env-file .env up -d --build
echo -n "waiting for Jenkins "; until curl -sf -u "admin:$JENKINS_TOKEN" "$JENKINS_URL/api/json" >/dev/null; do echo -n .; sleep 5; done; echo " up"
echo -n "waiting for Airflow "; until curl -sf "$AIRFLOW_URL/api/v2/monitor/health" >/dev/null; do echo -n .; sleep 5; done; echo " up"

echo
echo "All systems up:"
echo "  Argo CD  https://localhost:30443  (admin / see ARGOCD_PASSWORD in .env)"
echo "  Jenkins  $JENKINS_URL  (admin / JENKINS_TOKEN)"
echo "  Airflow  $AIRFLOW_URL  (admin / admin)"
echo "Next: python scenarios.py bootstrap   (first Argo CD sync of traffic-api)"
