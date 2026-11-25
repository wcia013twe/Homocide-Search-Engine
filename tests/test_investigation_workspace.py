"""The submission handoff and a single case-owned investigation view."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class InvestigationWorkspaceTests(unittest.TestCase):
    def test_submission_opens_exact_investigation(self):
        app = AppTest.from_string('''
import streamlit as st
from research_app.search import _submit_investigation
st.session_state.update(research_user='alice', search_live_query='Example incident',
    search_target_case='case', search_case_options=['case'])
_submit_investigation()
''')
        with patch('research_app.investigation_tasks.submit', return_value='case') as submit:
            app.run(timeout=30)
        self.assertFalse(app.exception)
        task = submit.call_args.args[0]
        self.assertEqual(app.session_state['case_investigation_case'], task['id'])
        self.assertEqual(app.session_state['nav_page'], 'Cases')
        self.assertIn('background', app.session_state['workspace_notice'])

    def view(self, *, actor='alice', status='awaiting_review', pending=None, values=None):
        task = dict(id='run', actor='alice', query='Example incident', status=status, revision=4)
        snapshot = SimpleNamespace(values=values or {}, tasks=[SimpleNamespace(
            interrupts=[SimpleNamespace(value=pending)] if pending else [])])

        @contextmanager
        def session(*args, **kwargs):
            yield SimpleNamespace(inspect=lambda *args: snapshot)

        app = AppTest.from_string('''
import streamlit as st
from research_app.investigation_detail import render_live
st.session_state['research_user'] = st.session_state['viewer']
render_live(st.session_state['task'], case_id='case')
''')
        app.session_state['viewer'] = actor
        app.session_state['task'] = task
        return app, task, session

    def run_view(self, app, task, session):
        with patch('research_app.investigation_tasks.get_case_task', return_value=task), \
             patch('research_app.hosted_session.open_hosted_session', session), \
             patch('research_app.evidence_registry.annotate_state', side_effect=lambda _, state: state), \
             patch('research_app.review_controls.get_task', return_value=task):
            app.run(timeout=30)
        self.assertFalse(app.exception)

    def test_old_coding_pause_has_handoff_instead_of_field_controls(self):
        pending = dict(stage='final_coding', search_run_id='search',
                       fields={'city': {'claims': [], 'status': 'Unclear'}})
        app, task, session = self.view(pending=pending, values={'profile': {'city': {}}})
        self.run_view(app, task, session)
        self.assertIn('Complete investigation', [button.label for button in app.button])
        self.assertNotIn('Submit coding review', [button.label for button in app.button])
        self.assertFalse(app.multiselect)

    def test_owner_decision_draft_survives_refresh_and_queues_once(self):
        pending = dict(search_run_id='search', next_queries=[dict(query='Follow up',
            target_gap='incident date', reason='Resolve conflicting dates', based_on_ranks=[1])])
        app, task, session = self.view(pending=pending,
            values={'results': [dict(result_rank=1, title='Report', snippet='Conflicting dates')]})
        self.run_view(app, task, session)
        app.text_area[0].set_value('Check later report')
        self.run_view(app, task, session)
        self.assertEqual(app.text_area[0].value, 'Check later report')
        self.assertTrue(any('Resolve conflicting dates' in item.value for item in app.markdown))
        with patch('research_app.review_controls.enqueue') as enqueue:
            app.button[0].click()
            self.run_view(app, task, session)
            enqueue.assert_called_once()
        task['status'] = 'queued'
        self.run_view(app, task, session)
        self.assertEqual(len(app.button), 0)
        pending['search_run_id'] = 'next-search'
        task['status'] = 'awaiting_review'
        self.run_view(app, task, session)
        self.assertEqual(app.text_area[0].value, '')

    def test_other_researcher_has_findings_without_decision_controls(self):
        app, task, session = self.view(actor='bob', pending={'next_queries': []})
        self.run_view(app, task, session)
        self.assertEqual(len(app.button), 0)
        self.assertTrue(any('owner' in item.value for item in app.caption))

    def test_failed_investigation_preserves_saved_activity(self):
        app, task, session = self.view(status='failed', values={
            'search_history': [{'query': 'Earlier search', 'search_run_id': 'search'}]})
        self.run_view(app, task, session)
        self.assertTrue(any('Saved evidence is preserved' in item.value for item in app.error))
        self.assertIn('Search 1: Earlier search', [item.label for item in app.expander])

    def test_case_selection_is_preserved_when_new_tasks_arrive(self):
        tasks = [dict(id='new', query='New investigation', status='running'),
                 dict(id='old', query='Selected investigation', status='finished')]
        app = AppTest.from_string('''
import streamlit as st
from research_app.cases import _investigations
_investigations({'id': 'case'}, active=True)
''')
        app.session_state['case_investigation_case'] = 'old'
        with patch('research_app.cases.list_case_tasks', return_value=tasks), \
             patch('research_app.investigation_detail.render_live') as render:
            app.run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(render.call_args.args[0]['id'], 'old')
            app.run(timeout=30)
            self.assertEqual(render.call_args.args[0]['id'], 'old')
