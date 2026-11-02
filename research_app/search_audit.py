"""Durable raw artifacts and Delta rows for deliberate web searches."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from io import BytesIO
import os
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_app.search_provider import SearchResponse


CATALOG = "homicide_research"
SCHEMA = "research"
RUNS_TABLE = f"{CATALOG}.{SCHEMA}.search_runs"
RESULTS_TABLE = f"{CATALOG}.{SCHEMA}.search_results"


class AuditConfigurationError(RuntimeError):
    """The app is running without the configured durable audit resources."""


@dataclass(frozen=True)
class SearchAuditRecord:
    search_run_id: str
    raw_request_path: str
    raw_response_path: str
    raw_response_sha256: str


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json(path: Path, value: Any) -> str:
    payload = _json_bytes(value)
    if path.as_posix().startswith("/Volumes/"):
        from databricks.sdk import WorkspaceClient

        files = WorkspaceClient().files
        files.create_directory(path.parent.as_posix())
        files.upload(path.as_posix(), BytesIO(payload), overwrite=False)
        return sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return sha256(payload).hexdigest()


class SearchAuditStore:
    """Write raw artifacts to a UC volume and metadata to Delta through SQL."""

    def __init__(self, volume_path: str, warehouse_id: str):
        if not volume_path or not warehouse_id:
            raise AuditConfigurationError("Search audit storage is not configured for this app.")
        self.volume_path = Path(volume_path)
        self.warehouse_id = warehouse_id
        self.runs_table = RUNS_TABLE
        self.results_table = RESULTS_TABLE

    @classmethod
    def from_environment(cls) -> "SearchAuditStore":
        return cls(
            os.environ.get("HR_SEARCH_AUDIT_VOLUME", ""),
            os.environ.get("HR_SEARCH_AUDIT_WAREHOUSE_ID", ""),
        )

    def record(self, response: SearchResponse, actor: str) -> SearchAuditRecord:
        now = datetime.now(timezone.utc)
        run_id = str(uuid4())
        relative_dir = Path("raw") / "search_runs" / response.provider / now.strftime("%Y-%m-%d") / run_id
        request_path = self.volume_path / relative_dir / "request.json"
        response_path = self.volume_path / relative_dir / "response.json"
        request_payload = {"provider": response.provider, "query": response.query, "request": response.request}
        _write_json(request_path, request_payload)
        response_hash = _write_json(response_path, response.raw_response)
        record = SearchAuditRecord(run_id, str(request_path), str(response_path), response_hash)
        self._insert_rows(record, response, actor, now)
        return record

    def _connection(self):
        from databricks import sql
        from databricks.sdk.core import Config

        config = Config()
        hostname = config.host.removeprefix("https://").removeprefix("http://").rstrip("/")
        return sql.connect(
            server_hostname=hostname,
            http_path=f"/sql/1.0/warehouses/{self.warehouse_id}",
            credentials_provider=lambda: config.authenticate,
        )

    def record_triage(self, search_run_id: str, decision: dict) -> str:
        from uuid import UUID

        run_id = str(UUID(search_run_id))
        # A new artifact per model decision preserves prior prompt/model outputs.
        path = self.volume_path / "raw" / "research_triage" / run_id / f"{uuid4()}.json"
        digest = _write_json(path, {"search_run_id": run_id, "decision": decision,
                                    "recorded_at": datetime.now(timezone.utc).isoformat()})
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"UPDATE {self.runs_table} SET triage_artifact_path = ?, triage_artifact_sha256 = ? WHERE run_id = ?",
                    [str(path), digest, run_id],
                )
            finally:
                cursor.close()
        return str(path)

    def record_review(self, search_run_id: str, decision: dict) -> str:
        from uuid import UUID

        run_id = str(UUID(search_run_id))
        path = self.volume_path / "raw" / "research_reviews" / run_id / f"{uuid4()}.json"
        _write_json(path, {"search_run_id": run_id, "review": decision})
        return str(path)

    def record_profile(self, search_run_id: str, decision: dict) -> str:
        from uuid import UUID

        run_id = str(UUID(search_run_id))
        path = self.volume_path / "raw" / "research_profiles" / run_id / f"{uuid4()}.json"
        _write_json(path, {"search_run_id": run_id, "profile_update": decision,
                           "recorded_at": datetime.now(timezone.utc).isoformat()})
        return str(path)

    def _insert_rows(self, record: SearchAuditRecord, response: SearchResponse, actor: str, now: datetime) -> None:
        run_sql = f"""
            INSERT INTO {self.runs_table} (
                run_id, provider, provider_request_id, query, request_options_json,
                requested_by, searched_at, completed_at, status, result_count, provider_cost_usd,
                provider_search_time_ms, warnings_json, notices_json, raw_request_path,
                raw_response_path, raw_response_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        run_values = [
            record.search_run_id,
            response.provider,
            response.provider_request_id,
            response.query,
            json.dumps(response.request, ensure_ascii=False, sort_keys=True),
            actor,
            now,
            now,
            "succeeded",
            len(response.results),
            response.cost_usd,
            response.provider_search_time_ms,
            json.dumps(response.warnings, ensure_ascii=False),
            json.dumps(response.notices, ensure_ascii=False),
            record.raw_request_path,
            record.raw_response_path,
            record.raw_response_sha256,
        ]
        result_sql = f"""
            INSERT INTO {self.results_table} (
                search_result_id, run_id, result_rank, provider, provider_result_id,
                url, title, published_date_raw, author, snippet, highlights_json,
                raw_result_json, disposition, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        result_values = [
            [
                str(uuid4()),
                record.search_run_id,
                rank,
                response.provider,
                result.provider_result_id,
                result.url,
                result.title,
                result.published_date,
                result.author,
                result.snippet,
                json.dumps(result.highlights, ensure_ascii=False),
                json.dumps(result.raw or {}, ensure_ascii=False, sort_keys=True),
                "candidate",
                now,
            ]
            for rank, result in enumerate(response.results, start=1)
        ]
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(run_sql, run_values)
                if result_values:
                    cursor.executemany(result_sql, result_values)
            finally:
                cursor.close()


class SQLiteSearchAuditStore(SearchAuditStore):
    """Local integration-test backend sharing the production audit writer."""

    def __init__(self, directory: str | Path):
        self.volume_path = Path(directory).resolve()
        self.volume_path.mkdir(parents=True, exist_ok=True)
        self.database = self.volume_path / "search_audit.sqlite3"
        self.runs_table = "search_runs"
        self.results_table = "search_results"
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS search_runs (
                    run_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                    provider_request_id TEXT, query TEXT NOT NULL,
                    request_options_json TEXT, requested_by TEXT NOT NULL,
                    searched_at TIMESTAMP, completed_at TIMESTAMP,
                    status TEXT, result_count INTEGER, provider_cost_usd REAL,
                    provider_search_time_ms INTEGER, warnings_json TEXT, notices_json TEXT,
                    raw_request_path TEXT, raw_response_path TEXT, raw_response_sha256 TEXT,
                    triage_artifact_path TEXT, triage_artifact_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS search_results (
                    search_result_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES search_runs(run_id),
                    result_rank INTEGER NOT NULL CHECK (result_rank > 0),
                    provider TEXT, provider_result_id TEXT, url TEXT, title TEXT,
                    published_date_raw TEXT, author TEXT, snippet TEXT,
                    highlights_json TEXT, raw_result_json TEXT, disposition TEXT,
                    retrieved_at TIMESTAMP, UNIQUE(run_id, result_rank)
                );
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
