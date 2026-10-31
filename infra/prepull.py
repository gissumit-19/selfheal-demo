"""Optional, for classrooms: pull the ~3 GB of images ahead of time (e.g. the night before, on good Wi-Fi).

    python infra/prepull.py
"""
import os

from _common import run

for img in ["jenkins/jenkins:lts-jdk21", os.getenv("AIRFLOW_IMAGE", "apache/airflow:3.3.2"),
            "python:3.12-alpine", "kindest/node:latest"]:
    print(f"==> {img}")
    run("docker", "pull", img)
print("Argo CD images are pulled inside the kind cluster during `python infra/up.py`.")
