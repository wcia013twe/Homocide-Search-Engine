from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from research_app.research_session import open_session
from research_app.search_audit import SQLiteSearchAuditStore
from research_app.search_provider import SearchResponse, SearchResult


def response(query="padmini waldron ucf"):
    return SearchResponse("exa", query, {}, {"fixture": True}, (
        SearchResult("Synthetic test result", "https://example.invalid", "Test excerpt"),))


def triage():
    return {"assessments": [{"result_rank": 1, "label": "uncertain", "reason": "Need original.",
                            "duplicate_of_rank": None}], "next_queries": [{
        "query": '"Padmini Waldron" DeLand updates', "target_gap": "Incident status",
        "reason": "Seek later reporting.", "based_on_ranks": [1]}]}


class ResearchSessionTests(unittest.TestCase):
    def test_restart_resumes_selected_query_without_repeating_initial_search(self):
        with tempfile.TemporaryDirectory() as directory:
            search, model = Mock(return_value=response()), Mock(return_value=triage())
            with open_session(directory, model, search, max_searches=2) as session:
                first = session.start("case-one", "researcher", "padmini waldron ucf")
                self.assertTrue(first["__interrupt__"])
                run_id = first["search_run_id"]
            self.assertEqual(search.call_count, 1)
            with open_session(directory, model, search, max_searches=2) as session:
                state = session.inspect("case-one", "researcher")
                self.assertEqual(state.values["search_run_id"], run_id)
                final = session.resume("case-one", "researcher", {
                    "action": "search", "search_run_id": run_id, "query_index": 0,
                    "reason": "Check later reporting.",
                })
                self.assertEqual(final["status"], "budget_reached")
                self.assertEqual(final["search_count"], 2)
                self.assertEqual(len(final["search_history"]), 2)
                with self.assertRaisesRegex(ValueError, "not waiting"):
                    session.resume("case-one", "researcher", {"action": "stop", "search_run_id": final["search_run_id"], "reason": "Done"})
            self.assertEqual(search.call_count, 2)
            search.assert_called_with("Exa", '"Padmini Waldron" DeLand updates')
            self.assertEqual(model.call_count, 2)
            self.assertEqual(len(list(Path(directory).glob("raw/research_reviews/**/*.json"))), 1)

    def test_import_saved_run_and_stop_without_new_search_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteSearchAuditStore(directory)
            saved = store.record(response(), "researcher")
            store.record_triage(saved.search_run_id, triage())
            search, model = Mock(), Mock()
            with open_session(directory, model, search) as session:
                paused = session.import_search("imported-case", "researcher", saved.search_run_id)
                self.assertTrue(paused["__interrupt__"])
                for person, run_id, index in (("other", saved.search_run_id, 0),
                                              ("researcher", "stale", 0),
                                              ("researcher", saved.search_run_id, 99)):
                    with self.assertRaises(ValueError):
                        session.resume("imported-case", person, {"action": "search", "search_run_id": run_id,
                                                                "query_index": index, "reason": "Test"})
                stopped = session.resume("imported-case", "researcher", {"action": "stop",
                    "search_run_id": saved.search_run_id, "reason": "Review complete"})
                self.assertEqual(stopped["status"], "stopped_by_researcher")
                with self.assertRaisesRegex(ValueError, "exists"):
                    session.start("imported-case", "researcher", "seed")
            search.assert_not_called()
            model.assert_not_called()

    def test_empty_search_finishes_without_review_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Mock()
            with open_session(directory, model, Mock(return_value=SearchResponse("exa", "seed", {}, {}, ()))) as session:
                state = session.start("empty", "researcher", "seed")
                self.assertEqual(state["status"], "no_results")
                self.assertFalse(session.inspect("empty", "researcher").next)
            model.assert_not_called()

    def test_repeated_proposal_stops_without_another_search(self):
        with tempfile.TemporaryDirectory() as directory:
            output = triage()
            output["next_queries"][0]["query"] = "  PADMINI   WALDRON UCF "
            search = Mock(return_value=response())
            with open_session(directory, Mock(return_value=output), search) as session:
                state = session.start("repeated", "researcher", "padmini waldron ucf")
                final = session.resume("repeated", "researcher", {"action": "search", "query_index": 0,
                    "search_run_id": state["search_run_id"], "reason": "Test normalized duplicate"})
                self.assertEqual(final["status"], "repeated_query")
                search.assert_called_once()
