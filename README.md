# Homicide Research

A Streamlit research workspace deployed on Databricks Apps. Researchers start investigations, review sources and coding decisions in shared cases, and approve records for the Dataset. Shared investigations, evidence, cases, approvals, and usage live in Postgres; source captures and private issue diagnostics live in a Unity Catalog volume.

## Source of truth

`main` is the source for both localhost and deployment. The deployed application was recovered into this checkout on 2026-11-25; do not develop against an older exported deployment directory. Local recovery backups and diagnostics under `local-audit/` are ignored by Git.

## Run locally

Install Python dependencies and authenticate to the configured Databricks workspace:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
databricks auth login --profile pc
.venv/bin/python scripts/run_deployed_local.py
```

Open http://localhost:8501. The launcher reads `app.yaml`, resolves the deployed app's resource bindings, and uses your Databricks login for database access. Provider secrets remain in process memory. Localhost uses the shared research database and configured jobs: submitted investigations, edits, and issue reports are real. It binds only to the loopback interface and disables hosted proxy identity checks locally.

For an isolated local Postgres workflow, see `scripts/local_workflow.py`; that launcher requires a disposable Postgres database on port 55439.

## Deploy from main

Use a clean, verified `main` checkout. Check for newer workspace edits before synchronizing; recover any outstanding changes into Git first.

```sh
databricks sync . /Workspace/Users/wcia013twe@gmail.com/homicide-research-ui --profile pc
databricks apps deploy homocide-ai-research --source-code-path /Workspace/Users/wcia013twe@gmail.com/homicide-research-ui --mode SNAPSHOT --profile pc
```

Database migrations and app-role grants are applied explicitly through `hosting/setup_database.py` with the existing worker configuration. The database and case history are separate from the app filesystem. Researcher snapshot upload/download controls have been removed.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app.py research_app scripts hosting
```

Database integration tests require an explicit disposable `HR_COLLABORATION_TEST_DSN`. See `docs/search-testing-checklist.md` for research workflow checks and `docs/issue-reporting.md` for private diagnostics and GitHub issue delivery.
