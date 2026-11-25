"""Databricks Apps entrypoint for the UI-first research workspace."""
import os
import uuid
from pathlib import Path

import streamlit as st

from research_app import cases, dataset, guide, search, usage
from research_app.repository import ConflictError, Repository
from research_app.theme import apply_theme

st.set_page_config(page_title="Homicide Research", page_icon=":material/library_books:", layout="wide", initial_sidebar_state="auto")
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
        st.session_state.local_identity = "local-" + str(uuid.uuid4())
    return st.session_state.local_identity


identity = user_identity()
repo = Repository(Path(os.environ.get("HR_DATA_DIR", "/tmp/homicide-research")) / "workspaces.sqlite3", identity)
st.session_state["research_user"] = identity
st.session_state["research_email"] = (st.context.headers.get("X-Forwarded-Email") or identity) if os.environ.get("HR_REQUIRE_PROXY_IDENTITY", "false").lower() == "true" else identity
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
            if key.startswith(("search_", "usage_")):
                del st.session_state[key]
        st.rerun()
    except (ValueError, OSError) as exc:
        st.session_state.workspace, st.session_state.revision = repo.load()
        st.error(f"The change could not be saved: {exc}")
        return False


with st.sidebar:
    st.title("Homicide Research")
    st.caption("Research workspace")
    page = st.radio("Workspace navigation", [
        "Search",
        "Cases",
        "Dataset",
        "Usage",
        "User Guide",
    ], label_visibility="collapsed", key="nav_page")
    from research_app.issue_ui import render as render_issue_form
    render_issue_form()
    st.divider()
    st.caption("Search → Cases → Dataset")

if st.session_state.get("workspace_notice"):
    st.success(st.session_state.pop("workspace_notice"))
if st.session_state.get("workspace_error"):
    st.error(st.session_state.pop("workspace_error"))

try:
    {
        "Search": search,
        "Cases": cases,
        "Dataset": dataset,
        "Usage": usage,
        "User Guide": guide,
    }[page].render(st.session_state.workspace, save)
except Exception as exc:
    from research_app.issue_reporting import capture_error
    capture_error(exc, page + ".render")
    st.error("This page could not finish. Use Submit issue in the sidebar to report it; your saved research is preserved.")
