# Homicide Research Platform

A small Streamlit researcher workspace for Databricks Apps. It currently provides live web search, search auditing, a usage summary, and a user guide. The seeded usage data is fictional and labeled in the app.

## Run locally

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## What this scaffold does

- Search the live web with Brave or Exa and inspect returned sources.
- Record each completed search in a configured audit volume and SQL tables.
- Inspect fictional seeded usage and coverage data.
- Download and restore a validated workspace snapshot.

Brave and Exa live web search are available when their API keys are configured as app secrets. The provider selector uses one normalized result shape and preserves the provider's raw response when the search-audit resources are configured. Dataset management, document ingestion, extraction, analysis, collaboration permissions, and the Databricks ingestion pipeline are not connected.

## Search audit setup

The current workspace already has `search_runs`, `search_results`, and the `sources_documents` volume. Apply [`sql/003_extend_existing_search_tables.sql`](sql/003_extend_existing_search_tables.sql) once to extend those existing tables. Fresh workspaces use migrations 001 and 002 instead; do not apply both paths. In the Databricks App resource settings, attach `sources_documents` as a read/write UC volume resource with key `search_audit_volume`, and a SQL warehouse with key `search_audit_warehouse`. Add the existing provider secrets with keys `brave_secret` and `exa_secret`. The app records raw request/response JSON in the volume and writes one row to `search_runs` plus one row per URL to `search_results`. API keys are never written to artifacts.

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
