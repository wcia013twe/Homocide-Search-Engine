from contextlib import contextmanager
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from research_app.agent_server import app
from research_app.research_session import open_session
from research_app.search_provider import SearchResponse, SearchResult


class SessionAPITests(unittest.TestCase):
    def test_local_http_workflow_reopens_checkpoints_and_does_not_repeat_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            search = Mock(return_value=SearchResponse("exa", "seed", {}, {}, (
                SearchResult("Fixture", "https://example.invalid", "Test"),)))
            model = Mock(return_value={"assessments": [{"result_rank": 1, "label": "uncertain",
                "reason": "Need original", "duplicate_of_rank": None}], "next_queries": [{
                    "query": "seed followup", "target_gap": "Incident confirmation", "reason": "Check updates",
                    "based_on_ranks": [1]}]})

            @contextmanager
            def local_backend(unused_key):
                with open_session(directory, model, search, max_searches=2) as session:
                    yield session

            with patch.dict(os.environ, {"DATABRICKS_APP_NAME": "test-app"}), patch(
                "research_app.agent_server.open_hosted_session", local_backend
            ):
                client = TestClient(app)
                headers = {"x-forwarded-user": "researcher"}
                session_id = str(uuid4())
                body = {"session_id": session_id, "query": "seed", "provider": "Exa"}
                first = client.post("/sessions", json=body, headers=headers)
                self.assertEqual(first.status_code, 200, first.text)
                self.assertEqual(len(first.json()["pending_review"]), 1)
                run_id = first.json()["search_run_id"]
                self.assertEqual(client.post("/sessions", json=body, headers=headers).status_code, 200)
                search.assert_called_once()
                self.assertEqual(client.get(f"/sessions/{session_id}", headers=headers).status_code, 200)
                self.assertEqual(client.get(f"/sessions/{session_id}", headers={"x-forwarded-user": "other"}).status_code, 404)
                changed = body | {"query": "different"}
                self.assertEqual(client.post("/sessions", json=changed, headers=headers).status_code, 409)
                resume = {"action": "search", "query_index": 0, "search_run_id": run_id, "reason": "Check updates"}
                final = client.post(f"/sessions/{session_id}/resume", json=resume, headers=headers)
                self.assertEqual(final.status_code, 200, final.text)
                self.assertEqual(final.json()["status"], "budget_reached")
                self.assertEqual(client.post(f"/sessions/{session_id}/resume", json=resume, headers=headers).status_code, 409)
                self.assertEqual(search.call_count, 2)
                self.assertEqual(model.call_count, 2)

    @patch.dict(os.environ, {"DATABRICKS_APP_NAME": "test-app"})
    @patch("research_app.agent_server.open_hosted_session")
    def test_identity_is_required_before_opening_session_storage(self, backend):
        response = TestClient(app).post("/sessions", json={"session_id": str(uuid4())})
        self.assertEqual(response.status_code, 401)
        backend.assert_not_called()
