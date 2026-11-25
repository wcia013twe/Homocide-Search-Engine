"""One research journey through the UI, with only paid services replaced."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from research_app.research_session import open_session
from research_app.search_provider import SearchResponse, SearchResult


class ResearchWorkflowUITests(unittest.TestCase):
    def test_padmini_start_review_follow_up_and_finish_share_one_saved_run(self):
        with tempfile.TemporaryDirectory() as directory:
            def search_response(provider, query):
                return SearchResponse(provider.lower(), query, {"query": query}, {"fixture": True}, (
                    SearchResult("Fictional workflow evidence", "https://example.invalid/report", "Synthetic source excerpt."),))

            search = Mock(side_effect=search_response)
            model = Mock(return_value={
                "assessments": [{"result_rank": 1, "label": "uncertain", "reason": "Synthetic evidence needs follow-up.",
                                 "duplicate_of_rank": None}],
                "next_queries": [{"query": '"Padmini Waldron" updates', "target_gap": "Later reporting",
                                  "reason": "Look for an update.", "based_on_ranks": [1]}],
            })

            def local_session(path, triage):
                return open_session(path, triage, search=search)

            with patch.dict(os.environ, {"HR_DATA_DIR": directory, "HR_REQUIRE_PROXY_IDENTITY": "false",
                                         "EXA_API_KEY": "synthetic-key", "HR_RESEARCH_MODEL_ENDPOINT": "synthetic-model"}), patch(
                "research_app.research_ui.open_session", side_effect=local_session
            ), patch("research_app.research_ui.DatabricksTriage.from_environment", return_value=model):
                app = AppTest.from_string('''
import streamlit as st
from research_app.research_ui import render
st.session_state.setdefault('research_user', 'workflow-test')
render('Exa')
''', default_timeout=30).run()
                app.button(key="research_start").click().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                search.assert_called_once_with("Exa", "padmini waldron ucf")
                self.assertEqual(model.call_count, 1)
                app.run()
                app.run()
                self.assertEqual(search.call_count, 1)
                reason = next(item for item in app.text_input if item.key.startswith("research_reason_"))
                reason.set_value("Find later reporting about this case.").run()
                app.button(key="research_continue").click().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                self.assertEqual(search.call_count, 2)
                search.assert_called_with("Exa", '"Padmini Waldron" updates')
                self.assertEqual(model.call_count, 2)
                reason = next(item for item in app.text_input if item.key.startswith("research_reason_"))
                reason.set_value("Enough evidence for this research pass.").run()
                app.button(key="research_stop").click().run()
                self.assertFalse(app.exception)
                self.assertFalse(app.error)
                self.assertTrue(any("Stopped by researcher" in item.value for item in app.markdown))
                self.assertEqual(search.call_count, 2)
                self.assertEqual(model.call_count, 2)
                rows = app.dataframe[0].value
                self.assertEqual(list(rows["Audit"]), ["Verified", "Verified"])
                self.assertEqual(list(rows["Assessed"]), [1, 1])
                reviews = list(Path(directory).glob("research-runs/*/raw/research_reviews/**/*.json"))
                self.assertEqual(len(reviews), 2)
                events = [json.loads(path.read_text())["review"] for path in reviews]
                self.assertEqual({event["action"] for event in events}, {"search", "stop"})


if __name__ == "__main__":
    unittest.main()
