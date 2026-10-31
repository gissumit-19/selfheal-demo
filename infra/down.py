"""Removes everything up.py created: the Compose stack (with its volumes) and the kind cluster.

    python infra/down.py
"""
from _common import ENV_FILE, ROOT, run

run("docker", "compose", "-f", str(ROOT / "infra" / "compose.yaml"), "--env-file", str(ENV_FILE), "down", "-v", check=False)
run("kind", "delete", "cluster", "--name", "heal-demo", check=False)
print("removed. Free the image disk space too with: docker system prune -a")
