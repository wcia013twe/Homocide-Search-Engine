from io import BytesIO
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from databricks.sdk.errors import NotFound, ResourceAlreadyExists
from streamlit.testing.v1 import AppTest

from research_app.issue_reporting import (REPOSITORY, deliver_report, diagnostic, make_report,
                                        observe_task_status, public_issue, report_path, submit_report)

VOLUME = '/Volumes/test/research/audit'


class FileStore:
    def __init__(self):
        self.data = {}

    def create_directory(self, path):
        pass

    def upload(self, path, content, overwrite=False):
        if path in self.data and not overwrite:
            raise ResourceAlreadyExists('exists')
        self.data[path] = content.read()

    def download(self, path):
        if path not in self.data:
            raise NotFound('missing')
        return SimpleNamespace(contents=BytesIO(self.data[path]))


class IssueReportingTests(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(files=FileStore(), jobs=Mock())
        self.client.jobs.run_now.return_value.response.run_id = 123
        self.http = Mock()
        self.http.get.return_value.json.return_value = []
        self.http.post.return_value.json.return_value = {
            'number': 7, 'html_url': f'https://github.com/{REPOSITORY}/issues/7'}

    def test_report_survives_trigger_failure_and_retry_uses_same_job_token(self):
        report = make_report('Cases', 'Source button does not open', actor='private-user', case_id='private-case')
        self.client.jobs.run_now.side_effect = RuntimeError('job temporarily unavailable')
        with self.assertRaises(RuntimeError):
            submit_report(self.client, VOLUME, 10, report)
        self.assertIn(report_path(VOLUME, report['id']), self.client.files.data)
        self.client.jobs.run_now.side_effect = None
        self.assertEqual(submit_report(self.client, VOLUME, 10, report), 123)
        self.assertEqual(len(self.client.files.data), 1)
        self.client.jobs.run_now.assert_called_with(job_id=10, job_parameters={'report_id': report['id']},
                                                    idempotency_token='issue-' + report['id'])

    def test_public_body_omits_private_context_and_redacts_credentials(self):
        with patch.dict(os.environ, {'EXA_API_KEY': 'known-secret-key'}):
            try:
                raise RuntimeError('password=hidden-value user=private-user known-secret-key')
            except RuntimeError as exc:
                error = diagnostic(exc, 'cases.render')
            report = make_report('Cases', 'Button failed with known-secret-key', actor='private-user',
                                 case_id='private-case', investigation_id='private-investigation', error=error)
        payload, unused = public_issue(report)
        body = json.dumps(payload)
        for private in ('known-secret-key', 'hidden-value', 'private-user', 'private-case', 'private-investigation'):
            self.assertNotIn(private, body)
        self.assertNotIn('hidden-value', error['message'])
        self.assertIn('RuntimeError', body)
        self.assertTrue(error['frames'])

    def test_delivery_recovers_lost_post_response_and_receipt_prevents_repeat(self):
        report = make_report('Search', 'Button missing')
        submit_report(self.client, VOLUME, 10, report)
        self.http.post.side_effect = TimeoutError('response lost')
        with self.assertRaises(TimeoutError):
            deliver_report(self.client, VOLUME, report['id'], 'token', http=self.http)
        payload, unused = public_issue(report)
        self.http.get.return_value.json.return_value = [{'number': 7, 'state': 'open', 'body': payload['body'],
            'html_url': f'https://github.com/{REPOSITORY}/issues/7'}]
        receipt = deliver_report(self.client, VOLUME, report['id'], 'token', http=self.http)
        self.assertEqual(receipt['issue_number'], 7)
        self.assertEqual(self.http.post.call_count, 1)
        self.http.get.reset_mock()
        self.assertEqual(deliver_report(self.client, VOLUME, report['id'], 'token', http=self.http), receipt)
        self.http.get.assert_not_called()

    def test_repeated_report_reuses_open_matching_issue(self):
        first = make_report('Cases', 'Small display problem')
        second = make_report('Cases', 'Small display problem')
        payload, unused = public_issue(first)
        self.http.get.return_value.json.return_value = [{'number': 7, 'state': 'open', 'body': payload['body'],
            'html_url': f'https://github.com/{REPOSITORY}/issues/7'}]
        submit_report(self.client, VOLUME, 10, second)
        deliver_report(self.client, VOLUME, second['id'], 'token', http=self.http)
        self.http.post.assert_not_called()

    def test_ui_optional_description_and_github_receipt(self):
        source = """import streamlit as st
from research_app.issue_ui import render
st.session_state['research_user'] = 'private-user'
st.session_state['nav_page'] = 'Cases'
render()
"""
        with patch.dict(os.environ, {'HR_ISSUE_REPORTER_JOB_ID': '10', 'HR_SEARCH_AUDIT_VOLUME': VOLUME}), patch(
            'databricks.sdk.WorkspaceClient', return_value=self.client):
            app = AppTest.from_string(source, default_timeout=30).run()
            self.assertEqual(len(app.text_area), 0)
            app.button(key='issue_open').click().run()
            app.button(key='issue_submit').click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            report_id = app.session_state['issue_submitted_id']
            report = json.loads(self.client.files.data[report_path(VOLUME, report_id)])
            self.assertEqual(report['description'], '')
            deliver_report(self.client, VOLUME, report_id, 'token', http=self.http)
            app.button(key='issue_get_link').click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(app.session_state['issue_receipt']['issue_number'], 7)
            self.assertEqual(self.client.jobs.run_now.call_count, 1)

    def test_error_hint_and_optional_attachment_in_modal(self):
        source = """import streamlit as st
from research_app.issue_ui import render
st.session_state['research_user'] = 'private-user'
st.session_state['nav_page'] = 'Cases'
st.session_state['issue_last_error'] = {'operation': 'cases.render', 'error_type': 'RuntimeError', 'message': 'private detail', 'frames': []}
render()
"""
        with patch.dict(os.environ, {'HR_ISSUE_REPORTER_JOB_ID': '10', 'HR_SEARCH_AUDIT_VOLUME': VOLUME}), patch(
            'databricks.sdk.WorkspaceClient', return_value=self.client):
            app = AppTest.from_string(source, default_timeout=30).run()
            self.assertTrue(any('Error detected' in item.value for item in app.caption))
            self.assertEqual(len(app.text_area), 1)
            self.client.jobs.run_now.assert_not_called()
            # Closing the modal suppresses another automatic prompt for this error.
            app.session_state['issue_dialog_open'] = False
            app.run()
            self.assertEqual(len(app.text_area), 0)
            app.button(key='issue_open').click().run()
            self.assertTrue(app.checkbox(key='issue_attach_error').value)
            app.checkbox(key='issue_attach_error').uncheck()
            app.button(key='issue_submit').click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            report_id = app.session_state['issue_submitted_id']
            report = json.loads(self.client.files.data[report_path(VOLUME, report_id)])
            self.assertIsNone(report['error'])

    def test_artifact_paths_are_bounded(self):
        for report_id in ('../outside', 'not-a-uuid'):
            with self.assertRaises(ValueError):
                report_path(VOLUME, report_id)
        with self.assertRaises(ValueError):
            report_path('/tmp/not-a-volume', make_report('Search')['id'])

    def test_auto_prompt_does_not_repeat_previously_dismissed_errors(self):
        source = """import streamlit as st
from research_app.issue_ui import render
st.session_state.setdefault('issue_last_error', {'operation': 'cases.render', 'error_type': 'RuntimeError', 'frames': []})
render()
"""
        app = AppTest.from_string(source, default_timeout=30).run()
        self.assertEqual(len(app.text_area), 1)
        first = dict(app.session_state['issue_last_error'])
        app.session_state['issue_dialog_open'] = False
        app.run()
        self.assertEqual(len(app.text_area), 0)
        app.session_state['issue_last_error'] = {**first, 'operation': 'dataset.render'}
        app.run()
        self.assertEqual(len(app.text_area), 1)
        app.session_state['issue_dialog_open'] = False
        app.session_state['issue_last_error'] = first
        app.run()
        self.assertEqual(len(app.text_area), 0)
        self.assertFalse(app.exception)

    def test_new_worker_failure_is_detected_but_old_failures_are_quiet(self):
        with patch('streamlit.session_state', {} ) as state:
            observe_task_status({'id': 'old-run', 'status': 'failed'})
            self.assertNotIn('issue_last_error', state)
            observe_task_status({'id': 'new-run', 'status': 'running'})
            observe_task_status({'id': 'new-run', 'status': 'failed', 'stage': 'discover', 'error': 'Provider unavailable'})
            self.assertEqual(state['issue_last_error']['investigation_id'], 'new-run')
            self.assertEqual(state['issue_last_error']['operation'], 'investigation.discover')
            del state['issue_last_error']
            observe_task_status({'id': 'new-run', 'status': 'failed'})
            self.assertNotIn('issue_last_error', state)


if __name__ == '__main__':
    unittest.main()
