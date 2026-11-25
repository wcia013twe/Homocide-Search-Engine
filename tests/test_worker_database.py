"""Real queue transactions; requires an explicit disposable Postgres DSN."""
from concurrent.futures import ThreadPoolExecutor
import os
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from research_app import investigation_tasks as tasks
from research_app.repository import ConflictError
from research_app.worker import claim, finish, recover_interrupted, release


@skipUnless(os.environ.get('HR_COLLABORATION_TEST_DSN'), 'Set a disposable Postgres test DSN')
class WorkerDatabaseTests(TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        self.schema = 'worker_test_' + uuid4().hex
        self.dsn = os.environ['HR_COLLABORATION_TEST_DSN']
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        environment = patch.dict(os.environ, {'HR_RESEARCH_CHECKPOINT_DSN': make_conninfo(self.dsn, options='-c search_path=' + self.schema)})
        environment.start()
        self.addCleanup(environment.stop)
        tasks.setup()
        from research_app.collaboration import setup as setup_cases
        setup_cases()
        tasks.submit({'id': 'a', 'actor': 'alice', 'query': 'single incident'})

    def cleanup_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_submission_and_claim_are_durable_and_exclusive(self):
        def take(_):
            with tasks.connection() as conn:
                return claim(conn)
        with ThreadPoolExecutor(max_workers=2) as pool:
            commands = list(pool.map(take, range(2)))
        self.assertEqual(sum(command is not None for command in commands), 1)
        self.assertEqual(tasks.get_task('a', 'alice')['status'], 'running')
        with self.assertRaises(ValueError):
            tasks.get_task('a', 'bob')
        command = next(command for command in commands if command)
        with tasks.connection() as conn:
            finish(conn, command, 'awaiting_review')
        saved = tasks.get_task('a', 'alice')
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['status'], 'awaiting_review')

    def test_stale_and_simultaneous_reviews_cannot_enqueue_twice(self):
        with tasks.connection() as conn:
            first = claim(conn)
            finish(conn, first, 'awaiting_review')
        payload = {'search_run_id': 'saved-run', 'action': 'stop', 'reason': 'Review now'}
        def queue(_):
            try:
                return tasks.enqueue('a', 'alice', 'resume', payload, expected_revision=1)
            except ConflictError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            commands = list(pool.map(queue, range(2)))
        self.assertEqual(sum(command is not None for command in commands), 1)
        with tasks.connection() as conn:
            count = conn.execute("SELECT count(*) AS n FROM investigation_commands WHERE status='queued'").fetchone()['n']
            self.assertEqual(count, 1)

    def test_review_commands_are_owner_scoped(self):
        with tasks.connection() as conn:
            finish(conn, claim(conn), 'awaiting_review')
        with self.assertRaisesRegex(ValueError, 'not found'):
            tasks.enqueue('a', 'bob', 'resume', {'action': 'stop'})
        with tasks.connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM investigation_commands WHERE kind='resume'").fetchone()['n'], 0)

    def test_publication_retries_only_failed_or_interrupted_receipts(self):
        key = tasks.enqueue_publication('case-a', 1, 'alice')
        self.assertEqual(tasks.enqueue_publication('case-a', 1, 'alice'), key)
        with tasks.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM investigation_commands WHERE id=%s', [key]).fetchone()['n'], 1)
            conn.execute("UPDATE investigation_commands SET status='running' WHERE id=%s", [key])
        tasks.enqueue_publication('case-a', 1, 'alice')
        with tasks.connection() as conn:
            self.assertEqual(conn.execute('SELECT status FROM investigation_commands WHERE id=%s', [key]).fetchone()['status'], 'running')
            conn.execute("UPDATE investigation_commands SET status='interrupted' WHERE id=%s", [key])
        tasks.enqueue_publication('case-a', 1, 'alice')
        with tasks.connection() as conn:
            self.assertEqual(conn.execute('SELECT status FROM investigation_commands WHERE id=%s', [key]).fetchone()['status'], 'queued')
            conn.execute("UPDATE investigation_commands SET status='succeeded' WHERE id=%s", [key])
        tasks.enqueue_publication('case-a', 1, 'alice')
        with tasks.connection() as conn:
            self.assertEqual(conn.execute('SELECT status FROM investigation_commands WHERE id=%s', [key]).fetchone()['status'], 'succeeded')

    def test_distinct_investigations_run_together_and_live_locks_survive_recovery(self):
        tasks.submit({'id': 'b', 'actor': 'bob', 'query': 'another incident'})
        with tasks.connection() as first, tasks.connection() as second, tasks.connection() as observer:
            a = claim(first)
            b = claim(second)
            self.assertNotEqual(a['investigation_id'], b['investigation_id'])
            self.assertIsNone(claim(observer))
            recover_interrupted(observer)
            running = observer.execute("SELECT count(*) AS n FROM investigation_commands WHERE status='running'").fetchone()['n']
            self.assertEqual(running, 2)
            with self.assertRaises(ConflictError):
                tasks.enqueue(a['investigation_id'], a['actor'], 'resume', {})
            finish(first, a, 'awaiting_review')
            release(first, a)
            # Finishing one investigation must leave the other active.
            recover_interrupted(observer)
            self.assertEqual(tasks.get_task(b['investigation_id'], b['actor'])['status'], 'running')
            finish(second, b, 'awaiting_review')
            release(second, b)

    def test_lost_runner_is_interrupted_without_replaying(self):
        with tasks.connection() as runner:
            command = claim(runner)
        with tasks.connection() as replacement:
            recover_interrupted(replacement)
            self.assertIsNone(claim(replacement))
            saved = replacement.execute('SELECT status FROM investigation_commands WHERE id=%s', [command['id']]).fetchone()
            self.assertEqual(saved['status'], 'interrupted')
        self.assertEqual(tasks.get_task('a', 'alice')['status'], 'interrupted')

    def test_trigger_happens_after_commit_and_failure_keeps_work_durable(self):
        with patch.dict(os.environ, {'HR_RESEARCH_WORKER_JOB_ID': '123'}), patch('databricks.sdk.WorkspaceClient') as client:
            def verify_committed(**kwargs):
                self.assertEqual(kwargs['job_id'], 123)
                self.assertEqual(tasks.get_task('new', 'alice')['status'], 'queued')
                raise RuntimeError('Trigger unavailable')
            client.return_value.jobs.run_now.side_effect = verify_committed
            with self.assertLogs('research_app.investigation_tasks', level='ERROR'):
                tasks.submit({'id': 'new', 'actor': 'alice', 'query': 'new incident'})
            client.return_value.jobs.run_now.assert_called_once()
            self.assertEqual(tasks.get_task('new', 'alice')['status'], 'queued')

    def test_dispatch_happens_after_submission_commit(self):
        def observe():
            with tasks.connection() as observer:
                self.assertIsNotNone(observer.execute("SELECT 1 FROM investigation_commands WHERE investigation_id='committed'").fetchone())
        with patch.object(tasks, 'dispatch', side_effect=observe) as dispatch:
            tasks.submit({'id': 'committed', 'actor': 'alice', 'query': 'incident'})
        dispatch.assert_called_once()

    def test_timing_separates_worker_queue_and_human_review(self):
        from datetime import datetime, timezone
        from research_app.investigation_progress import timing_text
        with tasks.connection() as conn:
            conn.execute("UPDATE investigation_tasks SET created_at='2026-11-16 12:00:00+00', status='awaiting_review' WHERE id='a'")
            conn.execute("""UPDATE investigation_commands SET status='succeeded',
                created_at='2026-11-16 12:00:00+00', started_at='2026-11-16 12:00:30+00',
                finished_at='2026-11-16 12:02:00+00' WHERE investigation_id='a'""")
        saved = tasks.get_task('a', 'alice')
        later = datetime(2026, 11, 16, 13, tzinfo=timezone.utc)
        self.assertEqual(saved['worker_seconds'], 90)
        self.assertEqual(saved['queue_seconds'], 30)
        self.assertIn('Total elapsed 2m 00s', timing_text(saved, later))
        self.assertIn('First review ready in 2m 00s', timing_text(saved, later))
        self.assertEqual(tasks.list_tasks('alice')[0]['first_review_at'], saved['first_review_at'])
        tasks.enqueue('a', 'alice', 'resume', {})
        with tasks.connection() as conn:
            conn.execute("""UPDATE investigation_commands SET status='succeeded',
                created_at='2026-11-16 12:10:00+00', started_at='2026-11-16 12:10:10+00',
                finished_at='2026-11-16 12:11:00+00' WHERE kind='resume'""")
            conn.execute("UPDATE investigation_tasks SET status='finished' WHERE id='a'")
        saved = tasks.get_task('a', 'alice')
        self.assertEqual(saved['worker_seconds'], 140)
        self.assertEqual(saved['queue_seconds'], 40)
        self.assertIn('Total elapsed 11m 00s', timing_text(saved, later))
        self.assertIn('First review ready in 2m 00s', timing_text(saved, later))


    def test_submission_links_to_case_before_dispatch_and_lists_all_team_runs(self):
        with tasks.connection() as conn:
            case_id = conn.execute("SELECT case_id FROM research_case_investigations WHERE investigation_id='a'").fetchone()['case_id']
        tasks.submit({'id': 'b', 'actor': 'bob', 'query': 'Team verification', 'submitted_by_email': 'bob@example.com'}, target_case=case_id)
        tasks.submit({'id': 'c', 'actor': 'alice', 'query': 'Completed search'}, target_case=case_id)
        with tasks.connection() as conn:
            conn.execute("UPDATE investigation_tasks SET status='running' WHERE id='b'")
            conn.execute("UPDATE investigation_tasks SET status='finished' WHERE id='c'")
        runs = tasks.list_case_tasks(case_id)
        self.assertEqual({run['id'] for run in runs}, {'a', 'b', 'c'})
        self.assertEqual([run['created_at'] for run in runs], sorted((run['created_at'] for run in runs), reverse=True))
        self.assertEqual({run['actor'] for run in runs}, {'alice', 'bob'})
        self.assertEqual({run['id']: run['submitted_by_email'] for run in runs}['b'], 'bob@example.com')
        self.assertEqual({run['id']: run['submitted_by_email'] for run in runs}['a'], 'alice')
        self.assertEqual(tasks.get_case_task('b', case_id)['actor'], 'bob')
        with self.assertRaises(ValueError):
            tasks.get_case_task('b', 'other-case')
        with self.assertRaises(ValueError):
            tasks.enqueue('b', 'alice', 'resume', {})
        with self.assertRaises(ValueError):
            tasks.submit({'id': 'missing', 'actor': 'alice', 'query': 'Missing case'}, target_case='missing')
        with tasks.connection() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM investigation_tasks WHERE id='missing'").fetchone())
            self.assertIsNone(conn.execute("SELECT 1 FROM investigation_commands WHERE investigation_id='missing'").fetchone())
