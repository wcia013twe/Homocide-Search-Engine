"""Exercise Dataset writes in real Postgres through a SQL dialect adapter."""
from copy import deepcopy
import os
import re
import unittest
from uuid import uuid4

from research_app.gold import GOLD_FIELDS, GoldStore


class SqlCursor:
    """Translate warehouse syntax, keeping real SQL evaluation and row contents."""
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, query, parameters=None):
        if query.startswith('DESCRIBE TABLE '):
            table = query.removeprefix('DESCRIBE TABLE ')
            query = '''SELECT column_name, CASE WHEN data_type='text' THEN 'string' ELSE data_type END
                FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s
                ORDER BY ordinal_position'''
            parameters = [table]
        else:
            query = re.sub(r'`([^`]+)`', r'"\1"', query).replace('<=>', 'IS NOT DISTINCT FROM')
            query = re.sub(r''''(?:''|[^'])*'|"(?:""|[^"])*"|\?''', lambda match: '%s' if match[0] == '?' else match[0], query)
            if 'THEN UPDATE SET' in query:
                before, after = query.split('THEN UPDATE SET', 1)
                query = before + 'THEN UPDATE SET' + re.sub(r't\.("[^"]+")\s*=', r'\1 =', after)
        self.cursor.execute(query, parameters)

    @property
    def description(self):
        return self.cursor.description

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()


class SqlConnection:
    def __init__(self, dsn):
        import psycopg
        self.connection = psycopg.connect(dsn, autocommit=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def cursor(self):
        return SqlCursor(self.connection.cursor())


@unittest.skipUnless(os.environ.get('HR_COLLABORATION_TEST_DSN'), 'Set a disposable Postgres test DSN')
class DatasetPublicationTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from unittest.mock import patch
        self.base_dsn = os.environ['HR_COLLABORATION_TEST_DSN']
        self.schema = 'dataset_test_' + uuid4().hex
        self.dsn = make_conninfo(self.base_dsn, options='-c search_path=' + self.schema)
        with psycopg.connect(self.base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            columns = sql.SQL(', ').join(sql.SQL('{} text').format(sql.Identifier(name)) for name in GOLD_FIELDS)
            conn.execute(sql.SQL('CREATE TABLE homicide_gold ({})').format(columns))
        table = patch('research_app.gold.TABLE', 'homicide_gold')
        table.start()
        self.addCleanup(table.stop)
        self.store = GoldStore()
        self.store._connection = lambda: SqlConnection(self.dsn)
        self.snapshot = {'gold_key': 'case-1', 'fields': {name: {'value': None} for name in GOLD_FIELDS if name != 'case_id'}}
        self.snapshot['fields']['Victim Age']['value'] = '47'

    def drop_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(self.base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def row(self):
        with SqlConnection(self.dsn) as conn, conn.cursor() as cursor:
            cursor.execute('SELECT * FROM homicide_gold')
            return cursor.fetchall()

    def test_insert_reapprove_update_same_id_and_identical_retry(self):
        self.store.publish(self.snapshot)
        with self.assertRaises(ValueError):
            self.store.publish(self.snapshot)
        updated = deepcopy(self.snapshot)
        updated['fields']['Victim Age']['value'] = '48'
        self.store.publish(updated, previous_snapshot=self.snapshot)
        self.assertEqual(len(self.row()), 1)
        self.assertEqual(self.row()[0][list(GOLD_FIELDS).index('Victim Age')], '48')
        self.store.publish(updated, previous_snapshot=self.snapshot, allow_existing=True)
        self.assertEqual(len(self.row()), 1)

    def test_external_change_missing_row_and_different_id_are_rejected(self):
        self.store.publish(self.snapshot)
        with SqlConnection(self.dsn) as conn, conn.cursor() as cursor:
            cursor.execute('UPDATE homicide_gold SET `Victim Age`=?', ['99'])
        updated = deepcopy(self.snapshot)
        updated['fields']['Victim Age']['value'] = '48'
        with self.assertRaisesRegex(ValueError, 'changed since'):
            self.store.publish(updated, previous_snapshot=self.snapshot)
        self.assertEqual(self.row()[0][list(GOLD_FIELDS).index('Victim Age')], '99')
        with SqlConnection(self.dsn) as conn, conn.cursor() as cursor:
            cursor.execute('DELETE FROM homicide_gold')
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.store.publish(updated, previous_snapshot=self.snapshot)
        updated['gold_key'] = 'different-id'
        with self.assertRaisesRegex(ValueError, 'same record ID'):
            self.store.publish(updated, previous_snapshot=self.snapshot)
