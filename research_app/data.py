"""Deterministic, wholly fictional records for interface development.

No record describes a real incident, person, publication, or public record.
"""
from __future__ import annotations
from urllib.parse import urlsplit


def validate_workspace(workspace: dict) -> None:
    """Reject malformed snapshots before persistence; raises readable ValueError."""
    required = {
        "projects": "id name description dataset_ids",
        "datasets": "id name description project_ids incident_ids source_ids status created_at",
        "incidents": "id dataset_ids title date county state review_status fields source_ids",
        "sources": "id title publisher published_at url kind text snippet processing_status incident_ids dataset_ids",
        "variables": "id key label type allowed_values definition codebook_version",
        "runs": "id dataset_id kind status started_at source_count incident_count detail",
        "reviews": "id incident_id field previous_value new_value reason reviewer reviewed_at",
        "usage_events": "id kind at units cost_usd",
    }
    if not isinstance(workspace, dict) or set(workspace) != set(required):
        raise ValueError("Snapshot must contain exactly the eight workspace collections.")
    indexes = {}
    for collection, fields in required.items():
        rows = workspace[collection]
        if not isinstance(rows, list):
            raise ValueError(f"{collection} must be a list.")
        indexes[collection] = {}
        for row in rows:
            if not isinstance(row, dict) or not set(fields.split()).issubset(row):
                raise ValueError(f"{collection} contains a record with missing required fields.")
            identifier = row["id"]
            if not isinstance(identifier, str) or not identifier or identifier in indexes[collection]:
                raise ValueError(f"{collection} IDs must be non-empty unique strings.")
            indexes[collection][identifier] = row
            for key in fields.split():
                if key in {"fields", "allowed_values", "previous_value", "new_value", "cost_usd", "units", "source_count", "incident_count"} or key.endswith("_ids"):
                    continue
                if not isinstance(row[key], str):
                    raise ValueError(f"{collection}.{key} must be text.")
    targets = {"project_ids": "projects", "dataset_ids": "datasets", "incident_ids": "incidents", "source_ids": "sources"}
    for collection in required:
        for row in workspace[collection]:
            for key, target in targets.items():
                if key in row:
                    ids = row[key]
                    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or any(i not in indexes[target] for i in ids):
                        raise ValueError(f"Invalid {collection}.{key} references.")
            for key, target in {"dataset_id": "datasets", "incident_id": "incidents"}.items():
                if key in row and row[key] not in indexes[target]:
                    raise ValueError(f"Unknown {collection}.{key} reference.")
    variables = {}
    for variable in workspace["variables"]:
        if variable["key"] in variables or variable["type"] not in {"integer", "number", "boolean", "text", "category"} or not isinstance(variable["allowed_values"], list):
            raise ValueError("Variables require unique keys, supported types, and allowed_values lists.")
        variables[variable["key"]] = variable
    for incident in workspace["incidents"]:
        if incident["review_status"] not in {"Needs review", "In review", "Verified"} or not isinstance(incident["fields"], dict):
            raise ValueError("Invalid incident review status or fields.")
        for key, field in incident["fields"].items():
            if key not in variables or not isinstance(field, dict) or not {"value", "status", "evidence_ids"}.issubset(field):
                raise ValueError("Incident field must reference a variable and include value, status, and evidence_ids.")
            status, value, evidence = field["status"], field["value"], field["evidence_ids"]
            if status not in ("Reported", "Not Reported", "Unclear") or (status != "Reported" and value is not None):
                raise ValueError("Invalid field status/value combination.")
            if not isinstance(evidence, list) or any(not isinstance(i, str) or i not in incident["source_ids"] for i in evidence):
                raise ValueError("Field evidence must reference this incident's sources.")
            if len(set(evidence)) != len(evidence):
                raise ValueError("Field evidence IDs must be unique.")
            kind = variables[key]["type"]
            if status == "Reported":
                valid = {"integer": type(value) is int, "number": type(value) in (int, float), "boolean": type(value) is bool, "text": isinstance(value, str), "category": value in variables[key]["allowed_values"]}[kind]
                if not valid or value is None or (isinstance(value, str) and not value.strip()):
                    raise ValueError(f"Field {key} does not match its variable type or allowed values.")
                if not evidence:
                    raise ValueError("Reported fields require supporting evidence.")
        if incident["review_status"] == "Verified":
            if not variables or set(incident["fields"]) != set(variables) or any(f["status"] == "Unclear" or not f["evidence_ids"] for f in incident["fields"].values()):
                raise ValueError("Verified incidents require every variable to be coded with evidence and no unresolved fields.")
    for source in workspace["sources"]:
        if source["kind"] not in {"News article", "Public record", "Uploaded document"}:
            raise ValueError("Unsupported source kind.")
        if source["url"]:
            try:
                parsed = urlsplit(source["url"])
                valid_url = parsed.scheme in ("http", "https") and bool(parsed.hostname) and parsed.username is None and parsed.password is None and not any(c.isspace() or ord(c) < 32 for c in source["url"])
                parsed.port
            except ValueError:
                valid_url = False
            if not valid_url:
                raise ValueError("Source URLs must be blank or valid http(s) URLs without credentials.")
    for left, left_key, right, right_key in [("projects", "dataset_ids", "datasets", "project_ids"), ("datasets", "incident_ids", "incidents", "dataset_ids"), ("datasets", "source_ids", "sources", "dataset_ids"), ("incidents", "source_ids", "sources", "incident_ids")]:
        for a, a_key, b, b_key in [(left, left_key, right, right_key), (right, right_key, left, left_key)]:
            for row in workspace[a]:
                if any(row["id"] not in indexes[b][i][b_key] for i in row[a_key]):
                    raise ValueError(f"Membership must agree between {a} and {b}.")
    for review in workspace["reviews"]:
        if review["field"] not in variables and review["field"] != "review_status":
            raise ValueError("Review field must reference a variable or review_status.")
        if not review["reason"].strip() or not review["reviewer"].strip() or not review["reviewed_at"].strip():
            raise ValueError("Reviews require a reason, reviewer, and timestamp.")
        if review["field"] == "review_status":
            if review["previous_value"] not in ("Needs review", "In review", "Verified") or review["new_value"] not in ("Needs review", "In review", "Verified"):
                raise ValueError("Review status transitions must use supported statuses.")
        else:
            if not {"previous_status", "new_status", "previous_evidence_ids", "new_evidence_ids", "codebook_version"}.issubset(review):
                raise ValueError("Field reviews require before/after statuses, evidence IDs, and codebook_version.")
            if not isinstance(review["codebook_version"], str) or not review["codebook_version"]:
                raise ValueError("Field review codebook_version must be non-empty text.")
            for prefix in ("previous", "new"):
                permitted_statuses = ("Reported", "Not Reported", "Unclear", None) if prefix == "previous" else ("Reported", "Not Reported", "Unclear")
                if review[f"{prefix}_status"] not in permitted_statuses:
                    raise ValueError("Field review status is invalid.")
                refs = review[f"{prefix}_evidence_ids"]
                if not isinstance(refs, list) or any(not isinstance(i, str) or i not in indexes["sources"] for i in refs):
                    raise ValueError("Review evidence must reference existing sources.")
                if review[f"{prefix}_status"] is None and (review[f"{prefix}_value"] is not None or refs):
                    raise ValueError("An uncoded previous field must have null value and no evidence.")
    for run in workspace["runs"]:
        if any(type(run[key]) is not int or run[key] < 0 for key in ("source_count", "incident_count")):
            raise ValueError("Run counts must be non-negative integers.")
    for event in workspace["usage_events"]:
        if type(event["units"]) not in (int, float) or event["units"] < 0 or (event["cost_usd"] is not None and (type(event["cost_usd"]) not in (int, float) or event["cost_usd"] < 0)):
            raise ValueError("Usage units/cost must be non-negative numbers, with null allowed for unknown cost.")
    import json
    try:
        json.dumps(workspace, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Snapshot must contain finite JSON-compatible values.") from exc


def seed_workspace() -> dict:
    variables = [
        {"id": "var-age", "key": "victim_age", "label": "Victim age", "type": "integer", "allowed_values": [], "definition": "Age in completed years as explicitly reported; do not infer from appearance.", "codebook_version": "demo-1.0"},
        {"id": "var-relationship", "key": "relationship", "label": "Victim–suspect relationship", "type": "category", "allowed_values": ["Intimate partner", "Family", "Acquaintance", "Stranger"], "definition": "Relationship explicitly attributed by a source. An allegation does not establish guilt.", "codebook_version": "demo-1.0"},
        {"id": "var-location", "key": "location_type", "label": "Location type", "type": "category", "allowed_values": ["Residence", "Public space", "Business"], "definition": "Setting of the incident, distinct from where a body was discovered.", "codebook_version": "demo-1.0"},
        {"id": "var-circumstance", "key": "circumstance", "label": "Reported circumstance", "type": "text", "allowed_values": [], "definition": "Source-described circumstance. Preserve attribution and uncertainty.", "codebook_version": "demo-1.0"},
    ]
    specs = [
        ("2023-01-14", "Cedar County (fictional)", 34, "Acquaintance", "Residence", "Reported argument", "Verified"),
        ("2023-02-08", "Willow County (fictional)", 27, "Intimate partner", "Residence", "Reported domestic dispute", "Needs review"),
        ("2023-03-19", "Cedar County (fictional)", None, None, "Public space", None, "Needs review"),
        ("2023-04-03", "Mesa County (fictional)", 46, "Stranger", "Business", "Reported robbery", "In review"),
        ("2023-05-22", "Willow County (fictional)", 51, "Family", "Residence", "Circumstances under investigation", "Verified"),
        ("2023-07-11", "Mesa County (fictional)", 22, "Acquaintance", "Public space", "Reported argument", "Needs review"),
        ("2023-09-06", "Cedar County (fictional)", 39, None, "Business", None, "In review"),
        ("2023-11-17", "Willow County (fictional)", 63, "Family", "Residence", "Circumstances under investigation", "Needs review"),
    ]
    incidents, sources = [], []
    for number, (date, county, age, relationship, location, circumstance, review) in enumerate(specs, 1):
        incident_id, source_id = f"incident-{number:03}", f"source-{number:03}"
        dataset_ids = ["dataset-texas-2023"] + (["dataset-evidence-review"] if number in (2, 3, 6, 7) else [])
        values = {"victim_age": age, "relationship": relationship, "location_type": location, "circumstance": circumstance}
        fields = {key: {"value": value, "status": "Reported" if value is not None else "Not Reported", "evidence_ids": [source_id]} for key, value in values.items()}
        if number == 2:
            fields["victim_age"] = {"value": None, "status": "Unclear", "evidence_ids": [source_id, "source-009"]}
        if number == 6:
            fields["relationship"] = {"value": None, "status": "Unclear", "evidence_ids": [source_id, "source-010"]}
        source_ids = [source_id] + (["source-009"] if number == 2 else ["source-010"] if number == 6 else [])
        incidents.append({"id": incident_id, "dataset_ids": dataset_ids, "title": f"Fictional case {number:02} · {county}", "date": date, "county": county, "state": "TX", "review_status": review, "fields": fields, "source_ids": source_ids})
        text = (
            f"FICTIONAL DEMONSTRATION MATERIAL — NOT A REAL CASE.\n\n"
            f"Training record {number:02} describes a fictional homicide incident dated {date} in {county}, Texas. "
            f"The fictional report identifies the setting as {location.lower()}. "
            + (f"The victim's age is reported as {age}. " if age is not None else "The victim's age is not provided. ")
            + (f"The report describes the victim–suspect relationship as {relationship.lower()}. " if relationship else "The relationship is not stated. ")
            + (f"The source describes the circumstance as: {circumstance.lower()}. " if circumstance else "No circumstance is supplied by this source. ")
            + "\n\nThis is a synthetic training narrative. The relationship and circumstance are source assertions, not judicial findings. "
            "A researcher should retain this distinction when coding the incident. Missing information must remain missing."
        )
        sources.append({"id": source_id, "title": f"Fictional source {number:02}: incident summary", "publisher": "Fictional Research Training Bulletin", "published_at": date, "url": "", "kind": "Public record" if number % 3 == 0 else "News article", "text": text, "snippet": text.split("\n\n")[1][:220], "processing_status": "Processed", "incident_ids": [incident_id], "dataset_ids": dataset_ids})
    for source_id, incident_number, date, detail in [
        ("source-009", 2, "2023-02-10", "A follow-up fictional record gives the victim's age as 29, while the initial article gives 27. Neither record explains the discrepancy. The age must remain Unclear pending researcher review."),
        ("source-010", 6, "2023-07-13", "A fictional supplemental record states that the victim and suspect were strangers. The earlier narrative describes them as acquaintances. These conflicting source assertions require review; no relationship can yet be selected."),
    ]:
        incident = incidents[incident_number - 1]
        sources.append({"id": source_id, "title": f"Fictional follow-up: case {incident_number:02}", "publisher": "Fictional Training Records Office", "published_at": date, "url": "", "kind": "Uploaded document", "text": "FICTIONAL DEMONSTRATION MATERIAL — NOT A REAL CASE.\n\n" + detail, "snippet": detail, "processing_status": "Processed", "incident_ids": [incident["id"]], "dataset_ids": list(incident["dataset_ids"])})
    datasets = [
        {"id": "dataset-texas-2023", "name": "Texas 2023 · Demo", "description": "Eight wholly fictional incidents for testing collection, coding, and evidence review. Not research data.", "project_ids": ["project-coverage"], "incident_ids": [i["id"] for i in incidents], "source_ids": [s["id"] for s in sources], "status": "In progress", "created_at": "2026-10-20T14:00:00Z"},
        {"id": "dataset-evidence-review", "name": "Evidence review · Demo", "description": "Four fictional cases illustrating missing information and contradictory reports.", "project_ids": ["project-coverage"], "incident_ids": [i["id"] for i in incidents if "dataset-evidence-review" in i["dataset_ids"]], "source_ids": [s["id"] for s in sources if "dataset-evidence-review" in s["dataset_ids"]], "status": "In review", "created_at": "2026-10-21T10:00:00Z"},
    ]
    return {
        "projects": [{"id": "project-coverage", "name": "Homicide evidence coverage · Demo", "description": "Explore evidence completeness and classification consistency using fictional records only.", "dataset_ids": [d["id"] for d in datasets]}],
        "datasets": datasets, "incidents": incidents, "sources": sources, "variables": variables,
        "runs": [
            {"id": "run-001", "dataset_id": "dataset-texas-2023", "kind": "Demo collection", "status": "Completed", "started_at": "2026-10-20T14:05:00Z", "source_count": 10, "incident_count": 8, "detail": "Loaded synthetic fixtures; no external search or extraction was executed."},
            {"id": "run-002", "dataset_id": "dataset-evidence-review", "kind": "Demo evaluation", "status": "Completed", "started_at": "2026-10-21T10:10:00Z", "source_count": 6, "incident_count": 4, "detail": "Fixture flags illustrate two conflicts and incomplete fields. Not a model accuracy evaluation."},
        ],
        "reviews": [],
        "usage_events": [{"id": "usage-001", "kind": "Demo fixture load", "at": "2026-10-20T14:05:00Z", "units": 10, "cost_usd": None}],
    }
