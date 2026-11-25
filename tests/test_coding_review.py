import unittest
from copy import deepcopy

from research_app.coding_review import prepare_coding_review, apply_coding_review, automatic_coding


class CodingReviewTests(unittest.TestCase):
    def setUp(self):
        self.sources = {'news': {'source_type': 'media_report'},
                        'court': {'source_type': 'official_criminal_justice_document'}}
        self.profile = {'age': {'value': None, 'conflicting': True, 'claims': [
            {'claim_id': 'a', 'source_id': 'news', 'value': 47},
            {'claim_id': 'b', 'source_id': 'court', 'value': 48}]}}
        self.decision = {'reason': 'Reviewed case material', 'fields': {
            'age': {'status': 'Reported', 'value': 48, 'claim_ids': ['b'],
                    'source_ids': [], 'reason': 'Court record resolves conflict.'}}}

    def test_hierarchy_suggests_but_keeps_conflicting_claims(self):
        prepared = prepare_coding_review(self.profile, self.sources)
        self.assertEqual(prepared['fields']['age']['suggestion']['value'], 48)
        original = deepcopy(self.profile)
        result = apply_coding_review(self.profile, self.sources, self.decision)
        self.assertEqual(result['coded_fields']['age']['value'], 48)
        self.assertEqual(len(result['coded_fields']['age']['claims']), 2)
        self.assertEqual(self.profile, original)

    def test_unclassified_source_does_not_receive_rank_from_url(self):
        self.sources['court'] = {'url': 'https://court.gov/case'}
        self.assertIsNone(prepare_coding_review(self.profile, self.sources)['fields']['age']['suggestion'])

    def test_rejects_unsupported_value_and_foreign_reference(self):
        for changes in [{'value': 50}, {'claim_ids': ['foreign']}]:
            decision = deepcopy(self.decision)
            decision['fields']['age'].update(changes)
            with self.assertRaises(ValueError):
                apply_coding_review(self.profile, self.sources, decision)

    def test_missing_and_unclear_are_explicit(self):
        decision = {'reason': 'Review complete', 'fields': {
            'race': {'status': 'Not Reported', 'value': None, 'source_ids': ['news'], 'reason': 'Reviewed sources omit race.'},
            'age': {'status': 'Unclear', 'value': None, 'claim_ids': ['a', 'b'], 'reason': 'Conflict remains.'}}}
        result = apply_coding_review(self.profile, self.sources, decision, ('race',))
        self.assertEqual(result['unresolved_fields'], ['age'])
        decision['fields']['race']['source_ids'] = []
        with self.assertRaises(ValueError):
            apply_coding_review(self.profile, self.sources, decision, ('race',))

    def test_every_field_needs_review(self):
        with self.assertRaises(ValueError):
            apply_coding_review(self.profile, self.sources, self.decision, ('race',))

    def test_subject_field_satisfies_legacy_required_name(self):
        profile = {'victim_1.age': self.profile['age']}
        prepared = prepare_coding_review(profile, self.sources, ('age',))
        self.assertEqual(list(prepared['fields']), ['victim_1.age'])

    def test_review_preserves_classification_and_codebook(self):
        self.decision.update(source_types={'court': 'official_criminal_justice_document'}, codebook_version='local-1')
        result = apply_coding_review(self.profile, self.sources, self.decision)
        self.assertEqual(result['coding_review']['source_types'], self.decision['source_types'])
        self.assertEqual(result['coded_fields']['age']['codebook_version'], 'local-1')
        self.decision['source_types']['court'] = 'government_domain'
        with self.assertRaises(ValueError):
            apply_coding_review(self.profile, self.sources, self.decision)

    def test_automatic_consolidation_inference_and_conflicts(self):
        sources = {'s': {'text': 'She was killed on January 2, 2020. Female.'}}
        date_claim = {'claim_id': 'date', 'source_id': 's', 'value': '2020-01-02',
                      'passage': 'She was killed on January 2, 2020.'}
        female = {'claim_id': 'f', 'source_id': 's', 'value': 'Female', 'passage': 'Female.'}
        female2 = {**female, 'claim_id': 'f2', 'value': 'female'}
        profile = {'Date Of Incident': {'claims': [date_claim]}, 'Victim Gender': {'claims': [female, female2]}}
        proposals = {
            'Victim Gender': {'value': 'female', 'claim_ids': ['f', 'f2'], 'confidence': .95,
                              'reason': 'Equivalent gender values.', 'inferred': False},
            'Date Of Death': {'value': '2020-01-02', 'claim_ids': ['date'], 'confidence': .95,
                              'reason': 'The source says she was killed that day.', 'inferred': True}}
        coded = automatic_coding(profile, sources, proposals, ('Date Of Death',))
        self.assertEqual(set(coded), {'Victim Gender', 'Date Of Death'})
        self.assertTrue(coded['Date Of Death']['inferred'])
        self.assertEqual(coded['Date Of Death']['supporting_claims'][0]['passage'], date_claim['passage'])
        profile['Victim Gender']['claims'].append({**female, 'claim_id': 'm', 'value': 'Male'})
        proposals['Date Of Death']['confidence'] = .7
        self.assertEqual(automatic_coding(profile, sources, proposals, ('Date Of Death',)), {})
        proposals['Date Of Death']['confidence'] = .95
        profile['Date Of Incident']['claims'].append({**date_claim, 'claim_id': 'other', 'value': '2020-01-03'})
        self.assertEqual(automatic_coding(profile, sources, proposals, ('Date Of Death',)), {})

    def test_automatic_coding_rejects_unattributed_support(self):
        claim = {'claim_id': 'a', 'source_id': 's', 'value': 'female', 'passage': 'not in document'}
        proposal = {'gender': {'value': 'female', 'claim_ids': ['a'], 'confidence': .99,
                               'reason': 'Reported', 'inferred': False}}
        self.assertEqual(automatic_coding({'gender': {'claims': [claim]}}, {'s': {'text': 'other'}}, proposal), {})
