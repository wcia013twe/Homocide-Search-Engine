# Homicide Research Platform

A UI-first researcher workspace built with Streamlit for Databricks Apps. Includes Search, Datasets (seven tabs), Library, Projects, and Usage. Example incidents and documents are entirely fictional and labeled in the app.

## Run locally

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## What this scaffold does

- Filter sample discovery sources, preview evidence, and collect sources into datasets.
- Inspect and correct structured incident fields alongside evidence, with review reasons and audit history.
- Manage dataset metadata and codebook definitions; inspect runs, missingness, and uncertainty.
- Upload UTF-8 text/Markdown documents and link them to datasets.
- Group datasets into projects, compare coverage, and export CSV.
- Inspect recorded activity and costs when available; absent metering is labeled unmetered.
- Download and restore a validated workspace snapshot.

Live web searches, PDF extraction, model calls, Text-to-SQL, collaboration permissions, and the Databricks ingestion pipeline are not connected. UI preview results are never represented as completed external operations. Review coverage is not an extraction-accuracy measurement.

## State and identity

In Databricks, `HR_REQUIRE_PROXY_IDENTITY=true` scopes saved state to the user identity supplied by the Databricks Apps reverse proxy. Missing identity blocks access. Do not expose that mode behind an untrusted proxy. Local previews use a fresh session ID and never trust caller-supplied identity headers.

SQLite under `HR_DATA_DIR` preserves edits across sessions for the same hosted identity while the app filesystem survives. This is scaffold storage, **not durable storage across Databricks redeployments or compute replacement**. Download a workspace snapshot before redeploying. Future durable storage is described in [the data contract](docs/data-contract.md). No existing Databricks tables, volumes, or jobs are modified by the scaffold.

The repository uses revision checks to reject stale writes and validates references before committing. Every workspace starts with a fresh copy of fictional records. Sharing controls are unavailable until authorization and durable storage are integrated.

## Deploy to the existing Databricks app

```sh
databricks auth login --profile magneto
databricks sync . /Workspace/Users/wcia013twe@gmail.com/homicide-research-ui --profile magneto
databricks apps deploy homocide-ai-research --source-code-path /Workspace/Users/wcia013twe@gmail.com/homicide-research-ui --mode SNAPSHOT --profile magneto
```

`app.yaml` binds Streamlit to the Databricks-assigned port and enables proxy identity checks. The existing app's workspace access policy is preserved. Source is deployed from a workspace folder; the empty linked GitHub repository is not published or modified in this pass.

## Verification

```sh
python -m unittest discover -s tests -v
python -m compileall -q app.py research_app
```

Repository tests cover tenant isolation, revision conflicts, atomic persistence, reset, and invalid snapshots. UI tests exercise navigation and core research actions through Streamlit's AppTest. Browser review covers a wide desktop and narrow mobile viewport.
