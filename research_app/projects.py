"""Research projects, dataset comparison, and transparent exports."""
import csv
import io
import json
from uuid import uuid4
import streamlit as st


def render(workspace: dict, save):
    st.title("Projects")
    st.caption("Bring datasets together around a research question.")
    with st.expander("Create a project"):
        with st.form("proj_create_form"):
            name = st.text_input("Project name", key="proj_new_name")
            description = st.text_area("Research question or description", key="proj_new_description")
            create = st.form_submit_button("Create project")
        if create:
            if not name.strip():
                st.error("Enter a project name.")
            else:
                workspace.setdefault("projects", []).append({"id": str(uuid4()), "name": name.strip(), "description": description.strip(), "dataset_ids": []})
                if save():
                    st.success("Project created. Add datasets below.")
    projects = {p["id"]: p for p in workspace.get("projects", [])}
    if not projects:
        st.info("Create a project to group datasets and compare research coverage.")
        return
    chosen = st.selectbox("Project", list(projects), format_func=lambda x: projects[x]["name"], key="proj_selected")
    project = projects[chosen]
    st.subheader(project["name"])
    st.write(project.get("description") or "Add datasets to begin exploring this project.")
    datasets = {d["id"]: d for d in workspace.get("datasets", [])}
    with st.expander("Manage datasets"):
        with st.form(f"proj_datasets_form_{chosen}"):
            selected = st.multiselect("Included datasets", list(datasets), default=[x for x in project.get("dataset_ids", []) if x in datasets], format_func=lambda x: datasets[x]["name"], key=f"proj_datasets_{chosen}")
            update = st.form_submit_button("Save dataset selection")
        if update:
            project["dataset_ids"] = selected
            for dataset in datasets.values():
                memberships = dataset.setdefault("project_ids", [])
                if dataset["id"] in selected and chosen not in memberships:
                    memberships.append(chosen)
                elif dataset["id"] not in selected and chosen in memberships:
                    memberships.remove(chosen)
            if save():
                st.success("Project datasets updated.")
    included = [datasets[x] for x in project.get("dataset_ids", []) if x in datasets]
    if not included:
        st.info("Use Manage datasets to include existing datasets in this project.")
        return
    dataset_ids = {d["id"] for d in included}
    incidents = [i for i in workspace.get("incidents", []) if dataset_ids.intersection(i.get("dataset_ids", []))]
    st.subheader("Dataset comparison")
    rows = []
    for dataset in included:
        members = [i for i in incidents if dataset["id"] in i.get("dataset_ids", [])]
        rows.append({"Dataset": dataset["name"], "Incidents": len(members), "Sources": len(dataset.get("source_ids", [])), "Verified": sum(i.get("review_status") == "Verified" for i in members)})
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("An incident may appear in multiple datasets. Project exports include each incident once.")
    if incidents:
        st.subheader("Incident coverage")
        dimension = st.selectbox("Compare by", ["County", "State", "Year", "Review status"], key="proj_dimension")
        counts = {}
        for incident in incidents:
            label = str(incident.get({"County": "county", "State": "state", "Year": "date", "Review status": "review_status"}[dimension]) or "Unknown")
            if dimension == "Year" and label != "Unknown":
                label = label[:4]
            counts[label] = counts.get(label, 0) + 1
        st.bar_chart([{dimension: k, "Incidents": v} for k, v in sorted(counts.items())], x=dimension, y="Incidents", color="#16756A")
        output = io.StringIO()
        fields = sorted({field for incident in incidents for field in incident.get("fields", {})})
        headings = ["id", "title", "date", "county", "state", "review_status", "dataset_ids", "source_ids"] + [f"field:{f}" for f in fields]
        writer = csv.DictWriter(output, fieldnames=headings)
        writer.writeheader()
        def safe(value):
            value = "" if value is None else str(value)
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for incident in incidents:
            row = {k: safe(json.dumps(incident.get(k, [])) if k in ("dataset_ids", "source_ids") else incident.get(k, "")) for k in headings if not k.startswith("field:")}
            for field in fields:
                row[f"field:{field}"] = safe(incident.get("fields", {}).get(field, {}).get("value"))
            writer.writerow(row)
        st.download_button("Export project incidents · CSV", output.getvalue(), "project_incidents.csv", "text/csv", key="proj_export")
        st.caption("Export includes current review status and source IDs. Unverified records remain labeled.")
    else:
        st.write("No incident records are linked yet. Add incidents in Datasets to compare coverage and export records.")
    st.subheader("Ask your research")
    st.text_input("Research question", placeholder="How does verified coverage vary by county?", key="proj_question", disabled=True)
    st.caption("Natural-language analysis is not connected. Use the comparison and CSV export above to explore collected records.")
