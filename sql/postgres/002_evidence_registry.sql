-- Additive registry migration. Source text remains in immutable volume artifacts.
CREATE TABLE IF NOT EXISTS evidence_documents (
 id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE,
 document_id TEXT UNIQUE, title TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS evidence_document_versions (
 version_id TEXT PRIMARY KEY, document_key TEXT NOT NULL REFERENCES evidence_documents(id),
 content_sha256 TEXT NOT NULL, evidence_kind TEXT NOT NULL,
 artifact_path TEXT NOT NULL, retrieved_at TEXT,
 UNIQUE(document_key, content_sha256, evidence_kind)
);
CREATE TABLE IF NOT EXISTS evidence_source_aliases (
 investigation_id TEXT NOT NULL, source_id TEXT NOT NULL,
 version_id TEXT NOT NULL REFERENCES evidence_document_versions(version_id),
 PRIMARY KEY(investigation_id, source_id)
);
CREATE TABLE IF NOT EXISTS evidence_search_links (
 version_id TEXT NOT NULL REFERENCES evidence_document_versions(version_id),
 search_run_id TEXT NOT NULL, result_rank INTEGER NOT NULL,
 search_result_id TEXT,
 PRIMARY KEY(version_id, search_run_id, result_rank)
);
CREATE TABLE IF NOT EXISTS evidence_passages (
 passage_id TEXT PRIMARY KEY,
 version_id TEXT NOT NULL REFERENCES evidence_document_versions(version_id),
 quotation TEXT NOT NULL, start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
 end_offset INTEGER NOT NULL CHECK(end_offset > start_offset), page INTEGER
);
CREATE TABLE IF NOT EXISTS evidence_claims (
 id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL, claim_id TEXT NOT NULL,
 subject_id TEXT NOT NULL, original_field TEXT NOT NULL,
 reported_value JSONB NOT NULL,
 passage_id TEXT NOT NULL REFERENCES evidence_passages(passage_id),
 UNIQUE(investigation_id, claim_id)
);
CREATE TABLE IF NOT EXISTS evidence_field_assignments (
 sequence_id BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
 assignment_id TEXT PRIMARY KEY, claim_key TEXT NOT NULL REFERENCES evidence_claims(id),
 field_key TEXT, rationale TEXT NOT NULL, actor TEXT NOT NULL,
 supersedes TEXT REFERENCES evidence_field_assignments(assignment_id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
