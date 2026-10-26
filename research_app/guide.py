"""Researcher instructions matched to the available scaffold workflows."""
import streamlit as st


def render(workspace: dict, save):
    st.title("User Guide")
    st.caption("Collect evidence, build incident records, and document your research decisions.")
    st.info("This is a working UI preview with fictional sample records. External search, automated extraction, and AI analysis are not connected yet.")

    start, review, reference, backup = st.tabs([
        "Getting started", "Reviewing evidence", "Workspace reference", "Saving & access"
    ])
    with start:
        st.subheader("Your first research workflow")
        st.markdown("""
1. **Find evidence in Search → Discovery.** Enter keywords or a location, and optionally limit publication dates. Select the source checkboxes and open **Preview evidence** to read the text. Discovery currently searches sample sources only.
2. **Collect sources into a dataset.** Below the results, choose an existing dataset or enter a new dataset name, then select **Collect sources**. This links evidence to the dataset; it does not automatically create incident records.
3. **Add an incident in Datasets → Incidents.** Select your dataset and expand **Add an incident**. Enter the case details and select its supporting sources. New records start as **Needs review**.
4. **Code and review the incident.** Choose a record under **Open incident**, compare its fields with the source preview, and save your review with a reason. The next tab in this guide explains the evidence statuses.
5. **Check and export your work.** Use **Evaluation** to find incomplete or uncertain records. Export incident data from **Incidents**, or compare datasets in **Projects**.
""")
        st.subheader("Bring your own evidence")
        st.markdown("In **Library → Upload a document**, choose a UTF-8 `.txt` or `.md` file up to **2 MB**, then select **Add to library**. Preview the uploaded source and use **Link to dataset → Link source** to attach it to a collection. PDF and web-page extraction are not available yet.")
        st.caption("Use Search → Research to revisit incident details and evidence text already in your workspace.")

    with review:
        st.subheader("Keep each field connected to evidence")
        st.markdown("Open **Datasets → Incidents → Open incident**. Read the source beside the coding form. For each variable, follow its definition, enter a value when supported, and select the relevant **Supporting sources**.")
        st.markdown("""
- **Reported:** The source supports a value. Enter the value and cite at least one supporting source.
- **Not Reported:** The reviewed evidence does not provide the value. Leave the value blank; missing information does not mean a negative answer.
- **Unclear:** The evidence is ambiguous or conflicting. Leave the value blank and keep the incident under review.
""")
        st.subheader("Save a defensible review")
        st.markdown("Select the **Incident review status**, write a **Reason for changes**, and select **Save review**. Prior values and review details remain available under **Review history**. Check for a success message before leaving the page.")
        st.markdown("To mark an incident **Verified**, every codebook variable must be coded, no field can remain **Unclear**, and each field needs supporting sources—including fields marked **Not Reported**. Cite the sources you checked for missing information.")
        st.caption("Codebook changes can return verified incidents to Needs review. Recheck affected records in Evaluation after changing variable definitions.")

    with reference:
        st.subheader("Where to find your work")
        st.markdown("Projects group datasets. Datasets collect incidents and sources. Incidents contain coded variable values supported by sources. A source can be reused across collections.")
        with st.expander("Search and Library", expanded=True):
            st.markdown("**Search → Discovery** filters sample evidence and collects it into datasets. **Search → Research** searches workspace records. **Library** holds source text, uploads, and links to the datasets and incidents that reference it.")
        with st.expander("Dataset tabs"):
            st.markdown("""
- **Overview:** Counts, research progress, and recent activity.
- **Incidents:** Filter and sort records, add cases, review fields with evidence, and export CSV.
- **Sources:** Read the evidence linked to the selected dataset.
- **Variables:** Define research fields, data types, allowed values, and coding definitions. The scaffold uses a workspace-wide codebook.
- **Runs:** Inspect collection history. Sample collection entries do not represent external search or extraction.
- **Evaluation:** Find missing information, uncertain fields, and records needing review.
- **Settings:** Update the dataset's configuration. Team sharing is not connected yet.
""")
        with st.expander("Projects and Usage"):
            st.markdown("**Projects** groups datasets around a research question, compares incident coverage, and exports combined records. Natural-language AI analysis is not connected. **Usage** shows recorded activity; costs are unmetered rather than a live Databricks bill.")

    with backup:
        st.subheader("Save a workspace snapshot")
        st.markdown("Changes are stored separately for each signed-in user. They survive normal page reloads in Databricks, but app storage can be lost when compute is replaced or the app is redeployed. Shared team datasets and durable cloud storage are not connected yet.")
        st.markdown("""
1. Expand **Workspace snapshots** in the sidebar.
2. Select **Download workspace** to save a JSON backup containing your workspace records and source text.
3. To restore it, upload the file under **Restore workspace snapshot**, then select **Restore snapshot**. The file must be smaller than 10 MB. Restoring replaces your current workspace, so download a backup first.
""")
        st.caption("CSV exports are for analysis. Use the JSON workspace snapshot to restore your work. Reset preview replaces your workspace with sample records.")
        st.subheader("Sign-in and troubleshooting")
        st.markdown("""
- **Cannot open the app:** Ask the account administrator to add your Databricks identity and grant **CAN USE** access to this app. Sign in with your own account and review any first-use authorization request.
- **No search results:** Clear keywords or widen the date range. Sources without a publication date are excluded by date filters.
- **Review will not save:** Check the displayed error, required reason, variable type or allowed values, and supporting sources.
- **Workspace changed in another session:** The latest saved version is loaded. Review it before entering your change again.
- **Work is missing after a deployment:** Restore your downloaded JSON snapshot. Without a backup, temporary app storage may not be recoverable.
""")
