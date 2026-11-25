import unittest

from research_app.evidence_groups import group_field_sources, case_evidence, state_evidence


class EvidenceGroupingTests(unittest.TestCase):
    def test_case_alternatives_count_documents_across_investigations(self):
        def snapshot(value, document):
            return {'profile': {'Victim Age': {'claims': [
                {'claim_id': 'age', 'source_id': 's', 'value': value, 'passage': 'Reported age'}]}},
                'sources': {'s': {'document_id': document}}}
        fields, sources = case_evidence([
            {'investigation_id': 'first', 'snapshot': snapshot('47', 'same-document')},
            {'investigation_id': 'second', 'snapshot': snapshot('47', 'same-document')},
            {'investigation_id': 'third', 'snapshot': snapshot('48', 'other-document')}])
        groups = group_field_sources(fields['Victim Age']['claims'], sources)
        self.assertEqual([(group['value'], group['source_count']) for group in groups], [('47', 1), ('48', 1)])
        self.assertEqual(len(groups[0]['sources'][0]['captures']), 2)

    def test_inference_remains_identifiable_with_its_original_passage(self):
        claim = {'claim_id': 'c', 'source_id': 's', 'value': '2020-01-02',
                 'passage': 'She was killed on January 2, 2020.'}
        state = {'profile': {'Date Of Incident': {'claims': [claim]}}, 'sources': {'s': {}},
                 'coded_fields': {'Date Of Death': {'value': '2020-01-02', 'status': 'Reported',
                     'inferred': True, 'supporting_claims': [claim], 'reason': 'Killed on that date.'}}}
        fields, _ = state_evidence(state, 'case')
        inferred = fields['Date Of Death']['claims'][0]
        self.assertTrue(inferred['inferred'])
        self.assertEqual(inferred['supporting_claim_id'], 'c')
        self.assertEqual(inferred['passage'], claim['passage'])
        self.assertEqual(fields['Date Of Incident']['claims'][0]['claim_id'], 'case:c')

    def test_preserves_conflicts_passages_and_selection(self):
        claims = [
            {'claim_id': 'a', 'source_id': 's1', 'value': '32', 'passage': 'first'},
            {'claim_id': 'b', 'source_id': 's1', 'value': '32', 'passage': 'second'},
            {'claim_id': 'c', 'source_id': 's2', 'value': '32', 'passage': 'third'},
            {'claim_id': 'd', 'source_id': 's3', 'value': '34', 'passage': 'fourth'},
        ]
        groups = group_field_sources(claims, {'s1': {'title': 'Report'}}, ['b'])
        self.assertEqual([(g['value'], g['source_count']) for g in groups], [('32', 2), ('34', 1)])
        self.assertTrue(groups[0]['sources'][0]['selected'])
        self.assertEqual([c['passage'] for c in groups[0]['sources'][0]['claims']], ['first', 'second'])
        self.assertIsNone(groups[1]['sources'][0]['source'])

    def test_versions_count_as_one_document_and_subjects_stay_separate(self):
        claims = [{'claim_id': 'a', 'source_id': 'v1', 'value': '32', 'subject_id': 'victim_1'},
                  {'claim_id': 'b', 'source_id': 'v2', 'value': '32', 'subject_id': 'victim_1'},
                  {'claim_id': 'c', 'source_id': 'v1', 'value': '32', 'subject_id': 'victim_2'}]
        groups = group_field_sources(claims, {'v1': {'document_id': 'doc'}, 'v2': {'document_id': 'doc'}})
        self.assertEqual([g['source_count'] for g in groups], [1, 1])
        self.assertEqual(len(groups[0]['sources'][0]['captures']), 2)

    def test_scoped_ids_and_reassignment_retain_original_evidence(self):
        state = {'profile': {'victim_1.age': {'value': '47', 'claims': [
            {'claim_id': 'same', 'source_id': 'source', 'value': '47', 'passage': 'age 47'}]}},
            'sources': {'source': {'title': 'Original', 'document_id': 'doc'}}}
        links = [{'investigation_id': 'first', 'snapshot': state}, {'investigation_id': 'second', 'snapshot': state}]
        fields, sources = case_evidence(links, {'Offender Age': {'value': '47', 'claim_ids': ['first:same'], 'status': 'Reported'}})
        moved = fields['Offender Age']['claims'][0]
        self.assertEqual(moved['original_field'], 'victim_1.age')
        self.assertEqual(moved['passage'], 'age 47')
        self.assertEqual(fields['Victim Age']['claims'][0]['claim_id'], 'second:same')
        self.assertIn('first:source', sources)
        self.assertEqual(state['profile']['victim_1.age']['claims'][0]['claim_id'], 'same')

    def test_legacy_unqualified_age_is_not_assumed_to_be_victim(self):
        fields, _ = state_evidence({'profile': {'age': {'value': '47'}}})
        self.assertIn('age', fields)
        self.assertNotIn('Victim Age', fields)


    def test_sources_deduplicate_existing_ids_and_urls_without_losing_captures(self):
        from research_app.evidence_groups import deduplicate_sources
        sources = {'a:1': {'document_id': 'doc', 'title': 'Capture one'},
                   'b:2': {'document_id': 'doc', 'title': 'Capture two'},
                   'a:3': {'url': 'https://EXAMPLE.com/report#section-one'},
                   'b:4': {'url': 'https://example.com/report#section-two'},
                   'a:5': {'document_key': 'stored-key'}, 'b:6': {'document_key': 'stored-key'},
                   'a:7': {}, 'b:8': {}}
        documents = deduplicate_sources(sources)
        self.assertEqual(len(documents), 5)
        self.assertEqual([len(item['captures']) for item in documents], [2, 2, 2, 1, 1])
        self.assertEqual(sum(len(item['captures']) for item in documents), len(sources))
