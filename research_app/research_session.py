"""Persist and resume a local research graph at explicit review checkpoints."""
from contextlib import contextmanager
import json
from pathlib import Path

from langgraph.types import Command

from research_app.audit_review import review as review_saved_run
from research_app.research_agent import build_research_graph
from research_app.research_review import ReviewDecision
from research_app.search_audit import SQLiteSearchAuditStore


@contextmanager
def open_session(directory, model, search=None, max_searches=3, **workflow):
    from langgraph.checkpoint.sqlite import SqliteSaver

    store = SQLiteSearchAuditStore(directory)
    with SqliteSaver.from_conn_string(str(store.volume_path / "checkpoints.sqlite3")) as saver:
        yield build_session(store, saver, model, search, max_searches, **workflow)


def build_session(store, saver, model, search=None, max_searches=3, **workflow):
    actor = [None]
    if workflow.get("extract_claims") is not None:
        workflow.setdefault("record_profile", store.record_profile)
    options = {"search": search} if search is not None else {}
    graph = build_research_graph(
        **options, **workflow, triage=model, checkpointer=saver, review=True, max_searches=max_searches,
        record_search=lambda response: store.record(response, actor[0]),
        record_triage=lambda state, decision: store.record_triage(state["search_run_id"], decision),
        record_review=store.record_review,
    )
    return ResearchSession(graph, store, actor)


class ResearchSession:
    def __init__(self, graph, store, actor):
        self.graph, self.store, self.actor = graph, store, actor
        self.progress = None

    def _invoke(self, value, config):
        if self.progress is None:
            return self.graph.invoke(value, config)
        for _ in self.graph.stream(value, config, stream_mode="updates"):
            self.progress(self.graph.get_state(config))
        return self.graph.get_state(config).values

    def _config(self, session_id):
        if not session_id or len(session_id) > 200:
            raise ValueError("Provide a session ID of 1–200 characters.")
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 1000}

    def inspect(self, session_id, researcher):
        snapshot = self.graph.get_state(self._config(session_id))
        if not snapshot.values:
            raise ValueError("Session does not exist.")
        if snapshot.values["researcher"] != researcher:
            raise ValueError("Session belongs to another researcher.")
        return snapshot

    def start(self, session_id, researcher, query, provider="Exa", *, automatic_searches=False):
        config = self._config(session_id)
        if not researcher.strip():
            raise ValueError("Researcher identity is required.")
        if self.graph.get_state(config).values:
            raise ValueError("Session exists; inspect or resume it instead of starting again.")
        self.actor[0] = researcher
        return self._invoke({"query": query, "provider": provider, "researcher": researcher,
                             "automatic_searches": automatic_searches}, config)

    def import_search(self, session_id, researcher, run_id):
        config = self._config(session_id)
        if self.graph.get_state(config).values:
            raise ValueError("Session already exists.")
        saved = review_saved_run(self.store.volume_path, run_id)
        if saved["triage_artifact_path"] is None:
            raise ValueError("A saved triage decision is required before review.")
        with self.store._connection() as connection:
            owner = connection.execute("SELECT requested_by FROM search_runs WHERE run_id = ?", [run_id]).fetchone()[0]
        if owner != researcher:
            raise ValueError("Search run belongs to another researcher.")
        decision = json.loads(Path(saved["triage_artifact_path"]).read_text())["decision"]
        self.actor[0] = researcher
        self.graph.update_state(config, {
            "query": saved["query"], "provider": saved["provider"].capitalize(),
            "researcher": researcher, "search_run_id": run_id,
            "results": saved["results"], "triage": decision,
            "search_count": 1, "review_history": [], "status": "awaiting_review",
            "search_history": [{"query": saved["query"], "provider": saved["provider"], "search_run_id": run_id}],
        }, as_node="inspect_results")
        return self._invoke(None, config)

    def finalize(self, session_id, researcher, decision):
        """Release an old coding interrupt without making human coding decisions."""
        snapshot = self.inspect(session_id, researcher)
        if 'final_coding' not in snapshot.next:
            raise ValueError('Session is not waiting for final coding review.')
        if decision.get('search_run_id') != snapshot.values.get('search_run_id'):
            raise ValueError('Coding handoff refers to a stale search run.')
        if decision != {'search_run_id': snapshot.values.get('search_run_id'), 'action': 'case_review'}:
            raise ValueError('Field decisions belong in case Review. Complete the investigation without coding decisions.')
        self.actor[0] = researcher
        return self._invoke(Command(resume=decision), self._config(session_id))

    def resume(self, session_id, researcher, decision):
        snapshot = self.inspect(session_id, researcher)
        choice = ReviewDecision.model_validate(decision)
        if "review_next" not in snapshot.next:
            raise ValueError("Session is not waiting for review.")
        if choice.search_run_id != snapshot.values["search_run_id"]:
            raise ValueError("Review refers to a stale search run.")
        if choice.action == "search":
            proposals = snapshot.values["triage"].get("next_queries", [])
            if choice.query_index is None or choice.query_index >= len(proposals):
                raise ValueError("Select an existing proposed query.")
            if not proposals[choice.query_index]["query"].strip():
                raise ValueError("The selected query must not be empty.")
        self.actor[0] = researcher
        return self._invoke(Command(resume=choice.model_dump()), self._config(session_id))


