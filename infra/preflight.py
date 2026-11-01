"""Run this FIRST. It changes nothing; it tells you what to fix. Same command on every OS:

    python infra/preflight.py          (Windows: py infra/preflight.py also works)
"""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request

from _common import IS_WINDOWS, IS_WSL, ROOT, ENV_FILE, has, out, read_env

results = {"ok": 0, "warn": 0, "fail": 0}


def ok(msg): results["ok"] += 1; print(f"  [ OK ] {msg}")
def warn(msg): results["warn"] += 1; print(f"  [WARN] {msg}")
def bad(msg): results["fail"] += 1; print(f"  [FAIL] {msg}")


def http(url: str, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def key_source(name: str) -> str:
    return "your shell environment" if os.environ.get(name) else ".env"


def chosen_provider(env: dict) -> str:
    return env.get("LLM_PROVIDER") or ("anthropic" if env.get("ANTHROPIC_API_KEY") else "openai")


def provider_text(env: dict) -> str:
    p = chosen_provider(env)
    if env.get("LLM_PROVIDER"):
        return f"provider {p} (LLM_PROVIDER)"
    key = "ANTHROPIC_API_KEY" if p == "anthropic" else "OPENAI_API_KEY"
    both = env.get("ANTHROPIC_API_KEY") and env.get("OPENAI_API_KEY")
    return (f"provider {p} (automatic: {key} is set, from {key_source(key)})"
            + ("; both keys are set, so set LLM_PROVIDER in .env to choose" if both else ""))


def key_hint(provider: str) -> str:
    key = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    other = "openai" if provider == "anthropic" else "anthropic"
    hint = f"wrong or revoked {key} (taken from {key_source(key)})"
    if os.environ.get(key):
        hint += f"; it is exported in your shell, which wins over .env: `unset {key}` (PowerShell: `Remove-Item Env:{key}`)"
    return hint + f", or use the other provider: LLM_PROVIDER={other} in .env"


def sdk_check(env: dict) -> None:
    """Connect the way the agent does (through the model SDK), so proxy/certificate problems show up here."""
    sys.path.insert(0, str(ROOT))
    import heal  # noqa: F401  (switches HTTPS to the OS certificate store, like the agent)
    provider = chosen_provider(env)
    try:
        if provider == "openai" and env.get("OPENAI_API_KEY"):
            import openai
            openai.OpenAI(api_key=env["OPENAI_API_KEY"], base_url=env.get("OPENAI_BASE_URL") or None).models.list()
        elif provider == "anthropic" and env.get("ANTHROPIC_API_KEY"):
            import anthropic
            anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"]).models.list()
        else:
            return
        ok(f"{provider} SDK can connect (same path the agent uses)")
    except Exception as e:
        cause = e
        while cause.__cause__ or cause.__context__:
            cause = cause.__cause__ or cause.__context__
        why = f"{type(cause).__name__}: {str(cause)[:160]}"
        hint = ("corporate HTTPS inspection: ask IT for the root certificate to be in the Windows store, "
                "or set SSL_CERT_FILE to it" if "CERTIFICATE" in why.upper() else
                "proxy/firewall: set HTTPS_PROXY=http://<proxy>:<port> in .env, or try off the VPN"
                if any(w in why.lower() for w in ("connect", "timed out", "getaddrinfo", "resolve", "proxy")) else
                key_hint(provider) if "401" in why or "authentication" in why.lower() else
                "check the key" + (" and OPENAI_BASE_URL" if provider == "openai" else "") + " in .env")
        bad(f"{provider} SDK cannot connect ({why}) -> {hint}")


def main() -> int:
    where = "Windows" if IS_WINDOWS else "WSL" if IS_WSL else sys.platform
    print(f"== system: {where}, Python {sys.version.split()[0]}")
    if IS_WSL and str(ROOT).startswith("/mnt/"):
        bad(f"project is on the Windows drive ({ROOT}); clone it inside WSL under ~ instead")
    if sys.version_info >= (3, 11):
        ok("Python 3.11+")
    else:
        bad(f"Python {sys.version.split()[0]} is too old: install 3.11 or newer (see the guide, step 1)")

    print("== tools")
    for tool, how in [("git", "Git"), ("docker", "Docker Desktop"), ("kind", "kind"), ("kubectl", "kubectl")]:
        if has(tool):
            v = out(tool, "--version") or out(tool, "version", "--client")
            ok(f"{tool}: {v.splitlines()[0][:60] if v else 'installed'}")
        else:
            bad(f"{tool} not found: install {how} (guide step 1), then open a NEW terminal")
    if has("git"):
        name, email = out("git", "config", "user.name"), out("git", "config", "user.email")
        if name and email:
            ok(f"git identity: {name} <{email}>")
        else:
            bad('git has no name/email (the scenarios make commits): git config --global user.name "Your Name" '
                '; git config --global user.email "you@example.com"')
    if has("gh"):
        ok(f"gh: {out('gh', '--version').splitlines()[0]}")
    else:
        warn("gh not installed: you'll need GITHUB_TOKEN in .env and to create the repo in the browser")

    print("== docker")
    info = out("docker", "info", "--format", "{{json .}}")
    if info.startswith("{"):
        d = json.loads(info)
        ok("docker is running")
        gb = int(d.get("MemTotal", 0)) // 1024 ** 3
        hint = ("set memory=8GB in %UserProfile%\\.wslconfig, then run `wsl --shutdown` (guide step W2)"
                if IS_WINDOWS or IS_WSL else "Docker Desktop > Settings > Resources > Memory")
        ok(f"docker memory {gb} GB") if gb >= 6 else bad(f"docker has {gb} GB memory, needs 6+: {hint}")
        ok(f"architecture {d.get('Architecture')} (all images are multi-arch)")
    else:
        bad("docker is not running: start Docker Desktop and wait until it says 'Engine running'"
            + (" (in WSL also enable Settings > Resources > WSL integration)" if IS_WSL else ""))

    print("== .env")
    env = read_env()
    if not ENV_FILE.exists():
        bad("no .env file: copy .env.example to .env and fill it in (guide step 4)")
    else:
        ok(".env found")
        if env.get("ANTHROPIC_API_KEY") or env.get("OPENAI_API_KEY"):
            ok(f"model key set: {provider_text(env)}")
        else:
            bad("set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")
        repo = env.get("GITHUB_REPO", "")
        if not repo or repo.startswith("your-user/"):
            bad("set GITHUB_REPO=<your-github-user>/selfheal-demo in .env")
        else:
            ok(f"GITHUB_REPO={repo}")
        if env.get("JENKINS_TOKEN") == "change-me-jenkins":
            warn("JENKINS_TOKEN is still the default password (fine on a laptop)")

    print("== ports (must be free before `python infra/up.py`, or already used by the demo itself)")
    ours = out("docker", "ps", "--format", "{{.Ports}}")
    for port, name in [(int(env.get("JENKINS_PORT", 8081)), "Jenkins"), (int(env.get("AIRFLOW_PORT", 8082)), "Airflow"),
                       (30080, "traffic-api"), (30443, "Argo CD")]:
        if not port_busy(port):
            ok(f"port {port} ({name}) free")
        elif f":{port}->" in ours:
            ok(f"port {port} ({name}) used by the demo's own container")
        else:
            bad(f"port {port} ({name}) is taken by another program: free it or change the port in .env (guide troubleshooting)")

    print("== model API (free models-list call, no tokens used)")
    p = chosen_provider(env)
    if env.get("ANTHROPIC_API_KEY") and p == "anthropic":
        code, _ = http("https://api.anthropic.com/v1/models",
                       {"x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        ok("Anthropic key accepted") if code == 200 else bad(f"Anthropic key check: HTTP {code} -> " + (key_hint("anthropic") if code == 401 else "no network/proxy (see the SDK line below)"))
    if env.get("OPENAI_API_KEY") and p == "openai":
        base = (env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        code, _ = http(f"{base}/models", {"Authorization": f"Bearer {env['OPENAI_API_KEY']}"})
        ok(f"OpenAI key accepted ({base})") if code == 200 else bad(f"OpenAI key check: HTTP {code} -> " + (key_hint("openai") if code == 401 else "no network/proxy (see the SDK line below)"))

    print("== GitHub")
    token = env.get("GITHUB_TOKEN") or (out("gh", "auth", "token") if has("gh") else "")
    repo = env.get("GITHUB_REPO", "")
    if not token:
        bad("no GitHub login: run `gh auth login` or set GITHUB_TOKEN in .env")
    elif repo and not repo.startswith("your-user/"):
        code, body = http(f"https://api.github.com/repos/{repo}", {"Authorization": f"Bearer {token}"})
        if code == 200:
            r = json.loads(body)
            ok(f"repo {repo} is public") if r.get("visibility") == "public" else bad(
                f"repo {repo} is private: make it public (Argo CD and Jenkins clone it without credentials)")
            ok("your login can push to it") if r.get("permissions", {}).get("push") else bad(f"your login cannot push to {repo}")
            if r.get("fork") and r.get("has_issues") is False:
                bad("Issues are OFF on your fork (GitHub's default): Settings > General > Features > tick Issues, "
                    f"or run: gh repo edit {repo} --enable-issues")
            elif r.get("has_issues"):
                ok("Issues enabled (the agent opens escalations there)")
            code, body = http(f"https://api.github.com/repos/{repo}/actions/workflows", {"Authorization": f"Bearer {token}"})
            states = {w["path"].rsplit("/", 1)[-1]: w["state"] for w in json.loads(body).get("workflows", [])} if code == 200 else {}
            if states.get("ci.yml") == "active":
                ok("GitHub Actions enabled (ci.yml active)")
            else:
                bad(f"GitHub Actions not enabled on {repo} (ci.yml: {states.get('ci.yml', 'not visible')}): open "
                    f"https://github.com/{repo}/actions and click 'I understand my workflows, go ahead and enable them'")
        else:
            warn(f"repo {repo} not found yet (HTTP {code}): create it in guide step 3, then run this again")
        remote = out("git", "remote", "get-url", "origin")
        ok(f"git remote origin: {remote}") if remote else warn("this folder has no git remote yet (guide step 3)")

    print("== python packages")
    try:
        import anthropic, dotenv, openai, requests, truststore, yaml  # noqa: F401
        ok("requirements installed")
        sdk_check(env)
    except ImportError as e:
        bad(f"missing package ({e.name}): activate the venv and run `pip install -r requirements.txt` (guide step 4)")

    print("== kubernetes context")
    print(f"  [INFO] current context: '{out('kubectl', 'config', 'current-context') or 'none'}'. "
          "The demo only ever uses 'kind-heal-demo'.")

    print(f"\npassed {results['ok']}, warnings {results['warn']}, failed {results['fail']}")
    if results["fail"]:
        print("Fix the FAIL lines, then run this again.")
        return 1
    print("Ready: python infra/up.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
