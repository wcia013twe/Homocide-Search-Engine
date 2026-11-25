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
def open_hosted_session(session_id: str, *, read_only=False, report_stage=None, investigation_id=None, model_endpoint=None):
    from research_app.investigation_tasks import connection as checkpoint_connection, database_configured, read_connection
    from langgraph.checkpoint.postgres import PostgresSaver

    if not database_configured():
        raise RuntimeError("Shared checkpoint database is not configured.")
    key = int.from_bytes(sha256(session_id.encode("utf-8")).digest()[:8], "big", signed=True)
    with (read_connection() if read_only else checkpoint_connection(prepare_threshold=0)) as connection:
        locked = False if read_only else connection.execute("SELECT pg_try_advisory_lock(%s) AS locked", [key]).fetchone()["locked"]
        if not locked and not read_only:
            raise SessionBusyError("This research session is already running.")
        try:
            saver = PostgresSaver(connection)
            from functools import partial
            from research_app.source_collection import collect_sources
            from research_app.research_profile import DatabricksClaimExtractor, DatabricksChatFieldDecisions
            from research_app.coding_review import DatabricksCodingPass
            store = SearchAuditStore.from_environment()
            from research_app.providers import search_web
            from research_app.usage_store import begin_call, finish_call
            def usage(kind, provider):
                call_id = begin_call(investigation_id, kind, provider)
                return lambda **kwargs: finish_call(call_id, **kwargs)
            def search(provider, query):
                complete = usage('search', provider)
                response = search_web(provider, query)
                complete(cost=response.cost_usd)
                return response
            recorder = usage if investigation_id else None
            model = (DatabricksTriage(model_endpoint or os.environ.get('HR_RESEARCH_MODEL_ENDPOINT', ''), usage=recorder)
                     if investigation_id else DatabricksTriage.from_environment())
            from research_app.gold_fields import GOLD_FIELDS
            fields = tuple(name for name in GOLD_FIELDS if name != 'case_id')
            yield build_session(store, saver, model, search=search if investigation_id else None,
                collect_sources=partial(collect_sources, volume_path=store.volume_path),
                extract_claims=DatabricksClaimExtractor(model.endpoint, fields, usage=recorder),
                decide_claims=DatabricksChatFieldDecisions(model.endpoint, usage=recorder), record_profile=store.record_profile,
                coding_pass=DatabricksCodingPass(model.endpoint, usage=recorder),
                report_stage=report_stage,
                required_fields=fields)
        finally:
            if locked:
                connection.execute("SELECT pg_advisory_unlock(%s)", [key])


if __name__ == "__main__":
    # Explicit deployment preparation step; never create checkpoint tables in a request.
    from langgraph.checkpoint.postgres import PostgresSaver

    from research_app.investigation_tasks import connection
    with connection(prepare_threshold=0) as conn:
        PostgresSaver(conn).setup()
    from research_app.investigation_tasks import setup
    setup()
    print("Shared checkpoint and task tables initialized.")
