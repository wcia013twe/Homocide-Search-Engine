"""Investigation evidence labels stay separate from final human coding."""
import unittest
from streamlit.testing.v1 import AppTest


class FieldStatusTests(unittest.TestCase):
    def test_live_labels_expose_support_conflict_and_missing_without_choices(self):
        app = AppTest.from_string('''
from research_app.evidence_view import render_fields
fields = {
    'Victim Age': {'value': '47', 'claims': [
        {'claim_id': 'a', 'source_id': 's', 'value': '47', 'passage': 'Age 47.'}]},
    'Date Of Incident': {'value': None, 'claims': [
        {'claim_id': 'b', 'source_id': 's', 'value': '2020-01-01', 'passage': 'January 1'},
        {'claim_id': 'c', 'source_id': 's', 'value': '2020-01-02', 'passage': 'January 2'}]},
    'Victim Race': {'value': None}}
render_fields(fields, {'s': {'title': 'Synthetic report', 'text': 'Age 47. January 1. January 2'}}, compact=True)
''', default_timeout=30).run()
        self.assertFalse(app.exception)
        captions = [item.value for item in app.caption]
        for label in ('Supported', 'Conflicting', 'Missing or unclear'):
            self.assertIn(label, captions)
        self.assertFalse(app.radio)

    def test_case_review_keeps_multiple_choices_and_final_evidence_statuses(self):
        app = AppTest.from_string('''
import streamlit as st
from research_app.evidence_view import render_fields
with st.form('review'):
    render_fields({'Victim Age': {'claims': [
        {'claim_id': 'a', 'source_id': 's', 'value': '47', 'passage': 'Age 47'},
        {'claim_id': 'b', 'source_id': 't', 'value': '48', 'passage': 'Age 48'}]}},
        {'s': {'title': 'First report'}, 't': {'title': 'Second report'}},
        decisions={}, key='case-review')
    st.form_submit_button('Approve')
''', default_timeout=30).run()
        self.assertFalse(app.exception)
        choice = app.radio(key='case-review:choice:Victim Age')
        self.assertEqual(choice.options, ['47 · incident', '48 · incident', 'Unclear'])
        self.assertIsNone(choice.value)
