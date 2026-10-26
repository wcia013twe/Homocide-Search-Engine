"""Researcher dataset workspace. All persisted changes use the provided save hook."""
from __future__ import annotations

import copy
import csv
import io
import math
import re
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

import streamlit as st


REVIEW_STATES = ["Needs review", "In review", "Verified"]
FIELD_STATES = ["Reported", "Not Reported", "Unclear"]


def _id(prefix):
    return f"{prefix}_{uuid4().hex[:12]}"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _persist(workspace, before, save, message):
    try:
        saved = save()
    except Exception:
        saved = False
    if saved:
        st.success(message)
        return True
    workspace.clear()
    workspace.update(before)
    st.error("Changes could not be saved. Your previous records have been restored. Try again.")
    return False


def _source_preview(source):
    st.subheader(source.get("title", "Untitled source"))
    st.caption(" · ".join(str(source.get(k) or "Unknown") for k in ("publisher", "published_at", "kind")))
    url = source.get("url", "")
    if url.startswith(("https://", "http://")):
        st.link_button("Open original source", url)
    st.write(source.get("text") or source.get("snippet") or "No document text is available yet.")
    st.caption(f"Source ID: {source['id']} · Processing: {source.get('processing_status', 'Unknown')}")


def _csv(incidents, variables):
    output = io.StringIO()
    keys = [v["key"] for v in variables]
    columns = ["incident_id", "title", "date", "county", "state", "review_status", "source_ids"]
    columns += [f"{k}{suffix}" for k in keys for suffix in ("", "__status", "__evidence_ids")]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for inc in incidents:
        row = {k: inc.get(k, "") for k in columns[:7]}
        row["incident_id"] = inc["id"]
        row["source_ids"] = "|".join(inc.get("source_ids", []))
        for key in keys:
            field = inc.get("fields", {}).get(key, {})
            row[key] = field.get("value", "")
            row[f"{key}__status"] = field.get("status", "Not Reported")
            row[f"{key}__evidence_ids"] = "|".join(field.get("evidence_ids", []))
        # Spreadsheet applications interpret leading operators as formulas.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in row.items()})
    return output.getvalue()


