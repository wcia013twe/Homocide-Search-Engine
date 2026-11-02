"""One auditable discovery pass, shared by the hosted API and future UI."""
from research_app.research_agent import build_research_graph
from research_app.research_triage import DatabricksTriage
from research_app.search_audit import SearchAuditStore


def run_research(query: str, provider: str, actor: str) -> dict:
    store = SearchAuditStore.from_environment()
    model = DatabricksTriage.from_environment()
    graph = build_research_graph(
        record_search=lambda response: store.record(response, actor),
        triage=model,
        record_triage=lambda state, decision: store.record_triage(state["search_run_id"], decision),
    )
    state = graph.invoke({"query": query, "provider": provider})
    # Large raw payloads and exact model exchanges remain in the volume audit trail.
    triage = state.get("triage", {})
    return {
        "search_run_id": state["search_run_id"], "query": state["query"],
        "provider": state["provider"], "status": state["status"],
        "results": [{key: value for key, value in result.items() if key != "raw"}
                    for result in state["results"]],
        "assessments": triage.get("assessments", []),
        "next_queries": triage.get("next_queries", []),
        "prompt_version": triage.get("prompt_version"),
        "stop_reason": state["stop_reason"],
    }
