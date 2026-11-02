import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from research_app.agent_server import app


class AgentServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_never_calls_search(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    @patch.dict(os.environ, {"DATABRICKS_APP_NAME": "research-agent"})
    @patch("research_app.agent_server.run_research")
    def test_uses_proxy_identity_and_validated_provider(self, run):
        run.return_value = {"status": "awaiting_review"}
        response = self.client.post("/research", json={"provider": "Brave"},
                                    headers={"x-forwarded-user": "researcher-id"})
        self.assertEqual(response.status_code, 200)
        run.assert_called_once_with("padmini waldron ucf", "Brave", "researcher-id")

    @patch.dict(os.environ, {"DATABRICKS_APP_NAME": "research-agent"})
    @patch("research_app.agent_server.run_research")
    def test_rejects_missing_identity_and_bad_input_without_search(self, run):
        self.assertEqual(self.client.post("/research", json={}).status_code, 401)
        for body in ({"provider": "Unknown"}, {"query": " "}, {"actor": "spoofed"}):
            self.assertEqual(self.client.post("/research", json=body).status_code, 422)
        run.assert_not_called()

    @patch.dict(os.environ, {"DATABRICKS_APP_NAME": "research-agent"})
    @patch("research_app.agent_server.run_research", side_effect=RuntimeError("secret-value"))
    def test_error_does_not_expose_provider_exception(self, run):
        response = self.client.post("/research", json={}, headers={"x-forwarded-user": "researcher"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-value", response.text)
