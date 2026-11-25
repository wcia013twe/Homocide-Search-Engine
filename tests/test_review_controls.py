import unittest
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class ReviewControlsTests(unittest.TestCase):
    def app(self, pending, values=None):
        snapshot = SimpleNamespace(values=values or {}, tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value=pending)])])
        app = AppTest.from_string('''
import streamlit as st
from research_app.review_controls import render_review_controls
st.session_state['research_user'] = 'alice'
render_review_controls({'id': 'run'}, st.session_state['snapshot'])
''')
        app.session_state['snapshot'] = snapshot
        return app

    @patch('research_app.review_controls.get_task', return_value={'revision': 4, 'status': 'awaiting_review'})
    @patch('research_app.review_controls.enqueue')
    def test_search_review_enqueues_existing_proposal(self, enqueue, get_task):
        app = self.app({'search_run_id': 'search', 'next_queries': [{'query': 'Follow up'}]}).run()
        app.text_area[0].set_value('Seek a later report')
        app.button[0].click().run()
        self.assertFalse(app.exception)
        enqueue.assert_called_once_with('run', 'alice', 'resume', {
            'search_run_id': 'search', 'action': 'search', 'query_index': 0, 'reason': 'Seek a later report'}, expected_revision=4)

    @patch('research_app.review_controls.get_task', return_value={'revision': 4, 'status': 'awaiting_review'})
    @patch('research_app.review_controls.enqueue')
    def test_old_coding_pause_enqueues_handoff_without_field_decisions(self, enqueue, get_task):
        app = self.app({'stage': 'final_coding', 'search_run_id': 'search', 'fields': {'city': {}}}).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.multiselect)
        self.assertFalse(app.text_area)
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        enqueue.assert_called_once_with('run', 'alice', 'finalize',
            {'search_run_id': 'search', 'action': 'case_review'}, expected_revision=4)

    @patch('research_app.review_controls.get_task', return_value={'revision': 5, 'status': 'queued'})
    @patch('research_app.review_controls.enqueue')
    def test_queued_review_does_not_show_duplicate_submit(self, enqueue, get_task):
        app = self.app({'search_run_id': 'search', 'next_queries': []}).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.button), 0)
        enqueue.assert_not_called()
