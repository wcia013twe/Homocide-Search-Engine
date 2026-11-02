-- Run after 001. Existing research tables are preserved.
ALTER TABLE homicide_research.research.search_runs ADD COLUMNS (
  triage_artifact_path STRING,
  triage_artifact_sha256 STRING
);
