"""Discovery preview and persistent workspace search."""
from datetime import datetime, timezone
from uuid import uuid4
import streamlit as st


def _now():
    return datetime.now(timezone.utc).isoformat()


def _preview(source):
    st.write(source.get("text") or source.get("snippet") or "No extracted text is available.")
    url = source.get("url", "")
    if url.startswith(("https://", "http://")):
        st.link_button("Open original source", url)


def render(workspace: dict, save):
    st.title("Search")
    st.caption("Discover sources, collect evidence, and revisit your research.")
    discovery, research = st.tabs(["Discovery", "Research"])
    with discovery:
        st.info("Preview mode · Search the fictional sample sources below. External discovery and extraction are not connected.")
        query = st.text_input("Search sample sources", placeholder="Keywords, place, or case details", key="search_discovery_query")
        c1, c2, c3 = st.columns([2, 1, 1])
        location = c1.text_input("Location", placeholder="Texas or county", key="search_location")
        start = c2.date_input("Published from", value=None, key="search_start")
        end = c3.date_input("Published through", value=None, key="search_end")
        if start and end and start > end:
            st.error("Choose an end date on or after the start date.")
            matches = []
        else:
            matches = []
            for source in workspace.get("sources", []):
                # Uploaded researcher documents belong to Research, not discovery fixtures.
                if source.get("publisher") == "Researcher upload":
                    continue
                corpus = " ".join(str(source.get(k, "")) for k in ("title", "snippet", "text", "publisher")).lower()
                published = source.get("published_at", "")[:10]
                if query and not all(word in corpus for word in query.lower().split()):
                    continue
                if location and location.lower() not in corpus:
                    continue
                if start and (not published or published < start.isoformat()):
                    continue
                if end and (not published or published > end.isoformat()):
                    continue
                matches.append(source)
        st.caption(f"{len(matches)} matching sample sources")
        selected = []
        for source in matches:
            with st.container(border=True):
                if st.checkbox(source["title"], key=f"search_pick_{source['id']}"):
                    selected.append(source)
                st.caption(f"{source.get('publisher', 'Unknown publisher')} · {source.get('published_at', '')[:10] or 'Date unknown'}")
                st.write(source.get("snippet", ""))
                with st.expander("Preview evidence"):
                    _preview(source)
        if not matches:
            st.write("No sources match these filters. Try fewer keywords or a wider date range.")
        st.subheader("Collect selected sources")
        datasets = workspace.get("datasets", [])
        lookup = {d["id"]: d for d in datasets}
        destination = st.selectbox("Save to dataset", ["new"] + list(lookup), format_func=lambda x: "Create a new dataset" if x == "new" else lookup[x]["name"], key="search_destination")
        name = st.text_input("New dataset name", key="search_dataset_name") if destination == "new" else ""
        if st.button("Collect sources", type="primary", disabled=not selected, key="search_collect"):
            if destination == "new" and not name.strip():
                st.error("Enter a name for the new dataset.")
            else:
                if destination == "new":
                    dataset = {"id": str(uuid4()), "name": name.strip(), "description": "", "project_ids": [], "incident_ids": [], "source_ids": [], "status": "Draft", "created_at": _now()}
                    workspace.setdefault("datasets", []).append(dataset)
                else:
                    dataset = lookup[destination]
                added = 0
                for source in selected:
                    if source["id"] not in dataset.setdefault("source_ids", []):
                        dataset["source_ids"].append(source["id"])
                        added += 1
                    if dataset["id"] not in source.setdefault("dataset_ids", []):
                        source["dataset_ids"].append(dataset["id"])
                workspace.setdefault("runs", []).append({"id": str(uuid4()), "dataset_id": dataset["id"], "kind": "sample_collection", "status": "Completed", "started_at": _now(), "source_count": added, "incident_count": 0, "detail": "Sample sources linked by researcher; no external search or extraction performed."})
                workspace.setdefault("usage_events", []).append({"id": str(uuid4()), "kind": "sample_collection", "at": _now(), "units": added, "cost_usd": None})
                if save():
                    st.session_state["workspace_notice"] = f"Collected {added} new sources in {dataset['name']}. Review them in Datasets or Library."
                    st.rerun()
    with research:
        query = st.text_input("Search collected research", placeholder="Incident title or evidence text", key="search_research_query")
        datasets = {d["id"]: d for d in workspace.get("datasets", [])}
        scope = st.selectbox("Dataset", ["all"] + list(datasets), format_func=lambda x: "All datasets" if x == "all" else datasets[x]["name"], key="search_research_scope")
        def matches(item, keys):
            corpus = " ".join(str(item.get(k, "")) for k in keys).lower()
            return (scope == "all" or scope in item.get("dataset_ids", [])) and all(w in corpus for w in query.lower().split())
        incidents = [i for i in workspace.get("incidents", []) if matches(i, ("title", "county", "state"))]
        sources = [s for s in workspace.get("sources", []) if matches(s, ("title", "text", "snippet"))]
        st.subheader(f"Incidents · {len(incidents)}")
        if incidents:
            st.dataframe([{ "Incident": i["title"], "Date": i.get("date"), "County": i.get("county"), "Review": i.get("review_status")} for i in incidents], hide_index=True, width="stretch")
            st.caption("Open Datasets → Incidents to inspect and correct a record.")
        else:
            st.write("No incidents match. Collect evidence and add incident records in Datasets.")
        st.subheader(f"Sources · {len(sources)}")
        for source in sources:
            with st.expander(source["title"]):
                st.caption(f"{source.get('publisher', '')} · {source.get('published_at', '')[:10]}")
                _preview(source)
        if not sources:
            st.write("No evidence matches this search. Try a broader query or upload a document in Library.")
