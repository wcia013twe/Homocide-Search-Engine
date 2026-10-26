"""Evidence repository and plain-text import."""
from datetime import datetime, timezone
from uuid import uuid4
import streamlit as st


def uploaded_source(data: bytes, filename: str, title: str = "") -> dict:
    """Validate supported upload bytes before producing a source record."""
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("This file is larger than 2 MB. Upload a smaller text document.")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The file is not UTF-8 text. Save it with UTF-8 encoding and try again.") from exc
    if not content.strip():
        raise ValueError("This document is empty. Choose a file containing evidence text.")
    return {"id": str(uuid4()), "title": title.strip() or filename, "publisher": "Researcher upload", "published_at": "", "url": "", "kind": "Uploaded document", "text": content, "snippet": content[:240], "processing_status": "Text available", "incident_ids": [], "dataset_ids": []}


def render(workspace: dict, save):
    st.title("Library")
    st.caption("Original evidence, shared across your datasets and incidents.")
    with st.expander("Upload a document"):
        st.caption("Upload UTF-8 text or Markdown, up to 2 MB. PDF and web extraction are not connected in this scaffold.")
        with st.form("lib_upload_form"):
            upload = st.file_uploader("Document", type=["txt", "md"], key="lib_upload")
            title = st.text_input("Document title (optional)", key="lib_upload_title")
            submitted = st.form_submit_button("Add to library")
        if submitted:
            if not upload:
                st.error("Choose a text or Markdown file first.")
            else:
                try:
                    source = uploaded_source(upload.getvalue(), upload.name, title)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    workspace.setdefault("sources", []).append(source)
                    workspace.setdefault("usage_events", []).append({"id": str(uuid4()), "kind": "document_upload", "at": datetime.now(timezone.utc).isoformat(), "units": 1, "cost_usd": None})
                    if save():
                        st.success("Document added. Link it to a dataset through the controls below.")
    query = st.text_input("Find evidence", placeholder="Search titles, publishers, or text", key="lib_query")
    c1, c2, c3 = st.columns(3)
    source_kinds = sorted({s.get("kind", "unknown") for s in workspace.get("sources", [])})
    kind = c1.selectbox("Source type", ["All types"] + source_kinds, key="lib_kind")
    start = c2.date_input("Published from", value=None, key="lib_from")
    end = c3.date_input("Published through", value=None, key="lib_through")
    incidents = {i["id"]: i for i in workspace.get("incidents", [])}
    incident_scope = st.selectbox("Linked incident", ["all", "unlinked"] + list(incidents), format_func=lambda x: "All incidents" if x == "all" else "Unlinked sources" if x == "unlinked" else incidents[x]["title"], key="lib_incident_filter")
    sources = []
    for s in workspace.get("sources", []):
        corpus = " ".join(str(s.get(k, "")) for k in ("title", "publisher", "text")).lower()
        date = s.get("published_at", "")[:10]
        if not all(w in corpus for w in query.lower().split()) or (kind != "All types" and s.get("kind") != kind):
            continue
        if (start and (not date or date < start.isoformat())) or (end and (not date or date > end.isoformat())):
            continue
        if incident_scope == "unlinked" and s.get("incident_ids"):
            continue
        if incident_scope not in ("all", "unlinked") and incident_scope not in s.get("incident_ids", []):
            continue
        sources.append(s)
    if not sources:
        st.info("No sources match. Clear filters or upload a document to begin.")
        return
    st.dataframe([{ "Title": s["title"], "Publisher": s.get("publisher"), "Published": s.get("published_at", "")[:10] or "Unknown", "Type": s.get("kind"), "Status": s.get("processing_status"), "Incidents": len(s.get("incident_ids", []))} for s in sources], hide_index=True, width="stretch")
    by_id = {s["id"]: s for s in sources}
    chosen = st.selectbox("Preview source", list(by_id), format_func=lambda x: by_id[x]["title"], key="lib_preview")
    source = by_id[chosen]
    content, links = st.columns([2, 1])
    with content:
        st.subheader(source["title"])
        st.caption(f"{source.get('publisher', '')} · {source.get('published_at', '')[:10] or 'Publication date unknown'}")
        if source.get("url", "").startswith(("https://", "http://")):
            st.link_button("Open original", source["url"])
        st.text_area("Document text", source.get("text") or source.get("snippet", ""), height=380, disabled=True, key=f"lib_text_{chosen}")
    with links:
        st.subheader("References")
        datasets = {d["id"]: d for d in workspace.get("datasets", [])}
        linked = [datasets[x]["name"] for x in source.get("dataset_ids", []) if x in datasets]
        st.write("Datasets: " + (", ".join(linked) or "Not linked"))
        linked_incidents = [incidents[x]["title"] for x in source.get("incident_ids", []) if x in incidents]
        st.write("Incidents: " + (", ".join(linked_incidents) or "Not linked"))
        if datasets:
            dest = st.selectbox("Link to dataset", list(datasets), format_func=lambda x: datasets[x]["name"], key=f"lib_dataset_{chosen}")
            if st.button("Link source", key=f"lib_link_{chosen}"):
                if dest not in source.setdefault("dataset_ids", []):
                    source["dataset_ids"].append(dest)
                if chosen not in datasets[dest].setdefault("source_ids", []):
                    datasets[dest]["source_ids"].append(chosen)
                if save():
                    st.session_state["workspace_notice"] = "Source linked to dataset."
                    st.rerun()
