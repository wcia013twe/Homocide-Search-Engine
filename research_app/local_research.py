"""Run a live discovery pass with audit data kept in local SQLite and files."""
import argparse
import base64
import json
import os

from research_app.research_agent import PADMINI_QUERY, build_research_graph
from research_app.research_triage import DatabricksTriage
from research_app.search_audit import SQLiteSearchAuditStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("Exa", "Brave"), default="Exa")
    parser.add_argument("--query", default=PADMINI_QUERY)
    parser.add_argument("--directory", default="local-audit")
    parser.add_argument("--profile", default="pc")
    parser.add_argument("--model-endpoint", help="Omit to inspect search only")
    parser.add_argument("--secret-scope", help="Read the provider key into memory from this Databricks scope")
    parser.add_argument("--retriage-run", help="Reassess a saved local search without another search API call")
    parser.add_argument("--fill-profile", action="store_true", help="Extract and immediately fill supported values using ai_decide")
    args = parser.parse_args()
    if args.fill_profile and (not args.model_endpoint or args.retriage_run):
        parser.error("--fill-profile requires --model-endpoint and cannot be combined with --retriage-run")
    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient(profile=args.profile)
    actor = client.current_user.me().user_name
    if args.secret_scope and not args.retriage_run:
        key_name = "EXA_API_KEY" if args.provider == "Exa" else "BRAVE_API_KEY"
        secret = client.secrets.get_secret(scope=args.secret_scope, key=key_name)
        os.environ[key_name] = base64.b64decode(secret.value).decode("utf-8")
    store = SQLiteSearchAuditStore(args.directory)
    model = DatabricksTriage(args.model_endpoint) if args.model_endpoint else None
    if args.retriage_run:
        if model is None:
            parser.error("--retriage-run requires --model-endpoint")
        import sqlite3

        with store._connection() as connection:
            connection.row_factory = sqlite3.Row
            run = connection.execute("SELECT query FROM search_runs WHERE run_id = ?",
                                     [args.retriage_run]).fetchone()
            if run is None:
                parser.error("Saved search run was not found in this local audit directory")
            rows = connection.execute("SELECT * FROM search_results WHERE run_id = ? ORDER BY result_rank",
                                      [args.retriage_run]).fetchall()
        results = [dict(row) | {"published_date": row["published_date_raw"]} for row in rows]
        if results:
            decision = model(run["query"], results)
            store.record_triage(args.retriage_run, decision)
        print(json.dumps({"search_run_id": args.retriage_run,
                          "status": "awaiting_review" if results else "no_results"}), flush=True)
        return
    profile_options = {}
    if args.fill_profile:
        from research_app.research_profile import DatabricksClaimExtractor, DatabricksFieldDecisions
        fields = ("person_identity", "age", "city", "location", "agency", "manner", "medical_cause", "incident_date", "case_number")
        profile_options = {"extract_claims": DatabricksClaimExtractor(args.model_endpoint, fields),
                           "decide_claims": DatabricksFieldDecisions(client), "record_profile": store.record_profile}
    graph = build_research_graph(
        **profile_options,
        record_search=lambda response: store.record(response, actor),
        triage=model,
        record_triage=lambda state, decision: store.record_triage(state["search_run_id"], decision),
    )
    # Print only progress identifiers; full source and model payloads stay in audit files.
    for update in graph.stream({"query": args.query, "provider": args.provider}, stream_mode="updates"):
        for node, values in update.items():
            print(json.dumps({"node": node, "search_run_id": values.get("search_run_id"),
                              "status": values.get("status"),
                              "result_count": len(values["results"]) if "results" in values else None}), flush=True)


if __name__ == "__main__":
    main()
