CREATE VOLUME IF NOT EXISTS homicide_research.research.sources_documents;

CREATE TABLE IF NOT EXISTS homicide_research.research.search_runs (
  run_id STRING NOT NULL,
  provider STRING NOT NULL,
  provider_request_id STRING,
  query STRING NOT NULL,
  request_options_json STRING NOT NULL,
  requested_by STRING NOT NULL,
  searched_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP NOT NULL,
  status STRING NOT NULL,
  result_count INT NOT NULL,
  provider_cost_usd DECIMAL(18,6),
  provider_search_time_ms BIGINT,
  warnings_json STRING,
  notices_json STRING,
  raw_request_path STRING NOT NULL,
  raw_response_path STRING NOT NULL,
  raw_response_sha256 STRING NOT NULL
) USING DELTA;

CREATE TABLE IF NOT EXISTS homicide_research.research.search_results (
  search_result_id STRING NOT NULL,
  run_id STRING NOT NULL,
  result_rank INT NOT NULL,
  provider STRING NOT NULL,
  provider_result_id STRING,
  url STRING NOT NULL,
  title STRING NOT NULL,
  published_date_raw STRING,
  author STRING,
  snippet STRING,
  highlights_json STRING,
  raw_result_json STRING NOT NULL,
  disposition STRING NOT NULL,
  retrieved_at TIMESTAMP NOT NULL
) USING DELTA;
