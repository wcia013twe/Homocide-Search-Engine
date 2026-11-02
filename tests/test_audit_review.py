from pathlib import Path
import tempfile
import unittest

from research_app.audit_review import review
from research_app.search_audit import SQLiteSearchAuditStore
from research_app.search_provider import SearchResponse, SearchResult


class AuditReviewTests(unittest.TestCase):
    def test_reopens_saved_run_and_checks_artifact_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteSearchAuditStore(directory)
            record = store.record(SearchResponse("exa", "seed", {}, {"results": []}, (
                SearchResult("Test fixture", "https://example.invalid", "Excerpt"),)), "test")
            decision = {"assessments": [{"result_rank": 1, "label": "uncertain",
                         "reason": "Need original", "duplicate_of_rank": None}], "next_queries": []}
            store.record_triage(record.search_run_id, decision)
            self.assertEqual(len(review(directory)["runs"]), 1)
            result = review(directory, record.search_run_id)
            self.assertTrue(result["artifact_hashes_verified"])
            self.assertEqual(result["results"][0]["assessment"]["label"], "uncertain")
            Path(record.raw_response_path).write_text("{}")
            with self.assertRaisesRegex(ValueError, "hash"):
                review(directory, record.search_run_id)

    def test_unknown_directory_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as directory:
            import sqlite3

            with self.assertRaises(sqlite3.OperationalError):
                review(directory)
            self.assertFalse((Path(directory) / "search_audit.sqlite3").exists())
