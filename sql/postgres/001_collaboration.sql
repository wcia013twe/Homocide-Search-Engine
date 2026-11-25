-- Explicit, additive migration in the existing checkpoint Postgres database.
CREATE TABLE IF NOT EXISTS research_cases (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), revision INTEGER NOT NULL DEFAULT 0,
    fields JSONB NOT NULL DEFAULT '{}', gold_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS research_case_identifiers (
    kind TEXT NOT NULL, identifier TEXT NOT NULL,
    case_id TEXT NOT NULL REFERENCES research_cases(id),
    PRIMARY KEY (kind, identifier)
);
CREATE TABLE IF NOT EXISTS research_case_investigations (
    investigation_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES research_cases(id),
    owner TEXT NOT NULL, snapshot JSONB NOT NULL, linked_by TEXT NOT NULL,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research_case_history (
    id BIGSERIAL PRIMARY KEY, case_id TEXT NOT NULL REFERENCES research_cases(id),
    revision INTEGER NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
    reason TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research_case_publications (
    case_id TEXT NOT NULL REFERENCES research_cases(id), revision INTEGER NOT NULL,
    approved_by TEXT NOT NULL, approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    snapshot JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    published_at TIMESTAMPTZ, error TEXT,
    PRIMARY KEY (case_id, revision)
);
