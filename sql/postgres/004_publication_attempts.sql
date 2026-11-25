-- Durable receipt distinguishes retries from pre-existing gold records.
ALTER TABLE research_case_publications ADD COLUMN IF NOT EXISTS attempt_started_at TIMESTAMPTZ;
