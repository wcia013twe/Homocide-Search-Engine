"""Activity and coverage from recorded workspace state."""
import streamlit as st


def render(workspace: dict, save):
    st.title("Usage")
    st.caption("Recorded workspace activity and verification coverage.")
    events = workspace.get("usage_events", [])
    runs = workspace.get("runs", [])
    incidents = workspace.get("incidents", [])
    sources = workspace.get("sources", [])
    st.subheader("Research coverage")
    verified = sum(i.get("review_status") == "Verified" for i in incidents)
    fields = [f for incident in incidents for f in incident.get("fields", {}).values()]
    evidenced = sum(bool(f.get("evidence_ids")) for f in fields)
    st.dataframe([
        {"Measure": "Incident records", "Coverage": str(len(incidents))},
        {"Measure": "Verified incidents", "Coverage": f"{verified} of {len(incidents)}"},
        {"Measure": "Collected source records", "Coverage": str(len(sources))},
        {"Measure": "Sources linked to incidents", "Coverage": f"{sum(bool(s.get('incident_ids')) for s in sources)} of {len(sources)}"},
        {"Measure": "Fields with evidence links", "Coverage": f"{evidenced} of {len(fields)}"},
    ], hide_index=True, width="stretch")
    st.caption("Counts reflect this workspace, including labeled sample records. They do not measure completeness against all homicides in a region.")
    st.subheader("Activity and costs")
    if events:
        groups = {}
        for event in events:
            group = groups.setdefault(event.get("kind", "unknown"), {"Activity": event.get("kind", "unknown").replace("_", " ").title(), "Events": 0, "Units": 0, "metered": [], "unmetered": 0})
            group["Events"] += 1
            group["Units"] += event.get("units", 0)
            if event.get("cost_usd") is None:
                group["unmetered"] += 1
            else:
                group["metered"].append(event["cost_usd"])
        rows = []
        for group in groups.values():
            cost = f"${sum(group['metered']):.4f}" if group["metered"] else "Unavailable"
            if group["metered"] and group["unmetered"]:
                cost += " (partial)"
            rows.append({k: group[k] for k in ("Activity", "Events", "Units")} | {"Recorded cost": cost})
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.write("No usage events have been recorded. Collection and uploads will appear here.")
    st.caption("Provider billing is not connected. Unmetered activity has no recorded cost; it is not reported as free.")
    st.subheader("Processing history")
    if runs:
        status_options = sorted({r.get("status", "unknown") for r in runs})
        status = st.selectbox("Run status", ["All statuses"] + status_options, key="usage_status")
        datasets = {d["id"]: d["name"] for d in workspace.get("datasets", [])}
        filtered = [r for r in runs if status == "All statuses" or r.get("status") == status]
        st.dataframe([{ "Started": r.get("started_at", ""), "Dataset": datasets.get(r.get("dataset_id"), "Unknown dataset"), "Activity": r.get("kind", "").replace("_", " "), "Status": r.get("status"), "Sources": r.get("source_count", 0), "Incidents": r.get("incident_count", 0), "Details": r.get("detail", "")} for r in sorted(filtered, key=lambda r: r.get("started_at", ""), reverse=True)], hide_index=True, width="stretch")
    else:
        st.write("No processing runs yet. Collect sample sources from Search to record your first collection.")
