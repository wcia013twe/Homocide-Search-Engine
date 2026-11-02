import os
import unittest
from unittest.mock import Mock, patch

from research_app.brave import brave_search


class BraveSearchTests(unittest.TestCase):
    @patch("research_app.brave.requests.get")
    @patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"})
    def test_returns_display_safe_web_results(self, get):
        response = Mock()
        response.json.return_value = {"web": {"results": [{"title": "Example", "url": "https://example.com", "description": "Example result"}]}}
        get.return_value = response

        self.assertEqual(brave_search("homicide research"), [{"title": "Example", "url": "https://example.com", "description": "Example result"}])
        get.assert_called_once_with(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": "test-key"},
            params={"q": "homicide research", "count": 3},
            timeout=15,
        )

    @patch.dict(os.environ, {"BRAVE_API_KEY": ""})
    def test_requires_configured_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            brave_search("homicide research")


if __name__ == "__main__":
    unittest.main()
