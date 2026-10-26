"""Databricks Apps entrypoint for the UI-first research workspace."""
import json
import os
import uuid
from pathlib import Path

import streamlit as st

from research_app import datasets, guide, library, projects, search, usage
from research_app.repository import ConflictError, Repository
from research_app.theme import apply_theme

st.set_page_config(page_title="Homicide Research", page_icon=":material/library_books:", layout="wide")
apply_theme()


def user_identity():
    """Trust the header only when hosted behind the Databricks Apps proxy."""
    if os.environ.get("HR_REQUIRE_PROXY_IDENTITY", "false").lower() == "true":
        headers = st.context.headers
        identity = headers.get("X-Forwarded-User") or headers.get("X-Forwarded-Email")
        if not identity:
            st.error("Your workspace identity could not be verified. Open this app through Databricks and sign in again.")
            st.stop()
        return identity
    if "local_identity" not in st.session_state:
        st.session_state.local_identity = "local-preview-" + str(uuid.uuid4())
    return st.session_state.local_identity


identity = user_identity()
repo = Repository(Path(os.environ.get("HR_DATA_DIR", "/tmp/homicide-research")) / "workspaces.sqlite3", identity)
st.session_state["research_user"] = identity
if st.session_state.get("workspace_owner") != identity:
    st.session_state.workspace, st.session_state.revision = repo.load()
    st.session_state.workspace_owner = identity


def save():
    try:
        st.session_state.revision = repo.save(st.session_state.workspace, st.session_state.revision)
        return True
    except ConflictError:
        st.session_state.workspace, st.session_state.revision = repo.load()
        st.session_state.workspace_error = "This workspace changed in another session. The latest saved version is loaded. Review it before making your change again."
        for key in list(st.session_state):
            if key.startswith(("ds_", "search_", "lib_", "proj_", "usage_")):
                del st.session_state[key]
        st.rerun()
    except (ValueError, OSError) as exc:
        st.session_state.workspace, st.session_state.revision = repo.load()
        st.error(f"The change could not be saved: {exc}")
        return False


with st.sidebar:
    st.title("Homicide Research")
    st.caption("Research workspace")
    page = st.radio("Workspace navigation", ["Search", "Datasets", "Library", "Projects", "Usage", "User Guide"], label_visibility="collapsed", key="nav_page")
    st.divider()
    st.caption("UI preview · fictional sample records")
    st.caption("Search, extraction, and AI analysis services are not connected yet.")
    with st.expander("Workspace snapshots"):
        st.caption("Changes survive page reloads in Databricks. Download a snapshot before redeploying; hosted durable storage is not connected yet.")
        st.download_button("Download workspace", json.dumps(st.session_state.workspace, indent=2, ensure_ascii=False), "research-workspace.json", "application/json", use_container_width=True)
        incoming = st.file_uploader("Restore workspace snapshot", type=["json"], key="snapshot_upload")
        if incoming and st.button("Restore snapshot", use_container_width=True):
            try:
                if incoming.size > 10 * 1024 * 1024:
                    raise ValueError("Snapshot must be smaller than 10 MB.")
                payload = json.loads(incoming.getvalue())
                revision = repo.save(payload, st.session_state.revision)
                st.session_state.workspace = payload
                st.session_state.revision = revision
                st.rerun()
            except (ValueError, TypeError, ConflictError) as exc:
                st.error(f"Snapshot could not be restored: {exc}")
        confirm_reset = st.checkbox("Replace my preview with sample records", key="confirm_reset")
        if st.button("Reset preview", disabled=not confirm_reset, use_container_width=True):
            try:
                repo.reset(st.session_state.revision)
                st.session_state.workspace, st.session_state.revision = repo.load()
                for key in list(st.session_state):
                    if key.startswith(("ds_", "search_", "lib_", "proj_", "usage_")):
                        del st.session_state[key]
                st.rerun()
            except ConflictError:
                st.error("Another session changed this workspace. Reload before resetting.")

if st.session_state.get("workspace_notice"):
    st.success(st.session_state.pop("workspace_notice"))
if st.session_state.get("workspace_error"):
    st.error(st.session_state.pop("workspace_error"))

{"Search": search, "Datasets": datasets, "Library": library, "Projects": projects, "Usage": usage, "User Guide": guide}[page].render(st.session_state.workspace, save)
