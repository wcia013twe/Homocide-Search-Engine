import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from research_app.agent_service import run_research
from research_app.search_provider import SearchResponse, SearchResult


class AgentServiceTests(unittest.TestCase):
    @patch("research_app.agent_service.DatabricksTriage.from_environment")
    @patch("research_app.agent_service.SearchAuditStore.from_environment")
    def test_full_service_links_search_and_triage(self, audit_factory, model_factory):
        response = SearchResponse("brave", "padmini waldron ucf", {}, {}, (
            SearchResult("Fixture article", "https://example.invalid", "Fixture", raw={"private_raw": True}),))
        audit = audit_factory.return_value
        audit.record.return_value = SimpleNamespace(search_run_id="run-123")
        decision = {"assessments": [{"result_rank": 1, "label": "uncertain", "reason": "Need original source.",
                                     "duplicate_of_rank": None}], "next_queries": []}
        model_factory.return_value = Mock(return_value=decision)
        with patch.dict("research_app.providers.PROVIDERS", {"Brave": Mock(return_value=response)}):
            result = run_research("padmini waldron ucf", "Brave", "researcher")
        self.assertEqual(result["search_run_id"], "run-123")
        self.assertEqual(result["status"], "awaiting_review")
        audit.record.assert_called_once_with(response, "researcher")
        audit.record_triage.assert_called_once_with("run-123", decision)
        self.assertNotIn("raw", result["results"][0])

    @patch("research_app.agent_service.DatabricksTriage.from_environment")
    @patch("research_app.agent_service.SearchAuditStore.from_environment")
    def test_audit_failure_does_not_run_model(self, audit_factory, model_factory):
        audit_factory.return_value.record.side_effect = RuntimeError("storage unavailable")
        response = SearchResponse("exa", "seed", {}, {}, ())
        with patch.dict("research_app.providers.PROVIDERS", {"Exa": Mock(return_value=response)}):
            with self.assertRaises(RuntimeError):
                run_research("seed", "Exa", "researcher")
        model_factory.return_value.assert_not_called()
