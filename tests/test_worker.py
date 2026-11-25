"""Worker behavior around real checkpointed graphs and external boundaries."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from research_app.research_session import open_session
from research_app.search_provider import SearchResponse, SearchResult
from research_app.worker import execute


class WorkerTests(unittest.TestCase):
    def test_node_progress_observes_saved_state_and_pause(self):
        response = SearchResponse('exa', 'seed', {}, {}, (SearchResult('Report', 'https://example.invalid', 'evidence'),))
        triage = lambda query, results: {'assessments': [{'result_rank': 1, 'label': 'uncertain',
            'reason': 'Check source', 'duplicate_of_rank': None}], 'next_queries': []}
        observed = []
        with tempfile.TemporaryDirectory() as directory:
            with open_session(directory, triage, lambda provider, query: response) as session:
                session.progress = lambda snapshot: observed.append(snapshot)
                session.start('worker-case', 'alice', 'seed')
                self.assertTrue(any(snapshot.values.get('search_count') == 1 for snapshot in observed))
                self.assertTrue(any(task.interrupts for task in session.inspect('worker-case', 'alice').tasks))
            with open_session(directory, triage) as session:
                self.assertEqual(session.inspect('worker-case', 'alice').values['search_count'], 1)
        self.assertGreaterEqual(len(observed), 3)

    def test_publication_failure_does_not_claim_success(self):
        with patch('research_app.collaboration.CaseStore') as store:
            store.return_value.publish.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'Publication failed'):
                execute({'kind': 'publish', 'actor': 'alice', 'payload': {'case_id': 'case-a', 'revision': 2}})
            store.return_value.publish.assert_called_once_with('case-a', 2)

    def test_start_uses_stored_task_owner_and_saved_projection(self):
        task = {'id': 'incident', 'actor': 'alice', 'query': 'A single incident'}
        snapshot = SimpleNamespace(values={'researcher': 'alice'}, tasks=[SimpleNamespace(interrupts=['review'])])
        with patch('research_app.worker.tasks.get_task', return_value=task), patch('research_app.worker.open_hosted_session') as opened, patch('research_app.worker.persist_progress', return_value={'researcher': 'alice'}) as persist, patch('research_app.collaboration.CaseStore') as cases:
            session = opened.return_value.__enter__.return_value
            session.inspect.return_value = snapshot
            status = execute({'kind': 'start', 'actor': 'alice', 'investigation_id': 'incident', 'payload': {}})
            self.assertEqual(status, 'awaiting_review')
            session.start.assert_called_once()
            self.assertEqual(session.start.call_args.args[1:], ('alice', 'A single incident', 'Exa'))
            self.assertEqual(session.start.call_args.kwargs, {'automatic_searches': True})
            cases.return_value.link_snapshot.assert_called_once_with(task, {'researcher': 'alice'})
            persist.assert_called_once_with('incident', 'alice', snapshot)

    def test_dispatch_triggers_job_without_waiting_for_completion(self):
        from research_app.investigation_tasks import dispatch
        with patch.dict('os.environ', {'HR_RESEARCH_WORKER_JOB_ID': '123'}), patch('databricks.sdk.WorkspaceClient') as client:
            dispatch()
            client.return_value.jobs.run_now.assert_called_once_with(job_id=123)
            client.return_value.jobs.run_now.return_value.result.assert_not_called()

    def test_trigger_failure_leaves_scheduled_recovery_available(self):
        from research_app.investigation_tasks import dispatch
        with patch.dict('os.environ', {'HR_RESEARCH_WORKER_JOB_ID': '123'}), patch('databricks.sdk.WorkspaceClient', side_effect=RuntimeError('Unavailable')):
            with self.assertLogs('research_app.investigation_tasks', level='ERROR'):
                dispatch()
