import unittest
from research_app.evidence import source_record, attributed_claim
from research_app.research_profile import update_profile
from test_research_profile import answer


class EvidenceTests(unittest.TestCase):
    def test_locator_and_version_bind_to_saved_text(self):
        source = source_record('s', url='https://example.com', text='Age 47.')
        claim = attributed_claim(dict(claim_id='c', field='age', value=47,
                                     source_id='s', passage='47', subject_id='victim_1'), {'s': source})
        self.assertEqual(claim['locator'], dict(start=4, end=6, page=None))
        self.assertEqual(claim['content_sha256'], source['content_sha256'])
        with self.assertRaises(ValueError):
            attributed_claim({**claim, 'locator': dict(start=0, end=2, page=None)}, {'s': source})

    def test_subjects_do_not_conflict_with_each_other(self):
        sources = {'s': source_record('s', url='https://example.com', text='47 and 49')}
        claims = [dict(claim_id=subject, subject_id=subject, field='age', value=value,
                       source_id='s', passage=str(value))
                  for subject, value in [('victim_1', 47), ('offender_1', 49)]]
        result = update_profile({}, claims, sources, {c['claim_id']: answer() for c in claims}, ())
        self.assertEqual(result['profile']['victim_1.age']['value'], 47)
        self.assertEqual(result['profile']['offender_1.age']['value'], 49)
        self.assertEqual(result['gaps'], [])
