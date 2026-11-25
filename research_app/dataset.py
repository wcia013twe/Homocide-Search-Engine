"""Approved gold records and their case publication receipts."""
import csv
from io import StringIO
import os
from research_app.investigation_tasks import database_configured

import streamlit as st
from research_app.issue_reporting import capture_error

from research_app.collaboration import CaseStore
from research_app.cases import open_case
from research_app.gold import GOLD_FIELDS, GoldStore, STATES


DATASET_COLUMNS = (*GOLD_FIELDS, 'Approved on', 'Approved by')
DEFAULT_COLUMNS = ('case_id', 'Victim Name_First', 'Victim Name_Last',
                   'Incident Information_Location', 'Date Of Incident', 'Approved on', 'Approved by')


def _dataset_rows(records, published):
    rows = []
    for record in records:
        receipt = published.get(record.get('case_id'), {})
        rows.append({**{field: record.get(field) for field in GOLD_FIELDS},
                     'Approved on': str(receipt['approved_at']) if receipt.get('approved_at') else 'Unknown',
                     'Approved by': receipt.get('approved_by') or 'Unknown'})
    return rows


def _export_csv(published, selection):
    output = StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=DATASET_COLUMNS)
    writer.writeheader()
    writer.writerows(_dataset_rows(GoldStore().export_records(**selection), published))
    return output.getvalue().encode('utf-8-sig')


@st.cache_data(ttl=30, max_entries=8, scope='session', show_spinner=False)
def _publications(actor):
    return CaseStore(actor).publications()


@st.cache_data(ttl=30, max_entries=32, scope='session', show_spinner='Loading dataset…')
def _browse(actor, offset, *, state=None, year=None, query=''):
    return GoldStore().browse(offset, state=state, year=year, query=query)


def _refresh():
    for read in (_publications, _browse):
        read.clear()
    _reset_record()


def render(workspace, save):
    st.title('Dataset')
    st.caption('Browse golden rows, check approvals, and export research data.')
    st.button('Refresh dataset', key='dataset_refresh', on_click=_refresh,
              help='Reload records and approvals now. Results are reused for up to 30 seconds between interactions.')
    actor = st.session_state['research_user']
    _gold_records(actor)


def _gold_records(actor):
    if not os.environ.get('HR_SEARCH_AUDIT_WAREHOUSE_ID'):
        st.info('Connect the SQL warehouse to browse approved Dataset records.')
        return
    try:
        selection = dict(state=st.session_state.get('dataset_state'), year=st.session_state.get('dataset_year'),
                         query=st.session_state.get('dataset_query', ''))
        page = st.session_state.get('dataset_page', 1)
        records, total, years = _browse(actor, (page - 1) * 100, **selection)
        pages = max(1, (total + 99) // 100)
        if page > pages:
            st.session_state['dataset_page'] = pages
            page = pages
            records, total, years = _browse(actor, (page - 1) * 100, **selection)
        search, filters = st.columns([4, 1], vertical_alignment='bottom')
        query = search.text_input('Look up records', placeholder='Name, location, case ID, or other value',
                                  key='dataset_query', on_change=_reset_page)
        with filters.popover('Filters', icon=':material/filter_list:', width='stretch'):
            state = st.selectbox('State', [None] + sorted(STATES, key=STATES.__getitem__),
                                 format_func=lambda value: STATES[value] if value else 'All states',
                                 key='dataset_state', on_change=_reset_page)
            year = st.selectbox('Year', [None] + years,
                                format_func=lambda value: value or 'All years',
                                key='dataset_year', on_change=_reset_page)
            st.caption('State matches a state name or postal code at the end of the recorded location. Year uses the incident date. Missing values appear under All states and All years.')
        if pages > 1:
            page = st.number_input('Page', min_value=1, max_value=pages, step=1,
                                   key='dataset_page', on_change=_reset_record, width=180)
        active = [STATES[state] if state else 'All states', year or 'All years']
        page_label = f' · Page {page} of {pages}' if pages > 1 else ''
        st.caption(f"{total:,} matching {'record' if total == 1 else 'records'} · {' · '.join(active)}{page_label}")
        if not records:
            st.info('No records match. Clear the search or change the state and year filters.' if state or year or query.strip()
                    else 'No Dataset records are available yet.')
            return
        receipts, history_available = _history(actor)
        published = {}
        for receipt in receipts:
            if receipt['status'] == 'published' and (receipt['gold_key'] not in published or
                    receipt['revision'] > published[receipt['gold_key']]['revision']):
                published[receipt['gold_key']] = receipt
        rows = _dataset_rows(records, published)
        columns_control, export = st.columns([1, 2], vertical_alignment='bottom')
        with columns_control.popover('Columns', icon=':material/view_column:', width='stretch'):
            columns = st.multiselect('Visible columns', DATASET_COLUMNS, default=DEFAULT_COLUMNS,
                                     format_func=lambda field: 'Record ID' if field == 'case_id' else field,
                                     key='dataset_columns')
        export.download_button('Download matching records (CSV)',
                               data=lambda: _export_csv(published, selection),
                               file_name='homicide_dataset.csv', mime='text/csv',
                               on_click='ignore', key='dataset_export',
                               help=f'All {total:,} matching records, with every golden-row field and approval metadata. Includes columns hidden from the table.')
        if not history_available:
            st.caption('Approval metadata is unavailable. Approval dates and approvers are shown as Unknown.')
        st.caption('Select a row to see every field. Open its case review for sources and revision history.')
        selected = st.dataframe(rows, hide_index=True, width='stretch',
                                column_order=columns or DEFAULT_COLUMNS,
                                column_config={'case_id': st.column_config.TextColumn('Record ID')},
                                on_select='rerun', selection_mode='single-row', key='dataset_results')
        if not selected.selection.rows or not 0 <= selected.selection.rows[0] < len(rows):
            return
        row = rows[selected.selection.rows[0]]
        key = row.get('case_id')
        receipt = published.get(key) if key else None
        name = ' '.join(str(row.get(field) or '').strip() for field in
                        ('Victim Name_First', 'Victim Name_Last')).strip()
        st.subheader(name or 'Name not recorded')
        if receipt:
            st.button('Open case review', icon=':material/open_in_new:', key='dataset_edit',
                      help='View supporting sources, saved choices, and revision history.',
                      on_click=open_case, args=(receipt['case_id'], 'Review'))
        elif history_available:
            st.info('No linked case approval was found for this record. Its approval metadata is unknown.')
        st.markdown('**Full record**')
        st.dataframe([{'Field': 'Record ID' if field == 'case_id' else field,
                       'Value': str(value) if value not in (None, '') else 'Not recorded'}
                      for field, value in row.items()],
                     hide_index=True, width='stretch')
    except Exception as issue_exc:
        capture_error(issue_exc, "dataset._gold_records")
        st.error('Dataset records are temporarily unavailable. Check warehouse access and reload.')


def _history(actor):
    if database_configured():
        try:
            return _publications(actor), True
        except Exception as issue_exc:
            capture_error(issue_exc, "dataset._history")
            st.warning('Approval history is unavailable. Check shared case storage and reload.')
    return [], False


def _reset_record():
    st.session_state.pop('dataset_results', None)


def _reset_page():
    st.session_state['dataset_page'] = 1
    _reset_record()
