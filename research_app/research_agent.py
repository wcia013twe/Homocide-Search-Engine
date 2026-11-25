"""First research graph: validate a seed, search, and pause for inspection."""
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from research_app.evidence import source_record, attributed_claim
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
    sources: dict
    previous_sources: dict
    collection_review_recommended: bool
    collection_stop_reason: str
    new_source_ids: list[str]
    coded_fields: dict
    coding_review: dict
    automatic_searches: bool
    search_round: int
    round_queries: list[str]
    query_plan: dict
    automatic_coded_fields: dict


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
    collect_sources=None,
    report_stage=None,
    coding_pass=None,
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
        result_ids: tuple[str, ...] = getattr(audit, 'search_result_ids', ())
        return {
            "results": [dict(asdict(result), result_rank=rank,
                             search_result_id=(result_ids[rank - 1] if result_ids else None))
                        for rank, result in enumerate(response.results, 1)],
            "provider_request_id": response.provider_request_id,
            "search_run_id": getattr(audit, "search_run_id", None),
            "search_count": state.get("search_count", 0) + 1,
            "search_round": state.get("search_round", 1),
            "search_history": state.get("search_history", []) + [{
                "query": state["query"], "provider": state["provider"],
                "search_round": state.get("search_round", 1),
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

        terminal = "prepare_coding" if extract_claims is not None else END
        automatic = state.get("automatic_searches", False)
        if automatic and extract_claims is not None:
            # A round can contain several searches. Finish its queue before
            # planning the next pass from the accumulated profile.
            queued = state.get("round_queries", [])
            if queued:
                return Command(goto="discover", update={"query": queued[0], "round_queries": queued[1:], "status": "searching"})
            round_number = state.get("search_round", 1)
            if round_number >= max_searches:
                return Command(goto=terminal, update={"status": "budget_reached", "stop_reason": "Search round budget reached."})
            searched = {" ".join(item["query"].lower().split()) for item in state.get("search_history", [])}
            queries = []
            for proposal in state.get("triage", {}).get("next_queries", []):
                query = proposal["query"].strip()
                key = " ".join(query.lower().split())
                if key and key not in searched:
                    queries.append(query)
                    searched.add(key)
            if not queries:
                return Command(goto=terminal, update={"status": "no_next_query", "stop_reason": "No unsearched proposed queries remain."})
            return Command(goto="discover", update={"query": queries[0], "round_queries": queries[1:],
                                                     "search_round": round_number + 1, "status": "searching"})
        if not state["results"]:
            return Command(goto=terminal)
        if state["search_count"] >= max_searches:
            return Command(goto=terminal, update={"status": "budget_reached", "stop_reason": "Search budget reached."})
        proposals = state["triage"].get("next_queries", [])
        pending = {"search_run_id": state["search_run_id"], "query": state["query"],
                   "search_count": state["search_count"], "next_queries": proposals,
                   "collection_review_recommended": state.get("collection_review_recommended", False),
                   "collection_stop_reason": state.get("collection_stop_reason"),
                   "gaps": state.get("gaps", [])}
        automatic = state.get('automatic_searches', False)
        if automatic:
            searched = {' '.join(item['query'].lower().split()) for item in state['search_history']}
            index = next((i for i, proposal in enumerate(proposals)
                          if proposal['query'].strip() and ' '.join(proposal['query'].lower().split()) not in searched), None)
            choice = ReviewDecision.model_validate({'search_run_id': state['search_run_id'],
                'action': 'search' if index is not None else 'stop', 'query_index': index,
                'reason': 'Automatically continue with the first unsearched proposed query.' if index is not None
                          else 'No unsearched proposed query remains.'})
        else:
            choice = ReviewDecision.model_validate(interrupt(pending))
        if choice.search_run_id != state["search_run_id"]:
            raise ValueError("Review does not match the pending search run.")
        event = {**choice.model_dump(), "researcher": state.get("researcher"),
                 "decision_origin": "automatic" if automatic else "researcher",
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
            return Command(goto=terminal, update={**updates, "status": "no_next_query" if automatic else "stopped_by_researcher",
                                            "stop_reason": choice.reason})
        query = selected["query"].strip()
        previous = {" ".join(item["query"].lower().split()) for item in state["search_history"]}
        if " ".join(query.lower().split()) in previous:
            return Command(goto=terminal, update={**updates, "status": "repeated_query",
                                            "stop_reason": "The selected query was already searched."})
        return Command(goto="discover", update={**updates, "query": query, "status": "searching"})

    def fill_profile(state: ResearchState):
        from research_app.research_profile import update_profile

        if report_stage is not None:
            report_stage('collecting_sources')
        previous_sources = state.get("sources", {})
        eligible = {item["result_rank"] for item in state.get("triage", {}).get("assessments", [])
                    if item["label"] in ("candidate_evidence", "primary_target", "uncertain")}
        if collect_sources is not None:
            sources = collect_sources(state["results"], state.get("triage", {}).get("assessments", []),
                                      state.get("search_run_id") or str(state["search_count"]),
                                      existing_sources=previous_sources)
        else:
            sources = dict(previous_sources)
            for r in state["results"]:
                if r["result_rank"] not in eligible:
                    continue
                source_id = f"{state.get('search_run_id') or state['search_count']}:{r['result_rank']}"
                sources[source_id] = source_record(
                    source_id, url=r["url"], text=r.get("snippet") or "",
                    title=r.get("title"), published_at=r.get("published_date"),
                    search_run_id=state.get("search_run_id"), result_rank=r["result_rank"])
        seed = state.get("seed_query", state["query"])
        if report_stage is not None:
            report_stage('extracting_claims')
        claims = [attributed_claim(c, sources) for c in extract_claims(seed, sources)] if sources else []
        if report_stage is not None:
            report_stage('validating_claims')
        decision = decide_claims(seed, claims, sources, state.get("profile", {}))
        updated = update_profile(state.get("profile", {}), claims, sources, decision["answers"], required_fields)
        from research_app.collection_planning import plan_collection
        plan = plan_collection(seed, sources, previous_sources, updated["gaps"],
                               state["search_history"], state.get("triage", {}).get("next_queries", []),
                               result_ranks=[r["result_rank"] for r in state["results"]])
        triage_output = {**state.get("triage", {}), "next_queries": plan.pop("next_queries")}
        event = {"search_run_id": state.get("search_run_id"), "claims": claims, "sources": sources, **decision}
        if record_profile is not None:
            event["artifact_path"] = record_profile(state["search_run_id"], {**event, **updated})
        return {**updated, **plan, "sources": sources, "previous_sources": previous_sources, "triage": triage_output,
                "field_decisions": state.get("field_decisions", []) + [event],
                "status": "awaiting_review",
                "stop_reason": "Review collected evidence and decide whether to continue collection."}

    def plan_next_queries(state: ResearchState):
        # Plan at round boundaries, using the evidence accumulated across searches.
        planner = getattr(type(triage), "plan_queries", None)
        if (planner is None or not state.get("automatic_searches") or state.get("round_queries")
                or state.get("search_round", 1) >= max_searches or not state.get("results")):
            return {}
        context = {
            "seed_query": state.get("seed_query"), "profile": state.get("profile", {}),
            "gaps": state.get("gaps", []), "search_history": state.get("search_history", []),
            "sources": [{key: source.get(key) for key in
                         ("source_id", "title", "url", "publisher", "source_type", "retrieval_status")}
                        for source in state.get("sources", {}).values()],
        }
        decision = planner(triage, state["query"], state["results"], context)
        from research_app.research_triage import validate_query_plan
        validate_query_plan({"next_queries": decision["next_queries"]}, state["results"])
        return {"query_plan": decision, "triage": {**state["triage"], "next_queries": decision["next_queries"]}}

    def prepare_coding(state: ResearchState):
        if coding_pass is None or not state.get('sources'):
            return {'status': 'awaiting_coding_review'}
        if report_stage is not None:
            report_stage('final_coding')
        coded = coding_pass(state.get('seed_query', state['query']), state.get('profile', {}),
                            state['sources'], required_fields)
        return {'automatic_coded_fields': coded, 'coded_fields': coded, 'status': 'awaiting_coding_review'}

    def final_coding(state: ResearchState):
        # Keep this node name so persisted final-coding checkpoints can resume.
        from research_app.coding_review import review_field_names

        if not state.get('sources'):
            return {'status': 'no_evidence', 'stop_reason': 'No source material was collected for coding review.'}
        automatic = state.get('automatic_coded_fields', {})
        event = {'automatic_fields': automatic, 'decision_origin': 'automatic',
                 'unresolved_fields': [name for name in review_field_names(state.get('profile', {}), required_fields)
                                       if name not in automatic],
                 'prepared_at': datetime.now(timezone.utc).isoformat()}
        if record_profile is not None:
            event['artifact_path'] = record_profile(state['search_run_id'], event)
        return {'coded_fields': automatic, 'coding_review': event, 'status': 'ready_for_case_review',
                'stop_reason': 'Research complete. Resolve coding and approve the case in the case Review tab.'}

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
        graph.add_node("plan_next_queries", plan_next_queries)
        graph.add_edge("fill_profile", "plan_next_queries")
        last_node = "plan_next_queries"
    if review:
        destinations = ("discover", "prepare_coding", END) if extract_claims is not None else ("discover", END)
        graph.add_node("review_next", review_next, destinations=destinations)
        graph.add_edge(last_node, "review_next")
        if extract_claims is not None:
            graph.add_node("prepare_coding", prepare_coding)
            graph.add_edge("prepare_coding", "final_coding")
            graph.add_node("final_coding", final_coding)
            graph.add_edge("final_coding", END)
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
