import json
import unittest
from unittest.mock import Mock, patch

from research_app.research_triage import DatabricksTriage, PROMPT_VERSION


class DatabricksTriageTests(unittest.TestCase):
    @patch("databricks.sdk.WorkspaceClient")
    @patch("research_app.research_triage.requests.post")
    def test_real_adapter_validates_response_and_retains_model_exchange(self, post, client):
        client.return_value.config.host = "https://workspace.example"
        client.return_value.config.authenticate.return_value = {"Authorization": "Bearer TEST_ONLY"}
        output = {"assessments": [{"result_rank": 1, "label": "uncertain", "reason": "Insufficient excerpt",
                                   "duplicate_of_rank": None}], "next_queries": []}
        response = Mock()
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(output)}}], "model": "test-model", "usage": {"total_tokens": 100}}
        post.return_value = response
        result = DatabricksTriage("test-model")("seed", [{"result_rank": 1, "snippet": "x" * 7000}])
        self.assertEqual(result["prompt_version"], PROMPT_VERSION)
        self.assertEqual(result["model_response"], response.json.return_value)
        user_input = json.loads(result["model_input"]["messages"][1]["content"])
        self.assertEqual(len(user_input["results"][0]["excerpt"]), 6000)
        self.assertNotIn("Authorization", json.dumps(result))

    @patch("databricks.sdk.WorkspaceClient")
    @patch("research_app.research_triage.requests.post")
    def test_truncated_output_is_rejected(self, post, client):
        client.return_value.config.host = "https://workspace.example"
        response = Mock()
        response.json.return_value = {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
        post.return_value = response
        with self.assertRaisesRegex(ValueError, "did not finish"):
            DatabricksTriage("test-model")("seed", [])
