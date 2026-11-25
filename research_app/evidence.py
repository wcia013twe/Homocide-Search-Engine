"""Shared evidence dictionaries; offsets use Python character indices, end exclusive."""
from hashlib import sha256


def source_record(source_id, *, url, text, title=None, publisher=None,
                  published_at=None, source_type="unclassified", search_run_id=None,
                  result_rank=None, retrieval_status="not_attempted", retrieved_at=None,
                  artifact_path=None, evidence_kind="search_excerpt"):
    return dict(source_id=source_id, url=url, title=title, publisher=publisher,
                published_at=published_at, source_type=source_type,
                search_run_id=search_run_id, result_rank=result_rank,
                retrieval_status=retrieval_status, retrieved_at=retrieved_at,
                content_sha256=sha256(text.encode("utf-8")).hexdigest(),
                artifact_path=artifact_path, text=text, evidence_kind=evidence_kind)


def attributed_claim(claim, sources):
    """Add provenance to legacy claims and validate supplied text locators."""
    source = sources.get(claim.get("source_id"))
    passage = claim.get("passage")
    if not source or not isinstance(passage, str) or not passage or passage not in source["text"]:
        raise ValueError("Claim provenance must quote the supplied source text exactly.")
    locator = claim.get("locator")
    if locator is None:
        start = source["text"].index(passage)
        locator = {"start": start, "end": start + len(passage), "page": None}
    start, end = locator.get("start"), locator.get("end")
    if (type(start) is not int or type(end) is not int or start < 0 or end <= start
            or source["text"][start:end] != passage):
        raise ValueError("Claim locator must match the exact supporting passage.")
    subject_id = claim.get("subject_id", "incident")
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ValueError("Claims require a subject ID.")
    return {**claim, "subject_id": subject_id, "locator": dict(locator),
            "content_sha256": source.get("content_sha256") or sha256(source["text"].encode("utf-8")).hexdigest()}
