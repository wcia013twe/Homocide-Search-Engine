"""The investigation workspace inside a case."""
import streamlit as st

from research_app.issue_reporting import capture_error
from research_app.evidence_groups import state_evidence
from research_app.evidence_view import render_fields
from research_app.investigation_progress import render_activity


def render_live(task, case_id=None):
    """The case fragment owns polling, so forms have one stable render scope."""
    st.session_state['issue_active_investigation'] = task['id']
    from research_app.hosted_session import open_hosted_session, scoped_session_id
    from research_app.issue_reporting import observe_task_status
    try:
        from research_app.investigation_tasks import get_task, get_case_task
        if task['status'] != 'saved':
            task = get_case_task(task['id'], case_id) if case_id else get_task(task['id'], st.session_state['research_user'])
        observe_task_status(task)
        st.subheader(task['query'])
        render_activity(task, compact=True)
        if task['status'] in ('failed', 'interrupted'):
            from research_app.issue_reporting import sanitize
            st.session_state['issue_last_error'] = {
                'operation': 'Investigation failed', 'error_type': 'InvestigationFailure',
                'message': sanitize(task.get('error') or task['status']),
                'investigation_id': task['id'], 'frames': [],
            }
            st.error(task.get('error') or 'Research stopped unexpectedly. Saved evidence is preserved. Use Submit issue to report this investigation.')
        elif task['status'] == 'queued':
            return
        elif task['status'] == 'saved':
            st.info('Saved findings are available in the case Review and Sources tabs.')
            return
        key = scoped_session_id(task['id'], task['actor'])
        with open_hosted_session(key, read_only=True) as session:
            snapshot = session.inspect(key, task['actor'])
    except ValueError:
        st.caption('Preparing the first saved checkpoint. Progress updates automatically.')
        return
    except Exception as exc:
        capture_error(exc, 'investigation_detail.render_live')
        st.error('Investigation details are temporarily unavailable. Saved research is preserved. Reload this view to try again.')
        return
    from research_app.evidence_registry import annotate_state
    try:
        state = annotate_state(task['id'], snapshot.values)
    except Exception as exc:
        capture_error(exc, 'investigation_detail.render_live')
        st.error('Saved evidence references are temporarily unavailable. Reload this view to try again.')
        return
    pending = [item.value for item in snapshot.tasks for item in item.interrupts]
    if task['status'] == 'awaiting_review' and pending:
        st.info('This older investigation can be completed without individual field decisions.' if pending[0].get('stage') == 'final_coding'
                else 'Your input is needed to choose the next research step.')
        if task['actor'] == st.session_state['research_user']:
            from research_app.review_controls import render_review_controls
            render_review_controls(task, snapshot)
        else:
            st.caption('The investigation owner can submit this decision. You can inspect the saved findings below.')
    elif task['status'] == 'finished':
        st.success('Research pass finished. Review the combined findings in the case Review tab before approving the case.')
    if state.get('stop_reason') and task['status'] not in ('running', 'queued'):
        st.write(state['stop_reason'])
    st.subheader('Findings so far')
    st.caption('Provisional findings from this investigation. Case approval happens in the Review tab.')
    fields, sources = state_evidence(state)
    render_fields(fields, sources, mode='live', key='investigation_' + task['id'], compact=True)
    if state.get('gaps'):
        with st.expander('Missing or conflicting information', expanded=True):
            for gap in state['gaps']:
                st.write(gap['field'].replace('_', ' ') + ': ' + gap['reason'])
    st.subheader('Research activity')
    history = state.get('search_history', [])
    if not history:
        st.caption('No completed searches have been saved yet.')
    # Search records have no timestamps; attach decisions by run ID rather than inventing times.
    for index, search in enumerate(history, 1):
        with st.expander(f"Search {index}: {search['query']}", expanded=index == len(history)):
            st.caption('Search completed · ' + search.get('provider', state.get('provider', '')))
            if search.get('search_run_id'):
                captured = [source for source in sources.values()
                            if source.get('search_run_id') == search['search_run_id']]
                st.caption(f'{len(captured)} saved source captures linked to this search')
                for source in captured:
                    st.write(source.get('title') or source.get('url') or 'Saved source')
            for event in state.get('review_history', []):
                if search.get('search_run_id') and event.get('search_run_id') == search['search_run_id']:
                    proposal = event.get('selected_proposal', {})
                    st.write('Continue: ' + proposal['query'] if proposal else 'Stop collection')
                    st.write(event.get('reason', ''))
            if search.get('search_run_id'):
                with st.expander('Technical details'):
                    st.code(search['search_run_id'])
    with st.expander(f'Saved sources ({len(sources)})'):
        for source_id, source in sources.items():
            st.write(source.get('title') or source.get('url') or 'Saved source')
            if source.get('url', '').startswith(('https://', 'http://')):
                st.link_button('Open source', source['url'], key='source_' + task['id'] + source_id)
            st.caption(source.get('evidence_kind', 'Saved evidence').replace('_', ' ').capitalize())
            st.text(source.get('text') or source.get('snippet') or 'No saved text is available.')
    with st.expander('Investigation details'):
        st.text('Investigation ' + task['id'])
        from research_app.investigation_progress import timing_text
        st.caption(timing_text(task))
