import unittest
from unittest.mock import Mock

from research_app.research_agent import PADMINI_QUERY, build_research_graph
from research_app.search_provider import SearchResponse, SearchResult


class ResearchAgentTests(unittest.TestCase):
    def test_both_providers_follow_same_graph_and_record_response(self):
        for provider in ("Exa", "Brave"):
            with self.subTest(provider=provider):
                response = SearchResponse(provider.lower(), PADMINI_QUERY, {}, {}, (
                    SearchResult("Fixture article", "https://example.invalid/article", "Fixture excerpt"),
                ))
                search, record = Mock(return_value=response), Mock()
                state = build_research_graph(search, record).invoke({"query": PADMINI_QUERY, "provider": provider})
                search.assert_called_once_with(provider, PADMINI_QUERY)
                record.assert_called_once_with(response)
                self.assertEqual(state["status"], "awaiting_inspection")
                self.assertEqual(state["results"][0]["result_rank"], 1)

    def test_invalid_seed_does_not_call_provider(self):
        search = Mock()
        graph = build_research_graph(search)
        for seed in ({"query": " "}, {"query": PADMINI_QUERY, "provider": "Unknown"}):
            with self.assertRaises(ValueError):
                graph.invoke(seed)
        search.assert_not_called()

    def test_empty_results_stop_without_inventing_claims(self):
        search = Mock(return_value=SearchResponse("exa", PADMINI_QUERY, {}, {}, ()))
        state = build_research_graph(search).invoke({"query": PADMINI_QUERY})
        self.assertEqual(state["status"], "no_results")
        self.assertEqual(state["results"], [])


if __name__ == "__main__":
    unittest.main()
