# Updating your copy to the latest version

Run these in the folder where you cloned the repo. They make your fork and your clone **exactly** match the latest
version. Your `.env` and `.venv` are kept (git ignores them). Any local edits to tracked files are thrown away.

**1. Update your fork on GitHub** (replace `<you>` with your GitHub user name):
```
gh repo sync <you>/selfheal-demo --source pravinmenghani1/selfheal-demo --force
```
No gh? On your fork's GitHub page click **Sync fork > Update branch** (choose **Discard commits** if asked).

**2. Update your clone.** Run all four, in this order. The last two re-check out every file, which also fixes
Windows line endings:
```
git fetch origin
git reset --hard origin/main
git rm -r -q --cached .
git reset --hard origin/main
```
Check: `git log --oneline -1` shows the newest commit from the repo page, and `infra/` contains `preflight.py`
(no `.sh` files).

**3. Turn on Actions and Issues for your fork.** GitHub switches both off on new forks:
- Actions: open `https://github.com/<you>/selfheal-demo/actions` and click **I understand my workflows, go ahead and enable them**.
- Issues: `gh repo edit <you>/selfheal-demo --enable-issues` (or Settings > General > Features > tick **Issues**).

**4. Refresh the Python packages and check everything:**

| macOS / Linux | Windows (PowerShell) |
|---|---|
| `python3 -m venv .venv` (only if you have no `.venv` yet) | `py -m venv .venv` (only if you have no `.venv` yet) |
| `. .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| `python infra/preflight.py` | `python infra/preflight.py` |

Fix any `[FAIL]` lines. In particular, `GITHUB_REPO` in `.env` must be **your** fork (`<you>/selfheal-demo`).

**5. Continue with the guide.** If you already brought the systems up with the old `up.sh`, nothing needs rebuilding:
`python infra/up.py` is safe to run again. Then `python scenarios.py bootstrap`.
The old `up.sh` may have switched your kubectl context to `kind-heal-demo`. Check with
`kubectl config current-context`, and switch back with `kubectl config use-context <your-old-context>` if you use other clusters.
