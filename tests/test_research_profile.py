import unittest
import json
from pathlib import Path
import tempfile
from uuid import uuid4
from unittest.mock import Mock

from research_app.research_agent import build_research_graph
from research_app.research_profile import DatabricksFieldDecisions, fill_question, update_profile
from research_app.search_provider import SearchResponse, SearchResult


def answer(choice="fill"):
    return {"type": "choice", "choice": choice, "probabilities": {
        "fill": .9 if choice == "fill" else .1, "leave_empty": .1 if choice == "fill" else .9}, "confidence": .8}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"news": {"url": "https://example.invalid/news", "text": "Padmini Waldron, 47, in DeLand.", "evidence_kind": "search_excerpt"}}
        self.claim = {"claim_id": "age", "field": "age", "value": "47", "source_id": "news", "passage": "Padmini Waldron, 47"}

    def test_secondary_excerpt_fills_immediately_with_provenance(self):
        result = update_profile({}, [self.claim], self.sources, {"age": answer()}, ("age", "city"))
        self.assertEqual(result["profile"]["age"]["value"], "47")
        saved = result["profile"]["age"]["claims"][0]
        self.assertEqual(saved["passage"], self.claim["passage"])
        self.assertEqual(saved["url"], self.sources["news"]["url"])
        self.assertEqual(saved["decision"]["confidence"], .8)
        self.assertEqual(result["gaps"], [{"field": "city", "reason": "missing"}])
        self.assertNotIn("pending", str(result))

    def test_conflict_preserves_both_values_without_overwrite(self):
        first = update_profile({}, [self.claim], self.sources, {"age": answer()}, ("age",))
        other = {"other": {"url": "https://example.invalid/other", "text": "Age was 48."}}
        claim = {**self.claim, "claim_id": "other-age", "value": "48", "source_id": "other", "passage": "Age was 48."}
        result = update_profile(first["profile"], [claim], other, {"other-age": answer()}, ("age",))
        self.assertIsNone(result["profile"]["age"]["value"])
        self.assertEqual(len(result["profile"]["age"]["claims"]), 2)
        self.assertEqual(first["profile"]["age"]["value"], "47")
        self.assertEqual(result["gaps"], [{"field": "age", "reason": "conflicting"}])

    def test_unsupported_claim_leaves_existing_data_unchanged(self):
        result = update_profile({}, [self.claim], self.sources, {"age": answer("leave_empty")}, ("age",))
        self.assertEqual(result["profile"], {})
        self.assertEqual(result["gaps"], [{"field": "age", "reason": "missing"}])

    def test_missing_decisions_fabricated_quotes_and_invalid_scores_fail(self):
        for claims, answers in [([self.claim], {}), ([{**self.claim, "passage": "invented"}], {"age": answer()}),
                                ([self.claim], {"age": {**answer(), "confidence": float("nan")}})]:
            with self.subTest(claims=claims, answers=answers), self.assertRaises(ValueError):
                update_profile({}, claims, self.sources, answers, ("age",))

    def test_adapter_batches_claims_and_preserves_exchange(self):
        client = Mock()
        client.api_client.do.return_value = {"response": {"answers": {"age": answer(), "city": answer()}}}
        second = {**self.claim, "claim_id": "city", "field": "city", "value": "DeLand", "passage": "DeLand"}
        result = DatabricksFieldDecisions(client)("seed", [self.claim, second], self.sources, {})
        client.api_client.do.assert_called_once()
        self.assertEqual(set(result["request"]["questions"]), {"age", "city"})
        self.assertEqual(set(fill_question(self.claim)["criteria"]), {"fill", "leave_empty"})

    def test_real_graph_fills_and_proposes_only_remaining_gaps(self):
        search = Mock(return_value=SearchResponse("exa", "seed", {}, {}, (
            SearchResult("Report", "https://example.invalid/news", self.sources["news"]["text"]),)))
        triage = Mock(return_value={"assessments": [{"result_rank": 1, "label": "candidate_evidence", "reason": "Incident lead", "duplicate_of_rank": None}], "next_queries": []})
        def extract(seed, sources):
            return [{**self.claim, "source_id": next(iter(sources))}]
        decisions = Mock(return_value={"answers": {"age": answer()}})
        graph = build_research_graph(search=search, triage=triage, extract_claims=extract,
                                     decide_claims=decisions, required_fields=("age", "city"))
        state = graph.invoke({"query": "seed"})
        self.assertEqual(state["profile"]["age"]["value"], "47")
        self.assertEqual([p["target_gap"] for p in state["triage"]["next_queries"]], ["city"])
        self.assertEqual(state["field_decisions"][0]["claims"][0]["value"], "47")
        search.assert_called_once()

    def test_complete_profile_has_no_confirmation_search(self):
        sources = self.sources
        updated = update_profile({}, [self.claim], sources, {"age": answer()}, ("age",))
        self.assertEqual(updated["gaps"], [])

    def test_profile_audit_retains_decisions_without_database_migration(self):
        from research_app.search_audit import SQLiteSearchAuditStore
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteSearchAuditStore(directory)
            path = store.record_profile(str(uuid4()), {"claims": [self.claim], "answers": {"age": answer()}})
            event = json.loads(Path(path).read_text())
            self.assertEqual(event["profile_update"]["claims"][0]["passage"], self.claim["passage"])


if __name__ == "__main__":
    unittest.main()
