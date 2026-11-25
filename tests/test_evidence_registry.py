"""Evidence identities and provenance must remain stable across replay and reassignment."""
from copy import deepcopy
from hashlib import sha256
import tempfile
import unittest
from unittest.mock import MagicMock, Mock

from research_app.evidence_registry import canonical_url, prepare_state
from research_app.source_collection import collect_sources


class EvidenceRegistryTests(unittest.TestCase):
    def state(self, directory):
        sources = collect_sources(
            [dict(result_rank=1, url='https://example.com/report', snippet='Age 47.', search_result_id='result-1')],
            [dict(result_rank=1, label='candidate_evidence')], 'run-1', volume_path=directory,
            fetch=Mock(return_value=dict(text='Age 47.', final_url='https://example.com/report')))
        source_id = next(iter(sources))
        return dict(sources=sources, profile={'victim_1.age': {'claims': [dict(
            claim_id='claim-1', source_id=source_id, subject_id='victim_1', value='47',
            passage='Age 47.', locator=dict(start=0, end=7, page=None),
            content_sha256=sha256(b'Age 47.').hexdigest())]}})

    def test_scoped_claims_shared_document_versions_and_idempotent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.state(directory)
            first = prepare_state('investigation-a', original)
            again = prepare_state('investigation-a', first)
            second = prepare_state('investigation-b', original)
        self.assertEqual(first, again)
        self.assertNotEqual(first['profile']['victim_1.age']['claims'][0]['registry_claim_id'],
                            second['profile']['victim_1.age']['claims'][0]['registry_claim_id'])
        self.assertEqual(next(iter(first['sources'].values()))['version_id'],
                         next(iter(second['sources'].values()))['version_id'])
        self.assertNotIn('registry_claim_id', original['profile']['victim_1.age']['claims'][0])

    def test_reassignment_keeps_claim_passage_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            state = prepare_state('run', self.state(directory))
        moved = deepcopy(state)
        moved['profile']['Offender Age'] = moved['profile'].pop('victim_1.age')
        moved = prepare_state('run', moved)
        claim = state['profile']['victim_1.age']['claims'][0]
        reassigned = moved['profile']['Offender Age']['claims'][0]
        self.assertEqual(claim['registry_claim_id'], reassigned['registry_claim_id'])
        self.assertEqual(claim['passage_id'], reassigned['passage_id'])
        self.assertEqual(reassigned['original_field'], 'victim_1.age')

    def test_invalid_hash_or_passage_rejects_entire_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.state(directory)
            claim = state['profile']['victim_1.age']['claims'][0]
            claim['passage'] = 'Invented age'
            with self.assertRaisesRegex(ValueError, 'exact source text'):
                prepare_state('run', state)
            claim['passage'] = 'Age 47.'
            next(iter(state['sources'].values()))['content_sha256'] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'content hash'):
                prepare_state('run', state)

    def test_source_versions_distinguish_excerpt_from_full_text(self):
        with tempfile.TemporaryDirectory() as directory:
            full = self.state(directory)
            excerpt = deepcopy(full)
            next(iter(excerpt['sources'].values()))['evidence_kind'] = 'search_excerpt'
            self.assertNotEqual(next(iter(prepare_state('run', full)['sources'].values()))['version_id'],
                                next(iter(prepare_state('run', excerpt)['sources'].values()))['version_id'])

    def test_canonical_url_does_not_discard_query_or_change_path(self):
        self.assertEqual(canonical_url('https://Example.COM/Report?a=2#section'), 'https://example.com/Report?a=2')
        with self.assertRaises(ValueError):
            canonical_url('https://user:password@example.com/')

    def test_document_matching_reuses_existing_identity_and_rejects_ambiguous_urls(self):
        from research_app.evidence_registry import DatabricksDocuments
        audit = MagicMock()
        cursor = audit._connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [('existing-document',)]
        with tempfile.TemporaryDirectory() as directory:
            source = next(iter(prepare_state('run', self.state(directory))['sources'].values()))
        documents = DatabricksDocuments(audit)
        self.assertEqual(documents.persist(source), 'existing-document')
        merge = cursor.execute.call_args_list[-1]
        self.assertIn('WHEN NOT MATCHED THEN INSERT', merge.args[0])
        self.assertNotIn('UPDATE SET', merge.args[0])
        cursor.fetchall.return_value = [('one',), ('two',)]
        with self.assertRaisesRegex(ValueError, 'Multiple document records'):
            documents.persist(source)
        self.assertIsNone(documents.resolve_result('run', 1))


import os
from unittest.mock import patch
from uuid import uuid4


