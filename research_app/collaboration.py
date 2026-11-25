"""Shared case contributions. Does not execute or modify research workflows."""
from copy import deepcopy
import json
import logging
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

from research_app.investigation_tasks import connection, read_connection
from research_app.repository import ConflictError
from research_app.gold_fields import GOLD_FIELDS, CODEBOOK_VERSION
from research_app.coding_review import apply_coding_review
from research_app.evidence_groups import case_evidence


def _annotate_links(links, conn):
    from research_app.evidence_registry import annotate_state
    for link in links:
        if any(source.get('version_id') for source in link['snapshot'].get('sources', {}).values()):
            link['snapshot'] = annotate_state(link['investigation_id'], link['snapshot'], conn=conn)
    return links


def identifiers(state):
    """Only unambiguous exact identifiers qualify for automatic association."""
    profile = state.get('coded_fields') or state.get('profile') or {}

    def value(name):
        field = profile.get(name)
        if isinstance(field, dict):
            if field.get('conflicting') or field.get('status') in ('Unclear', 'Not Reported'):
                return None
            field = field.get('value')
        return str(field).strip() if field is not None and str(field).strip() else None

    found = []
    if value('case_id'):
        found.append(('case_id', value('case_id')))
    if value('agency') and value('case_number'):
        found.append(('agency_case', json.dumps([value('agency').casefold(), value('case_number').casefold()])))
    return found


def matching_signals(state):
    """Human-review hints only; never used for automatic association."""
    profile = state.get('profile') or state.get('coded_fields') or {}
    found = set()
    for key in ('person_identity', 'incident_date', 'city', 'location'):
        field = profile.get(key)
        if isinstance(field, dict):
            if field.get('conflicting') or field.get('status') in ('Unclear', 'Not Reported'):
                continue
            field = field.get('value')
        if isinstance(field, str) and field.strip():
            found.add(key + ': ' + ' '.join(field.casefold().split()))
    return found


def setup():
    with connection() as conn, conn.transaction():
        conn.execute(Path(__file__).resolve().parents[1].joinpath('sql/postgres/001_collaboration.sql').read_text())
        conn.execute(Path(__file__).resolve().parents[1].joinpath('sql/postgres/004_publication_attempts.sql').read_text())


