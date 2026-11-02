# Research agent: step 1

Install the independent agent dependencies with `pip install -r hosting/requirements.txt`.
The root UI requirements currently pin Streamlit 1.66.1, which was unavailable
from the development package index; the agent package does not depend on Streamlit.

## Supported-value autofill

The optional profile stage now implements the agreed rule: fill an explicitly supported
value immediately, keeping its source URL, exact passage, evidence kind, decision scores,
and rubric version. A secondary source or search excerpt can supply a value; there is
no pending-verification status or mandatory primary-source/independent-source count.
Missing and conflicting fields alone drive subsequent query proposals. Unsupported
new claims never erase existing values. Conflicting supported values are both retained
in `claims`; the single-value slot is empty until the conflict is addressed.

`build_research_graph` accepts `extract_claims`, `decide_claims`, `required_fields`, and
`record_profile`. Both extraction and decisions must be supplied together, with source
triage enabled. The optional `fill_profile` node follows triage. It currently reads only
selected saved search excerpts, not full pages. Field decisions share one ai_decide
request; deterministic code fills values and computes gaps. These changes do not
enable an autonomous retrieval loop or bypass the existing review/search budget.
Graph state retains profile updates; `record_profile` writes separate audit artifacts
under `raw/research_profiles/<search_run_id>/`, without changing the database schema.

`python -m research_app.local_research --fill-profile --model-endpoint ENDPOINT ...`
opts into the new stage for a normal discovery pass. It makes live search/model calls;
it is not an offline replay command. This option is not enabled by default or in the
hosted service. `system.ai.ai_decide` is present in the catalog, but both the REST
probe and SQL execution failed; SQL reported batch inference was not enabled.
Live filling has not been verified. Use mocked local tests until execution succeeds.

The saved-result experiment is `python -m dev.decision_replay`; inspection without
`--execute` stays offline. Its rubric is now `supported-autofill-v1`. Historical failed
requests retain their original rubric; the earlier replay report describes those
attempts, not the new policy.

## Step 2: optional model triage

Set `HR_RESEARCH_MODEL_ENDPOINT` to an existing Databricks chat model endpoint
supporting Chat Completions `response_format: json_schema`. Grant the caller
permission to query it. Then add `--triage` to the command below. The adapter uses
Databricks SDK unified authentication; do not put a token in the source code.

The triage prompt is `incident-discovery-triage-v4` in `research_triage.py`.
It returns one assessment per result and up to three proposed queries, each linked
to result ranks. Python validates coverage, labels, duplicate references, and query
references before accepting the output. A model assessment is provisional.
An empty search skips the model. Proposed follow-up queries require review and are
not automatically run yet.

Graph state includes the prompt version, endpoint, reported model identifier,
token usage, exact model input, and response. CLI emits this state to stdout;
triage artifacts are also written to the audit volume and linked from search_runs.
Keep stdout private. Search raw artifacts are already written through the audit
adapter. Exa now searches the general web to include university and agency pages.

Model endpoint support varies: consult Databricks structured output documentation;
some Claude endpoints require the Messages API and cannot use this adapter.

The first runnable LangGraph slice is `validate_seed → discover → inspect_results`.
The default query is `padmini waldron ucf`. This is a search input, not a fixture
claim about the incident. No LLM is involved in this first step.

State is the dictionary passed between nodes. Each node returns only the keys it
changes. Edges establish which node executes next. `build_research_graph()` compiles
those definitions into an executable graph. The provider function and audit writer
are injected, letting tests exercise the actual graph without paid requests.

## Run with real searches

Test locally first using SQLite and local JSON artifacts:

```sh
python -m unittest discover -s tests -p test_sqlite_search_audit.py -v
python -m research_app.research_agent --provider Exa --actor local-researcher --local-audit local-audit
```

