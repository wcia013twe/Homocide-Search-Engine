"""Submit investigations and open their case workspace."""
import os
from research_app.investigation_tasks import database_configured
from uuid import uuid4

import streamlit as st
from research_app.issue_reporting import capture_error

from research_app import investigation_tasks
from research_app.hosted_session import scoped_session_id


def render(workspace: dict, save):
    if st.session_state.get('investigation_case_id'):
        from research_app.cases import open_case
        st.caption('For case: ' + st.session_state['investigation_case_title'])
        st.button('← Back to case', on_click=open_case, args=(st.session_state['investigation_case_id'],))
    st.title("Search")
    st.caption("Start an investigation. Follow progress and review evidence inside its case.")
    configured = database_configured() and all(os.environ.get(name) for name in (
        "HR_SEARCH_AUDIT_VOLUME", "HR_SEARCH_AUDIT_WAREHOUSE_ID", "HR_RESEARCH_MODEL_ENDPOINT"))
    if not configured:
        st.info("Live investigations are not connected. Ask the app administrator to check shared storage, search, and model access.")
    cases = []
    cases_available = True
    if configured and not st.session_state.get('investigation_case_id'):
        try:
            from research_app.collaboration import CaseStore
            cases = CaseStore(st.session_state['research_user']).list_cases()
        except Exception as issue_exc:
            capture_error(issue_exc, "search.render")
            cases_available = False
            st.warning('Existing cases are temporarily unavailable. Try again when access is restored.')
    st.session_state['search_case_options'] = [case['id'] for case in cases] if cases_available else []
    with st.form("investigation_search", border=False):
        if not st.session_state.get('investigation_case_id') and cases_available:
            labels = {'__new_case__': 'Create a new case', **{case['id']: case['title'] + ' · ' + case['gold_key'] for case in cases}}
            st.selectbox('Case', list(labels), index=None, placeholder='Choose a case', format_func=labels.get,
                         key='search_target_case', help='Choose the case that will contain this investigation and its evidence.')
        st.text_area("Investigation query", placeholder="Person's name, location, and any known incident details",
                             height=100, key="search_live_query",
                             help="Include a state or incident year when known. Results need source review.")
        st.form_submit_button("Submit investigation", type="primary", disabled=not configured or not cases_available,
                                         key="search_live_submit", on_click=_submit_investigation)


def _submit_investigation():
    if not st.session_state['search_live_query'].strip():
        st.session_state['workspace_error'] = 'Enter a name, location, or incident detail to investigate.'
        return
    actor = st.session_state['research_user']
    public_id = str(uuid4())
    task = {'id': public_id, 'key': scoped_session_id(public_id, actor), 'actor': actor,
            'query': st.session_state['search_live_query'].strip(),
            'submitted_by_email': st.session_state.get('research_email', actor)}
    target = st.session_state.get('investigation_case_id')
    if not target:
        choice = st.session_state.get('search_target_case')
        if choice == '__new_case__':
            target = None
        elif choice in st.session_state.get('search_case_options', []):
            target = choice
        else:
            st.session_state['workspace_error'] = 'Choose a case or create a new case before submitting.'
            return
    try:
        case_id = investigation_tasks.submit(task, target_case=target) if target else investigation_tasks.submit(task)
    except Exception as issue_exc:
        capture_error(issue_exc, "search._submit_investigation")
        st.session_state['workspace_error'] = 'Unable to submit investigation. Check backend configuration and logs.'
        return
    if case_id:
        from research_app.cases import open_case
        st.session_state.pop('investigation_case_id', None)
        st.session_state.pop('investigation_case_title', None)
        st.session_state.pop('search_target_case', None)
        st.session_state['case_investigation_' + case_id] = public_id
        st.session_state['workspace_notice'] = 'Investigation started. You can leave this page; research continues in the background.'
        open_case(case_id)
