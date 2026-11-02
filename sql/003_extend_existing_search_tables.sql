-- Additive migration for the actual workspace schema inspected on 2026-10-28.
-- Existing run_id/query/url/searched_at/status/result_count/error columns are retained.
-- Apply once; inspect DESCRIBE TABLE first if an earlier migration was applied elsewhere.
ALTER TABLE homicide_research.research.search_runs ADD COLUMNS (
  provider_request_id STRING,
  request_options_json STRING,
  requested_by STRING,
  completed_at TIMESTAMP,
  provider_cost_usd DECIMAL(18,6),
  provider_search_time_ms BIGINT,
  warnings_json STRING,
  notices_json STRING,
  raw_request_path STRING,
  raw_response_path STRING,
  raw_response_sha256 STRING,
  triage_artifact_path STRING,
  triage_artifact_sha256 STRING
);

ALTER TABLE homicide_research.research.search_results ADD COLUMNS (
  search_result_id STRING,
  provider STRING,
  provider_result_id STRING,
  published_date_raw STRING,
  author STRING,
  highlights_json STRING,
  disposition STRING
);
