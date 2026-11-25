"""Researcher instructions for the shared investigation and case workflows."""
import streamlit as st


def render(workspace: dict, save):
    st.title('User Guide')
    st.caption('From an investigation to an approved dataset record.')
    st.markdown('Use **Search** to gather evidence, **Cases** to review it with your team, and **Dataset** to inspect published records and their sources.')
    start, review, dataset, backup = st.tabs([
        'Search', 'Cases', 'Dataset', 'Saving'
    ])
    with start:
        st.subheader('Start an investigation')
        st.markdown('''
1. Open **Search**. Choose a case or create a new one, enter identifying incident details, then select **Submit investigation**.
2. The case opens with the new investigation selected. Research continues in the background when you leave the page.
3. Follow the investigation's activity, AI-coded findings, and saved evidence. Field labels distinguish **Supported**, **Conflicting**, and **Missing or unclear** evidence.
4. If research pauses for a search decision, choose the next search or stop collection and explain why. AI coding finishes without a separate researcher coding pass. Older coding pauses offer **Complete investigation** to retain their findings for case Review.
5. In the case **Review** tab, choose among findings from all investigations, resolve conflicting values, and approve the final coding for Dataset.
''')
        st.caption('Search results and extracted claims need review. Open the original sources and compare supporting passages before accepting a finding.')
    with review:
        st.subheader('Bring findings into a shared case')
        st.markdown('''
1. Open **Cases** and select a case from the library. Filter **Case status** to **Open** or **Closed**. Closed cases have an approved current revision, appear grey, and remain openable.
2. **Investigations** lists all team runs, with running work first. Select **New investigation** to add research to this case.
3. In **Review**, compare findings across investigations, select conflicting values, and mark missing fields with their evidence status and checked sources.
4. Enter a review reason and select **Approve & add to Dataset**. The complete review saves atomically and queues the Dataset update. This is the only case approval action.
5. **Sources** lists deduplicated documents and retains their saved captures. Use **Retry Dataset update** if an approved update needs another attempt.
''')
        st.caption('Contributions preserve original findings and advance the case revision. New contributions need a new approval. A stale draft must be reviewed again against the current revision.')
        st.subheader('Read evidence status')
        st.markdown('**Reported** records a supported value. **Not Reported** and **Unclear** publish a blank value; checked sources and the decision reason explain why. Uncoded fields remain available under **Uncoded fields**.')
    with dataset:
        st.subheader('Find a record and inspect its origin')
        st.markdown('''
- Use **Look up records** to search recorded values across the dataset. Open **Filters** to choose a state or incident year.
- Browse the matching records by page. Choose **Inspect record** to see its table and record identifier, then open its source and approval history.
- Select the pencil **Edit case** beside the chosen record to open its case **Review** with saved choices. Approving changes updates the same record. New findings or edits require a new approval before the case is Closed again.
- Select **Refresh dataset** after a publication or when you need the latest records. Browsing results are reused for up to 30 seconds between interactions.
''')
        st.caption('State uses the recorded location suffix; year uses the incident date. Missing locations and dates appear under All states and All years. A row without a matching published approval has no confirmed source history in this app.')
        st.subheader('Understand Usage')
        st.write('Usage shows your live investigations, known provider costs, and success rate. Choose the search provider and model endpoint for new investigations. Exa search costs are estimates. Model estimates use recorded tokens and the endpoint prices you enter; missing token counts or prices can make estimates unavailable or partial.')
    with backup:
        st.subheader('Your research is saved')
        st.write('Saved investigations, evidence, cases, and approvals are available when you return. Published records appear in Dataset.')
        st.subheader('Access and troubleshooting')
        st.markdown('''
- **Cannot open the app:** Ask the administrator to grant your Databricks identity access, then sign in with your own account.
- **Investigation remains queued:** A worker may be starting or busy. Progress updates automatically; check with the administrator if it does not advance.
- **Shared data is unavailable:** Ask the administrator to check shared database and warehouse access, then reload the page.
- **A case changed while you were editing:** Review the latest revision before submitting your contribution again.
- **A new publication is missing:** Check its status in Cases, then select **Refresh dataset** after it is published.
''')