def _incident_detail(workspace, incident, save):
    sources = {s["id"]: s for s in workspace["sources"]}
    variables = workspace["variables"]
    linked = [sid for sid in incident.get("source_ids", []) if sid in sources]
    st.divider()
    st.subheader(incident["title"])
    st.caption(f"{incident['id']} · {incident.get('date') or 'Date unknown'} · {incident.get('county') or 'County unknown'}, {incident.get('state', '')}")
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("**Coding & review**")
        st.caption("Changes require a reason and retain the previous value in the review history.")
        with st.form(f"ds_review_{incident['id']}"):
            proposed = {}
            for variable in variables:
                key = variable["key"]
                field = incident.get("fields", {}).get(key, {})
                st.markdown(f"**{variable.get('label', key)}**")
                if variable.get("definition"):
                    st.caption(variable["definition"])
                old_value = field.get("value")
                value = st.text_input("Value", value="" if old_value is None else str(old_value), key=f"ds_value_{incident['id']}_{key}")
                options = variable.get("allowed_values") or []
                if options:
                    st.caption("Allowed values: " + ", ".join(map(str, options)))
                state = field.get("status", "Not Reported")
                state = state if state in FIELD_STATES else "Unclear"
                status = st.selectbox("Evidence status", FIELD_STATES, index=FIELD_STATES.index(state), key=f"ds_status_{incident['id']}_{key}")
                refs = st.multiselect("Supporting sources", linked, default=[s for s in field.get("evidence_ids", []) if s in linked], format_func=lambda sid: sources[sid]["title"], key=f"ds_evidence_{incident['id']}_{key}")
                proposed[key] = {"value": value.strip() or None, "status": status, "evidence_ids": refs}
            current_status = incident.get("review_status", "Needs review")
            review_status = st.selectbox("Incident review status", REVIEW_STATES, index=REVIEW_STATES.index(current_status) if current_status in REVIEW_STATES else 0, key=f"ds_review_status_{incident['id']}")
            reason = st.text_area("Reason for changes", placeholder="Explain the correction or the evidence used to verify this incident.", key=f"ds_reason_{incident['id']}")
            submitted = st.form_submit_button("Save review", type="primary")
        if submitted:
            errors = []
            if not reason.strip():
                errors.append("Add a reason for this review.")
            reviewer = st.session_state.get("research_user")
            if not reviewer:
                errors.append("Set your researcher identity before saving a review.")
            if review_status == "Verified" and not variables:
                errors.append("Define the research codebook before verifying an incident.")
            for variable in variables:
                field = proposed[variable["key"]]
                label = variable.get("label", variable["key"])
                if field["status"] == "Reported" and field["value"] is None:
                    errors.append(f"{label}: enter a reported value or choose Not Reported.")
                if field["status"] == "Reported" and not field["evidence_ids"]:
                    errors.append(f"{label}: cite a supporting source for the reported value.")
                if field["status"] != "Reported" and field["value"] is not None:
                    errors.append(f"{label}: clear the value when selecting {field['status']}.")
                allowed = variable.get("allowed_values") or []
                if field["value"] and allowed and str(field["value"]) not in [str(v) for v in allowed]:
                    errors.append(f"{label}: choose a value listed in the codebook.")
                if field["value"] is not None and variable.get("type") in ("integer", "number", "float"):
                    try:
                        field["value"] = int(field["value"]) if variable["type"] == "integer" else float(field["value"])
                        if not math.isfinite(field["value"]):
                            raise ValueError("Nonfinite value")
                    except (ValueError, TypeError):
                        errors.append(f"{label}: enter a valid {variable['type']} value.")
                if field["value"] is not None and variable.get("type") == "boolean":
                    if str(field["value"]).lower() in ("true", "false"):
                        field["value"] = str(field["value"]).lower() == "true"
                    else:
                        errors.append(f"{label}: enter true or false.")
                if review_status == "Verified" and (field["status"] == "Unclear" or not field["evidence_ids"]):
                    errors.append(f"{label}: resolve uncertainty and cite an inspected source before verification, including for a Not Reported decision.")
            for error in errors:
                st.error(error)
            if not errors:
                before = copy.deepcopy(workspace)
                old_fields = copy.deepcopy(incident.get("fields", {}))
                changes = [{"field": key, "previous": old_fields.get(key), "new": value} for key, value in proposed.items() if old_fields.get(key) != value]
                for change in changes:
                    previous = change["previous"] or {}
                    new = change["new"]
                    workspace.setdefault("reviews", []).append({"id": _id("review"), "incident_id": incident["id"], "field": change["field"], "previous_value": previous.get("value"), "new_value": new.get("value"), "previous_status": previous.get("status"), "new_status": new.get("status"), "previous_evidence_ids": previous.get("evidence_ids", []), "new_evidence_ids": new.get("evidence_ids", []), "reviewer": reviewer, "reviewed_at": _now(), "reason": reason.strip(), "codebook_version": next(v["codebook_version"] for v in variables if v["key"] == change["field"]), "codebook_versions": {v["key"]: v.get("codebook_version") for v in variables}})
                workspace.setdefault("reviews", []).append({"id": _id("review"), "incident_id": incident["id"], "field": "review_status", "previous_value": current_status, "new_value": review_status, "reviewer": reviewer, "reviewed_at": _now(), "reason": reason.strip(), "previous_fields": old_fields, "new_fields": copy.deepcopy(proposed), "codebook_versions": {v["key"]: v.get("codebook_version") for v in variables}})
                incident["fields"] = proposed
                incident["review_status"] = review_status
                _persist(workspace, before, save, "Review saved with its evidence and change history.")
    with right:
        st.markdown("**Supporting evidence**")
        if linked:
            source_id = st.selectbox("Preview source", linked, format_func=lambda sid: sources[sid]["title"], key=f"ds_preview_{incident['id']}")
            _source_preview(sources[source_id])
        else:
            st.info("No source is linked to this incident. Collect evidence from Search before verifying reported fields.")
        with st.expander("Review history"):
            history = [r for r in workspace.get("reviews", []) if r.get("incident_id") == incident["id"]]
            if not history:
                st.caption("No researcher reviews have been saved.")
            for review in reversed(history):
                st.write(f"{review.get('reviewed_at', '')} · {review.get('reviewer', 'Unknown researcher')}")
                st.write(review.get("reason", ""))
                st.caption(f"{review.get('field', '')}: {review.get('previous_value', '')} → {review.get('new_value', '')}")
                st.json(review, expanded=False)


