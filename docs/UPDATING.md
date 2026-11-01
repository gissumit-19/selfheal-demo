# Updating your copy to the latest version

## The one command (after the first time)

In the project folder, with the venv active (`(.venv)` in your prompt), on Windows, macOS or Linux:
```
python infra/update.py
```
It fetches the latest version from the trainer's repo, updates your files, makes your GitHub fork match,
installs new Python packages, restarts only the containers whose setup changed, and runs the preflight check.
Your `.env`, `.venv` and `runtime/` are kept. If you edited any lab files, it lists them and asks before
discarding them.

The agent also tells you when a newer version exists: `python -m heal ...` then prints
`A newer version of the lab is available: run python infra/update.py`.

## The first time only (if `infra/update.py` doesn't exist in your copy yet)

Run these three lines once, then use the one command above from then on:
```
git fetch https://github.com/pravinmenghani1/selfheal-demo.git main
git checkout FETCH_HEAD -- infra/update.py infra/_common.py
python infra/update.py
```

## Also, once per fork

GitHub switches these off on new forks; `preflight` tells you if they are still off:
- Actions: open `https://github.com/<you>/selfheal-demo/actions` and click **I understand my workflows, go ahead and enable them**.
- Issues: `gh repo edit <you>/selfheal-demo --enable-issues` (or Settings > General > Features > tick **Issues**).

## Options

- `python infra/update.py --yes` updates without asking (it still discards local edits to lab files).
- `python infra/update.py --no-up` leaves the running containers alone.
