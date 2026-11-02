"""Shared Postgres checkpoints and per-session serialization for hosted review."""
from contextlib import contextmanager
from hashlib import sha256
import os

from research_app.research_session import build_session
from research_app.research_triage import DatabricksTriage
from research_app.search_audit import SearchAuditStore


class SessionBusyError(RuntimeError):
    pass


def scoped_session_id(session_id: str, actor: str) -> str:
    return sha256(actor.encode("utf-8")).hexdigest()[:32] + ":" + session_id


@contextmanager
def open_hosted_session(session_id: str):
    import psycopg
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = os.environ.get("HR_RESEARCH_CHECKPOINT_DSN")
    if not dsn:
        raise RuntimeError("Shared checkpoint database is not configured.")
    key = int.from_bytes(sha256(session_id.encode("utf-8")).digest()[:8], "big", signed=True)
    with psycopg.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row, connect_timeout=10) as connection:
        locked = connection.execute("SELECT pg_try_advisory_lock(%s) AS locked", [key]).fetchone()["locked"]
        if not locked:
            raise SessionBusyError("This research session is already running.")
        try:
            saver = PostgresSaver(connection)
            yield build_session(SearchAuditStore.from_environment(), saver, DatabricksTriage.from_environment())
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", [key])


if __name__ == "__main__":
    # Explicit deployment preparation step; never create checkpoint tables in a request.
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(os.environ["HR_RESEARCH_CHECKPOINT_DSN"]) as saver:
        saver.setup()
    print("Shared checkpoint tables initialized.")
