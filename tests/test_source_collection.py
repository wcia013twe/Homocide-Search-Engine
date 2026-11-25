import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from research_app.source_collection import _public_address, _Text, collect_sources


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.results = [dict(result_rank=1, url='https://example.com/article', title='Report', snippet='Excerpt')]
        self.assessments = [dict(result_rank=1, label='candidate_evidence')]

    def test_full_text_is_saved_and_reused(self):
        fetch = Mock(return_value=dict(text='Full report.', raw_base64='abc', final_url='https://example.com/article'))
        with tempfile.TemporaryDirectory() as directory:
            sources = collect_sources(self.results, self.assessments, 'run', volume_path=directory, fetch=fetch)
            source = next(iter(sources.values()))
            self.assertEqual(source['text'], 'Full report.')
            self.assertEqual(source['evidence_kind'], 'source_text')
            self.assertEqual(source['retrieval_status'], 'retrieved')
            self.assertEqual(json.loads(Path(source['artifact_path']).read_text())['source'], source)
            again = collect_sources(self.results, self.assessments, 'other-run', existing_sources=sources, fetch=fetch)
            self.assertEqual(len(again), 1)
            self.assertEqual(again[source['source_id']]['search_results'], [
                {'search_run_id': 'run', 'result_rank': 1, 'search_result_id': None},
                {'search_run_id': 'other-run', 'result_rank': 1, 'search_result_id': None},
            ])
            self.assertEqual(len(sources[source['source_id']]['search_results']), 1)
            fetch.assert_called_once()

    def test_failure_keeps_explicit_excerpt(self):
        sources = collect_sources(self.results, self.assessments, 'run', fetch=Mock(side_effect=ValueError('Unsupported PDF')))
        source = next(iter(sources.values()))
        self.assertEqual(source['text'], 'Excerpt')
        self.assertEqual(source['evidence_kind'], 'search_excerpt')
        self.assertEqual(source['retrieval_status'], 'failed')
        self.assertEqual(source['retrieval_error'], 'Unsupported PDF')

    def test_triage_exclusions_are_not_fetched(self):
        fetch = Mock()
        self.assertEqual(collect_sources(self.results, [dict(result_rank=1, label='irrelevant')], 'run', fetch=fetch), {})
        fetch.assert_not_called()

    def test_private_and_mixed_dns_are_rejected(self):
        for addresses in [['127.0.0.1'], ['8.8.8.8', '10.1.2.3'], ['::1']]:
            with self.subTest(addresses=addresses), patch('research_app.source_collection.socket.getaddrinfo',
                    return_value=[(2, 1, 6, '', (address, 443)) for address in addresses]):
                with self.assertRaises(ValueError):
                    _public_address('https://example.com')

    def test_credentials_and_non_web_schemes_rejected_before_dns(self):
        for url in ['file:///etc/passwd', 'https://name:pass@example.com', 'http://example.com:8080']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                _public_address(url)

    def test_html_omits_script_and_retains_paragraphs(self):
        parser = _Text()
        parser.feed('<article><p>First &amp; second.</p><script>hidden()</script><p>Next.</p></article>')
        text = ''.join(parser.parts)
        self.assertIn('First & second.', text)
        self.assertIn('Next.', text)
        self.assertNotIn('hidden()', text)