The tests mock only the external search/model calls and execute the real graph,
file writer, SQLite inserts, and triage update. The CLI command calls live search
but stores its audit locally; add --triage only when a model endpoint is configured.
SQLite verifies the common writer and graph contract. It does not prove Delta SQL,
UC privileges, network access, or Databricks app identity. Those need a later test.

To run search and optional triage with your existing Databricks login while keeping
all audit writes local:

```sh
python -m research_app.local_research --provider Exa --profile pc --secret-scope homicide-research-dev --model-endpoint databricks-gpt-oss-20b
```

The command reads the provider secret into process memory and makes a real search
and model call. It never prints the key. The endpoint name is configurable; this
example uses a model observed in the workspace. Omit --model-endpoint for search
only. Switch --provider to Brave to exercise the same graph with Brave results.
The local-audit directory holds SQLite rows and raw JSON; no Delta writes occur.

Install `requirements.txt` and configure `EXA_API_KEY` or `BRAVE_API_KEY` through
your environment/Databricks secrets. Configure `HR_SEARCH_AUDIT_VOLUME` and
`HR_SEARCH_AUDIT_WAREHOUSE_ID` as described in the README, then run:

```sh
python -m research_app.research_agent --provider Exa --actor YOUR_RESEARCHER_ID
python -m research_app.research_agent --provider Brave --actor YOUR_RESEARCHER_ID
```

These commands make a billable provider call and require audit storage. Each emits
node updates as JSON. A failed audit write fails the invocation rather than claiming
the search was recorded. The existing audit adapter writes successful responses;
it does not yet record failed provider attempts or provide retry deduplication.

## Learning checkpoints and hosting preparation

1. Verify the graph, provider switching, empty results, and invalid inputs.
2. Add a versioned structured triage prompt and a Databricks model endpoint.
   Record relevance decisions, result IDs, and concise reasons. Validate output.
3. Add source retrieval and claim extraction, then gap-driven query planning with
   explicit iteration and spend limits.
4. Add durable checkpoints, invocation IDs, and idempotent audit writes before
   enabling automatic recovery. Wire the graph to a Databricks agent server in
   a separate deployment from the existing Streamlit interface.

The optional `checkpointer` argument is the integration point for durable execution.
No checkpoint backend or hosted agent is provisioned by step 1. The graph currently
ends with `awaiting_inspection`; this is a reported status, not a resumable human
approval interrupt. Later steps will implement the review/resume contract.

## Step 4: local durable review and resume

`research_session.py` now enables real LangGraph interrupts and uses a separate
SQLite checkpoint database alongside the audit database. This session mode adds
`inspect_results → review_next → discover` and pauses before a proposed search.
The existing HTTP endpoint remains a synchronous single-pass endpoint.

Import the existing local Exa Padmini run without another search or model call:

```sh
python -m research_app.research_session import --session padmini-learning --actor YOUR_RECORDED_RESEARCHER_ID --run 99873483-702b-4183-906d-c6cf960a56b8
python -m research_app.research_session inspect --session padmini-learning --actor YOUR_RECORDED_RESEARCHER_ID
```

The actor must match the saved run's requested_by value. This is local attribution
and an accidental cross-session guard, not authentication. Protect the local files.
Review the returned proposals. To approve the first (zero-based index 0):

```sh
python -m research_app.research_session resume --session padmini-learning --actor YOUR_RECORDED_RESEARCHER_ID --run PENDING_SEARCH_UUID --action search --query-index 0 --reason "Seek later reporting" --model-endpoint databricks-gpt-oss-20b
```

Set the selected provider's API key in the environment and configure Databricks
authentication before resuming a live search. To stop without any external call:

```sh
python -m research_app.research_session resume --session padmini-learning --actor YOUR_RECORDED_RESEARCHER_ID --run PENDING_SEARCH_UUID --action stop --reason "Enough for this learning pass"
```

The session checks that the review belongs to the current search, rejects arbitrary
query text and stale proposals, and preserves the selected proposal, reason, actor,
and time in a review artifact and checkpoint. It stops after three searches or a
repeated query. Reopening a completed search at the review interrupt does not
repeat that search. Tests cover closing/reopening the SQLite connection, importing
a prior run, invalid approvals, researcher mismatch, stopping, and search limits.

