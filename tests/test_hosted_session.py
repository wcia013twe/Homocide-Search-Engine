import os
import unittest
from unittest.mock import Mock, patch

from research_app.hosted_session import open_hosted_session, scoped_session_id, SessionBusyError


class HostedSessionTests(unittest.TestCase):
    def test_actor_scopes_session_keys(self):
        self.assertNotEqual(scoped_session_id("same", "alice"), scoped_session_id("same", "bob"))

    @patch.dict(os.environ, {"HR_RESEARCH_CHECKPOINT_DSN": "postgresql://test-only"})
    @patch("psycopg.connect")
    @patch("research_app.hosted_session.build_session")
    @patch("research_app.hosted_session.DatabricksTriage.from_environment")
    @patch("research_app.hosted_session.SearchAuditStore.from_environment")
    def test_releases_advisory_lock_when_invocation_fails(self, store, model, build, connect):
        connection = connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = {"locked": True}
        with self.assertRaisesRegex(RuntimeError, "invocation failed"):
            with open_hosted_session("case-one"):
                raise RuntimeError("invocation failed")
        self.assertIn("pg_try_advisory_lock", connection.execute.call_args_list[0].args[0])
        self.assertIn("pg_advisory_unlock", connection.execute.call_args_list[-1].args[0])
        build.assert_called_once()

    @patch.dict(os.environ, {"HR_RESEARCH_CHECKPOINT_DSN": "postgresql://test-only"})
    @patch("psycopg.connect")
    @patch("research_app.hosted_session.build_session")
    def test_busy_session_does_not_build_or_run_graph(self, build, connect):
        connection = connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = {"locked": False}
        with self.assertRaises(SessionBusyError):
            with open_hosted_session("case-one"):
                self.fail("Must not enter a busy session")
        build.assert_not_called()
