"""Real Postgres transaction tests; set an explicit disposable test DSN to run."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from research_app.collaboration import CaseStore, identifiers, setup
from research_app.gold_fields import GOLD_FIELDS
from research_app.repository import ConflictError


class IdentifierTests(unittest.TestCase):
    def test_exact_keys_exclude_names_and_ambiguous_claims(self):
        self.assertEqual(identifiers({'profile': {'person_identity': {'value': 'Example'}}}), [])
        self.assertEqual(identifiers({'profile': {'case_id': {'value': 'A', 'conflicting': True}}}), [])
        found = identifiers({'profile': {'agency': {'value': 'Police'}, 'case_number': {'value': '123'}}})
        self.assertEqual(found, [('agency_case', '["police", "123"]')])


@unittest.skipUnless(os.environ.get('HR_COLLABORATION_TEST_DSN'), 'Set a disposable Postgres test DSN')
class CollaborationDatabaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.schema = 'collaboration_test_' + uuid4().hex
        self.dsn = os.environ['HR_COLLABORATION_TEST_DSN']
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        # Isolate tables in a unique schema; never drop or truncate shared tables.
        from psycopg.conninfo import make_conninfo
        env = patch.dict(os.environ, {'HR_RESEARCH_CHECKPOINT_DSN': make_conninfo(self.dsn, options='-c search_path=' + self.schema)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.drop_schema)
        setup()
        self.alice, self.bob = CaseStore('alice'), CaseStore('bob')
        self.task = {'id': 'run-a', 'actor': 'alice', 'query': 'Example case'}
        self.state = {'profile': {'agency': {'value': 'Example agency'}, 'case_number': {'value': '123'}},
                      'sources': {'source-a': {'title': 'Example evidence', 'text': 'Victim age 47.'}}}
        self.state['profile']['victim_1.age'] = {'value': '47', 'claims': [
            {'claim_id': 'age-claim', 'subject_id': 'victim_1', 'value': '47',
             'source_id': 'source-a', 'passage': 'Victim age 47.'}]}

        self.case_id = self.alice.link_snapshot(self.task, self.state)

    def drop_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_team_contributes_and_stale_revision_is_rejected(self):
        revision = self.alice.get(self.case_id)['revision']
        self.bob.contribute(self.case_id, revision, 'Victim Age', '47', 'Reported', ['run-a:source-a'], 'Explicit age', claim_ids=['run-a:age-claim'])
        with self.assertRaises(ConflictError):
            self.alice.contribute(self.case_id, revision, 'Victim Age', '48', 'Reported', ['run-a:source-a'], 'Stale edit', claim_ids=['run-a:age-claim'])
        saved = self.alice.get(self.case_id)
        self.assertEqual(saved['fields']['Victim Age']['value'], '47')
        self.assertEqual(saved['history'][0]['actor'], 'bob')
        with self.assertRaises(ValueError):
            self.bob.contribute(self.case_id, saved['revision'], 'Victim Age', '47', 'Reported', ['other:source'], 'Wrong evidence')

    def test_exact_grouping_and_manual_confirmation(self):
        other = {**self.task, 'id': 'run-b', 'actor': 'bob'}
        self.assertEqual(self.bob.link_snapshot(other, self.state), self.case_id)
        self.assertEqual(len(self.bob.list_cases(mine=True)), 1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda i: CaseStore('bob').link_snapshot(
                {**self.task, 'id': 'parallel-' + str(i)}, self.state), range(2)))
        self.assertEqual(results, [self.case_id, self.case_id])
        new = self.bob.link_snapshot({**self.task, 'id': 'run-unmatched'}, {'sources': {}})
        self.assertNotEqual(new, self.case_id)
        with self.assertRaises(ValueError):
            self.bob.link_snapshot({**self.task, 'id': 'wrong-target'}, self.state, new, 'Confirmed')
        self.assertEqual(self.bob.link_snapshot({**self.task, 'id': 'confirmed'}, {}, self.case_id, 'Same incident reviewed'), self.case_id)

    def test_concurrent_edit_only_one_wins(self):
        revision = self.alice.get(self.case_id)['revision']
        def edit(actor):
            try:
                CaseStore(actor).contribute(self.case_id, revision, 'Victim Age', '47', 'Reported', ['run-a:source-a'], actor, claim_ids=['run-a:age-claim'])
                return 'saved'
            except ConflictError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(executor.map(edit, ['alice', 'bob']), ['saved', 'conflict'])

    def test_approval_pins_revision_and_publish_retries(self):
        with self.assertRaises(ValueError):
            self.alice.approve(self.case_id, self.alice.get(self.case_id)['revision'], 'Incomplete')
        for field in GOLD_FIELDS:
            if field != 'case_id':
                revision = self.alice.get(self.case_id)['revision']
                self.alice.contribute(self.case_id, revision, field, '47' if field == 'Victim Age' else '',
                    'Reported' if field == 'Victim Age' else 'Not Reported', ['run-a:source-a'], 'Checked evidence',
                    claim_ids=['run-a:age-claim'] if field == 'Victim Age' else [])
        revision = self.alice.get(self.case_id)['revision']
        self.bob.approve(self.case_id, revision, 'Checked all fields')
        self.bob.approve(self.case_id, revision, 'Duplicate click')
        case = self.alice.get(self.case_id)
        self.assertEqual(len(case['publications']), 1)
        self.assertEqual(len([h for h in case['history'] if h['action'] == 'approval']), 1)
        self.alice.contribute(self.case_id, revision, 'Victim Age', '47', 'Reported', ['run-a:source-a'], 'New draft', claim_ids=['run-a:age-claim'])
        self.assertEqual(self.alice.publications()[0]['snapshot']['fields']['Victim Age']['value'], '47')
        # Real SQL tests above cover storage; the gold boundary is exercised separately.
        class UnavailableGold:
            def publish(self, snapshot):
                raise RuntimeError('Unavailable warehouse')
        with self.assertLogs('research_app.collaboration', level='ERROR'):
            self.assertFalse(self.alice.publish(self.case_id, revision, UnavailableGold()))
        self.assertEqual(self.alice.publications()[0]['status'], 'failed')
        new_revision = self.alice.get(self.case_id)['revision']
        self.alice.approve(self.case_id, new_revision, 'Updated review')
        with self.assertRaises(ValueError):
            self.alice.publish(self.case_id, revision, UnavailableGold())

    def test_registered_evidence_contribution_reassignment_is_atomic(self):
        import tempfile
        from hashlib import sha256
        from unittest.mock import Mock
        from research_app.evidence_registry import setup as setup_registry, persist_state, annotate_state
        from research_app.investigation_tasks import connection
        from research_app.search_audit import _write_json
        setup_registry()
        source = self.state['sources']['source-a']
        source.update(source_id='source-a', url='https://example.com/report', evidence_kind='source_text',
                      content_sha256=sha256(source['text'].encode()).hexdigest())
        claim = self.state['profile']['victim_1.age']['claims'][0]
        claim.update(locator={'start': 0, 'end': len(source['text']), 'page': None}, content_sha256=source['content_sha256'])
        documents = Mock()
        documents.persist.return_value = 'document-a'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.json'
            source['artifact_path'] = str(path)
            _write_json(path, {'source': source})
            state = persist_state(self.task['id'], self.state, actor='alice', document_store=documents)
            self.alice.link_snapshot(self.task, state)
            revision = self.alice.get(self.case_id)['revision']
            original_assignment = state['profile']['victim_1.age']['claims'][0]['assignment_id']
            with patch.object(self.bob, '_event', side_effect=RuntimeError('Case history unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'Case history unavailable'):
                    self.bob.contribute(self.case_id, revision, 'Victim Age', '47', 'Reported',
                        ['run-a:source-a'], 'Evidence reviewed', claim_ids=['run-a:age-claim'],
                        assignment_ids=[original_assignment])
            with connection() as conn:
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_field_assignments').fetchone()['n'], 1)
            self.assertEqual(self.alice.get(self.case_id)['revision'], revision)
            self.bob.contribute(self.case_id, revision, 'Victim Age', '47', 'Reported',
                ['run-a:source-a'], 'Evidence reviewed', claim_ids=['run-a:age-claim'],
                assignment_ids=[original_assignment])
            with self.assertRaises(ConflictError):
                self.alice.contribute(self.case_id, revision, 'Victim Age', '47', 'Reported',
                    ['run-a:source-a'], 'Stale revision', claim_ids=['run-a:age-claim'],
                    assignment_ids=[original_assignment])
            fresh = self.alice.get(self.case_id)
            current_claim = fresh['investigations'][0]['snapshot']['profile']['victim_1.age']['claims'][0]
            self.assertNotEqual(current_claim['assignment_id'], original_assignment)
            self.alice.contribute(self.case_id, fresh['revision'], 'Victim Age', '47', 'Reported',
                ['run-a:source-a'], 'Refreshed review', claim_ids=['run-a:age-claim'],
                assignment_ids=[current_claim['assignment_id']])
            latest = annotate_state('run-a', state)['profile']['victim_1.age']['claims'][0]
            self.assertEqual(latest['assigned_field'], 'Victim Age')
            self.assertEqual(latest['passage_id'], state['profile']['victim_1.age']['claims'][0]['passage_id'])


    def decisions(self):
        return {name: {'status': 'Reported' if name == 'Victim Age' else 'Not Reported',
                       'value': '47' if name == 'Victim Age' else None,
                       'claim_ids': ['run-a:age-claim'] if name == 'Victim Age' else [],
                       'source_ids': ['run-a:source-a']}
                for name in GOLD_FIELDS if name != 'case_id'}

    def test_bulk_review_is_atomic_and_unchanged_reapproval_keeps_revision(self):
        decisions = self.decisions()
        revision = self.alice.get(self.case_id)['revision']
        decisions['Victim Age']['claim_ids'] = ['other:claim']
        with self.assertRaises(ValueError):
            self.bob.review_and_approve(self.case_id, revision, decisions, 'Invalid claim')
        case = self.alice.get(self.case_id)
        self.assertEqual(case['revision'], revision)
        self.assertEqual(case['fields'], {})
        self.assertEqual(case['publications'], [])
        self.assertEqual(len(case['history']), 1)
        approved = self.bob.review_and_approve(self.case_id, revision, self.decisions(), 'All evidence reviewed')
        self.assertEqual(approved, revision + 1)
        self.assertEqual(self.alice.get(self.case_id)['publications'][0]['approved_by'], 'bob')
        self.assertEqual(self.alice.review_and_approve(self.case_id, approved, self.decisions(), 'Reopened unchanged'), approved)
        case = self.alice.get(self.case_id)
        self.assertEqual(len(case['publications']), 1)
        self.assertEqual(len(case['history']), 3)
        with self.assertRaises(ConflictError):
            self.alice.review_and_approve(self.case_id, revision, self.decisions(), 'Stale review')

    def test_reapproval_updates_the_published_dataset_record(self):
        from copy import deepcopy
        from psycopg import sql
        from research_app.gold import GoldStore
        from test_dataset_publication import SqlConnection
        from research_app.investigation_tasks import connection
        with connection() as conn:
            columns = sql.SQL(', ').join(sql.SQL('{} text').format(sql.Identifier(name)) for name in GOLD_FIELDS)
            conn.execute(sql.SQL('CREATE TABLE homicide_gold ({})').format(columns))
        with patch('research_app.gold.TABLE', 'homicide_gold'):
            gold = GoldStore()
            gold._connection = lambda: SqlConnection(os.environ['HR_RESEARCH_CHECKPOINT_DSN'])
            revision = self.alice.get(self.case_id)['revision']
            first = self.alice.review_and_approve(self.case_id, revision, self.decisions(), 'First review')
            self.assertTrue(self.alice.publish(self.case_id, first, gold))
            state = deepcopy(self.state)
            state['profile']['victim_1.age']['claims'][0].update(value='48', passage='Corrected age 48.')
            self.alice.link_snapshot(self.task, state)
            choices = self.decisions()
            choices['Victim Age']['value'] = '48'
            revision = self.alice.get(self.case_id)['revision']
            second = self.bob.review_and_approve(self.case_id, revision, choices, 'Corrected age')
            self.assertTrue(self.bob.publish(self.case_id, second, gold))
            self.assertTrue(self.alice.publish(self.case_id, first, gold))
            with connection() as conn:
                rows = conn.execute('SELECT case_id, "Victim Age" FROM homicide_gold').fetchall()
            self.assertEqual(rows, [{'case_id': self.case_id, 'Victim Age': '48'}])
            receipts = self.alice.get(self.case_id)['publications']
            self.assertEqual([receipt['status'] for receipt in receipts], ['published', 'published'])
            self.assertEqual(receipts[1]['snapshot']['fields']['Victim Age']['value'], '47')

    def test_two_reviewers_cannot_approve_different_drafts_at_the_same_revision(self):
        revision = self.alice.get(self.case_id)['revision']
        def approve(actor):
            try:
                CaseStore(actor).review_and_approve(self.case_id, revision, self.decisions(), actor)
                return 'approved'
            except ConflictError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(executor.map(approve, ['alice', 'bob']), ['approved', 'conflict'])
        self.assertEqual(len(self.alice.get(self.case_id)['publications']), 1)

    def case_app(self):
        from streamlit.testing.v1 import AppTest
        from research_app.investigation_tasks import setup as setup_tasks
        setup_tasks()
        app = AppTest.from_string('''
import streamlit as st
from research_app.cases import render
st.session_state.setdefault('research_user', 'bob')
render({}, lambda: None)
''').run()
        self.assertFalse(app.exception)
        return app

    def test_case_library_opens_three_tabs_without_default_conflict_choice(self):
        from copy import deepcopy
        state = deepcopy(self.state)
        state['profile']['victim_1.age']['claims'][0]['value'] = '48'
        self.bob.link_snapshot({'id': 'run-b', 'actor': 'bob', 'query': 'Age verification'}, state, self.case_id, 'Same case')
        app = self.case_app()
        self.assertEqual(len(app.tabs), 0)
        app.button(key='open_case_' + self.case_id).click().run()
        self.assertFalse(app.exception)
        self.assertEqual([tab.label for tab in app.tabs], ['Investigations', 'Review', 'Sources'])
        key = f"case_review_{self.case_id}_{self.alice.get(self.case_id)['revision']}:choice:Victim Age"
        self.assertIsNone(app.radio(key=key).value)

    def test_direct_review_route_ignores_library_filters_and_approved_case_stays_openable(self):
        revision = self.alice.get(self.case_id)['revision']
        approved = self.alice.review_and_approve(self.case_id, revision, self.decisions(), 'Reviewed')
        app = self.case_app()
        self.assertTrue(any('color:#586671' in item.value for item in app.markdown))
        app.text_input[0].set_value('no matching case').run()
        app.session_state['case_to_open'] = self.case_id
        app.session_state['case_tab_to_open'] = 'Review'
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['case_tabs_' + self.case_id], 'Review')
        key = f"case_review_{self.case_id}_{approved}:choice:Victim Age"
        self.assertEqual(app.radio(key=key).value, 0)
        self.assertEqual(self.alice.get(self.case_id)['revision'], approved)


if __name__ == '__main__':
    unittest.main()