@unittest.skipUnless(os.environ.get('HR_COLLABORATION_TEST_DSN'), 'Set a disposable Postgres test DSN')
class EvidenceRegistryDatabaseTests(unittest.TestCase):
    state = EvidenceRegistryTests.state
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        self.schema = 'evidence_test_' + uuid4().hex
        self.dsn = os.environ['HR_COLLABORATION_TEST_DSN']
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        env = patch.dict(os.environ, {'HR_RESEARCH_CHECKPOINT_DSN': make_conninfo(self.dsn, options='-c search_path=' + self.schema)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.drop_schema)
        from research_app.evidence_registry import setup
        setup()
        self.documents = Mock()
        self.documents.persist.side_effect = lambda source: source['document_key']
        self.documents.resolve_result.return_value = None
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def drop_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def persist(self, state, investigation='run'):
        from research_app.evidence_registry import persist_state
        return persist_state(investigation, state, actor='alice', document_store=self.documents)

    def test_replay_mapping_source_links_and_annotations(self):
        from research_app.evidence_registry import annotate_state
        from research_app.investigation_tasks import connection
        state = self.state(self.directory.name)
        first = self.persist(state)
        self.persist(first)
        self.documents.persist.assert_called_once()
        with connection() as conn:
            for table in ('evidence_documents', 'evidence_document_versions', 'evidence_claims', 'evidence_passages', 'evidence_field_assignments', 'evidence_search_links'):
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM ' + table).fetchone()['n'], 1, table)
            link = conn.execute('SELECT * FROM evidence_search_links').fetchone()
            self.assertEqual(link['search_result_id'], 'result-1')
        projected = annotate_state('run', state)
        self.assertEqual(next(iter(projected['sources'].values()))['document_id'],
                         next(iter(first['sources'].values()))['document_id'])
        self.assertEqual(projected['profile']['victim_1.age']['claims'][0]['assigned_field'], 'victim_1.age')
        self.persist(state, 'other-run')
        with connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_claims').fetchone()['n'], 2)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_documents').fetchone()['n'], 1)

    def test_reassignment_preserves_original_and_rejects_stale_revision(self):
        from research_app.evidence_registry import reassign_claim, annotate_state
        from research_app.repository import ConflictError
        from research_app.investigation_tasks import connection
        state = self.persist(self.state(self.directory.name))
        claim = state['profile']['victim_1.age']['claims'][0]
        selected = reassign_claim('run', claim['claim_id'], 'Victim Age', actor='bob', reason='Codebook mapping', expected_assignment_id=claim['assignment_id'])
        with self.assertRaises(ConflictError):
            reassign_claim('run', claim['claim_id'], 'Offender Age', actor='alice', reason='Old revision', expected_assignment_id=claim['assignment_id'])
        self.persist(state)
        read = annotate_state('run', state)
        self.assertEqual(read['profile']['victim_1.age']['claims'][0]['assignment_id'], selected)
        self.assertEqual(read['profile']['victim_1.age']['claims'][0]['assigned_field'], 'Victim Age')
        with connection() as conn:
            stored = conn.execute('SELECT * FROM evidence_claims').fetchone()
            self.assertEqual(stored['original_field'], 'victim_1.age')
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_field_assignments').fetchone()['n'], 2)

    def test_reused_alias_failure_rolls_back_whole_batch(self):
        from research_app.investigation_tasks import connection
        state = self.persist(self.state(self.directory.name))
        altered = deepcopy(state)
        source = next(iter(altered['sources'].values()))
        source['text'] = 'Age 49.'
        source['content_sha256'] = sha256(b'Age 49.').hexdigest()
        altered['profile'] = {}
        with self.assertRaisesRegex(ValueError, 'alias cannot change'):
            self.persist(altered)
        with connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_document_versions').fetchone()['n'], 1)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_claims').fetchone()['n'], 1)

    def test_shared_transaction_rolls_back_assignments_and_orders_same_timestamp(self):
        from research_app.evidence_registry import annotate_state, reassign_claim
        from research_app.investigation_tasks import connection
        state = self.persist(self.state(self.directory.name))
        claim = state['profile']['victim_1.age']['claims'][0]
        with self.assertRaisesRegex(RuntimeError, 'contribution failed'):
            with connection() as conn, conn.transaction():
                reassign_claim('run', claim['claim_id'], 'Victim Age', actor='bob', reason='Reviewed',
                               expected_assignment_id=claim['assignment_id'], conn=conn)
                raise RuntimeError('contribution failed')
        with connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence_field_assignments').fetchone()['n'], 1)
        with connection() as conn, conn.transaction():
            first = reassign_claim('run', claim['claim_id'], 'Victim Age', actor='bob', reason='Reviewed',
                                   expected_assignment_id=claim['assignment_id'], conn=conn)
            inside = annotate_state('run', state, conn=conn)['profile']['victim_1.age']['claims'][0]
            self.assertEqual(inside['assignment_id'], first)
            final = reassign_claim('run', claim['claim_id'], None, actor='bob', reason='Leave unassigned',
                                   expected_assignment_id=first, conn=conn)
        projected = annotate_state('run', state)['profile']['victim_1.age']['claims'][0]
        self.assertEqual(projected['assignment_id'], final)
        self.assertIsNone(projected['assigned_field'])
