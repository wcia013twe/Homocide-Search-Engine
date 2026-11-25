"""Case library and the shared Investigations, Review, and Sources workspace."""
from html import escape

import streamlit as st
from research_app.issue_reporting import capture_error

from research_app.collaboration import CaseStore
from research_app.investigation_progress import submitted_text
from research_app.evidence_groups import case_evidence, deduplicate_sources
from research_app.evidence_view import render_fields
from research_app.investigation_tasks import database_configured, list_case_tasks
from research_app.repository import ConflictError


def open_case(case_id, tab='Investigations'):
    st.session_state['case_to_open'] = case_id
    st.session_state['case_tab_to_open'] = tab
    st.session_state['nav_page'] = 'Cases'


def _start_investigation(case=None):
    st.session_state.pop('selected_investigation', None)
    st.session_state['investigation_case_id'] = case['id'] if case else None
    st.session_state['investigation_case_title'] = case['title'] if case else None
    st.session_state['search_target_case'] = None if case else '__new_case__'
    st.session_state['search_live_query'] = ''
    st.session_state['nav_page'] = 'Search'


def render(workspace, save):
    if not database_configured():
        st.title('Cases')
        st.info('Connect shared case storage to view team investigations and save reviews.')
        return
    store = CaseStore(st.session_state['research_user'])
    try:
        _render(store)
    except ConflictError as exc:
        st.warning(str(exc))
    except ValueError as exc:
        st.error(str(exc))
    except Exception as issue_exc:
        capture_error(issue_exc, "cases.render")
        st.error('Cases are temporarily unavailable. Check shared storage, then reload.')


def _render(store):
    # A direct case route takes precedence over library filters.
    requested = st.session_state.pop('case_to_open', None)
    if requested:
        st.session_state['case_workspace_id'] = requested
        st.session_state['case_tabs_' + requested] = st.session_state.pop('case_tab_to_open', 'Investigations')
    selected = st.session_state.get('case_workspace_id')
    if selected:
        _detail(store, store.get(selected))
    else:
        _library(store)


def _library(store):
    heading, action = st.columns([4, 1], vertical_alignment='center')
    heading.title('Cases')
    action.button('New case', icon=':material/add:', on_click=_start_investigation, width='stretch')
    st.caption('Organize research, investigations, and Dataset contributions.')
    metrics = st.columns(3)
    scope, search, status = st.columns([1, 3, 1])
    mine = scope.selectbox('Show', ['All team cases', 'My cases']) == 'My cases'
    term = search.text_input('Search cases', placeholder='Case title or identifier').strip().casefold()
    status_filter = status.selectbox('Case status', ['All statuses', 'Open', 'Closed'], key='case_status',
                                    help='Closed means the current revision is approved. New findings or changes require review again.')
    st.markdown('<style>[class*="st-key-approved_case_"] {background-color:#F5F7F8}</style>', unsafe_allow_html=True)
    cases = store.list_cases(mine)
    approved = lambda case: case.get('approved_revision') == case['revision']
    metrics[0].metric('Total cases', len(cases))
    metrics[1].metric('Open cases', sum(not approved(case) for case in cases))
    metrics[2].metric('Investigations', sum(case['investigations'] for case in cases))
    visible = [case for case in cases if (not term or term in (case['title'] + ' ' + case['gold_key']).casefold())
               and (status_filter == 'All statuses' or approved(case) == (status_filter == 'Closed'))]
    if not visible:
        st.info('No matching cases.' if cases else 'No cases yet. Start a new case with its first investigation.')
    for case in visible:
        is_approved = approved(case)
        with st.container(border=True, key=('approved_case_' if is_approved else 'case_card_') + case['id']):
            title, action = st.columns([4, 1], vertical_alignment='center')
            if is_approved:
                title.markdown('<h3 style="color:#586671">' + escape(case['title']) + '</h3>', unsafe_allow_html=True)
            else:
                title.subheader(case['title'])
            action.button('Open case →', key='open_case_' + case['id'], on_click=open_case, args=(case['id'],), width='stretch')
            st.caption(case['gold_key'])
            reviewed = len(set(case['fields']) - {'case_id'})
            st.caption(f"{case['investigations']} investigations · {reviewed} reviewed fields · " + ('Closed' if is_approved else 'Open · Needs review'))


def _back_to_library():
    st.session_state.pop('case_workspace_id', None)


def _detail(store, case):
    st.title(case['title'])
    back, action = st.columns([4, 1], vertical_alignment='center')
    back.button('← Case library', on_click=_back_to_library)
    action.button('New investigation', on_click=_start_investigation, args=(case,), width='stretch')
    st.caption(f"Case {case['gold_key']} · Revision {case['revision']}")
    latest = case['publications'][0] if case['publications'] else None
    is_approved = bool(latest and latest['revision'] == case['revision'])
    st.caption('Closed · Current revision approved' if is_approved else 'Open · Needs review')
    tabs = st.tabs(['Investigations', 'Review', 'Sources'], key='case_tabs_' + case['id'], on_change='rerun')
    with tabs[0]:
        _investigations(case, active=tabs[0].open)
    # Keep the form mounted across tabs so unsaved choices survive navigation.
    fields, sources = case_evidence(case['investigations'], case['fields'])
    fields.setdefault('case_id', {}).update(value=case['gold_key'], status='Case identifier')
    with tabs[1]:
        _review(store, case, fields, sources, latest)
    with tabs[2]:
        _sources(sources)


