import unittest
from unittest.mock import Mock

from research_app.research_agent import build_research_graph
from research_app.research_triage import validate_triage
from research_app.search_provider import SearchResponse, SearchResult


def decision():
    return {"assessments": [{"result_rank": 1, "label": "uncertain", "reason": "Excerpt is insufficient.",
                              "duplicate_of_rank": None}],
            "next_queries": [{"query": '"Padmini Waldron" police', "target_gap": "incident confirmation",
                              "reason": "Seek an agency source.", "based_on_ranks": [1]}]}


class TriageTests(unittest.TestCase):
    def test_graph_validates_triage_and_stops_for_review(self):
        search = Mock(return_value=SearchResponse("exa", "padmini waldron ucf", {}, {}, (
            SearchResult("Fixture", "https://example.invalid", "Insufficient excerpt"),)))
        model = Mock(return_value=decision())
        state = build_research_graph(search=search, triage=model).invoke({"query": "padmini waldron ucf"})
        self.assertEqual(state["status"], "awaiting_review")
        self.assertEqual(state["triage"]["assessments"][0]["label"], "uncertain")
        search.assert_called_once()

    def test_rejects_missing_results_and_invented_references(self):
        results = [{"result_rank": 1}]
        missing = decision()
        missing["assessments"] = []
        invented = decision()
        invented["next_queries"][0]["based_on_ranks"] = [99]
        duplicate = decision()
        duplicate["assessments"][0].update(label="duplicate", duplicate_of_rank=1)
        for invalid in (missing, invented, duplicate):
            with self.assertRaises(ValueError):
                validate_triage(invalid, results)

    def test_empty_results_do_not_spend_model_call(self):
        model = Mock()
        state = build_research_graph(
            search=Mock(return_value=SearchResponse("exa", "seed", {}, {}, ())), triage=model,
        ).invoke({"query": "seed"})
        self.assertEqual(state["status"], "no_results")
        model.assert_not_called()
