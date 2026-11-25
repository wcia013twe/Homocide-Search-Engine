import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class ResearchUITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"HR_DATA_DIR": directory.name, "HR_REQUIRE_PROXY_IDENTITY": "false",
            "HR_RESEARCH_CHECKPOINT_DSN": "test-only", "HR_SEARCH_AUDIT_VOLUME": "test-only",
            "HR_SEARCH_AUDIT_WAREHOUSE_ID": "test-only", "HR_RESEARCH_MODEL_ENDPOINT": "test-only"})
        env.start()
        self.addCleanup(env.stop)
        listing = patch("research_app.search.investigation_tasks.list_tasks", return_value=[])
        self.listing = listing.start()
        self.addCleanup(listing.stop)
        case_listing = patch("research_app.collaboration.CaseStore.list_cases", return_value=[])
        self.cases = case_listing.start()
        self.addCleanup(case_listing.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()

    def test_only_live_navigation_is_shown(self):
        self.assertEqual(list(self.app.radio(key="nav_page").options), ["Search", "Cases", "Dataset", "Usage", "User Guide"])
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.radio(key="nav_page").value == "Open investigation")

    def test_submission_is_persisted_for_backend_execution(self):
        calls = []
        with patch("research_app.search.investigation_tasks.submit", side_effect=lambda task: calls.append(("saved", task))):
            self.app.selectbox(key="search_target_case").select("__new_case__")
            self.app.text_area(key="search_live_query").set_value(" homicide Florida ")
            self.app.button(key="search_live_submit").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual([x[0] for x in calls], ["saved"])
        self.assertEqual(calls[0][1]["query"], "homicide Florida")
        self.assertEqual(calls[0][1]["actor"], self.app.session_state["research_user"])

    def test_submission_requires_case_choice(self):
        with patch('research_app.search.investigation_tasks.submit') as submit:
            self.app.text_area(key='search_live_query').set_value('additional search')
            self.app.button(key='search_live_submit').click().run()
        submit.assert_not_called()
        self.assertTrue(any('Choose a case' in item.value for item in self.app.error))

    def test_submission_can_add_investigation_to_existing_case(self):
        self.cases.return_value = [{'id': 'case-1', 'title': 'Padmini Devi', 'gold_key': 'case-1'}]
        self.app.run()
        with patch('research_app.search.investigation_tasks.submit', return_value='case-1') as submit:
            with patch('research_app.cases.open_case'):
                self.app.selectbox(key='search_target_case').select('case-1')
                self.app.text_area(key='search_live_query').set_value('additional search')
                self.app.button(key='search_live_submit').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(submit.call_args.kwargs['target_case'], 'case-1')

    def test_case_listing_failure_disables_submission(self):
        self.cases.side_effect = RuntimeError('unavailable')
        self.app.run()
        self.assertTrue(self.app.button(key='search_live_submit').disabled)

    def test_investigation_started_within_case_is_linked(self):
        self.app.session_state['investigation_case_id'] = 'case-1'
        self.app.session_state['investigation_case_title'] = 'Example case'
        self.app.run()
        with patch('research_app.search.investigation_tasks.submit', return_value='case-1') as submit:
            with patch('research_app.cases.open_case'):
                self.app.text_area(key='search_live_query').set_value('additional search')
                self.app.button(key='search_live_submit').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(submit.call_args.kwargs['target_case'], 'case-1')

    def test_missing_configuration_disables_submission(self):
        with patch.dict(os.environ, {"HR_RESEARCH_CHECKPOINT_DSN": ""}):
            self.app.text_area(key="search_live_query").set_value("Florida").run()
            self.assertTrue(self.app.button(key="search_live_submit").disabled)

    def test_search_does_not_read_or_render_investigation_progress(self):
        with patch('research_app.search.investigation_tasks.list_tasks') as listing:
            self.app.run()
        listing.assert_not_called()
        self.assertFalse(self.app.exception)
        self.assertNotIn('Investigations', [item.value for item in self.app.subheader])
