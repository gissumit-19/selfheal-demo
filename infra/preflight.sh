#!/usr/bin/env bash
# Run this FIRST on a learner machine. It changes nothing; it tells you what to fix.
#   ./infra/preflight.sh
cd "$(dirname "$0")/.."
PASS=0; FAIL=0; WARN=0
ok()   { echo "  [ OK ] $*"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }
warn() { echo "  [WARN] $*"; WARN=$((WARN+1)); }
has()  { command -v "$1" >/dev/null 2>&1; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&-; return 0; }; return 1; }

echo "== tools"
case "$PWD" in /mnt/[a-z]/*) bad "this folder is on the Windows drive ($PWD): clone it inside WSL under ~ instead (guide step W5)";; esac
for t in git curl docker kind kubectl python3; do
  if has "$t"; then
    v=$($t --version 2>/dev/null | head -1); [ -z "$v" ] && v=$($t version --client 2>/dev/null | head -1)
    ok "$t: ${v:0:60}"
  else bad "$t not installed (see docs/LEARNER_GUIDE.md, step 1)"; fi
done
has gh && ok "gh: $(gh --version | head -1)" || warn "gh not installed: you will need GITHUB_TOKEN (a PAT) in .env and to create the repo in the browser"
if has python3; then
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' && ok "python >= 3.11" || bad "python3 is $(python3 -V); need 3.11+"
fi

echo "== docker"
if docker info >/dev/null 2>&1; then
  ok "docker daemon running"
  MEM=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  GB=$((MEM / 1024 / 1024 / 1024))
  if grep -qi microsoft /proc/version 2>/dev/null; then HINT="WSL: set memory=8GB in %UserProfile%\\.wslconfig, then 'wsl --shutdown' (guide step W2)"
  else HINT="Docker Desktop > Settings > Resources > Memory"; fi
  [ "$GB" -ge 6 ] && ok "docker memory ${GB} GB" || bad "docker has ${GB} GB memory; give it at least 6 GB ($HINT)"
  [ "$(docker info --format '{{.Architecture}}' 2>/dev/null)" ] && ok "architecture $(docker info --format '{{.Architecture}}') (all images are multi-arch)"
else
  bad "docker is not running: start Docker Desktop (on WSL also enable Settings > Resources > WSL integration > Ubuntu), or the docker service on Linux"
fi

echo "== .env"
if [ -f .env ]; then
  set -a; . ./.env; set +a; ok ".env found"
  if [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ]; then ok "model key set (provider: ${LLM_PROVIDER:-auto})"
  else bad "set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env"; fi
  case "${GITHUB_REPO:-}" in ""|your-user/*) bad "set GITHUB_REPO=<your-github-user>/selfheal-demo";; *) ok "GITHUB_REPO=$GITHUB_REPO";; esac
  [ "${JENKINS_TOKEN:-}" = "change-me-jenkins" ] && warn "JENKINS_TOKEN is still the default password (fine on a laptop)"
else
  bad "no .env: cp .env.example .env and fill it in"
fi

echo "== ports (must be free before ./infra/up.sh; fine if they are OUR containers already running)"
for p in "${JENKINS_PORT:-8081}:Jenkins" "${AIRFLOW_PORT:-8082}:Airflow" "30080:traffic-api" "30443:Argo CD"; do
  n=${p%%:*}; name=${p#*:}
  if port_busy "$n"; then
    if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$n->"; then ok "port $n ($name) used by the demo's own container"
    else bad "port $n ($name) is taken by another program; free it or change the port in .env (see guide)"; fi
  else ok "port $n ($name) free"; fi
done

echo "== model API (free models-list call, no tokens used)"
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${LLM_PROVIDER:-}" != openai ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' https://api.anthropic.com/v1/models \
         -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01")
  [ "$code" = 200 ] && ok "Anthropic API key accepted" || bad "Anthropic key check returned HTTP $code (401 = wrong key; 000 = no network/proxy)"
fi
if [ -n "${OPENAI_API_KEY:-}" ] && [ "${LLM_PROVIDER:-}" != anthropic ]; then
  base="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
  code=$(curl -s -o /dev/null -w '%{http_code}' "${base%/}/models" -H "Authorization: Bearer $OPENAI_API_KEY")
  [ "$code" = 200 ] && ok "OpenAI API key accepted ($base)" || bad "OpenAI key check returned HTTP $code (401 = wrong key; 000 = no network/proxy)"
fi

echo "== GitHub"
TOKEN="${GITHUB_TOKEN:-}"
[ -z "$TOKEN" ] && has gh && TOKEN=$(gh auth token 2>/dev/null)
if [ -z "$TOKEN" ]; then
  bad "no GitHub credentials: run 'gh auth login' or set GITHUB_TOKEN in .env"
elif [ -z "${GITHUB_REPO:-}" ]; then
  bad "GITHUB_REPO not set, so the repo cannot be checked"
else
  body=$(curl -s -H "Authorization: Bearer $TOKEN" "https://api.github.com/repos/$GITHUB_REPO")
  if echo "$body" | grep -q '"full_name"'; then
    echo "$body" | grep -q '"visibility": *"public"' && ok "repo $GITHUB_REPO exists and is public" \
      || bad "repo $GITHUB_REPO is private: make it public (Argo CD and Jenkins clone it without credentials)"
    echo "$body" | grep -q '"push": *true' && ok "token can push to the repo" || bad "token cannot push to $GITHUB_REPO"
  else
    warn "repo $GITHUB_REPO not found yet: create it in step 3 of the guide, then re-run preflight"
  fi
  git remote get-url origin >/dev/null 2>&1 && ok "git remote origin: $(git remote get-url origin)" \
    || warn "this folder has no git remote yet (step 3 of the guide)"
fi

echo "== python packages"
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
$PY -c "import anthropic, openai, requests, yaml, dotenv" 2>/dev/null && ok "requirements installed ($PY)" \
  || bad "run: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"

echo "== kubernetes context"
has kubectl && echo "  [INFO] your current context is '$(kubectl config current-context 2>/dev/null || echo none)'. The demo only ever uses 'kind-heal-demo'."

echo
echo "passed $PASS, warnings $WARN, failed $FAIL"
[ "$FAIL" -eq 0 ] && echo "Ready: ./infra/up.sh" || { echo "Fix the FAIL lines, then run this again."; exit 1; }