class CaseStore:
    def __init__(self, actor):
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('Authenticated researcher identity is required.')
        self.actor = actor

    def list_cases(self, mine=False):
        with read_connection() as conn:
            return conn.execute('''SELECT c.*, (SELECT count(*) FROM research_case_investigations i
                WHERE i.case_id=c.id) AS investigations,
                (SELECT max(revision) FROM research_case_publications p WHERE p.case_id=c.id) AS approved_revision
                FROM research_cases c WHERE NOT %s OR c.created_by=%s OR EXISTS
                (SELECT 1 FROM research_case_investigations i WHERE i.case_id=c.id AND i.owner=%s)
                ORDER BY c.created_at DESC''', [mine, self.actor, self.actor]).fetchall()

    def get(self, case_id):
        with read_connection() as conn:
            case = conn.execute('SELECT * FROM research_cases WHERE id=%s', [case_id]).fetchone()
            if not case:
                raise ValueError('Case not found.')
            case['investigations'] = conn.execute('SELECT * FROM research_case_investigations WHERE case_id=%s ORDER BY linked_at', [case_id]).fetchall()
            _annotate_links(case['investigations'], conn)
            case['history'] = conn.execute('SELECT * FROM research_case_history WHERE case_id=%s ORDER BY id DESC', [case_id]).fetchall()
            case['publications'] = conn.execute('SELECT * FROM research_case_publications WHERE case_id=%s ORDER BY revision DESC', [case_id]).fetchall()
            return case

    def _saved_investigation(self, investigation_id):
        from research_app.hosted_session import open_hosted_session, scoped_session_id
        with read_connection() as conn:
            task = conn.execute('SELECT * FROM investigation_tasks WHERE id=%s', [investigation_id]).fetchone()
        if not task:
            raise ValueError('Investigation not found.')
        key = scoped_session_id(task['id'], task['actor'])
        with open_hosted_session(key, read_only=True) as session:
            snapshot = session.inspect(key, task['actor'])
        if not snapshot.values:
            raise ValueError('This investigation has no saved findings yet.')
        return task, deepcopy(snapshot.values)

    def associate(self, investigation_id, target_case=None, reason='Exact identifier association'):
        """Load owner from storage, never from the viewing researcher's supplied data."""
        task, state = self._saved_investigation(investigation_id)
        return self.link_snapshot(task, state, target_case, reason)

    def suggestions(self, investigation_id):
        _, state = self._saved_investigation(investigation_id)
        signals = matching_signals(state)
        with read_connection() as conn:
            links = conn.execute('SELECT i.case_id,i.snapshot,c.title FROM research_case_investigations i JOIN research_cases c ON c.id=i.case_id WHERE i.investigation_id<>%s', [investigation_id]).fetchall()
        matches = {}
        for link in links:
            shared = sorted(signals & matching_signals(link['snapshot']))
            if shared:
                entry = matches.setdefault(link['case_id'], {'title': link['title'], 'signals': set()})
                entry['signals'].update(shared)
        return matches

    def link_snapshot(self, task, state, target_case=None, reason='Exact identifier association'):
        """Internal workflow adapter; task and snapshot must come from trusted storage."""
        with connection() as conn, conn.transaction():
            return self._link_snapshot(conn, task, state, target_case, reason)

    def _link_snapshot(self, conn, task, state, target_case=None, reason='Exact identifier association'):
        exact = identifiers(state)
        # Serialize association so two researchers cannot create duplicate exact identifiers.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('research-case-association'))")
        existing = conn.execute('SELECT case_id FROM research_case_investigations WHERE investigation_id=%s', [task['id']]).fetchone()
        matches = {row['case_id'] for kind, identifier in exact for row in
                   conn.execute('SELECT case_id FROM research_case_identifiers WHERE kind=%s AND identifier=%s', [kind, identifier]).fetchall()}
        if len(matches) > 1:
            raise ValueError('Identifiers match different cases; resolve their identifiers before linking.')
        matched = next(iter(matches), None)
        if target_case and matched and target_case != matched:
            raise ValueError('Exact identifier belongs to another case.')
        case_id = target_case or (existing['case_id'] if existing else None) or matched or str(uuid4())
        if existing and existing['case_id'] != case_id:
            raise ValueError('Investigation is already linked to another case; its history cannot be moved silently.')
        if matched and matched != case_id:
            raise ValueError('Updated identifier conflicts with the existing case link.')
        if target_case and not conn.execute('SELECT 1 FROM research_cases WHERE id=%s', [target_case]).fetchone():
            raise ValueError('Target case not found.')
        if target_case and not reason.strip():
            raise ValueError('Confirm the case link with a reason.')
        gold_key = next((v for k, v in exact if k == 'case_id'), case_id)
        conn.execute('''INSERT INTO research_cases(id,title,created_by,gold_key) VALUES (%s,%s,%s,%s)
            ON CONFLICT (id) DO NOTHING''', [case_id, task['query'], self.actor, gold_key])
        current = conn.execute('SELECT gold_key FROM research_cases WHERE id=%s FOR UPDATE', [case_id]).fetchone()
        explicit_key = next((v for k, v in exact if k == 'case_id'), None)
        if explicit_key and current['gold_key'] != explicit_key:
            if conn.execute('SELECT 1 FROM research_case_publications WHERE case_id=%s', [case_id]).fetchone():
                raise ValueError('Case ID changed after approval; review the existing gold identity before linking.')
            conn.execute('UPDATE research_cases SET gold_key=%s WHERE id=%s', [explicit_key, case_id])
        for kind, identifier in exact:
            conn.execute('INSERT INTO research_case_identifiers VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', [kind, identifier, case_id])
        previous = conn.execute('SELECT snapshot FROM research_case_investigations WHERE investigation_id=%s', [task['id']]).fetchone()
        if previous and previous['snapshot'] == state:
            return case_id
        conn.execute('''INSERT INTO research_case_investigations(investigation_id,case_id,owner,snapshot,linked_by)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (investigation_id) DO UPDATE SET snapshot=EXCLUDED.snapshot''',
                     [task['id'], case_id, task['actor'], Jsonb(state), self.actor])
        self._event(conn, case_id, 'evidence', reason, {'investigation_id': task['id'], 'snapshot': state})
        return case_id

    def _event(self, conn, case_id, action, reason, payload):
        revision = conn.execute('UPDATE research_cases SET revision=revision+1 WHERE id=%s RETURNING revision', [case_id]).fetchone()['revision']
        conn.execute('''INSERT INTO research_case_history(case_id,revision,action,actor,reason,payload)
            VALUES (%s,%s,%s,%s,%s,%s)''', [case_id, revision, action, self.actor, reason, Jsonb(payload)])
        return revision

    def contribute(self, case_id, expected_revision, field, value, status, evidence, reason, claim_ids=(), assignment_ids=()):
        if field not in GOLD_FIELDS or field == 'case_id':
            raise ValueError('Choose an editable gold field.')
        if status not in ('Reported', 'Not Reported', 'Unclear') or not reason.strip() or not evidence:
            raise ValueError('A contribution needs a status, supporting evidence, and reason.')
        if status == 'Reported' and (not isinstance(value, str) or not value.strip()):
            raise ValueError('Reported fields require a value.')
        with connection() as conn, conn.transaction():
            case = self._locked_case(conn, case_id, expected_revision)
            links = conn.execute('SELECT investigation_id,snapshot FROM research_case_investigations WHERE case_id=%s', [case_id]).fetchall()
            allowed = evidence_options(links)
            if not set(evidence) <= set(allowed):
                raise ValueError('Evidence must belong to a linked investigation.')
            fields = case['fields']
            before = deepcopy(fields.get(field))
            proposed = {'value': value.strip() if status == 'Reported' else None, 'status': status,
                        'source_ids': list(evidence), 'claim_ids': list(claim_ids),
                        'assignment_ids': list(assignment_ids), 'reason': reason.strip(),
                        'codebook_version': CODEBOOK_VERSION}
            _annotate_links(links, conn)
            projected, sources = case_evidence(links, {**fields, field: proposed})
            candidates = [claim for item in projected.values() for claim in item.get('claims', [])]
            selected = [c for c in candidates if c['claim_id'] in claim_ids]
            known_assignments = {c.get('assignment_id') for c in selected} - {None}
            if not set(assignment_ids) <= known_assignments:
                raise ValueError('Assignments must reference selected claims.')
            # A reassignment changes this decision, never the original source assertion.
            target = deepcopy(projected.get(field, {'claims': []}))
            target['claims'] = list({c['claim_id']: c for c in target.get('claims', []) + selected}.values())
            validated = apply_coding_review({field: target}, sources,
                {'reason': reason.strip(), 'codebook_version': CODEBOOK_VERSION,
                 'fields': {field: proposed}}, (field,))['coded_fields'][field]
            from research_app.evidence_registry import reassign_claim
            revised_assignments = []
            for claim in selected:
                previous_assignment = claim.get('assignment_id')
                if previous_assignment:
                    investigation_id, raw_claim_id = claim['claim_id'].split(':', 1)
                    revised_assignments.append(reassign_claim(investigation_id, raw_claim_id, field,
                        actor=self.actor, reason=reason, expected_assignment_id=previous_assignment, conn=conn))
            fields[field] = {**validated, 'evidence': list(evidence),
                             'assignment_ids': revised_assignments}
            conn.execute('UPDATE research_cases SET fields=%s WHERE id=%s', [Jsonb(fields), case_id])
            return self._event(conn, case_id, 'contribution', reason.strip(), {'field': field, 'before': before, 'after': fields[field]})

    def _locked_case(self, conn, case_id, revision):
        case = conn.execute('SELECT * FROM research_cases WHERE id=%s FOR UPDATE', [case_id]).fetchone()
        if not case:
            raise ValueError('Case not found.')
        if case['revision'] != revision:
            raise ConflictError('This case changed. Reload and review the latest changes before saving.')
        return case

    def approve(self, case_id, expected_revision, reason):
        if not reason.strip():
            raise ValueError('Approval requires a reason.')
        with connection() as conn, conn.transaction():
            case = self._locked_case(conn, case_id, expected_revision)
            return self._approve_locked(conn, case, reason)

    def review_and_approve(self, case_id, expected_revision, decisions, reason):
        """Save one complete case review and its approval in the same transaction."""
        if not reason.strip():
            raise ValueError('Approval requires a reason.')
        if set(decisions) != set(GOLD_FIELDS) - {'case_id'}:
            raise ValueError('Review every Dataset field before approval.')
        with connection() as conn, conn.transaction():
            case = self._locked_case(conn, case_id, expected_revision)
            fields = {}
            for name, choice in decisions.items():
                if choice is None:
                    raise ValueError('Choose a value or evidence status for ' + name + '.')
                if choice['status'] == 'Reported' and (not isinstance(choice['value'], str) or not choice['value'].strip()):
                    raise ValueError('Reported fields require a text value: ' + name + '.')
                proposed = {key: deepcopy(choice[key]) for key in ('value', 'status', 'claim_ids', 'source_ids')}
                previous = case['fields'].get(name, {})
                same = all(previous.get(key) == proposed[key] for key in ('value', 'status')) and all(
                    set(previous.get(key, previous.get('evidence', []) if key == 'source_ids' else [])) == set(proposed[key])
                    for key in ('claim_ids', 'source_ids'))
                fields[name] = {**proposed, 'reason': previous['reason'] if same else reason.strip(),
                                'codebook_version': CODEBOOK_VERSION}
            # Keep the current revision when reopening and approving unchanged choices.
            changed = any(any(case['fields'].get(name, {}).get(key) != value for key, value in field.items())
                          for name, field in fields.items())
            if changed:
                conn.execute('UPDATE research_cases SET fields=%s WHERE id=%s', [Jsonb(fields), case_id])
                before, case['fields'] = case['fields'], fields
                case['revision'] = self._event(conn, case_id, 'contribution', reason.strip(), {'before': before, 'after': fields})
            return self._approve_locked(conn, case, reason)

    def _approve_locked(self, conn, case, reason):
        missing = set(GOLD_FIELDS) - {'case_id'} - set(case['fields'])
        if missing:
            raise ValueError('Review every gold field before approval: ' + ', '.join(sorted(missing)))
        links = conn.execute('SELECT investigation_id,owner,snapshot FROM research_case_investigations WHERE case_id=%s', [case['id']]).fetchall()
        _annotate_links(links, conn)
        projected, sources = case_evidence(links, case['fields'])
        subjects = {c.get('subject_id', 'incident') for item in projected.values() for c in item.get('claims', [])}
        if any(sum(subject.startswith(role + '_') for subject in subjects) > 1 for role in ('victim', 'offender')):
            raise ValueError('Multiple people require review of the gold row model before publication.')
        review_fields = {key: value for key, value in case['fields'].items() if key != 'case_id'}
        profile = {key: projected.get(key, {'claims': []}) for key in review_fields}
        validated = apply_coding_review(profile, sources,
            {'reason': reason.strip(), 'codebook_version': CODEBOOK_VERSION,
             'fields': {key: {**value, 'source_ids': value.get('source_ids', value.get('evidence', []))}
                        for key, value in review_fields.items()}}, tuple(review_fields))
        payload = {'fields': validated['coded_fields'], 'gold_key': case['gold_key'], 'reason': reason.strip(),
                   'investigations': links, 'evidence_fields': projected, 'sources': sources,
                   'codebook_version': CODEBOOK_VERSION, 'snapshot_version': 2}
        created = conn.execute('''INSERT INTO research_case_publications(case_id,revision,approved_by,snapshot)
            VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING revision''', [case['id'], case['revision'], self.actor, Jsonb(payload)]).fetchone()
        if not created:
            return case['revision']
        conn.execute('''INSERT INTO research_case_history(case_id,revision,action,actor,reason,payload)
            VALUES (%s,%s,'approval',%s,%s,%s)''', [case['id'], case['revision'], self.actor, reason.strip(), Jsonb(payload)])

        return case['revision']

    def publications(self):
        with read_connection() as conn:
            return conn.execute('''SELECT p.*,c.title,c.gold_key FROM research_case_publications p
                JOIN research_cases c ON c.id=p.case_id ORDER BY p.approved_at DESC''').fetchall()

    def publish(self, case_id, revision, gold=None):
        from research_app.gold import GoldStore
        with connection() as conn:
            # Serialize our publishers across cases and retain a durable attempt receipt.
            conn.execute("SELECT pg_advisory_lock(hashtext('gold-publication'))")
            try:
                with conn.transaction():
                    conn.execute('SELECT id FROM research_cases WHERE id=%s FOR UPDATE', [case_id])
                    record = conn.execute('SELECT * FROM research_case_publications WHERE case_id=%s AND revision=%s FOR UPDATE', [case_id, revision]).fetchone()
                    if not record:
                        raise ValueError('Approve this revision before publication.')
                    if record['status'] == 'published':
                        return True
                    newer = conn.execute('SELECT 1 FROM research_case_publications WHERE case_id=%s AND revision>%s', [case_id, revision]).fetchone()
                    if newer:
                        raise ValueError('A newer approved revision exists; publish that revision instead.')
                    previous = conn.execute("SELECT snapshot FROM research_case_publications WHERE case_id=%s AND status='published' AND revision<%s ORDER BY revision DESC LIMIT 1", [case_id, revision]).fetchone()
                    retry = record.get('attempt_started_at') is not None
                    conn.execute("UPDATE research_case_publications SET status='publishing',attempt_started_at=coalesce(attempt_started_at,now()) WHERE case_id=%s AND revision=%s", [case_id, revision])
                try:
                    writer = gold if gold is not None else GoldStore()
                    options = {'previous_snapshot': previous['snapshot']} if previous else {}
                    if gold is None or retry:
                        options['allow_existing'] = retry
                    writer.publish(record['snapshot'], **options)
                except Exception:
                    logging.getLogger(__name__).exception('Gold publication failed for case %s revision %s', case_id, revision)
                    conn.execute("UPDATE research_case_publications SET status='failed', error='Gold publication failed; check backend logs and retry.' WHERE case_id=%s AND revision=%s", [case_id, revision])
                    return False
                conn.execute("UPDATE research_case_publications SET status='published', published_at=now(), error=NULL WHERE case_id=%s AND revision=%s", [case_id, revision])
                return True
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtext('gold-publication'))")


def evidence_options(links):
    options = {}
    for link in links:
        state = link['snapshot']
        for source_id, source in state.get('sources', {}).items():
            options[link['investigation_id'] + ':' + source_id] = source.get('title') or source.get('url') or source_id
        for result in state.get('results', []):
            if result.get('url'):
                options[link['investigation_id'] + ':' + result['url']] = result.get('title') or result['url']
    return options


if __name__ == '__main__':
    setup()
    print('Shared case collaboration tables initialized.')