def main():
    import argparse
    from research_app.research_agent import PADMINI_QUERY
    from research_app.research_triage import DatabricksTriage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("start", "import", "inspect", "resume", "finalize"))
    parser.add_argument("--session", required=True)
    parser.add_argument("--actor", required=True, help="Local researcher attribution, not an authentication mechanism")
    parser.add_argument("--directory", default="local-audit")
    parser.add_argument("--query", default=PADMINI_QUERY)
    parser.add_argument("--provider", choices=("Exa", "Brave"), default="Exa")
    parser.add_argument("--model-endpoint")
    parser.add_argument("--run", help="Saved search to import, or expected pending search for resume")
    parser.add_argument("--action", choices=("search", "stop"))
    parser.add_argument("--query-index", type=int)
    parser.add_argument("--reason")
    parser.add_argument("--decision-file", help='Legacy completion JSON: search_run_id and action="case_review"')
    args = parser.parse_args()

    def missing_model(*unused):
        raise ValueError("Set --model-endpoint before starting or resuming a search.")

    if args.operation in ("start", "resume"):
        if not args.model_endpoint:
            parser.error("A model endpoint is required when running searches.")
    model = DatabricksTriage(args.model_endpoint) if args.model_endpoint else missing_model
    workflow = {}
    if args.model_endpoint:
        from functools import partial
        from research_app.source_collection import collect_sources
        from research_app.research_profile import DatabricksClaimExtractor, DatabricksChatFieldDecisions
        fields = ("person_identity", "age", "city", "location", "agency", "manner", "medical_cause", "incident_date", "case_number")
        workflow = {"extract_claims": DatabricksClaimExtractor(args.model_endpoint, fields),
                    "decide_claims": DatabricksChatFieldDecisions(args.model_endpoint),
                    "collect_sources": partial(collect_sources, volume_path=str(Path(args.directory).resolve()))}
    if args.operation == "finalize" and (not args.model_endpoint or not args.decision_file):
        parser.error("finalize requires --model-endpoint and --decision-file")
    with open_session(args.directory, model, **workflow) as session:
        if args.operation == "start":
            state = session.start(args.session, args.actor, args.query, args.provider)
        elif args.operation == "import":
            if not args.run:
                parser.error("import requires --run")
            state = session.import_search(args.session, args.actor, args.run)
        elif args.operation == "finalize":
            state = session.finalize(args.session, args.actor, json.loads(Path(args.decision_file).read_text()))
        elif args.operation == "resume":
            if not args.run or not args.action or not args.reason:
                parser.error("resume requires --run, --action, and --reason")
            state = session.resume(args.session, args.actor, {"search_run_id": args.run,
                "action": args.action, "query_index": args.query_index, "reason": args.reason})
        else:
            state = session.inspect(args.session, args.actor).values
        snapshot = session.inspect(args.session, args.actor)
        pending = [item.value for task in snapshot.tasks for item in task.interrupts]
        print(json.dumps({"session": args.session, "status": state.get("status"),
                          "search_run_id": state.get("search_run_id"),
                          "search_count": state.get("search_count"), "pending_review": pending}, indent=2))


if __name__ == "__main__":
    main()
