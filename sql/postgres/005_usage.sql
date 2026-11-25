ALTER TABLE investigation_tasks ADD COLUMN IF NOT EXISTS search_provider TEXT;
ALTER TABLE investigation_tasks ADD COLUMN IF NOT EXISTS model_endpoint TEXT;
CREATE TABLE IF NOT EXISTS research_usage_settings (
 actor TEXT PRIMARY KEY, search_provider TEXT NOT NULL, model_endpoint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_usage_calls (
 id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigation_tasks(id),
 kind TEXT NOT NULL, provider TEXT NOT NULL, cost_usd NUMERIC,
 input_tokens BIGINT, output_tokens BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS research_usage_calls_investigation ON research_usage_calls(investigation_id);
