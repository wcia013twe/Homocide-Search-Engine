import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from research_app.exa import exa_search
from research_app.search_audit import SearchAuditStore, _write_json


class ExaAndAuditTests(unittest.TestCase):
    @patch("databricks.sdk.WorkspaceClient")
    def test_uc_volume_artifact_uses_files_api_without_overwrite(self, client):
        from hashlib import sha256

        path = Path("/Volumes/homicide_research/research/sources_documents/raw/test.json")
        digest = _write_json(path, {"query": "seed"})
        files = client.return_value.files
        files.create_directory.assert_called_once_with(path.parent.as_posix())
        args, kwargs = files.upload.call_args
        self.assertEqual(args[0], path.as_posix())
        self.assertEqual(sha256(args[1].getvalue()).hexdigest(), digest)
        self.assertFalse(kwargs["overwrite"])

    @patch("research_app.exa.requests.post")
    @patch.dict(os.environ, {"EXA_API_KEY": "test-key"})
    def test_exa_normalizes_highlights_and_keeps_raw_response(self, post):
        response = Mock()
        response.json.return_value = {
            "requestId": "exa-request",
            "searchTime": 123,
            "costDollars": {"total": 0.004},
            "results": [{"id": "exa-result", "title": "Example", "url": "https://example.com", "highlights": ["A useful excerpt"]}],
        }
        post.return_value = response

        result = exa_search("Example homicide")

        self.assertEqual(result.provider, "exa")
        self.assertEqual(result.provider_request_id, "exa-request")
        self.assertEqual(result.cost_usd, 0.004)
        self.assertEqual(result.results[0].snippet, "A useful excerpt")
        self.assertEqual(result.raw_response["results"][0]["id"], "exa-result")
        post.assert_called_once_with(
            "https://api.exa.ai/search",
            headers={"x-api-key": "test-key", "Content-Type": "application/json"},
            json={"query": "Example homicide", "numResults": 10, "contents": {"highlights": True}},
            timeout=20,
        )

    def test_audit_writes_raw_artifacts_before_delta_rows(self):
        response = exa_search_response()
        with tempfile.TemporaryDirectory() as directory:
            store = SearchAuditStore(directory, "warehouse-id")
            with patch.object(store, "_insert_rows") as insert_rows:
                record = store.record(response, "researcher@example.edu")

            request = json.loads(Path(record.raw_request_path).read_text(encoding="utf-8"))
            raw_response = json.loads(Path(record.raw_response_path).read_text(encoding="utf-8"))
            self.assertEqual(request["query"], "Example homicide")
            self.assertEqual(raw_response, response.raw_response)
            self.assertEqual(len(record.raw_response_sha256), 64)
            insert_rows.assert_called_once()

    def test_triage_artifact_links_to_search_and_preserves_prior_decisions(self):
        from uuid import uuid4

        with tempfile.TemporaryDirectory() as directory:
            store = SearchAuditStore(directory, "warehouse-id")
            connection = Mock()
            connection.__enter__ = Mock(return_value=connection)
            connection.__exit__ = Mock(return_value=False)
            run_id = str(uuid4())
            with patch.object(store, "_connection", return_value=connection):
                first = store.record_triage(run_id, {"prompt_version": "v1"})
                second = store.record_triage(run_id, {"prompt_version": "v2"})
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(Path(first).read_text())["search_run_id"], run_id)
            self.assertEqual(json.loads(Path(first).read_text())["decision"]["prompt_version"], "v1")
            self.assertEqual(connection.cursor.return_value.execute.call_count, 2)


def exa_search_response():
    with patch("research_app.exa.requests.post") as post, patch.dict(os.environ, {"EXA_API_KEY": "test-key"}):
        response = Mock()
        response.json.return_value = {
            "requestId": "exa-request",
            "results": [{"id": "exa-result", "title": "Example", "url": "https://example.com", "highlights": ["A useful excerpt"]}],
        }
        post.return_value = response
        return exa_search("Example homicide")


if __name__ == "__main__":
    unittest.main()