def _investigations(case, active):
    tasks = list_case_tasks(case['id'])
    key = 'case_investigation_' + case['id']
    selected = next((task for task in tasks if task['id'] == st.session_state.get(key)), None)
    selected = selected or (tasks[0] if tasks else None)
    polling = bool(active and selected and selected['status'] in ('queued', 'running'))

    @st.fragment(run_every='2s' if polling else None)
    def content():
        tasks = list_case_tasks(case['id'])
        st.caption(f"{len(tasks)} team investigation{'s' if len(tasks) != 1 else ''}")
        if not tasks:
            st.info('No investigations yet. Start an investigation for this case.')
            return
        key = 'case_investigation_' + case['id']
        by_id = {task['id']: task for task in tasks}
        if st.session_state.get(key) not in by_id:
            st.session_state[key] = tasks[0]['id']
        selected = st.selectbox('Investigation', list(by_id), key=key,
            format_func=lambda task_id: by_id[task_id]['query'] + ' · ' + submitted_text(by_id[task_id])
                + ' · ' + by_id[task_id]['status'].replace('_', ' ').capitalize())
        if st.button('Refresh investigation', key='refresh_investigation_' + case['id']):
            st.rerun()
        needs_polling = bool(active and by_id[selected]['status'] in ('queued', 'running'))
        if polling != needs_polling:
            st.rerun()
        if active:
            from research_app.investigation_detail import render_live
            render_live(by_id[selected], case_id=case['id'])
    content()


def _review(store, case, fields, sources, latest):
    st.subheader('Review case evidence')
    st.caption('Compare findings across investigations. Choose conflicting values before approving this case for Dataset.')
    if latest:
        st.caption(f"Approved revision {latest['revision']} · Dataset: {latest['status']}")
    if not sources:
        st.info('No saved sources yet. Review becomes available when an investigation saves evidence.')
        return
    key = f"case_review_{case['id']}_{case['revision']}"
    saved_sources = list(dict.fromkeys(source_id for field in case['fields'].values()
                                     for source_id in field.get('source_ids', field.get('evidence', [])) if source_id in sources))
    with st.form(key):
        checked = st.multiselect('Checked sources', list(sources), default=saved_sources,
            format_func=lambda source_id: (sources[source_id].get('title') or sources[source_id].get('url') or 'Saved source') + ' · ' + source_id,
            help='Used for fields marked Not Reported or Unclear when they have no selected claims.')
        decisions = render_fields(fields, sources, mode='review', key=key, decisions=case['fields'])
        reason = st.text_area('Review reason', key=key + ':reason',
                              help='Explain the evidence review and any conflict resolution.')
        submitted = st.form_submit_button('Approve & add to Dataset', type='primary')
    if submitted:
        missing = [name for name, choice in decisions.items() if choice is None]
        if missing:
            st.warning('Choose a value or evidence status for: ' + ', '.join(missing))
        else:
            for choice in decisions.values():
                if choice['status'] != 'Reported':
                    choice['source_ids'] = checked or choice['source_ids']
            revision = store.review_and_approve(case['id'], case['revision'], decisions, reason)
            if latest and latest['revision'] == revision and latest['status'] == 'published':
                st.session_state['workspace_notice'] = 'Case review is already approved.'
            else:
                _queue_publication(case, revision, store.actor)
                st.session_state['workspace_notice'] = 'Case approved. Dataset update queued.'
            st.rerun()
    if latest and latest['revision'] == case['revision'] and latest['status'] in ('pending', 'failed'):
        st.caption('Approval saved. Dataset update ' + latest['status'] + '.')
        if st.button('Retry Dataset update', key='case_retry_' + case['id']):
            _queue_publication(case, latest['revision'], store.actor)
            st.success('Dataset update queued.')
    with st.expander('Review history'):
        for event in case['history']:
            st.write(f"Revision {event['revision']} · {event['action']} · {event['actor']}")
            st.write(event['reason'])


def _sources(sources):
    documents = deduplicate_sources(sources)
    st.subheader(f'{len(documents)} sources')
    if not documents:
        st.info('No sources have been saved for this case yet.')
    for document in documents:
        source, captures = document['source'], document['captures']
        with st.container(border=True):
            st.subheader(source.get('title') or source.get('url') or 'Saved source')
            if source.get('url'):
                st.link_button('Open source', source['url'])
            st.caption(f'{len(captures)} saved captures')
            with st.expander('Evidence captures'):
                for source_id, capture in captures.items():
                    st.caption('Investigation ' + source_id.split(':', 1)[0] + ' · ' + capture.get('evidence_kind', 'Saved evidence').replace('_', ' ').capitalize())
                    if capture.get('snippet'):
                        st.text(capture['snippet'])


def _queue_publication(case, revision, actor):
    from research_app.investigation_tasks import enqueue_publication
    enqueue_publication(case['id'], revision, actor)
