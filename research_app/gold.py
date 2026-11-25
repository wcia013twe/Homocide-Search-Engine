"""Existing gold table adapter; approved case snapshots are the only write input."""
import json

from research_app.gold_fields import GOLD_FIELDS
from research_app.search_audit import SearchAuditStore

TABLE = 'homicide_research.research.homicide_gold'
STATES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii',
    'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island',
    'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas',
    'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
    'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
}
INCIDENT_YEAR = "regexp_extract(coalesce(`Date Of Incident`, ''), '(?<![0-9])([12][0-9]{3})(?![0-9])', 1)"
LOCATION_STATE = (r'(?i)(?:^|[^a-z])(' + '|'.join(sorted(STATES.values(), key=len, reverse=True))
                  + '|' + '|'.join(STATES)
                  + r')(?:\s+\d{5}(?:-\d{4})?)?(?:,?\s+(?:USA|US|United States(?: of America)?))?\s*$')


def _record_filters(state=None, year=None, query=''):
    clauses, values = [], []
    if state is not None:
        if state not in STATES:
            raise ValueError('Choose a valid state.')
        # Extract the complete state suffix so overlapping names stay distinct.
        clauses.append("lower(regexp_extract(coalesce(`Incident Information_Location`, ''), ?, 1)) IN (?, ?)")
        values.extend([LOCATION_STATE, STATES[state].lower(), state.lower()])
    if year is not None:
        if not isinstance(year, str) or len(year) != 4 or not year.isascii() or not year.isdigit():
            raise ValueError('Choose a four-digit incident year.')
        clauses.append(f'{INCIDENT_YEAR} = ?')
        values.append(year)
    if query.strip():
        columns = ', '.join(f'`{field}`' for field in GOLD_FIELDS)
        clauses.append(f"instr(lower(concat_ws(' ', {columns})), ?) > 0")
        values.append(query.strip().lower())
    return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), values


class GoldStore:
    def _connection(self):
        return SearchAuditStore.from_environment()._connection()

    def browse(self, offset=0, *, state=None, year=None, query=''):
        """Read a page, matching count, and year choices in one warehouse request."""
        if type(offset) is not int or offset < 0:
            raise ValueError('Invalid page offset.')
        where, values = _record_filters(state, year, query)
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(f'''WITH matching AS (SELECT * FROM {TABLE}{where}),
                page AS (SELECT *, 1 AS _page_present FROM matching ORDER BY case_id LIMIT 100 OFFSET {offset}),
                stats AS (SELECT count(*) AS _record_total FROM matching),
                years AS (SELECT to_json(collect_set(nullif({INCIDENT_YEAR}, ''))) AS _incident_years FROM {TABLE})
                SELECT page.*, stats._record_total, years._incident_years
                FROM stats CROSS JOIN years LEFT JOIN page ON TRUE ORDER BY page.case_id''', values)
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        total = rows[0]['_record_total']
        years = sorted(json.loads(rows[0]['_incident_years']), reverse=True)
        records = [{name: row[name] for name in GOLD_FIELDS} for row in rows if row['_page_present']]
        return records, total, years

    def list_records(self, offset=0, *, state=None, year=None, query=''):
        if type(offset) is not int or offset < 0:
            raise ValueError('Invalid page offset.')
        where, values = _record_filters(state, year, query)
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'SELECT * FROM {TABLE}{where} ORDER BY case_id LIMIT 100 OFFSET {offset}', values)
                names = [item[0] for item in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]

    def count_records(self, *, state=None, year=None, query=''):
        where, values = _record_filters(state, year, query)
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'SELECT count(*) FROM {TABLE}{where}', values)
                return cursor.fetchone()[0]

    def export_records(self, *, state=None, year=None, query=''):
        """Read all matching golden rows, independently of browse pagination."""
        where, values = _record_filters(state, year, query)
        columns = ', '.join(f'`{field}`' for field in GOLD_FIELDS)
        with self._connection() as conn, conn.cursor() as cursor:
            cursor.execute(f'SELECT {columns} FROM {TABLE}{where} ORDER BY case_id', values)
            return [dict(zip(GOLD_FIELDS, row)) for row in cursor.fetchall()]

    def incident_years(self):
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT DISTINCT {INCIDENT_YEAR} AS year FROM {TABLE} WHERE {INCIDENT_YEAR} <> '' ORDER BY year DESC")
                return [row[0] for row in cursor.fetchall()]

    def publish(self, snapshot, *, allow_existing=False, previous_snapshot=None):
        columns = ', '.join(f'`{field}`' for field in GOLD_FIELDS)
        values = [snapshot['gold_key'] if field == 'case_id' else snapshot['fields'][field]['value'] for field in GOLD_FIELDS]
        previous_values = None
        if previous_snapshot:
            if previous_snapshot['gold_key'] != snapshot['gold_key']:
                raise ValueError('Dataset updates must keep the same record ID.')
            previous_values = [previous_snapshot['gold_key'] if field == 'case_id' else previous_snapshot['fields'][field]['value'] for field in GOLD_FIELDS]
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'DESCRIBE TABLE {TABLE}')
                schema = {row[0]: row[1] for row in cursor.fetchall() if row[0] and not row[0].startswith('#')}
                if set(schema) != set(GOLD_FIELDS) or any(schema[field] != 'string' for field in GOLD_FIELDS):
                    raise ValueError('Gold schema changed; review publication mapping before retrying.')
                cursor.execute(f'SELECT {columns} FROM {TABLE} WHERE case_id = ?', [snapshot['gold_key']])
                existing = cursor.fetchall()
                if existing:
                    if len(existing) == 1 and allow_existing and list(existing[0]) == values:
                        return
                    if len(existing) != 1 or previous_values is None or list(existing[0]) != previous_values:
                        raise ValueError('Dataset record changed since its last approved version. Reload before updating.')
                elif previous_values is not None:
                    raise ValueError('The previously published Dataset record is missing.')
                projection = ', '.join(f'? AS `{field}`' for field in GOLD_FIELDS)
                if previous_values is not None:
                    # Compare inside MERGE as well as before it, including null values.
                    unchanged = ' AND '.join(f't.`{field}` <=> ?' for field in GOLD_FIELDS)
                    update = ', '.join(f't.`{field}` = s.`{field}`' for field in GOLD_FIELDS if field != 'case_id')
                    cursor.execute(f'''MERGE INTO {TABLE} t USING (SELECT {projection}) s
                        ON t.case_id = s.case_id
                        WHEN MATCHED AND {unchanged} THEN UPDATE SET {update}''', values + previous_values)
                else:
                    cursor.execute(f'''MERGE INTO {TABLE} t USING (SELECT {projection}) s
                        ON t.case_id = s.case_id
                        WHEN NOT MATCHED THEN INSERT ({columns}) VALUES
                        ({', '.join(f's.`{field}`' for field in GOLD_FIELDS)})''', values)
                cursor.execute(f'SELECT {columns} FROM {TABLE} WHERE case_id = ?', [snapshot['gold_key']])
                written = cursor.fetchall()
                if len(written) != 1 or list(written[0]) != values:
                    raise ValueError('Gold publication does not match the approved snapshot.')
