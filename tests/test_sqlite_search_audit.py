from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from research_app.research_agent import PADMINI_QUERY, build_research_graph
from research_app.search_audit import SQLiteSearchAuditStore
from research_app.search_provider import SearchResponse, SearchResult


class SQLiteAuditTests(unittest.TestCase):
    def test_graph_roundtrip_persists_results_and_triage_for_both_providers(self):
        for provider in ("Exa", "Brave"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                store = SQLiteSearchAuditStore(directory)
                response = SearchResponse(provider.lower(), PADMINI_QUERY, {"query": PADMINI_QUERY},
                    {"results": [{"title": "Synthetic test result"}]}, (
                        SearchResult("Synthetic test result", "https://example.invalid", "Test excerpt"),))
                decision = {"assessments": [{"result_rank": 1, "label": "uncertain",
                    "reason": "Need original source", "duplicate_of_rank": None}], "next_queries": []}
                graph = build_research_graph(
                    search=lambda *args: response,
                    record_search=lambda result: store.record(result, "local-test-researcher"),
                    triage=lambda *args: decision,
                    record_triage=lambda state, output: store.record_triage(state["search_run_id"], output),
                )
                state = graph.invoke({"query": PADMINI_QUERY, "provider": provider})
                # Reopen the backend to prove data survives the original store object.
                reopened = SQLiteSearchAuditStore(directory)
                with reopened._connection() as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute("SELECT * FROM search_runs").fetchone()
                    self.assertEqual(row["run_id"], state["search_run_id"])
                    self.assertEqual(row["query"], PADMINI_QUERY)
                    self.assertEqual(row["requested_by"], "local-test-researcher")
                    self.assertIsNone(row["provider_cost_usd"])
                    self.assertEqual(connection.execute("SELECT count(*) FROM search_results WHERE run_id = ?",
                                                       [row["run_id"]]).fetchone()[0], 1)
                    for path_key, hash_key in (("raw_response_path", "raw_response_sha256"),
                                               ("triage_artifact_path", "triage_artifact_sha256")):
                        payload = Path(row[path_key]).read_bytes()
                        self.assertEqual(sha256(payload).hexdigest(), row[hash_key])
                    artifact = json.loads(Path(row["triage_artifact_path"]).read_text())
                    self.assertEqual(artifact["decision"], decision)
                    self.assertEqual(state["status"], "awaiting_review")

    def test_zero_results_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteSearchAuditStore(directory)
            record = store.record(SearchResponse("exa", "seed", {}, {}, ()), "test")
            with store._connection() as connection:
                self.assertEqual(connection.execute("SELECT result_count FROM search_runs WHERE run_id = ?",
                                                   [record.search_run_id]).fetchone()[0], 0)

    def test_failed_result_insert_rolls_back_run_and_keeps_raw_for_diagnosis(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteSearchAuditStore(directory)
            with store._connection() as connection:
                connection.execute("CREATE TRIGGER fail_result BEFORE INSERT ON search_results BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            response = SearchResponse("brave", "seed", {}, {}, (
                SearchResult("Test", "https://example.invalid", "Test"),))
            with self.assertRaises(sqlite3.IntegrityError):
                store.record(response, "test")
            with store._connection() as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM search_runs").fetchone()[0], 0)
            self.assertEqual(len(list(Path(directory).glob("raw/search_runs/**/response.json"))), 1)
