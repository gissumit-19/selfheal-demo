#!/usr/bin/env bash
# Optional, for classrooms: pull the ~3 GB of images ahead of time (e.g. the night before, on good Wi-Fi).
set -euo pipefail
cd "$(dirname "$0")/.."
AIRFLOW_IMAGE="${AIRFLOW_IMAGE:-apache/airflow:3.3.2}"
for img in jenkins/jenkins:lts-jdk21 "$AIRFLOW_IMAGE" python:3.12-alpine kindest/node:latest; do
  echo "==> $img"; docker pull "$img"
done
echo "Argo CD images are pulled inside the kind cluster during ./infra/up.sh."
