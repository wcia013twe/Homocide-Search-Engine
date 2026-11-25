"""Navigation and service-unavailable states need no live database."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class CollaborationUITests(unittest.TestCase):
    def test_closed_filter_uses_current_approval_and_keeps_cases_openable(self):
        cases = [dict(id='closed', title='Closed case', gold_key='record-1', revision=2, approved_revision=2,
                      investigations=1, fields={}),
                 dict(id='changed', title='Changed case', gold_key='record-2', revision=3, approved_revision=2,
                      investigations=1, fields={}),
                 dict(id='new', title='New case', gold_key='record-3', revision=0, approved_revision=None,
                      investigations=1, fields={})]
        with patch('research_app.cases.CaseStore.list_cases', return_value=cases):
            app = AppTest.from_string('''
import streamlit as st
from research_app.cases import _library
from research_app.collaboration import CaseStore
_library(CaseStore('researcher'))
''').run()
            self.assertFalse(app.exception)
            app.selectbox(key='case_status').select('Closed').run()
            self.assertFalse(app.exception)
            self.assertEqual([button.key for button in app.button if button.key and button.key.startswith('open_case_')],
                             ['open_case_closed'])
            app.text_input[0].set_value('record-2').run()
            self.assertTrue(any('No matching cases' in item.value for item in app.info))
            app.selectbox(key='case_status').select('Open').run()
            self.assertEqual([button.key for button in app.button if button.key and button.key.startswith('open_case_')],
                             ['open_case_changed'])
            app.text_input[0].set_value('').run()
            self.assertEqual([button.key for button in app.button if button.key and button.key.startswith('open_case_')],
                             ['open_case_changed', 'open_case_new'])
            app.selectbox(key='case_status').select('Closed').run()
            app.button(key='open_case_closed').click().run()
            self.assertEqual(app.session_state['case_to_open'], 'closed')
            self.assertEqual(app.session_state['nav_page'], 'Cases')

    def test_new_pages_explain_missing_services(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'HR_DATA_DIR': directory, 'HR_REQUIRE_PROXY_IDENTITY': 'false',
            'HR_RESEARCH_CHECKPOINT_DSN': '', 'HR_SEARCH_AUDIT_WAREHOUSE_ID': ''}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
            app.radio(key='nav_page').set_value('Cases').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, 'Cases')
            self.assertTrue(any('Connect shared case storage' in item.value for item in app.info))
            app.radio(key='nav_page').set_value('Dataset').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, 'Dataset')
            self.assertTrue(any('Connect the SQL warehouse' in item.value for item in app.info))

    def test_case_review_selects_scoped_claims(self):
        app = AppTest.from_string('''
import streamlit as st
from research_app.evidence_groups import case_evidence
from research_app.evidence_view import render_fields
links = [{'investigation_id': 'run', 'snapshot': {
    'sources': {'src': {'title': 'Fictional report', 'document_id': 'document'}},
    'profile': {'victim_1.age': {'claims': [
        {'claim_id': 'claim', 'source_id': 'src', 'value': '47', 'passage': 'Age 47'}]}}
}}]
fields, sources = case_evidence(links)
with st.form('review'):
    decisions = render_fields(fields, sources, mode='review', key='case', decisions={})
    if st.form_submit_button('Save'):
        st.session_state['saved'] = decisions
''', default_timeout=30).run()
        app.button[0].click().run()
        self.assertFalse(app.exception)
        saved = app.session_state['saved']['Victim Age']
        self.assertEqual(saved['claim_ids'], ['run:claim'])
        self.assertEqual(saved['source_ids'], ['run:src'])
        self.assertEqual(saved['value'], '47')

    def test_published_view_uses_immutable_evidence_snapshot(self):
        receipt = {'case_id': 'case', 'revision': 1, 'snapshot': {
            'evidence_fields': {'Victim Age': {'value': '47', 'status': 'Reported', 'claims': [
                {'claim_id': 'approved', 'source_id': 'source', 'value': '47', 'passage': 'Saved passage'}]}},
            'sources': {'source': {'title': 'Saved source'}},
            'investigations': [{'investigation_id': 'later', 'snapshot': {'profile': {'Victim Age': {'value': '99'}}}}]}}
        app = AppTest.from_string('''
import streamlit as st
from research_app.evidence_view import render_fields
snapshot = st.session_state['receipt']['snapshot']
render_fields(snapshot['evidence_fields'], snapshot['sources'], mode='published', key='approved')
''')
        app.session_state['receipt'] = receipt
        app.run()
        self.assertFalse(app.exception)
        self.assertIn('47', [item.value for item in app.markdown])
        self.assertNotIn('99', [item.value for item in app.markdown])
        self.assertIn('Saved passage', [item.value for item in app.text])