This local session runner assumes one operator per session. The hosted API now
uses the same graph/session logic with Postgres checkpoints and advisory locking,
as described below. Automatic crash retries inside a provider/audit-writing node
still require idempotent writes; SQLite on app-local disk is not durable hosting storage.

## Step 5: prepared hosted review/resume

The server now includes these endpoints in addition to the single-pass /research:

| Endpoint | Operation |
| --- | --- |
| POST /sessions | Start a session or return its existing state |
| GET /sessions/{session_id} | Inspect latest sources, assessments, and review proposals |
| POST /sessions/{session_id}/resume | Select a proposed query or stop |

Use a client-generated UUID for session_id. Retrying POST /sessions with the same
UUID and same seed inputs returns the saved state without running another search.
Different seed inputs with that UUID return 409. Session keys are scoped to the
authenticated researcher. A stale approval or simultaneous invocation returns 409.
Requests use the same trusted Databricks proxy identity as /research.

To prepare a deployment with review/resume:

1. Supply an existing shared Postgres database dedicated to this application, with
   a trusted connection string using TLS. Store the DSN as a Databricks app secret
   resource named research_checkpoint_dsn; never commit the DSN.
2. Initialize its checkpoint tables once from an authorized environment with
   HR_RESEARCH_CHECKPOINT_DSN configured: `python -m research_app.hosted_session`.
   Runtime requests never call setup or create tables.
3. Build `python hosting/package_agent.py agent-build/stateful --stateful`.
   The resulting app.yaml includes the checkpoint secret and the existing provider,
   model, warehouse, and audit-volume resources.
4. Deploy the staged folder as a separate Databricks App once those resources and
   grants exist. Then test the session endpoints using Databricks OAuth.

The application holds a Postgres advisory lock for the session during each request,
preventing two workers from resuming the same checkpoint concurrently. Graph state
is stored by PostgresSaver; sources/model exchanges and reviews remain in the audit
volume and Delta metadata. The complete HTTP lifecycle is tested locally with the
real SQLite graph/backend. Postgres lock acquisition/release is boundary-tested with
mocks. No shared cloud checkpoint database has been provisioned or integration-tested.

This service resumes explicit human review checkpoints. It does not automatically
restart a node that crashed mid-search or mid-audit write. Before such automatic
recovery is enabled, provider calls and external writes need idempotency handling.

## Step 3: audit persistence and hosting entry point

For the existing workspace apply `sql/003_extend_existing_search_tables.sql` once.
It preserves the actual run_id/query/searched_at/retrieved_at columns. Fresh workspaces
use 001 then 002 instead. Each triage
decision is stored in `raw/research_triage/<search_run_id>/<decision_id>.json`.
The corresponding search_runs row links its latest decision artifact and hash.
Older decision artifacts remain available. Model assessments do not change source
dispositions or approved incident facts.

`python -m research_app.agent_server` runs the HTTP server. `/health` checks process
health without making billable calls. `POST /research` accepts:

```json
{"query": "padmini waldron ucf", "provider": "Exa"}
```

It requires Databricks Apps proxy identity and uses that identity for audit attribution.
The requester cannot supply an actor in the JSON body. The app's service principal
performs model and storage calls; restrict app access to the research team. This
server must only be externally exposed behind Databricks Apps, which authenticates
requests and supplies trusted forwarded headers.

For a separate Databricks App deployment, stage `research_app/`, `requirements.txt`,
and `hosting/research-agent.app.yaml` renamed to `app.yaml`. Keep the Streamlit
deployment's root app.yaml. Attach the resource keys named in the hosting manifest:
provider secrets, a read/write UC volume, a SQL warehouse, and the `research_model`
serving endpoint. Grant the app service principal CAN QUERY on the model, CAN USE
on the warehouse, USE CATALOG/SCHEMA and SELECT/MODIFY on both audit tables, and
READ/WRITE VOLUME. The existing catalog/schema and migrations must already exist.

