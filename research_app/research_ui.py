"""Operate one local, checkpointed Padmini research run from Streamlit."""
from hashlib import sha256
import json
import os
from pathlib import Path

import streamlit as st

from research_app.audit_review import review
from research_app.research_agent import PADMINI_QUERY
from research_app.research_session import open_session
from research_app.research_triage import DatabricksTriage


def run_report(directory, state):
    """Read every completed search once, checking saved evidence without API calls."""
    runs = [review(directory, item["search_run_id"]) for item in state.get("search_history", [])]
    return {
        "seed_query": state["seed_query"], "status": state["status"],
        "search_count": state.get("search_count", 0), "search_limit": 3,
        "stop_reason": state.get("stop_reason"), "runs": runs,
        "reviews": state.get("review_history", []),
        "scope": "Search excerpts and source triage; incident profile extraction and full-page retrieval are not enabled.",
    }


def _triage(query, results):
    return DatabricksTriage.from_environment()(query, results)


def render(provider):
    st.subheader("Padmini research run")
    st.write("Follow sources, review what is missing, and choose the next search in one saved run.")
    st.caption(f"Seed query: {PADMINI_QUERY}.")
    if os.environ.get("HR_REQUIRE_PROXY_IDENTITY", "false").lower() == "true":
        st.info("This run panel currently uses local checkpoints. Hosted orchestration needs the shared session backend connected to this UI.")
        return
    actor = st.session_state["research_user"]
    actor_key = sha256(actor.encode()).hexdigest()
    directory = Path(os.environ.get("HR_DATA_DIR", "/tmp/homicide-research")) / "research-runs" / actor_key
    st.caption("Up to three searches. Each search and model triage runs once per chosen step; viewing progress makes no API calls. Local checkpoints stay on this machine and belong to this browser session.")
    try:
        with open_session(directory, _triage) as session:
            snapshot = session.graph.get_state(session._config("padmini"))
            if not snapshot.values:
                configured = bool(os.environ.get(f"{provider.upper()}_API_KEY") and os.environ.get("HR_RESEARCH_MODEL_ENDPOINT"))
                if not configured:
                    st.info("Live research is waiting for provider credentials and a model endpoint. Restore the Databricks login and restart the local app to load its configuration.")
                if st.button("Start Padmini run", type="primary", key="research_start", disabled=not configured):
                    # Check configuration before spending a provider call.
                    DatabricksTriage.from_environment()
                    with st.spinner("Searching and assessing sources..."):
                        session.start("padmini", actor, PADMINI_QUERY, provider)
                    st.rerun()
                return
            snapshot = session.inspect("padmini", actor)
            state = snapshot.values
            report = run_report(directory, state)
            st.write(f'**{state["status"].replace("_", " ").capitalize()}** · {state.get("search_count", 0)} of 3 searches')
            st.caption(f'Provider: {state["provider"]}. {state.get("stop_reason", "")}')
            st.caption("Evidence below comes from saved search excerpts. Incident profile extraction and full-page retrieval are not enabled.")
            if report["runs"]:
                st.dataframe([{
                    "Step": index, "Query": run["query"], "Sources": len(run["results"]),
                    "Assessed": sum(item["assessment"] is not None for item in run["results"]),
                    "Audit": "Verified" if run["artifact_hashes_verified"] else "Not verified",
                    "Run ID": run["run_id"],
                } for index, run in enumerate(report["runs"], 1)], hide_index=True, width="stretch")
                for index, run in enumerate(report["runs"], 1):
                    with st.expander(f'Step {index}: {run["query"]}', expanded=index == len(report["runs"])):
                        for result in run["results"]:
                            st.write(f'{result["result_rank"]}. {result["title"]}')
                            st.text(result["snippet"] or "No excerpt returned.")
                            assessment = result["assessment"]
                            if assessment:
                                st.caption(f'{assessment["label"]}: {assessment["reason"]}')
                            if result["url"].startswith(("https://", "http://")):
                                st.link_button("Open source", result["url"])
            st.download_button("Download research run", json.dumps(report, indent=2, ensure_ascii=False),
                               "padmini-research-run.json", "application/json", key="research_download")
            if snapshot.next != ("review_next",) or any(task.error for task in snapshot.tasks):
                if snapshot.next:
                    st.warning("This step did not finish. Inspect the saved evidence before recovering it; no search is automatically retried.")
                return
            proposals = state.get("triage", {}).get("next_queries", [])
            st.write("**Next research step**")
            selected = None
            if proposals:
                selected = st.selectbox("Proposed follow-up", range(len(proposals)),
                                        format_func=lambda index: proposals[index]["query"],
                                        key=f'research_proposal_{state["search_run_id"]}')
                proposal = proposals[selected]
                st.write(f'Gap: {proposal["target_gap"]}')
                st.caption(f'{proposal["reason"]} Based on sources: {proposal["based_on_ranks"]}')
            else:
                st.info("No follow-up queries were proposed. Review the sources and record why this pass should stop.")
            reason = st.text_input("Reason for next step or stopping", key=f'research_reason_{state["search_run_id"]}')
            continue_column, stop_column = st.columns(2)
            proceed = continue_column.button("Run selected follow-up", type="primary", key="research_continue",
                                              disabled=selected is None or not reason.strip())
            stop = stop_column.button("Finish research pass", key="research_stop", disabled=not reason.strip())
            if proceed or stop:
                with st.spinner("Updating the research run..."):
                    session.resume("padmini", actor, {"search_run_id": state["search_run_id"],
                        "action": "search" if proceed else "stop", "query_index": selected if proceed else None,
                        "reason": reason})
                st.rerun()
    except Exception:
        st.error("The research step could not finish. Check provider credentials, Databricks login, and model access. Saved checkpoints are preserved; no automatic retry was made.")
