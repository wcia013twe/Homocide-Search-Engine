"""AI coding completes investigations; humans resolve the combined case evidence."""
from functools import partial
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from research_app.research_session import open_session, ResearchSession
from research_app.search_provider import SearchResponse, SearchResult
from research_app.source_collection import collect_sources
from test_research_profile import answer


class CollectionWorkflowTests(unittest.TestCase):
    def services(self):
        search = Mock(side_effect=lambda provider, query: SearchResponse('exa', query, {}, {}, (
            SearchResult('Report', 'https://example.invalid/report', 'Age 47.'),)))
        triage = Mock(return_value={'assessments': [{'result_rank': 1, 'label': 'candidate_evidence',
            'reason': 'Relevant', 'duplicate_of_rank': None}], 'next_queries': []})
        def extract(seed, sources):
            return [dict(claim_id='age', subject_id='victim_1', field='age', value=47,
                         source_id=next(iter(sources)), passage='Age 47.')]
        return search, triage, dict(extract_claims=extract,
            decide_claims=lambda *args: {'answers': {'age': answer()}}, required_fields=('age', 'race'))

    def test_ai_coding_finishes_with_unresolved_fields_and_retains_evidence(self):
        search, triage, options = self.services()
        code = Mock(side_effect=lambda seed, profile, sources, fields: {
            'victim_1.age': dict(value=47, status='Reported', claim_ids=['age'],
                source_ids=[next(iter(sources))], reason='Explicit age')})
        with tempfile.TemporaryDirectory() as directory:
            with open_session(directory, triage, search, max_searches=1, coding_pass=code, **options) as session:
                state = session.start('case', 'researcher', 'seed', automatic_searches=True)
                self.assertEqual(state['status'], 'ready_for_case_review')
                self.assertFalse(session.inspect('case', 'researcher').next)
                self.assertEqual(state['coded_fields']['victim_1.age']['value'], 47)
                self.assertNotIn('race', state['coded_fields'])
                self.assertIn('race', state['coding_review']['unresolved_fields'])
                self.assertEqual(state['coding_review']['decision_origin'], 'automatic')
                self.assertEqual(state['profile']['victim_1.age']['claims'][0]['passage'], 'Age 47.')
                self.assertNotIn('reviewed_at', state['coding_review'])
            with open_session(directory, triage, search, max_searches=1, coding_pass=code, **options) as session:
                self.assertFalse(session.inspect('case', 'researcher').next)
            search.assert_called_once()
            code.assert_called_once()

    def test_automatic_collection_finishes_and_reopens_without_more_calls(self):
        search, _, options = self.services()
        def assess(query, results):
            return {'assessments': [{'result_rank': 1, 'label': 'candidate_evidence',
                'reason': 'Relevant', 'duplicate_of_rank': None}], 'next_queries': [{
                'query': query + ' updates', 'target_gap': 'case_collection',
                'reason': 'Seek later reporting', 'based_on_ranks': [1]}]}
        with tempfile.TemporaryDirectory() as directory:
            with open_session(directory, assess, search, **options) as session:
                state = session.start('automatic', 'researcher', 'seed', automatic_searches=True)
                self.assertEqual(state['search_round'], 3)
                completed_searches = state['search_count']
                self.assertFalse(session.inspect('automatic', 'researcher').next)
                self.assertEqual(state['status'], 'ready_for_case_review')
            with open_session(directory, assess, search, **options) as session:
                self.assertEqual(session.inspect('automatic', 'researcher').values['sources'], state['sources'])
                self.assertFalse(session.inspect('automatic', 'researcher').next)
            self.assertEqual(search.call_count, completed_searches)

    def test_restart_preserves_full_sources_and_search_decisions(self):
        search, triage, options = self.services()
        fetch = Mock(return_value={'text': 'Age 47.', 'media_type': 'text/html',
                                   'final_url': 'https://example.invalid/report'})
        with tempfile.TemporaryDirectory() as directory:
            options['collect_sources'] = partial(collect_sources, volume_path=directory, fetch=fetch)
            with open_session(directory, triage, search, max_searches=2, **options) as session:
                first = session.start('case', 'researcher', 'seed')
                self.assertEqual(session.inspect('case', 'researcher').next, ('review_next',))
            with open_session(directory, triage, search, max_searches=2, **options) as session:
                final = session.resume('case', 'researcher', dict(action='stop',
                    search_run_id=first['search_run_id'], reason='Enough collected evidence'))
                self.assertFalse(session.inspect('case', 'researcher').next)
                self.assertEqual(final['review_history'][0]['reason'], 'Enough collected evidence')
                self.assertEqual(next(iter(final['sources'].values()))['text'], 'Age 47.')
            fetch.assert_called_once()
            self.assertEqual(len(list(Path(directory).glob('raw/source_documents/**/*.json'))), 1)

    def test_empty_collection_does_not_claim_coding_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            extract = Mock()
            with open_session(directory, Mock(), Mock(return_value=SearchResponse('exa', 'seed', {}, {}, ())),
                              extract_claims=extract, decide_claims=lambda *args: {'answers': {}},
                              required_fields=('age',)) as session:
                result = session.start('empty', 'researcher', 'seed')
                self.assertEqual(result['status'], 'no_evidence')
                extract.assert_not_called()

    def test_legacy_checkpoint_handoff_is_guarded_and_makes_no_service_calls(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import StateGraph, START, END
        from langgraph.types import interrupt
        from research_app.research_agent import ResearchState, build_research_graph
        profile = {'victim_1.age': {'value': None, 'conflicting': True, 'claims': [
            dict(claim_id='a', source_id='s', value=47, passage='Age 47.'),
            dict(claim_id='b', source_id='s', value=48, passage='Age 48.')]}}
        state = dict(query='seed', researcher='alice', search_run_id='search', profile=profile,
                     sources={'s': {'text': 'Age 47. Age 48.', 'url': 'https://example.invalid'}},
                     automatic_coded_fields={})
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'checkpoints.sqlite3')
            with SqliteSaver.from_conn_string(db) as saver:
                old = StateGraph(ResearchState)
                old.add_node('final_coding', lambda state: interrupt(dict(stage='final_coding',
                    search_run_id=state['search_run_id'], fields=profile)))
                old.add_edge(START, 'final_coding')
                old.add_edge('final_coding', END)
                old.compile(checkpointer=saver).invoke(state, {'configurable': {'thread_id': 'legacy'}})
            with SqliteSaver.from_conn_string(db) as saver:
                search, triage = Mock(), Mock()
                graph = build_research_graph(search=search, triage=triage, checkpointer=saver, review=True,
                    extract_claims=Mock(), decide_claims=Mock(), required_fields=('age',))
                session = ResearchSession(graph, None, [None])
                decision = dict(search_run_id='search', action='case_review')
                for actor, payload in [('other', decision), ('alice', {**decision, 'search_run_id': 'stale'}),
                                       ('alice', {**decision, 'fields': {}})]:
                    with self.assertRaises(ValueError):
                        session.finalize('legacy', actor, payload)
                    self.assertEqual(session.inspect('legacy', 'alice').next, ('final_coding',))
                final = session.finalize('legacy', 'alice', decision)
                self.assertEqual(final['status'], 'ready_for_case_review')
                self.assertEqual(final['profile'], profile)
                self.assertEqual(final['sources'], state['sources'])
                self.assertFalse(session.inspect('legacy', 'alice').next)
                with self.assertRaises(ValueError):
                    session.finalize('legacy', 'alice', decision)
                search.assert_not_called()
                triage.assert_not_called()

    def test_session_api_finishes_without_a_human_coding_gate(self):
        from contextlib import contextmanager
        import os
        from uuid import uuid4
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from research_app.agent_server import app
        search, triage, options = self.services()
        with tempfile.TemporaryDirectory() as directory:
            @contextmanager
            def backend(key):
                with open_session(directory, triage, search, max_searches=1, **options) as session:
                    yield session
            with patch.dict(os.environ, {'DATABRICKS_APP_NAME': 'test-app'}), patch(
                    'research_app.agent_server.open_hosted_session', backend):
                client = TestClient(app)
                headers = {'x-forwarded-user': 'researcher'}
                sid = str(uuid4())
                response = client.post('/sessions', headers=headers, json=dict(session_id=sid, query='seed'))
                self.assertEqual(response.status_code, 200, response.text)
                state = response.json()
                self.assertEqual(state['status'], 'ready_for_case_review')
                self.assertFalse(state['pending_review'])
                result = client.post(f'/sessions/{sid}/finalize', headers=headers,
                    json=dict(search_run_id=state['search_run_id'], action='case_review'))
                self.assertEqual(result.status_code, 409)
