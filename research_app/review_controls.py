"""Queue existing LangGraph review decisions without executing in the UI."""
import streamlit as st

from research_app.investigation_tasks import enqueue, get_task


def render_review_controls(task, snapshot):
    pending = [item.value for item in snapshot.tasks for item in item.interrupts]
    if not pending:
        return
    actor = st.session_state['research_user']
    current = get_task(task['id'], actor)
    if current['status'] != 'awaiting_review':
        st.caption('Review command is queued or running. This view updates automatically.')
        return
    review = pending[0]
    st.subheader('Your next action')
    if review.get('stage') != 'final_coding':
        decision_key = task['id'] + '_' + str(review.get('search_run_id'))
        proposals = review.get('next_queries', [])
        index = st.selectbox('Proposed search', range(len(proposals)), format_func=lambda i: proposals[i]['query'],
                             key='proposal_' + decision_key) if proposals else None
        if index is not None:
            proposal = proposals[index]
            st.write('Research gap: ' + proposal.get('target_gap', 'Follow-up research'))
            st.write(proposal.get('reason', ''))
            for result in snapshot.values.get('results', []):
                if result.get('result_rank') in proposal.get('based_on_ranks', []):
                    st.caption(result.get('title') or result.get('url') or 'Supporting source')
                    st.write(result.get('snippet', ''))
        with st.container():
            action = st.selectbox('Action', ['Continue with proposed search', 'Stop collection'],
                                  key='search_action_' + decision_key) if proposals else 'Stop collection'
            reason = st.text_area('Decision reason', key='search_reason_' + decision_key)
            if st.button('Save search decision', key='search_decision_' + decision_key):
                if not reason.strip():
                    st.warning('Enter a decision reason.')
                else:
                    payload = {'search_run_id': review['search_run_id'], 'action': 'search' if action == 'Continue with proposed search' else 'stop', 'reason': reason}
                    if payload['action'] == 'search':
                        payload['query_index'] = index
                    enqueue(task['id'], actor, 'resume', payload, expected_revision=current['revision'])
                    st.session_state['workspace_notice'] = 'Search decision queued.'
                    st.rerun()
        return
    st.caption('This investigation paused under the previous coding workflow. Complete it to make the saved AI findings available for case Review. This does not approve the case.')
    if st.button('Complete investigation', key='complete_investigation_' + task['id']):
        enqueue(task['id'], actor, 'finalize',
                {'search_run_id': review['search_run_id'], 'action': 'case_review'},
                expected_revision=current['revision'])
        st.session_state['workspace_notice'] = 'Investigation completion queued. Resolve field choices in case Review.'
        st.rerun()
