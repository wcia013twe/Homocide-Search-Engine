"""Read saved discovery decisions without starting a provider or model call."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def _artifact(root: Path, filename: str, expected_hash: str | None = None):
    path = Path(filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Artifact path is outside this audit directory.")
    payload = path.read_bytes()
    if expected_hash is not None and sha256(payload).hexdigest() != expected_hash:
        raise ValueError("Artifact hash does not match the saved audit record.")
    return json.loads(payload)


def review(directory: str | Path, run_id: str | None = None) -> dict:
    root = Path(directory).resolve()
    database = root / "search_audit.sqlite3"
    # mode=ro prevents a typo from creating a new database or changing saved research.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        if run_id is None:
            return {"runs": [dict(row) for row in connection.execute(
                "SELECT run_id, provider, query, result_count, searched_at, "
                "triage_artifact_path IS NOT NULL AS has_triage FROM search_runs ORDER BY searched_at DESC") ]}
        row = connection.execute("SELECT * FROM search_runs WHERE run_id = ?", [run_id]).fetchone()
        if row is None:
            raise ValueError("Search run was not found.")
        results = [dict(result) for result in connection.execute(
            "SELECT result_rank, title, url, snippet, published_date_raw FROM search_results "
            "WHERE run_id = ? ORDER BY result_rank", [run_id])]
    if len(results) != row["result_count"]:
        raise ValueError("Saved result count does not match the search run.")
    _artifact(root, row["raw_response_path"], row["raw_response_sha256"])
    decision = {}
    if row["triage_artifact_path"]:
        artifact = _artifact(root, row["triage_artifact_path"], row["triage_artifact_sha256"])
        if artifact["search_run_id"] != run_id:
            raise ValueError("Triage artifact belongs to a different search run.")
        decision = artifact["decision"]
        from research_app.research_triage import validate_triage

        validate_triage({key: decision[key] for key in ("assessments", "next_queries")}, results)
    assessments = {item["result_rank"]: item for item in decision.get("assessments", [])}
    return {
        "run_id": run_id, "query": row["query"], "provider": row["provider"],
        "prompt_version": decision.get("prompt_version"), "model_endpoint": decision.get("model_endpoint"),
        "artifact_hashes_verified": True,
        "results": [result | {"assessment": assessments.get(result["result_rank"])} for result in results],
        "next_queries": decision.get("next_queries", []),
        "triage_artifact_path": row["triage_artifact_path"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="local-audit")
    parser.add_argument("--run")
    args = parser.parse_args()
    print(json.dumps(review(args.directory, args.run), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
