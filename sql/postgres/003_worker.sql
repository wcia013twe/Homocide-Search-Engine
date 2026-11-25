-- Queue and execution state. Apply explicitly before enabling the Job runner.
ALTER TABLE investigation_tasks ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE investigation_tasks ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE investigation_tasks ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE investigation_tasks ADD COLUMN IF NOT EXISTS error TEXT;
CREATE TABLE IF NOT EXISTS investigation_commands (
 id TEXT PRIMARY KEY, investigation_id TEXT REFERENCES investigation_tasks(id),
 actor TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('start','resume','finalize','publish')),
 payload JSONB NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'queued'
 CHECK(status IN ('queued','running','succeeded','failed','interrupted')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ,
 finished_at TIMESTAMPTZ, heartbeat_at TIMESTAMPTZ, error TEXT
);
CREATE INDEX IF NOT EXISTS investigation_commands_pending ON investigation_commands(created_at) WHERE status='queued';
CREATE UNIQUE INDEX IF NOT EXISTS investigation_one_active_command ON investigation_commands(investigation_id)
 WHERE investigation_id IS NOT NULL AND status IN ('queued','running');
