import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from research_app.explore_search import extract_leads, lead_extractor
from research_app.repository import Repository
from research_app.search_provider import SearchResponse, SearchResult


def response():
    return SearchResponse("exa", "homicide Example County Texas 2023", {}, {}, (
        SearchResult("Fictional incident report", "https://example.invalid/report",
                     "A person was found on Example Street. The date and name are unknown."),))


def claim(**changes):
    return {"claim_id": "street", "field": "location", "value": "Example Street", "source_id": "1",
            "passage": "A person was found on Example Street.", **changes}


class ExploreSearchTests(unittest.TestCase):
    def test_one_street_is_enough_without_name_date_or_case_number(self):
        model = Mock(return_value=[claim()])
        leads = extract_leads(response(), model, "audit-run")
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["identifying_detail"], "Example Street")
        self.assertEqual(leads[0]["status"], "Unverified lead")
        self.assertEqual(leads[0]["search_run_id"], "audit-run")
        self.assertEqual(leads[0]["search_query"], response().query)
        self.assertIn(leads[0]["supporting_excerpt"], model.call_args.args[1]["1"]["text"])

    def test_entire_batch_rejected_if_source_or_quote_or_value_is_fabricated(self):
        invalid = [claim(source_id="unknown"), claim(passage="Invented source text."),
                   claim(value="A different street"), claim(field="motive"),
                   claim(passage=""), "not a claim"]
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                extract_leads(response(), Mock(return_value=[claim(), bad]))

    def test_empty_results_skip_model_and_empty_extraction_is_valid(self):
        model = Mock()
        self.assertEqual(extract_leads(SearchResponse("exa", "query", {}, {}, ()), model), [])
        model.assert_not_called()
        self.assertEqual(extract_leads(response(), Mock(return_value=[])), [])

    def test_repeated_detail_has_stable_id_and_is_deduplicated(self):
        leads = extract_leads(response(), Mock(return_value=[claim(), claim(claim_id="duplicate")]))
        again = extract_leads(response(), Mock(return_value=[claim()]))
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["id"], again[0]["id"])

    def test_repository_round_trip_snapshot_and_user_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.sqlite3"
            alice = Repository(path, "alice")
            workspace, revision = alice.load()
            workspace["leads"] = extract_leads(response(), Mock(return_value=[claim()]))
            alice.save(workspace, revision)
            restored = json.loads(json.dumps(Repository(path, "alice").load()[0]))
            self.assertEqual(restored["leads"], workspace["leads"])
            self.assertNotIn("leads", Repository(path, "bob").load()[0])
            alice.save(restored, 1)
            invalid = copy.deepcopy(restored)
            invalid["leads"][0]["source_url"] = "javascript:alert(1)"
            with self.assertRaises(ValueError):
                alice.save(invalid, 2)
            self.assertEqual(alice.load()[0], restored)

    @patch("databricks.sdk.WorkspaceClient")
    @patch.dict("os.environ", {"HR_RESEARCH_MODEL_ENDPOINT": "fixture-endpoint"})
    def test_reuses_claim_adapter_with_lightweight_instructions(self, client):
        client.return_value.api_client.do.return_value = {"choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps({"claims": [claim()]})}}]}
        leads = extract_leads(response(), lead_extractor())
        self.assertEqual(len(leads), 1)
        request = client.return_value.api_client.do.call_args.kwargs["body"]
        self.assertIn("A single name", request["messages"][0]["content"])
        self.assertEqual(client.return_value.api_client.do.call_count, 1)

    @patch.dict("os.environ", {"HR_RESEARCH_MODEL_ENDPOINT": ""})
    def test_missing_model_configuration_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "HR_RESEARCH_MODEL_ENDPOINT"):
            lead_extractor()


if __name__ == "__main__":
    unittest.main()
