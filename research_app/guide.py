"""Researcher instructions matched to the available scaffold workflows."""
import streamlit as st


def render(workspace: dict, save):
    st.title("User Guide")
    st.caption("Search the web and understand the limits of this early workspace.")
    st.info("Brave and Exa search are available when configured. explore-search can extract and save identifying leads with a configured model endpoint. Incident-loop handoff is not connected yet.")

    start, review, reference, backup = st.tabs([
        "Getting started", "Reviewing results", "Workspace reference", "Saving & access"
    ])
    with start:
        st.subheader("Your first search")
        st.markdown("""
1. Open **Search** and choose Brave or Exa.
2. Enter a focused query. Optionally add a state, county, and incident year, then select **Search web**. These filters add search terms; they do not guarantee matching locations or incident dates.
3. Read the returned title, excerpt, date, and source link. Search results are leads, not verified facts.
4. Check the audit message beneath the search form. A recorded search has a run ID; an unrecorded search cannot be reproduced from this workspace.
""")
        st.caption("Select **explore-search** to find and save identifying details from the returned excerpts. A single useful detail is enough. These provisional leads are saved in your workspace and snapshots; they are not verified incident records.")

    with review:
        st.subheader("Treat results as leads")
        st.markdown("Search snippets, dates, and titles can be incomplete or wrong. Open original sources and retain your own notes before making a research claim.")
        st.subheader("Use the audit trail")
        st.markdown("Configured searches write the provider request and response to the audit storage and show a run ID. The app does not yet support field-level coding or formal verification.")

    with reference:
        st.subheader("What is available")
        st.markdown("**Search** submits a query and displays provider results. **Usage** displays seeded fictional workspace metrics, not provider billing. **User Guide** explains the current scope and backup behavior.")
        st.subheader("What is not available")
        st.markdown("Dataset management, saved source libraries, document upload, coding, collaboration, and incident-loop handoff are not connected yet. Identifying-lead extraction is available through explore-search.")

    with backup:
        st.subheader("Save a workspace snapshot")
        st.markdown("Changes are stored separately for each signed-in user. They survive normal page reloads in Databricks, but app storage can be lost when compute is replaced or the app is redeployed. Durable cloud storage is not connected yet.")
        st.markdown("""
1. Expand **Workspace snapshots** in the sidebar.
2. Select **Download workspace** to save a JSON backup.
3. To restore it, upload the file under **Restore workspace snapshot**, then select **Restore snapshot**. The file must be smaller than 10 MB. Restoring replaces your current workspace, so download a backup first.
""")
        st.caption("Use the JSON workspace snapshot to restore the current workspace state.")
        st.subheader("Sign-in and troubleshooting")
        st.markdown("""
- **Cannot open the app:** Ask the account administrator to add your Databricks identity and grant **CAN USE** access to this app. Sign in with your own account and review any first-use authorization request.
- **No search results:** Try fewer or more specific keywords, or switch providers.
- **Search was not recorded:** Check the configured audit volume and SQL warehouse before relying on its results.
- **Workspace changed in another session:** The latest saved version is loaded. Review it before entering your change again.
- **Work is missing after a deployment:** Restore your downloaded JSON snapshot. Without a backup, temporary app storage may not be recoverable.
""")
