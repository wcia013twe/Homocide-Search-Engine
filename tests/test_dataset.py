"""Dataset queries against real SQLite rows, with Spark string functions registered."""
import os
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from research_app.gold import GOLD_FIELDS, GoldStore


class Cursor(sqlite3.Cursor):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Connection(sqlite3.Connection):
    def cursor(self):
        return super().cursor(factory=Cursor)

    def __exit__(self, *args):
        super().__exit__(*args)
        self.close()


class CollectSet:
    def __init__(self):
        self.values = set()

    def step(self, value):
        if value is not None:
            self.values.add(value)

    def finalize(self):
        return json.dumps(sorted(self.values))


class DatasetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'gold.sqlite3'
        self.reads = 0
        with self.connection() as conn:
            columns = ', '.join(f'`{field}` TEXT' for field in GOLD_FIELDS)
            conn.execute(f'CREATE TABLE homicide_gold ({columns})')
            self.insert(conn, 'blank')
            self.insert(conn, 'florida', 'Miami, Florida', '2025-04-03', 'Alice')
            self.insert(conn, 'postal', 'Orlando, FL 32801', '04/03/2025', 'Beatrice')
            self.insert(conn, 'lowercase', 'Tampa fl, USA', 'April 3, 2024', 'Carmen')
            self.insert(conn, 'virginia', 'Richmond, Virginia', '2025-01-01')
            self.insert(conn, 'west-virginia', 'Charleston, West Virginia', '2025-01-01')
            self.insert(conn, 'dc', 'Washington, DC', '2025-01-01')
            self.insert(conn, 'washington', 'Seattle WA', '2025-01-01')
            self.insert(conn, 'prose', 'Reported in another location', 'Unclear')
            self.insert(conn, 'literal', 'Unknown', None, '100%_value')
            for index in range(105):
                self.insert(conn, f'texas-{index:03}', 'Austin, TX', '2023-01-01', f'Person {index}')
        table = patch('research_app.gold.TABLE', 'homicide_gold')
        table.start()
        self.addCleanup(table.stop)
        # Only the connection boundary changes; all application queries run in SQL.
        connection = patch.object(GoldStore, '_connection', self.connection)
        connection.start()
        self.addCleanup(connection.stop)
        self.store = GoldStore()

    def connection(self):
        self.reads += 1
        conn = sqlite3.connect(self.path, factory=Connection)
        conn.create_function('regexp_extract', 3, lambda value, pattern, group:
                             match.group(group) if (match := re.search(pattern, value)) else '')
        conn.create_function('concat_ws', -1, lambda separator, *values:
                             separator.join(value for value in values if value is not None))
        conn.create_aggregate('collect_set', 1, CollectSet)
        conn.create_function('to_json', 1, lambda value: value or '[]')
        return conn

    def insert(self, conn, key, location=None, date=None, name=None):
        conn.execute('''INSERT INTO homicide_gold
            (case_id, `Incident Information_Location`, `Date Of Incident`, `Victim Name_First`)
            VALUES (?, ?, ?, ?)''', [key, location, date, name])

    def keys(self, **filters):
        return [row['case_id'] for row in self.store.list_records(**filters)]

    def test_combines_state_year_and_case_insensitive_search(self):
        self.assertEqual(self.keys(state='FL', year='2025', query='  ALICE '), ['florida'])
        self.assertEqual(self.keys(state='FL', year='2025'), ['florida', 'postal'])
        self.assertEqual(self.keys(state='FL', year='2024'), ['lowercase'])
        self.assertEqual(self.store.incident_years(), ['2025', '2024', '2023'])
        self.assertEqual(self.store.count_records(state='FL', year='2025'), 2)

    def test_state_names_do_not_match_other_states_or_ordinary_words(self):
        self.assertEqual(self.keys(state='VA'), ['virginia'])
        self.assertEqual(self.keys(state='WV'), ['west-virginia'])
        self.assertEqual(self.keys(state='WA'), ['washington'])
        self.assertEqual(self.keys(state='DC'), ['dc'])
        self.assertEqual(self.keys(state='IN'), [])

    def test_searches_all_records_before_pagination_and_treats_text_literally(self):
        self.assertEqual(self.keys(query='texas-104'), ['texas-104'])
        self.assertEqual(self.keys(query='100%_value'), ['literal'])
        self.assertEqual(self.keys(query="' OR 1=1 --"), [])
        self.assertEqual(self.store.count_records(), 115)
        self.assertEqual(len(self.keys()), 100)
        self.assertEqual(len(self.keys(offset=100)), 15)
        self.assertIn('blank', self.keys())
        self.assertEqual(self.keys(query='   '), self.keys())

    def test_browse_reads_page_count_and_years_together_including_empty_matches(self):
        self.reads = 0
        records, total, years = self.store.browse(100)
        self.assertEqual(self.reads, 1)
        self.assertEqual(len(records), 15)
        self.assertEqual(total, 115)
        self.assertEqual(years, ['2025', '2024', '2023'])
        records, total, years = self.store.browse(state='FL', year='2025', query='Alice')
        self.assertEqual([row['case_id'] for row in records], ['florida'])
        self.assertEqual(total, 1)
        self.assertEqual(years, ['2025', '2024', '2023'])
        records, total, years = self.store.browse(query='missing')
        self.assertEqual((records, total), ([], 0))
        self.assertEqual(years, ['2025', '2024', '2023'])
        records, total, years = self.store.browse(1000)
        self.assertEqual((records, total), ([], 115))
        with self.connection() as conn:
            conn.execute('DELETE FROM homicide_gold')
        self.assertEqual(self.store.browse(), ([], 0, []))
        with self.connection() as conn:
            self.insert(conn, None)
        records, total, years = self.store.browse()
        self.assertEqual(total, 1)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]['case_id'])

    def test_invalid_filter_values_are_rejected(self):
        for filters in [dict(state="FL'"), dict(year='25'), dict(year="2025'"), dict(offset=-1)]:
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.store.list_records(**filters)

    def test_export_includes_all_matching_rows_and_every_field(self):
        from research_app.dataset import _export_csv
        receipt = {'approved_at': '2026-11-25', 'approved_by': 'researcher'}
        exported = _export_csv({'texas-104': receipt}, dict(state='TX', year='2023', query=''))
        reader = csv.DictReader(StringIO(exported.decode('utf-8-sig')))
        rows = list(reader)
        self.assertEqual(reader.fieldnames, [*GOLD_FIELDS, 'Approved on', 'Approved by'])
        self.assertEqual(len(rows), 105)
        self.assertEqual(rows[-1]['case_id'], 'texas-104')
        self.assertEqual(rows[-1]['Approved by'], 'researcher')
        self.assertEqual(rows[-1]['Approved on'], '2026-11-25')
        self.assertEqual(rows[0]['Approved by'], 'Unknown')
        self.assertEqual(rows[0]['Victim Age'], '')
        self.assertEqual(self.store.export_records(query='missing'), [])
        self.assertEqual([row['case_id'] for row in self.store.export_records(query='Alice')], ['florida'])

    def test_dataset_rows_preserve_values_and_handle_datetime_approvals(self):
        from research_app.dataset import _dataset_rows
        records = [{'case_id': 'approved', 'Victim Age': '0', 'Victim Name_First': 'José, Jr.'},
                   {'case_id': 'legacy'}]
        approved_at = datetime(2026, 11, 25, tzinfo=timezone.utc)
        rows = _dataset_rows(records, {'approved': {'approved_at': approved_at, 'approved_by': 'reviewer'}})
        self.assertEqual(rows[0]['Approved on'], str(approved_at))
        self.assertEqual(rows[0]['Victim Age'], '0')
        self.assertEqual(rows[0]['Victim Name_First'], 'José, Jr.')
        self.assertIsNone(rows[1]['Victim Age'])
        self.assertEqual(rows[1]['Approved on'], 'Unknown')

    def app(self):
        app = AppTest.from_string('''
import streamlit as st
from research_app.dataset import render, _refresh
# AppTest uses the same synthetic session ID across independent test apps.
if 'dataset_test_initialized' not in st.session_state:
    _refresh()
    st.session_state['dataset_test_initialized'] = True
st.session_state.setdefault('research_user', 'dataset-test')
render({}, lambda: None)
''', default_timeout=15)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        return app

    def test_browsing_reuses_reads_and_refresh_loads_new_records(self):
        with patch.dict(os.environ, {'HR_SEARCH_AUDIT_WAREHOUSE_ID': 'test',
                                     'HR_RESEARCH_CHECKPOINT_DSN': '', 'HR_LAKEBASE_ENDPOINT': ''}):
            self.reads = 0
            app = self.app()
            self.assertEqual(self.reads, 1)
            from research_app.dataset import DEFAULT_COLUMNS
            self.assertEqual(list(app.dataframe[0].proto.column_order), list(DEFAULT_COLUMNS))
            app.multiselect(key='dataset_columns').set_value(list(GOLD_FIELDS)).run()
            self.assertEqual(list(app.dataframe[0].proto.column_order), list(GOLD_FIELDS))
            app.run()
            self.assertEqual(self.reads, 1)
            app.number_input(key='dataset_page').set_value(2).run()
            self.assertEqual(self.reads, 2)
            app.text_input(key='dataset_query').set_value('Alice').run()
            self.assertEqual(self.reads, 3)
            app.session_state['research_user'] = 'another-researcher'
            app.run()
            self.assertEqual(self.reads, 4)
            with self.connection() as conn:
                self.insert(conn, 'new-alice', 'Miami, FL', '2025-01-01', 'Alice New')
            app.run()
            self.assertEqual(len(app.dataframe[0].value), 1)
            self.assertEqual(self.reads, 5)
            app.button(key='dataset_refresh').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.dataframe[0].value), 2)
            self.assertEqual(self.reads, 6)

    def test_controls_reset_pagination_and_inspection_and_keep_empty_state_usable(self):
        with patch.dict(os.environ, {'HR_SEARCH_AUDIT_WAREHOUSE_ID': 'test',
                                     'HR_RESEARCH_CHECKPOINT_DSN': '', 'HR_LAKEBASE_ENDPOINT': ''}):
            app = self.app()
            app.number_input(key='dataset_page').set_value(2).run()
            self.assertEqual(len(app.dataframe[0].value), 15)
            app.text_input(key='dataset_query').set_value('ALICE').run()
            self.assertFalse(app.exception)
            self.assertFalse(app.number_input)
            self.assertEqual(app.dataframe[0].value.iloc[0]['case_id'], 'florida')
            app.text_input(key='dataset_query').set_value('').run()
            app.selectbox(key='dataset_state').select('Florida').run()
            app.selectbox(key='dataset_year').select('2025').run()
            self.assertEqual(len(app.dataframe[0].value), 2)
            app.selectbox(key='dataset_year').select('2023').run()
            self.assertFalse(app.exception)
            self.assertTrue(any('No records match' in item.value for item in app.info))
            self.assertEqual(len(app.text_input), 1)
            app.selectbox(key='dataset_state').select('All states').run()
            self.assertEqual(len(app.dataframe[0].value), 100)

    def test_provenance_distinguishes_unavailable_history_from_no_publication(self):
        with patch.dict(os.environ, {'HR_SEARCH_AUDIT_WAREHOUSE_ID': 'test',
                                     'HR_RESEARCH_CHECKPOINT_DSN': '', 'HR_LAKEBASE_ENDPOINT': ''}):
            app = self.app()
            self.assertTrue(any('Approval metadata is unavailable' in item.value for item in app.caption))
            self.assertEqual(set(app.dataframe[0].value['Approved by']), {'Unknown'})
            self.assertFalse(any(button.key == 'dataset_edit' for button in app.button))
        with patch('research_app.dataset.database_configured', return_value=True), \
                patch('research_app.dataset.CaseStore.publications', return_value=[]), \
                patch.dict(os.environ, {'HR_SEARCH_AUDIT_WAREHOUSE_ID': 'test'}):
            app = self.app()
            app.session_state['dataset_results'] = {'selection': {'rows': [0]}}
            app.run()
            self.assertTrue(any('No linked case approval' in item.value for item in app.info))

    def test_published_record_displays_approval_and_saved_sources(self):
        receipt = dict(case_id='shared-case', gold_key='florida', title='Approved case',
                       revision=2, approved_by='researcher', approved_at='2026-11-16', status='published',
                       snapshot={'evidence_fields': {}, 'sources': {}})
        old_receipt = {**receipt, 'revision': 1, 'approved_by': 'old reviewer'}
        pending_receipt = {**receipt, 'revision': 3, 'status': 'pending', 'approved_by': 'pending reviewer'}
        with patch('research_app.dataset.database_configured', return_value=True), \
                patch('research_app.dataset.CaseStore.publications', return_value=[receipt, old_receipt, pending_receipt]), \
                patch.dict(os.environ, {'HR_SEARCH_AUDIT_WAREHOUSE_ID': 'test'}):
            app = self.app()
            app.text_input(key='dataset_query').set_value('Alice').run()
            frame = app.dataframe[0].value
            self.assertEqual(set(frame.columns), {*GOLD_FIELDS, 'Approved on', 'Approved by'})
            self.assertEqual(frame.iloc[0]['Approved by'], 'researcher')
            self.assertEqual(str(frame.iloc[0]['Approved on']), '2026-11-16')
            app.session_state['dataset_results'] = {'selection': {'rows': [0]}}
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            full_record = app.dataframe[1].value.set_index('Field')['Value']
            self.assertEqual(full_record['Record ID'], 'florida')
            self.assertEqual(full_record['Approved by'], 'researcher')
            self.assertEqual(len(full_record), len(GOLD_FIELDS) + 2)
            self.assertFalse(app.tabs)
            self.assertFalse(app.button(key='dataset_edit').disabled)
            app.button(key='dataset_edit').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['nav_page'], 'Cases')
            self.assertEqual(app.session_state['case_to_open'], 'shared-case')
            self.assertEqual(app.session_state['case_tab_to_open'], 'Review')


if __name__ == '__main__':
    unittest.main()