Build the deployment source folder with `python hosting/package_agent.py agent-build`.
This copies only agent modules and agent dependencies and installs the agent manifest
as app.yaml. It refuses an existing output directory and excludes credentials,
databases, tests, and UI modules. Deploy that folder as a separate app source.

Verify a staged package with `python hosting/check_package.py agent-build`.
This launches its HTTP server on localhost, checks /health and bad-request handling,
verifies that hosted invocations require the Databricks proxy, and stops the process.
It does not make external search or model calls and does not change Databricks.

Read-only inspection on 2026-10-28 verified CLI profile `pc` in WSL authenticates;
the existing app is running with both provider secrets; the actual volume is
`homicide_research.research.sources_documents`; warehouse `a5e11b7fe2c6dbbc`
exists and was STOPPED; and both search tables need migration 003. Model endpoints
exist but a structured-output endpoint still needs selection and a live test.
That initial inspection was read-only. The subsequent additive migration is
documented below; no app was deployed.

## Local live verification (2026-10-28)

Real Exa and Brave searches for `padmini waldron ucf` each returned 10 results,
then passed through the Databricks `databricks-gpt-oss-20b` endpoint and ended at
awaiting_review. These runs used local SQLite and local JSON only:

- Exa: `99873483-702b-4183-906d-c6cf960a56b8`
- Brave: `3029dc8a-c677-4840-a010-1012a40127ec`

Review caught a semantic error in v1: a news story was called primary_target.
Prompt v2 defines each category and distinguishes journalism quoting police from
original agency material. Schema validation catches malformed outputs, not every
incorrect judgment. Researchers still review decisions.

Replay triage against a saved local search without paying for a new search:

```sh
python -m research_app.local_research --retriage-run SEARCH_RUN_UUID --model-endpoint databricks-gpt-oss-20b
```

Replay makes one model call and saves a NEW decision artifact. Prior artifacts
remain intact. This allows direct comparison of prompt versions on identical leads.

The additive Databricks migration was applied and verified before local-first
testing was established. It added audit columns without replacing tables or rows.
No agent was deployed. Local verification does not establish hosted permissions,
Delta insert behavior, background recovery, or downstream source extraction.

Hosting readiness verification also passed for the staged `agent-build/release-v3`
package: a real localhost Uvicorn process served /health, rejected unsupported
providers, and required Databricks Apps identity for /research. Its independent
dependencies installed and `pip check` reported no broken requirements. The UC
Files API upload path is covered by a mocked boundary test; live UC writes are not
yet verified. The Streamlit app's manifest retains only its already-attached
provider resources; the separate agent manifest declares its additional resources.

Inspect runs without provider or model calls:

```sh
python -m research_app.audit_review
python -m research_app.audit_review --run SEARCH_RUN_UUID
```

The reader opens SQLite read-only, checks result counts and artifact hashes, and
joins each model assessment to its original title, URL, and excerpt. It also shows
the proposed queries and their cited result ranks. Use the same OS/path mapping
that wrote the artifacts (the development runs used WSL).

Inspection of Exa's first run found nine background results and one early news
report describing unexplained deaths. Prompt v3 now explicitly preserves unknown
incident classification and prefers searching for later updates before speculative
legal or forensic records. This avoids assuming a homicide merely from project context.

This is a synchronous, custom FastAPI service for one search-and-triage pass. It does
not claim the Databricks AgentKit invocation protocol or background crash recovery.
Do not automatically retry POST /research: each call starts a new billable search.
Durable checkpoints and idempotent storage remain required before enabling looping,
automatic retries, or unattended long-running investigations. A network timeout may
occur after the search was stored; inspect search_runs before manually retrying.

Hosting references:
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/system-env
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/connect-local
- https://docs.databricks.com/aws/en/machine-learning/model-serving/structured-outputs
