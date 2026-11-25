"""Durable source and claim references; exact source text lives in volume artifacts."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from psycopg.types.json import Jsonb

from research_app.investigation_tasks import connection, read_connection
from research_app.repository import ConflictError


def identity(*parts):
    return sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def canonical_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Evidence requires an HTTP(S) source URL without credentials.')
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', parsed.query, ''))


def setup():
    with connection() as conn, conn.transaction():
        conn.execute(Path(__file__).resolve().parents[1].joinpath('sql/postgres/002_evidence_registry.sql').read_text())


def _claims(state):
    seen = {}
    candidates = [(field, claim) for field, value in state.get('profile', {}).items()
                  for claim in value.get('claims', [])]
    candidates.extend((None, claim) for decision in state.get('field_decisions', [])
                      for claim in decision.get('claims', []))
    for field, claim in candidates:
        statement = {key: claim.get(key) for key in
                     ('source_id', 'subject_id', 'value', 'passage', 'locator', 'content_sha256')}
        fingerprint = identity(statement)
        previous = seen.get(claim['claim_id'])
        if previous is not None:
            if previous != fingerprint:
                raise ValueError('A claim ID cannot identify multiple source statements in one batch.')
            continue
        seen[claim['claim_id']] = fingerprint
        # Rejected candidates remain unassigned, rather than being presented as filled.
        yield field, claim


def prepare_state(investigation_id, state):
    """Validate the entire batch before external or database writes."""
    if not isinstance(investigation_id, str) or not investigation_id.strip():
        raise ValueError('An investigation ID is required.')
    result = deepcopy(state)
    for source in result.get('sources', {}).values():
        url = canonical_url(source.get('final_url') or source['url'])
        text = source.get('text')
        if not isinstance(text, str) or not source.get('artifact_path'):
            raise ValueError('Persist a source artifact before registering its evidence.')
        content_hash = sha256(text.encode()).hexdigest()
        if source.get('content_sha256') != content_hash:
            raise ValueError('Evidence content hash does not match its text.')
        source['document_key'] = identity('document', url)
        source['canonical_url'] = url
        source['version_id'] = identity(source['document_key'], content_hash, source['evidence_kind'])
    for field, claim in _claims(result):
        source = result.get('sources', {}).get(claim['source_id'])
        if source is None:
            raise ValueError('Claim source is missing from the evidence batch.')
        locator, passage = claim.get('locator', {}), claim.get('passage')
        start, end = locator.get('start'), locator.get('end')
        if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                or source['text'][start:end] != passage):
            raise ValueError('Claim passage must match the exact source text offsets.')
        if claim.get('content_sha256') != source['content_sha256']:
            raise ValueError('Claim content hash does not match its source.')
        claim['registry_claim_id'] = identity(investigation_id, claim['claim_id'])
        claim['passage_id'] = identity(source['version_id'], start, end, locator.get('page'))
        claim.setdefault('original_field', claim.get('field') or field or 'unassigned')
    return result


class DatabricksDocuments:
    """Match a logical document explicitly; content versions remain in artifacts."""
    def __init__(self, audit=None):
        from research_app.search_audit import SearchAuditStore
        self.audit = audit or SearchAuditStore.from_environment()

    def persist(self, source):
        table = 'homicide_research.research.documents'
        with self.audit._connection() as conn, conn.cursor() as cursor:
            cursor.execute(f'SELECT document_id FROM {table} WHERE url = ? OR url = ?',
                           [source['canonical_url'], source['url']])
            matches = {row[0] for row in cursor.fetchall()}
            if len(matches) > 1:
                raise ValueError('Multiple document records match this URL; resolve their identity first.')
            document_id = next(iter(matches), source['document_key'])
            cursor.execute(f'''MERGE INTO {table} t USING
                (SELECT ? AS document_id, ? AS url, ? AS title, ? AS raw_file_path, ? AS content_hash) s
                ON t.document_id=s.document_id WHEN NOT MATCHED THEN INSERT
                (document_id,url,title,raw_file_path,content_hash) VALUES
                (s.document_id,s.url,s.title,s.raw_file_path,s.content_hash)''',
                           [document_id, source['canonical_url'], source.get('title'),
                            source['artifact_path'], source['content_sha256']])
            return document_id

    def resolve_result(self, run_id, rank):
        with self.audit._connection() as conn, conn.cursor() as cursor:
            cursor.execute(f'SELECT search_result_id FROM {self.audit.results_table} WHERE run_id=? AND result_rank=?',
                           [run_id, rank])
            matches = {row[0] for row in cursor.fetchall() if row[0]}
            return next(iter(matches)) if len(matches) == 1 else None


def persist_state(investigation_id, state, *, actor=None, document_store=None):
    """Return annotated state only after a complete evidence batch is committed.

    Delta metadata is synced first. A failed Postgres transaction may leave harmless
    document metadata but never a partially visible claim batch. Replays reuse IDs.
    """
    result = prepare_state(investigation_id, state)
    if not result.get('sources'):
        return result
    actor = actor or state.get('researcher')
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('Authenticated researcher attribution is required.')
    documents = document_store or DatabricksDocuments()
    with connection() as conn, conn.transaction():
        # Serialize document matching across investigations; Delta has no unique URL constraint.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('evidence-document-sync'))")
        for source in result['sources'].values():
            existing = conn.execute('SELECT document_id FROM evidence_documents WHERE id=%s', [source['document_key']]).fetchone()
            source['document_id'] = existing['document_id'] if existing and existing['document_id'] else documents.persist(source)
            links = source.setdefault('search_results', [])
            if source.get('search_run_id') and source.get('result_rank') is not None:
                original = dict(search_run_id=source['search_run_id'], result_rank=source['result_rank'],
                                search_result_id=source.get('search_result_id'))
                if not any(link['search_run_id'] == original['search_run_id'] and link['result_rank'] == original['result_rank'] for link in links):
                    links.append(original)
            for link in links:
                if not link.get('search_result_id'):
                    link['search_result_id'] = documents.resolve_result(link['search_run_id'], link['result_rank'])
        for source_id, source in result['sources'].items():
            conn.execute('''INSERT INTO evidence_documents(id,canonical_url,document_id,title)
                VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING''',
                         [source['document_key'], source['canonical_url'], source['document_id'], source.get('title')])
            conn.execute('''INSERT INTO evidence_document_versions(version_id,document_key,content_sha256,evidence_kind,artifact_path,retrieved_at)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                         [source['version_id'], source['document_key'], source['content_sha256'], source['evidence_kind'], source['artifact_path'], source.get('retrieved_at')])
            previous = conn.execute('SELECT version_id FROM evidence_source_aliases WHERE investigation_id=%s AND source_id=%s',
                                    [investigation_id, source_id]).fetchone()
            if previous and previous['version_id'] != source['version_id']:
                raise ValueError('A source alias cannot change its evidence version.')
            conn.execute('INSERT INTO evidence_source_aliases VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                         [investigation_id, source_id, source['version_id']])
            for link in source['search_results']:
                conn.execute('''INSERT INTO evidence_search_links(version_id,search_run_id,result_rank,search_result_id)
                    VALUES (%s,%s,%s,%s) ON CONFLICT (version_id,search_run_id,result_rank) DO UPDATE
                    SET search_result_id=COALESCE(evidence_search_links.search_result_id,EXCLUDED.search_result_id)''',
                             [source['version_id'], link['search_run_id'], link['result_rank'], link['search_result_id']])
        for field, claim in _claims(result):
            source, locator = result['sources'][claim['source_id']], claim['locator']
            conn.execute('INSERT INTO evidence_passages VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         [claim['passage_id'], source['version_id'], claim['passage'], locator['start'], locator['end'], locator.get('page')])
            previous = conn.execute('SELECT * FROM evidence_claims WHERE id=%s', [claim['registry_claim_id']]).fetchone()
            if previous and (previous['passage_id'] != claim['passage_id'] or previous['reported_value'] != claim['value']
                             or previous['subject_id'] != claim.get('subject_id', 'incident')):
                raise ValueError('A claim ID cannot be reused for a different source statement.')
            conn.execute('''INSERT INTO evidence_claims(id,investigation_id,claim_id,subject_id,original_field,reported_value,passage_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                         [claim['registry_claim_id'], investigation_id, claim['claim_id'], claim.get('subject_id', 'incident'),
                          claim['original_field'], Jsonb(claim['value']), claim['passage_id']])
            assignment = conn.execute('SELECT * FROM evidence_field_assignments WHERE claim_key=%s ORDER BY sequence_id DESC LIMIT 1',
                                      [claim['registry_claim_id']]).fetchone()
            if not assignment:
                assignment_id = identity(claim['registry_claim_id'], 'initial', field)
                conn.execute('INSERT INTO evidence_field_assignments(assignment_id,claim_key,field_key,rationale,actor) VALUES (%s,%s,%s,%s,%s)',
                             [assignment_id, claim['registry_claim_id'], field, 'Agent proposed field assignment', actor])
            else:
                assignment_id = assignment['assignment_id']
            claim['assignment_id'] = assignment_id
    return result


def reassign_claim(investigation_id, claim_id, field_key, *, actor, reason,
                   expected_assignment_id, conn=None):
    """Append an assignment; a supplied connection shares the caller's transaction."""
    if not actor.strip() or not reason.strip():
        raise ValueError('Reassignment requires researcher attribution and a reason.')
    if conn is None:
        with connection() as owned, owned.transaction():
            return reassign_claim(investigation_id, claim_id, field_key, actor=actor, reason=reason,
                                  expected_assignment_id=expected_assignment_id, conn=owned)
    claim_key = identity(investigation_id, claim_id)
    found = conn.execute('SELECT id FROM evidence_claims WHERE id=%s FOR UPDATE', [claim_key]).fetchone()
    if not found:
        raise ValueError('Claim does not belong to this investigation.')
    current = conn.execute('SELECT assignment_id FROM evidence_field_assignments WHERE claim_key=%s ORDER BY sequence_id DESC LIMIT 1', [claim_key]).fetchone()
    if not current or current['assignment_id'] != expected_assignment_id:
        raise ConflictError('Field assignment changed; reload before saving.')
    assignment_id = identity(claim_key, expected_assignment_id, field_key, actor, reason)
    conn.execute('''INSERT INTO evidence_field_assignments(assignment_id,claim_key,field_key,rationale,actor,supersedes)
        VALUES (%s,%s,%s,%s,%s,%s)''',
                 [assignment_id, claim_key, field_key, reason.strip(), actor, expected_assignment_id])
    return assignment_id


