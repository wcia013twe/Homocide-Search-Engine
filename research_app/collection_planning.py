"""Plan continued case collection without treating filled fields as saturation."""
from hashlib import sha256


def _query_key(query):
    return " ".join(query.lower().split())


def _content_key(source):
    text = source.get("text", "")
    if not text.strip():
        return None
    return source.get("content_sha256") or sha256(text.encode("utf-8")).hexdigest()


def plan_collection(seed, sources, previous_sources, gaps, search_history,
                    triage_proposals=(), result_ranks=None):
    """Return reviewable proposals, never an automatic saturation decision.

    Sources are accumulated source-ID dictionaries. Novel text is a collection
    signal, not proof of new case facts. A repeated collection pass recommends
    researcher review; missing fields are retained and never invented to extend it.
    """
    previous_keys = {_content_key(s) for s in previous_sources.values()} - {None}
    seen = set(previous_keys)
    new_source_ids = []
    for source_id, source in sources.items():
        key = _content_key(source)
        if key is not None and key not in seen:
            new_source_ids.append(source_id)
            seen.add(key)
    follow_up = len(search_history) > 1
    review_recommended = follow_up and not new_source_ids
    reason = ("This follow-up added no distinct source text. Review whether collection is sufficient; "
              "this does not establish that all available case information has been found."
              if review_recommended else "New source material is available for coding and further collection."
              if new_source_ids else "No usable source text was collected. Review retrieval outcomes and search scope.")
    ranks = sorted(set(result_ranks if result_ranks is not None else
                       [s["result_rank"] for s in sources.values() if s.get("result_rank")]))
    searched = {_query_key(item["query"]) for item in search_history}
    proposals = []

    def add(query, gap, why, based_on=None):
        key = _query_key(query)
        references = sorted(set(based_on or ranks) & set(ranks))
        if key and key not in searched and references and len(proposals) < 3:
            proposals.append(dict(query=query, target_gap=gap, reason=why, based_on_ranks=references))
            searched.add(key)

    # Preserve useful model proposals, including expanded names or local context.
    for proposal in triage_proposals:
        add(proposal["query"], proposal["target_gap"], proposal["reason"], proposal.get("based_on_ranks"))
    # Reserve collection as a goal even when the profile is already populated.
    if not proposals:
        for suffix in ("incident updates", "investigation public records", "case reporting"):
            add(f"{seed} {suffix}", "case_collection",
                "Look for additional case information across reporting and public records.")
            if proposals:
                break
    for gap in gaps:
        field = gap["field"]
        suffix = " conflicting reports" if gap["reason"] == "conflicting" else ""
        add(f"{seed} {field.replace('_', ' ')}{suffix}", field,
            f"Address the {gap['reason']} coded field using additional source material.")
    if not proposals or (not gaps and len(proposals) < 3):
        for suffix in ("incident updates", "investigation public records", "case reporting"):
            add(f"{seed} {suffix}", "case_collection",
                "Look for additional case information across reporting and public records.")
    return dict(next_queries=proposals, collection_review_recommended=review_recommended,
                collection_stop_reason=reason, new_source_ids=new_source_ids)
