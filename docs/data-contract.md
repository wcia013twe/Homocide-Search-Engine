# Homicide Research Platform data contract

Version: UI prototype 1, 2026-10-26. All bundled content is explicitly fictional. No source URL, person, publication, or case is represented as real. The prototype performs no external discovery, extraction, or Databricks ingestion.

## Workspace API

`seed_workspace()` returns a fresh dictionary containing lists of `projects`, `datasets`, `incidents`, `sources`, `variables`, `runs`, `reviews`, and `usage_events`. IDs are stable strings. Dates use ISO 8601 dates; event timestamps use UTC ISO 8601 timestamps. References use IDs, never titles. Dataset and incident membership is many-to-many. A source may support several incidents and appear in several datasets. A project groups datasets without owning their evidence exclusively.

| Entity | Required properties |
| --- | --- |
| Project | id, name, description, dataset_ids |
| Dataset | id, name, description, project_ids, incident_ids, source_ids, status, created_at |
| Incident | id, dataset_ids, title, date, county, state, review_status, fields, source_ids |
| Source | id, title, publisher, published_at, url, kind, text, snippet, processing_status, incident_ids, dataset_ids |
| Variable | id, key, label, type, allowed_values, definition, codebook_version |
| Run | id, dataset_id, kind, status, started_at, source_count, incident_count, detail |
| Review | id, incident_id, field, previous_value, new_value, reason, reviewer, reviewed_at; field edits also require previous_status, new_status, previous_evidence_ids, new_evidence_ids, codebook_version |
| Usage event | id, kind, at, units, cost_usd |

Incident `review_status` is `Needs review`, `In review`, or `Verified`. Source `kind` is `News article`, `Public record`, or `Uploaded document`. Empty source URLs indicate local synthetic evidence and must not produce outbound links. Imported nonempty URLs must use HTTP(S), with a hostname and no embedded credentials or whitespace/control characters. Usage cost is nullable: null means unavailable, not zero.

## Coding and evidence

`incident.fields[variable.key]` contains `{value, status, evidence_ids}`. The JSON value matches the variable type: integer, number, boolean, text, or category. `Reported` means a source explicitly supports the value. `Not Reported` means the material reviewed does not supply it; value is null. `Unclear` means ambiguity or conflict prevents a defensible choice; value is null. A missing field has not yet been coded and is distinct from either of those statuses. Never infer a negative or a demographic attribute from silence. Category values must belong to the codebook's allowed values. Missingness belongs in status, not a category such as "Unknown".

The prototype's `evidence_ids` reference source IDs directly. This supports document-level navigation only: it is not a quotation-level citation contract. All sources associated with a conflict must remain accessible. `Reported` requires a non-null correctly typed value and at least one linked evidence source. `Verified` requires all defined variables coded, no unresolved fields, and evidence for each coding decision, including a source checked for a Not Reported decision. Adding a variable requires previously verified incidents to be reviewed against the expanded codebook. `Verified` is a researcher workflow decision, not a claim of legal certainty. Reported relationships and circumstances remain attributed source assertions.

Corrections update the selected incident field and append a review in the same workspace save. Preserve the source text. Review entries record old/new values, reason, actor, and time; field correction records also require old/new status, evidence references, and codebook version. Production adds model/run provenance. Status transitions use field `review_status` with supported old/new review statuses. A UI should not overwrite extracted claims when a researcher chooses a different coding. In this prototype, the source narrative preserves original assertions, and reviews retain value corrections; machine claims do not yet have their own immutable table. The SQLite adapter validates basic shapes, typed values, reference integrity, and reciprocal memberships. It does not enforce review completeness or authorization, so production writes need validated commands rather than arbitrary workspace replacement.

Codebook `demo-1.0` is an immutable fixture definition. Production codebooks need an immutable version identifier, effective date, author, definitions, permitted values, missingness rules, and migration policy. Each dataset binds a specific version. Updating a definition must create a new version and trigger explicit recoding rather than silently reinterpret prior records.

## Persistence and concurrency

`Repository(path, user_id).load()` returns `(workspace, revision)` and creates revision 0 on first use. `save(workspace, expected_revision)` atomically replaces that user's workspace and increments the revision. A stale revision raises `ConflictError`; reload and show the latest data before retrying. Never automatically resubmit a stale whole-workspace payload. `reset(expected_revision)` writes a fresh fixture workspace and increments the revision, so reset cannot create an ABA revision collision.

SQLite transactions make each payload change atomic, including incident edits plus their review entries. Every query is scoped by user ID and uses parameter binding. Two users in the same file have separate rows. This is application-level isolation, not authentication: the caller must derive user identity from a trusted authenticated session. A user-selectable string or shared demo ID is not suitable for confidential research data.

Store the database outside the application source directory, at a configurable runtime path. Local SQLite persists across app reruns and process restarts only while its filesystem survives. Databricks Apps container-local storage must not be treated as durable across deployments or instance replacement. The fixture store is for UI review; there is no backup, shared collaboration, immutable audit log, database encryption configuration, or multi-instance consistency guarantee. Production deployment requires a durable storage adapter and authenticated authorization. Whole-workspace saves are not appropriate for large evidence corpora.

## Future Databricks and Unity Catalog mapping

Keep the initial catalog/schema `homicide_research.research`. Use a `source_documents` Unity Catalog volume for original bytes, fetched responses, and immutable text extraction artifacts. Store content hashes, media types, byte lengths, extraction versions, and volume paths in Delta metadata tables. Never replace original evidence when a parser changes.

Proposed Delta entities:

- `projects`, `datasets`, `project_datasets`, `dataset_incidents`, `dataset_sources` represent ownership and membership.
- `incidents` holds stable incident identities; `incident_sources` is the many-to-many association with provenance and linkage confidence.
- `documents` holds source metadata and immutable document version IDs; `document_fetches` tracks retries and HTTP outcomes; `chunks` stores document/version-linked text offsets and embedding metadata.
- `evidence_spans` holds document-version ID, text offsets, quotation, locator/page, and extraction version. `claims` holds source assertions with typed values and certainty. `claim_evidence` is the many-to-many link between claims and spans.
- `codebooks`, `codebook_versions`, and `variables` define immutable field semantics. `dataset_codebooks` pins versions.
- `incident_field_decisions` stores researcher-selected typed values/statuses and references codebook versions; `decision_evidence` and `decision_claims` retain supporting and conflicting evidence. `review_events` append corrections with before/after snapshots and actor provenance.
- `search_runs`, `search_results`, `dataset_requests`, `processing_runs`, and `usage_events` retain query, scope, provider, idempotency key, timestamps, stage status, error category, retry count, and cost attribution.

The logical UI hierarchy is a navigation aid, not a strict ownership tree: variables are codebook definitions; evidence supports claims; incidents can participate in multiple datasets. Do not duplicate source documents solely to represent membership.

Production ingestion should use request idempotency keys scoped by tenant, canonical URL plus fetch/version metadata, and cryptographic content hashes. Repeated requests must reuse successful artifacts while recording retries. Document deduplication and incident entity resolution are different processes; matching article text must not automatically merge incidents. Preserve candidate links and human merge/split decisions.

Delta commands should enforce expected entity versions and atomic updates appropriate to the chosen serving architecture. Delta optimistic concurrency alone does not supply application-level compare-and-swap for arbitrary UI edits; verify row versions and affected results. For multi-table changes, use a transactional serving store or append a durable command/event before materializing Delta views. Authorization, audit retention, deletion policies, search/provider secrets, real usage billing, and durable job execution remain backend integration work.
