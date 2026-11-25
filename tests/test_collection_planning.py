import unittest

from research_app.collection_planning import plan_collection
from research_app.research_triage import NextQuery


class CollectionPlanningTests(unittest.TestCase):
    def test_filled_profile_still_proposes_case_collection(self):
        result = plan_collection('Case name', {'one': {'text': 'Some facts', 'result_rank': 1}},
                                 {}, [], [{'query': 'Case name'}])
        self.assertFalse(result['collection_review_recommended'])
        self.assertEqual(result['new_source_ids'], ['one'])
        self.assertTrue(result['next_queries'])
        for proposal in result['next_queries']:
            NextQuery.model_validate(proposal)
            self.assertEqual(proposal['target_gap'], 'case_collection')

    def test_repeated_text_recommends_review_without_claiming_saturation(self):
        previous = {'one': {'text': 'Same report', 'result_rank': 1}}
        current = {**previous, 'two': {'text': 'Same report', 'result_rank': 2}}
        result = plan_collection('Case', current, previous, [],
                                 [{'query': 'Case'}, {'query': 'Case incident updates'}], result_ranks=[2])
        self.assertTrue(result['collection_review_recommended'])
        self.assertEqual(result['new_source_ids'], [])
        self.assertNotIn('Case incident updates', [p['query'] for p in result['next_queries']])
        self.assertTrue(all(p['based_on_ranks'] == [2] for p in result['next_queries']))

    def test_new_text_at_same_url_is_new_material(self):
        old = {'a': {'url': 'https://example.com', 'text': 'Original'}}
        result = plan_collection('Case', {'b': {'url': 'https://example.com', 'text': 'Updated', 'result_rank': 1}},
                                 old, [], [{'query': 'Case'}, {'query': 'follow up'}])
        self.assertFalse(result['collection_review_recommended'])
        self.assertEqual(result['new_source_ids'], ['b'])

    def test_gap_and_model_proposals_keep_current_references(self):
        model = [dict(query='Case full name', target_gap='identity', reason='Name variant', based_on_ranks=[1])]
        result = plan_collection('Case', {'a': {'text': 'Facts', 'result_rank': 1}}, {},
                                 [dict(field='incident_date', reason='conflicting')],
                                 [{'query': 'Case'}], model, [1])
        self.assertEqual(result['next_queries'][0], model[0])
        self.assertTrue(any(p['target_gap'] == 'incident_date' for p in result['next_queries']))

    def test_empty_results_do_not_generate_invalid_proposals(self):
        result = plan_collection('Case', {}, {}, [], [{'query': 'Case'}], result_ranks=[])
        self.assertEqual(result['next_queries'], [])
        self.assertFalse(result['collection_review_recommended'])
