import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from research_app.search_audit import AuditConfigurationError
from research_app.search_provider import SearchResponse, SearchResult
from research_app.repository import Repository



class ResearchUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {"HR_DATA_DIR": self.directory.name, "HR_REQUIRE_PROXY_IDENTITY": "false"})
        env.start()
        self.addCleanup(env.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
        self.assert_clean()

    def assert_clean(self):
        self.assertEqual(len(self.app.exception), 0, str(self.app.exception))
        self.assertEqual(len(self.app.error), 0, str(self.app.error))

    def test_only_live_navigation_is_shown(self):
        self.assertEqual(list(self.app.radio(key="nav_page").options), ["Search", "Usage", "User Guide"])

    def test_scoped_search_sends_and_audits_the_displayed_query(self):
        expected = "homicide Brazos County Texas 2023"
        response = SearchResponse("exa", expected, {}, {}, ())
        with patch("research_app.search.search_web", return_value=response) as search, patch(
            "research_app.search.SearchAuditStore.from_environment"
        ) as audit:
            self.app.text_input(key="search_live_query").set_value(" homicide ")
            self.app.text_input(key="search_live_state").set_value(" Texas ")
            self.app.text_input(key="search_live_county").set_value(" Brazos ")
            self.app.number_input(key="search_live_year").set_value(2023)
            self.app.run()
            search.assert_not_called()
            self.assertIn(f"Search query: {expected}", [item.value for item in self.app.text])
            self.app.button(key="search_live_submit").click().run()
            self.assert_clean()
            search.assert_called_once_with("Exa", expected)
            audit.return_value.record.assert_called_once_with(response, self.app.session_state["research_user"])

    def test_unfiltered_search_and_audit_configuration_message(self):
        response = SearchResponse("exa", "research methods", {}, {}, ())
        with patch("research_app.search.search_web", return_value=response) as search, patch(
            "research_app.search.SearchAuditStore.from_environment", side_effect=AuditConfigurationError()
        ):
            self.app.text_input(key="search_live_query").set_value(" research methods ").run()
            self.app.button(key="search_live_submit").click().run()
            self.assert_clean()
            search.assert_called_once_with("Exa", "research methods")
            self.assertTrue(any("Configure the audit volume" in item.value for item in self.app.caption))

    def test_filters_alone_do_not_submit_search(self):
        self.app.text_input(key="search_live_county").set_value("Brazos").run()
        self.assertTrue(self.app.button(key="search_live_submit").disabled)

    def test_county_suffix_is_not_duplicated(self):
        from research_app.search import scoped_query

        self.assertEqual(scoped_query("homicide", "Texas", "Brazos County", 2023),
                         "homicide Brazos County Texas 2023")
        self.assertEqual(scoped_query("homicide", year=2023), "homicide 2023")

    def test_explore_search_saves_one_detail_and_keeps_it_after_rerun(self):
        response = SearchResponse("exa", "homicide", {}, {}, (
            SearchResult("Fictional report", "https://example.invalid/report", "Found on Example Street."),))
        model = Mock(return_value=[{"claim_id": "street", "field": "location", "value": "Example Street",
                                    "source_id": "1", "passage": "Found on Example Street."}])
        with patch("research_app.search.search_web", return_value=response) as search, patch(
            "research_app.search.lead_extractor", return_value=model
        ), patch("research_app.search.SearchAuditStore.from_environment") as audit:
            audit.return_value.record.return_value.search_run_id = "audit-run"
            self.app.text_input(key="search_live_query").set_value("homicide")
            self.app.radio(key="search_live_mode").set_value("explore-search").run()
            self.app.button(key="search_live_submit").click().run()
            self.assert_clean()
            leads = self.app.session_state["workspace"]["leads"]
            self.assertEqual(len(leads), 1)
            self.assertEqual(leads[0]["identifying_detail"], "Example Street")
            user = self.app.session_state["research_user"]
            repo = Repository(Path(self.directory.name) / "workspaces.sqlite3", user)
            self.assertEqual(repo.load()[0]["leads"], leads)
            self.app.run()
            model.assert_called_once()
            search.assert_called_once()
            self.app.button(key="search_live_submit").click().run()
            self.assert_clean()
            self.assertEqual(len(repo.load()[0]["leads"]), 1)

    def test_explore_search_missing_model_does_not_spend_a_search(self):
        with patch.dict(os.environ, {"HR_RESEARCH_MODEL_ENDPOINT": ""}), patch(
            "research_app.search.search_web"
        ) as search:
            self.app.text_input(key="search_live_query").set_value("homicide")
            self.app.radio(key="search_live_mode").set_value("explore-search").run()
            self.app.button(key="search_live_submit").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertIn("HR_RESEARCH_MODEL_ENDPOINT", self.app.error[0].value)
            search.assert_not_called()

    def test_explore_search_invalid_evidence_does_not_save_leads(self):
        response = SearchResponse("exa", "homicide", {}, {}, (
            SearchResult("Fictional report", "https://example.invalid/report", "No identifying detail."),))
        model = Mock(return_value=[{"claim_id": "bad", "field": "location", "value": "Invented Street",
                                    "source_id": "1", "passage": "Invented Street"}])
        with patch("research_app.search.search_web", return_value=response), patch(
            "research_app.search.lead_extractor", return_value=model
        ), patch("research_app.search.SearchAuditStore.from_environment"):
            self.app.text_input(key="search_live_query").set_value("homicide")
            self.app.radio(key="search_live_mode").set_value("explore-search").run()
            self.app.button(key="search_live_submit").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(len(self.app.error), 1)
            self.assertNotIn("leads", self.app.session_state["workspace"])


if __name__ == "__main__":
    unittest.main()