def annotate_state(investigation_id, state, *, conn=None):
    """Read registry references without advancing a graph or changing an interrupt."""
    result = deepcopy(state)
    if not result.get('sources'):
        return result
    if conn is None:
        with read_connection() as owned:
            return annotate_state(investigation_id, result, conn=owned)
    rows = conn.execute('''SELECT a.source_id,v.version_id,d.id AS document_key,d.document_id
        FROM evidence_source_aliases a JOIN evidence_document_versions v USING(version_id)
        JOIN evidence_documents d ON d.id=v.document_key WHERE a.investigation_id=%s''',
        [investigation_id]).fetchall()
    for row in rows:
        source = result['sources'].get(row['source_id'])
        if source is not None:
            source.update({key: row[key] for key in ('version_id', 'document_key', 'document_id')})
    claims = conn.execute('''SELECT c.claim_id,c.id AS registry_claim_id,c.passage_id,a.assignment_id,a.field_key
        FROM evidence_claims c LEFT JOIN LATERAL
        (SELECT assignment_id,field_key FROM evidence_field_assignments WHERE claim_key=c.id
         ORDER BY sequence_id DESC LIMIT 1) a ON TRUE
        WHERE c.investigation_id=%s''', [investigation_id]).fetchall()
    by_id = {row['claim_id']: row for row in claims}
    for _, claim in _claims(result):
        row = by_id.get(claim['claim_id'])
        if row:
            claim.update({key: row[key] for key in ('registry_claim_id', 'passage_id', 'assignment_id')})
            claim['assigned_field'] = row['field_key']
    return result
