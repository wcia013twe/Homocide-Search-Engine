"""First research graph: validate a seed, search, and pause for inspection."""
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from research_app.providers import search_web
from research_app.search_provider import SearchResponse


PADMINI_QUERY = "padmini waldron ucf"


class ResearchState(TypedDict, total=False):
    query: str
    provider: str
    results: list[dict]
    provider_request_id: str | None
    status: str
    stop_reason: str
    triage: dict
    search_run_id: str | None
    search_count: int
    search_history: list[dict]
    review_history: list[dict]
    researcher: str
    seed_query: str
    profile: dict
    gaps: list[dict]
    field_decisions: list[dict]


def build_research_graph(
    search: Callable[[str, str], SearchResponse] = search_web,
    record_search: Callable[[SearchResponse], object] | None = None,
    checkpointer=None,
    triage=None,
    record_triage=None,
    review: bool = False,
    max_searches: int = 3,
    record_review=None,
    extract_claims=None,
    decide_claims=None,
    record_profile=None,
    required_fields: tuple[str, ...] = ("person_identity", "age", "city", "location", "agency", "manner", "medical_cause", "incident_date", "case_number"),
):
    """Dependencies are explicit so tests never need live search credentials."""
    if review and (checkpointer is None or triage is None):
        raise ValueError("Review/resume requires a checkpointer and triage model.")
    if not 1 <= max_searches <= 10:
        raise ValueError("Search budget must be between 1 and 10.")
    if (extract_claims is None) != (decide_claims is None):
        raise ValueError("Profile filling requires both extraction and field decisions.")
    if extract_claims is not None and triage is None:
        raise ValueError("Profile filling requires source triage.")
    def validate_seed(state: ResearchState):
        query = state.get("query", "").strip()
        if not query:
            raise ValueError("A seed query is required.")
        provider = state.get("provider", "Exa")
        if provider not in ("Exa", "Brave"):
            raise ValueError("Provider must be Exa or Brave.")
        return {"query": query, "seed_query": state.get("seed_query", query), "provider": provider, "status": "searching"}

    def discover(state: ResearchState):
        response = search(state["provider"], state["query"])
        audit = None
        if record_search is not None:
            audit = record_search(response)
        return {
            "results": [dict(asdict(result), result_rank=rank)
                        for rank, result in enumerate(response.results, 1)],
            "provider_request_id": response.provider_request_id,
            "search_run_id": getattr(audit, "search_run_id", None),
            "search_count": state.get("search_count", 0) + 1,
            "search_history": state.get("search_history", []) + [{
                "query": state["query"], "provider": state["provider"],
                "search_run_id": getattr(audit, "search_run_id", None),
            }],
            "triage": {},
        }

    def inspect_results(state: ResearchState):
        if triage is not None and state["results"]:
            from research_app.research_triage import validate_triage
            decision = triage(state["query"], state["results"])
            validate_triage(decision if "prompt_version" not in decision else {
                "assessments": decision["assessments"], "next_queries": decision["next_queries"]
            }, state["results"])
            if record_triage is not None:
                record_triage(state, decision)
            return {"triage": decision, "status": "awaiting_review",
                    "stop_reason": "Review result assessments and proposed queries."}
        return {
            "status": "awaiting_inspection" if state["results"] else "no_results",
            "stop_reason": "Review discovery results before adding automated triage.",
        }

    def review_next(state: ResearchState):
        from langgraph.types import Command, interrupt
        from research_app.research_review import ReviewDecision

        if not state["results"] or state.get("status") == "profile_complete":
            return Command(goto=END)
        if state["search_count"] >= max_searches:
            return Command(goto=END, update={"status": "budget_reached", "stop_reason": "Search budget reached."})
        proposals = state["triage"].get("next_queries", [])
        pending = {"search_run_id": state["search_run_id"], "query": state["query"],
                   "search_count": state["search_count"], "next_queries": proposals}
        choice = ReviewDecision.model_validate(interrupt(pending))
        if choice.search_run_id != state["search_run_id"]:
            raise ValueError("Review does not match the pending search run.")
        event = {**choice.model_dump(), "researcher": state.get("researcher"),
                 "reviewed_at": datetime.now(timezone.utc).isoformat()}
        if choice.action == "search":
            if choice.query_index is None or choice.query_index >= len(proposals):
                raise ValueError("Select an existing proposed query.")
            selected = proposals[choice.query_index]
            if not selected["query"].strip():
                raise ValueError("The selected query must not be empty.")
            event["selected_proposal"] = selected
        if record_review is not None:
            event["artifact_path"] = record_review(state["search_run_id"], event)
        updates = {"review_history": state.get("review_history", []) + [event]}
        if choice.action == "stop":
            return Command(goto=END, update={**updates, "status": "stopped_by_researcher",
                                            "stop_reason": choice.reason})
        query = selected["query"].strip()
        previous = {" ".join(item["query"].lower().split()) for item in state["search_history"]}
        if " ".join(query.lower().split()) in previous:
            return Command(goto=END, update={**updates, "status": "repeated_query",
                                            "stop_reason": "The selected query was already searched."})
        return Command(goto="discover", update={**updates, "query": query, "status": "searching"})

    def fill_profile(state: ResearchState):
        from research_app.research_profile import update_profile

        if not state["results"]:
            return update_profile(state.get("profile", {}), [], {}, {}, required_fields)
        eligible = {item["result_rank"] for item in state.get("triage", {}).get("assessments", [])
                    if item["label"] in ("candidate_evidence", "primary_target", "uncertain")}
        sources = {f"{state.get('search_run_id') or state['search_count']}:{r['result_rank']}": {
            "url": r["url"], "text": r.get("snippet") or "", "evidence_kind": "search_excerpt",
            "search_run_id": state.get("search_run_id"), "result_rank": r["result_rank"],
        } for r in state["results"] if r["result_rank"] in eligible}
        seed = state.get("seed_query", state["query"])
        claims = extract_claims(seed, sources) if sources else []
        decision = decide_claims(seed, claims, sources, state.get("profile", {}))
        updated = update_profile(state.get("profile", {}), claims, sources, decision["answers"], required_fields)
        # Query proposals come only from missing/conflicting fields; populated fields do not request confirmation.
        proposals = [{"query": f"{seed} {gap['field'].replace('_', ' ')}" + (" conflicting reports" if gap["reason"] == "conflicting" else ""),
                      "target_gap": gap["field"], "reason": gap["reason"],
                      "based_on_ranks": sorted(eligible) or [r["result_rank"] for r in state["results"]]}
                     for gap in updated["gaps"][:3]]
        triage_output = {**state.get("triage", {}), "next_queries": proposals}
        event = {"search_run_id": state.get("search_run_id"), "claims": claims, "sources": sources, **decision}
        if record_profile is not None:
            event["artifact_path"] = record_profile(state["search_run_id"], {**event, **updated})
        return {**updated, "triage": triage_output,
                "field_decisions": state.get("field_decisions", []) + [event],
                "status": "awaiting_review" if updated["gaps"] else "profile_complete",
                "stop_reason": "Review missing/conflicting fields." if updated["gaps"] else "Required fields filled with supported values."}

    graph = StateGraph(ResearchState)
    graph.add_node("validate_seed", validate_seed)
    graph.add_node("discover", discover)
    graph.add_node("inspect_results", inspect_results)
    graph.add_edge(START, "validate_seed")
    graph.add_edge("validate_seed", "discover")
    graph.add_edge("discover", "inspect_results")
    last_node = "inspect_results"
    if extract_claims is not None:
        graph.add_node("fill_profile", fill_profile)
        graph.add_edge("inspect_results", "fill_profile")
        last_node = "fill_profile"
    if review:
        graph.add_node("review_next", review_next, destinations=("discover", END))
        graph.add_edge(last_node, "review_next")
    else:
        graph.add_edge(last_node, END)
    return graph.compile(checkpointer=checkpointer)


def main():
    import argparse
    import json
    from research_app.search_audit import SearchAuditStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("Exa", "Brave"), default="Exa")
    parser.add_argument("--query", default=PADMINI_QUERY)
    parser.add_argument("--actor", required=True, help="Researcher identity for the audit record")
    parser.add_argument("--triage", action="store_true", help="Assess results using the Databricks model endpoint")
    parser.add_argument("--local-audit", help="Use a local SQLite audit database and artifact directory")
    args = parser.parse_args()
    if args.local_audit:
        from research_app.search_audit import SQLiteSearchAuditStore
        store = SQLiteSearchAuditStore(args.local_audit)
    else:
        store = SearchAuditStore.from_environment()
    from research_app.research_triage import DatabricksTriage
    model = DatabricksTriage.from_environment() if args.triage else None
    graph = build_research_graph(
        record_search=lambda response: store.record(response, args.actor), triage=model,
        record_triage=lambda state, decision: store.record_triage(state["search_run_id"], decision),
    )
    for update in graph.stream({"query": args.query, "provider": args.provider}, stream_mode="updates"):
        print(json.dumps(update, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
