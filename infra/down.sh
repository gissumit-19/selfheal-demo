#!/usr/bin/env bash
# Removes everything up.sh created: the kind cluster and the Compose stack (with its volumes).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f infra/compose.yaml --env-file .env down -v || true
kind delete cluster --name heal-demo || true