def render(workspace: dict, save: Callable[[], bool]) -> None:
    st.title("Datasets")
    st.write("Organize incidents, inspect evidence, and build a verified research dataset.")
    with st.expander("Create a dataset"):
        with st.form("ds_create"):
            name = st.text_input("Dataset name", placeholder="Texas homicide incidents, 2023")
            description = st.text_area("Research scope", placeholder="Define the geography, dates, and inclusion criteria.")
            project_map = {p["id"]: p for p in workspace.get("projects", [])}
            projects = st.multiselect("Projects", list(project_map), format_func=lambda p: project_map[p]["name"])
            create = st.form_submit_button("Create dataset")
        if create:
            if not name.strip():
                st.error("Enter a dataset name.")
            else:
                before = copy.deepcopy(workspace)
                dataset_id = _id("dataset")
                workspace["datasets"].append({"id": dataset_id, "name": name.strip(), "description": description.strip(), "project_ids": projects, "incident_ids": [], "source_ids": [], "status": "Active", "created_at": _now()})
                for project in workspace.get("projects", []):
                    if project["id"] in projects:
                        project.setdefault("dataset_ids", []).append(dataset_id)
                if _persist(workspace, before, save, "Dataset created. Collect sources in Search to begin."):
                    st.session_state["ds_selected"] = dataset_id
    datasets = {d["id"]: d for d in workspace.get("datasets", [])}
    if not datasets:
        st.info("Create a dataset to collect sources and review incidents together.")
        return
    if st.session_state.get("ds_selected") not in datasets:
        st.session_state["ds_selected"] = next(iter(datasets))
    selected = st.selectbox("Dataset", list(datasets), format_func=lambda d: datasets[d]["name"], key="ds_selected")
    dataset = datasets[selected]
    incidents = [i for i in workspace["incidents"] if i["id"] in dataset.get("incident_ids", []) or selected in i.get("dataset_ids", [])]
    sources = [s for s in workspace["sources"] if s["id"] in dataset.get("source_ids", []) or selected in s.get("dataset_ids", [])]
    variables = workspace["variables"]
    st.caption(dataset.get("description") or "Add research scope in Settings.")
    overview, incident_tab, source_tab, variable_tab, runs_tab, evaluation, settings = st.tabs(["Overview", "Incidents", "Sources", "Variables", "Runs", "Evaluation", "Settings"])
    with overview:
        verified = sum(i.get("review_status") == "Verified" for i in incidents)
        st.subheader("Research progress")
        st.write(f"**{len(incidents)} incidents** · **{len(sources)} sources** · **{verified} verified incidents**")
        if incidents:
            st.progress(verified / len(incidents), text=f"{verified} of {len(incidents)} incidents verified by researchers")
        else:
            st.info("Use Search to collect source material, then review linked incidents here.")
        st.subheader("Recent activity")
        recent = [r for r in workspace.get("runs", []) if r.get("dataset_id") == selected]
        if recent:
            st.dataframe([{k: r.get(k, "") for k in ("started_at", "kind", "status", "detail")} for r in sorted(recent, key=lambda r: r.get("started_at", ""), reverse=True)[:5]], hide_index=True, width="stretch")
        else:
            st.caption("No collection or extraction runs have been recorded for this dataset.")
    with incident_tab:
        with st.expander("Add an incident"):
            st.caption("Create one incident record from collected evidence. Review its fields against the sources after saving.")
            with st.form(f"ds_add_incident_{selected}"):
                incident_title = st.text_input("Incident title", key=f"ds_new_incident_title_{selected}")
                incident_date = st.date_input("Incident date (leave empty if unknown)", value=None, key=f"ds_new_incident_date_{selected}")
                county = st.text_input("County", key=f"ds_new_incident_county_{selected}")
                state = st.text_input("State", key=f"ds_new_incident_state_{selected}")
                source_map = {s["id"]: s for s in sources}
                incident_sources = st.multiselect("Collected sources supporting this incident", list(source_map), format_func=lambda sid: source_map[sid]["title"], key=f"ds_new_incident_sources_{selected}")
                add_incident = st.form_submit_button("Create incident", disabled=not sources)
            if not sources:
                st.caption("Collect at least one source for this dataset in Search or Library first.")
            if add_incident:
                if not incident_title.strip() or not incident_sources:
                    st.error("Provide an incident title and at least one supporting source.")
                else:
                    before = copy.deepcopy(workspace)
                    identifier = _id("incident")
                    record = {"id": identifier, "dataset_ids": [selected], "title": incident_title.strip(), "date": incident_date.isoformat() if incident_date else "", "county": county.strip(), "state": state.strip(), "review_status": "Needs review", "fields": {v["key"]: {"value": None, "status": "Not Reported", "evidence_ids": []} for v in variables}, "source_ids": incident_sources}
                    workspace["incidents"].append(record)
                    dataset["incident_ids"].append(identifier)
                    for source_id in incident_sources:
                        source_map[source_id]["incident_ids"].append(identifier)
                    if _persist(workspace, before, save, "Incident created. Review the fields below against its supporting evidence."):
                        incidents.append(record)
        a, b, c = st.columns([2, 1, 1])
        query = a.text_input("Find incident", placeholder="Title, county, or incident ID", key="ds_filter")
        status_filter = b.selectbox("Review status", ["All"] + REVIEW_STATES, key="ds_filter_status")
        order = c.selectbox("Sort by", ["Date, newest first", "Date, oldest first", "Title"], key="ds_sort")
        filtered = [i for i in incidents if (status_filter == "All" or i.get("review_status") == status_filter) and query.lower() in " ".join(str(i.get(k, "")) for k in ("title", "county", "id")).lower()]
        filtered.sort(key=lambda i: str(i.get("title" if order == "Title" else "date") or ""), reverse=order == "Date, newest first")
        st.caption(f"{len(filtered)} of {len(incidents)} incidents · One row per incident")
        if filtered:
            st.dataframe([{k: i.get(k, "") for k in ("id", "title", "date", "county", "state", "review_status")} for i in filtered], hide_index=True, width="stretch")
            st.download_button("Export filtered incidents (CSV)", _csv(filtered, variables), file_name=f"{selected}-incidents.csv", mime="text/csv", key="ds_export")
            st.caption("Export grain: one row per incident, with field evidence status and source IDs. Includes unverified records when present in the filter.")
            incident_map = {i["id"]: i for i in filtered}
            chosen = st.selectbox("Open incident", list(incident_map), format_func=lambda i: incident_map[i]["title"], key=f"ds_incident_{selected}")
            _incident_detail(workspace, incident_map[chosen], save)
        else:
            st.info("No incidents match these filters. Clear the filters or collect new evidence in Search.")
    with source_tab:
        st.subheader("Dataset sources")
        if sources:
            st.dataframe([{k: s.get(k, "") for k in ("title", "publisher", "published_at", "kind", "processing_status")} for s in sources], hide_index=True, width="stretch")
            source_map = {s["id"]: s for s in sources}
            chosen = st.selectbox("Read source", list(source_map), format_func=lambda sid: source_map[sid]["title"], key=f"ds_source_{selected}")
            _source_preview(source_map[chosen])
        else:
            st.info("This dataset has no sources yet. Save documents from Search to begin collecting evidence.")
    with variable_tab:
        st.subheader("Research codebook")
        st.caption("This scaffold shares one codebook across all datasets. Changes here affect every dataset; existing field values and prior review records are retained. Definition changes return affected verified incidents to Needs review.")
        with st.expander("Define a new variable"):
            st.caption("New variables apply to every incident. Previously verified incidents return to Needs review because their expanded codebook requires a new check.")
            with st.form("ds_add_variable"):
                new_key = st.text_input("Variable key", placeholder="incident_setting", key="ds_new_variable_key")
                new_label = st.text_input("New variable label", key="ds_new_variable_label")
                new_type = st.selectbox("Data type", ["text", "integer", "number", "boolean", "category"], key="ds_new_variable_type")
                categories = st.text_area("Allowed categories (one per line; required for category type)", key="ds_new_variable_categories")
                new_definition = st.text_area("New variable definition and coding instructions", key="ds_new_variable_definition")
                new_version = st.text_input("Initial variable version", value="1.0", key="ds_new_variable_version")
                add_variable = st.form_submit_button("Add variable")
            if add_variable:
                allowed = list(dict.fromkeys(line.strip() for line in categories.splitlines() if line.strip()))
                if not re.fullmatch(r"[a-z][a-z0-9_]*", new_key.strip()):
                    st.error("Use a variable key beginning with a lowercase letter, followed by lowercase letters, numbers, or underscores.")
                elif new_key.strip() in {v["key"] for v in variables}:
                    st.error("This variable key already exists. Use a unique key.")
                elif not all(value.strip() for value in (new_label, new_definition, new_version)):
                    st.error("Provide a label, definition, and initial version.")
                elif new_type == "category" and not allowed:
                    st.error("Add at least one allowed category.")
                else:
                    before = copy.deepcopy(workspace)
                    key = new_key.strip()
                    variables.append({"id": _id("variable"), "key": key, "label": new_label.strip(), "type": new_type, "allowed_values": allowed if new_type == "category" else [], "definition": new_definition.strip(), "codebook_version": new_version.strip()})
                    for record in workspace["incidents"]:
                        record["fields"][key] = {"value": None, "status": "Not Reported", "evidence_ids": []}
                        if record["review_status"] == "Verified":
                            workspace["reviews"].append({"id": _id("review"), "incident_id": record["id"], "field": "review_status", "previous_value": "Verified", "new_value": "Needs review", "reason": f"Shared codebook expanded with {key}; the new variable requires researcher review.", "reviewer": st.session_state["research_user"], "reviewed_at": _now()})
                            record["review_status"] = "Needs review"
                    _persist(workspace, before, save, "Variable added to the shared codebook. Existing incidents start with Not Reported.")
        if variables:
            st.dataframe([{k: v.get(k, "") for k in ("key", "label", "type", "definition", "codebook_version")} for v in variables], hide_index=True, width="stretch")
            variable_map = {v["key"]: v for v in variables}
            selected_variable = st.selectbox("Edit variable definition", list(variable_map), format_func=lambda k: variable_map[k].get("label", k), key="ds_variable")
            variable = variable_map[selected_variable]
            with st.form(f"ds_variable_form_{selected_variable}"):
                label = st.text_input("Variable label", value=variable.get("label", ""))
                definition = st.text_area("Definition and coding instructions", value=variable.get("definition", ""))
                version = st.text_input("New codebook version", value=str(variable.get("codebook_version", "1.0")))
                update = st.form_submit_button("Save codebook definition")
            if update:
                if not label.strip() or not definition.strip() or not version.strip():
                    st.error("Provide a label, definition, and version.")
                elif version.strip() == str(variable.get("codebook_version", "")):
                    st.error("Enter a new codebook version to preserve the meaning of earlier coding.")
                else:
                    before = copy.deepcopy(workspace)
                    variable.setdefault("history", []).append({"label": variable.get("label"), "definition": variable.get("definition"), "codebook_version": variable.get("codebook_version"), "changed_at": _now(), "reviewer": st.session_state.get("research_user")})
                    variable.update(label=label.strip(), definition=definition.strip(), codebook_version=version.strip())
                    for record in workspace["incidents"]:
                        if record["review_status"] == "Verified" and selected_variable in record["fields"]:
                            workspace["reviews"].append({"id": _id("review"), "incident_id": record["id"], "field": "review_status", "previous_value": "Verified", "new_value": "Needs review", "reason": f"Codebook definition for {selected_variable} changed to version {version.strip()}; prior coding requires researcher review.", "reviewer": st.session_state["research_user"], "reviewed_at": _now()})
                            record["review_status"] = "Needs review"
                    _persist(workspace, before, save, "Shared codebook definition updated; previous definition retained.")
        else:
            st.info("No variables are defined. Connect a versioned research codebook before extraction.")
    with runs_tab:
        st.subheader("Collection & extraction history")
        st.caption("Recorded activity only. Demonstration runs do not represent live Databricks jobs.")
        runs = [r for r in workspace.get("runs", []) if r.get("dataset_id") == selected]
        if runs:
            st.dataframe([{k: r.get(k, "") for k in ("started_at", "kind", "status", "source_count", "incident_count", "detail")} for r in runs], hide_index=True, width="stretch")
        else:
            st.info("No runs recorded. Search and collection activity will appear here when saved.")
    with evaluation:
        st.subheader("Completeness & review queue")
        st.caption("Counts describe the stored records. Extraction accuracy requires a labeled evaluation set and is not yet measured.")
        rows = []
        for variable in variables:
            states = [i.get("fields", {}).get(variable["key"], {}).get("status", "Not Reported") for i in incidents]
            rows.append({"Variable": variable.get("label", variable["key"]), "Reported": states.count("Reported"), "Not Reported": states.count("Not Reported"), "Unclear": states.count("Unclear")})
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        pending = [i for i in incidents if i.get("review_status") != "Verified"]
        st.write(f"**{len(pending)} incidents await verification.** Open the Incidents tab to inspect and correct their evidence.")
    with settings:
        st.subheader("Dataset settings")
        with st.form(f"ds_settings_{selected}"):
            updated_name = st.text_input("Name", value=dataset["name"])
            updated_description = st.text_area("Description and inclusion criteria", value=dataset.get("description", ""))
            update_settings = st.form_submit_button("Save settings")
        if update_settings:
            if not updated_name.strip():
                st.error("Dataset name cannot be empty.")
            else:
                before = copy.deepcopy(workspace)
                dataset.update(name=updated_name.strip(), description=updated_description.strip())
                _persist(workspace, before, save, "Dataset settings saved.")
        st.markdown("**Sharing**")
        st.caption("Dataset access controls and invitations are unavailable until the identity and permissions backend is connected. Local settings do not grant or restrict access.")
