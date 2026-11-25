"""Durable researcher-scoped investigations and backend commands."""
import atexit
import logging
import os
from functools import lru_cache
from pathlib import Path
from threading import Lock
from uuid import uuid4

from psycopg.types.json import Jsonb

from research_app.repository import ConflictError


# Command timestamps already survive app/worker restarts. Human review time is
# included in wall time, but excluded from queue and worker time.
TASK_TIMING = '''SELECT t.*, timing.* FROM investigation_tasks t
    LEFT JOIN LATERAL (
        SELECT min(finished_at) FILTER (WHERE kind='start' AND status='succeeded') AS first_review_at,
            max(finished_at) AS last_finished_at,
            coalesce(sum(extract(epoch FROM coalesce(finished_at,now())-started_at))
                FILTER (WHERE started_at IS NOT NULL),0)::double precision AS worker_seconds,
            coalesce(sum(extract(epoch FROM coalesce(started_at,now())-created_at)),0)::double precision AS queue_seconds
        FROM investigation_commands WHERE investigation_id=t.id
    ) timing ON true'''


def dispatch():
    """Wake a runner after commit; the scheduled runner recovers trigger failures."""
    job_id = os.environ.get('HR_RESEARCH_WORKER_JOB_ID')
    if not job_id:
        return
    try:
        from databricks.sdk import WorkspaceClient
        WorkspaceClient().jobs.run_now(job_id=int(job_id))
    except Exception:
        logging.getLogger(__name__).exception('Worker trigger failed; command remains queued for scheduled pickup')


def database_configured():
    return bool(os.environ.get('HR_RESEARCH_CHECKPOINT_DSN') or os.environ.get('HR_LAKEBASE_ENDPOINT'))


def connection(**options):
    import psycopg
    from psycopg.rows import dict_row
    settings = dict(autocommit=True, row_factory=dict_row, connect_timeout=10)
    settings.update(options)
    endpoint = os.environ.get('HR_LAKEBASE_ENDPOINT')
    if endpoint:
        settings.setdefault('sslmode', 'require')
        from databricks.sdk import WorkspaceClient
        token = WorkspaceClient().postgres.generate_database_credential(endpoint=endpoint)
        return psycopg.connect(host=os.environ['PGHOST'], dbname=os.environ['PGDATABASE'],
            user=os.environ['PGUSER'], password=token.token, **settings)
    return psycopg.connect(os.environ['HR_RESEARCH_CHECKPOINT_DSN'], **settings)


_read_pool_lock = Lock()


@lru_cache(maxsize=4)
def _read_pool(endpoint, host, database, user):
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    class LakebaseConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo='', **kwargs):
            from databricks.sdk import WorkspaceClient
            token = WorkspaceClient().postgres.generate_database_credential(endpoint=endpoint)
            return super().connect(conninfo, password=token.token, **kwargs)

    pool = ConnectionPool(connection_class=LakebaseConnection,
        kwargs=dict(host=host, dbname=database, user=user, sslmode='require',
                    autocommit=True, row_factory=dict_row, connect_timeout=10, prepare_threshold=0),
        min_size=0, max_size=4, timeout=10, max_idle=300, max_lifetime=3300,
        check=ConnectionPool.check_connection, open=True)
    atexit.register(pool.close)
    return pool


def read_connection():
    """Lease independent read connections; execution locks keep dedicated sessions."""
    endpoint = os.environ.get('HR_LAKEBASE_ENDPOINT')
    if not endpoint:
        return connection(prepare_threshold=0)
    with _read_pool_lock:
        pool = _read_pool(endpoint, os.environ['PGHOST'], os.environ['PGDATABASE'], os.environ['PGUSER'])
    return pool.connection()


def setup():
    with connection() as conn, conn.transaction():
        conn.execute('''CREATE TABLE IF NOT EXISTS investigation_tasks (
            id TEXT PRIMARY KEY, actor TEXT NOT NULL, query TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
        conn.execute(Path(__file__).resolve().parents[1].joinpath('sql/postgres/003_worker.sql').read_text())
        conn.execute(Path(__file__).resolve().parents[1].joinpath('sql/postgres/005_usage.sql').read_text())
        conn.execute(Path(__file__).resolve().parents[1].joinpath('sql/postgres/006_model_prices.sql').read_text())


def submit(task, target_case=None):
    if not task['actor'].strip() or not task['query'].strip():
        raise ValueError('Researcher and incident query are required.')
    from research_app.usage_store import settings
    config = settings(task['actor'])
    if not config['model_endpoint']:
        raise ValueError('Set a model endpoint on the Usage page before starting an investigation.')
    with connection() as conn, conn.transaction():
        conn.execute('INSERT INTO investigation_tasks (id, actor, query, search_provider, model_endpoint) VALUES (%s, %s, %s, %s, %s)',
                     [task['id'], task['actor'], task['query'].strip(), config['search_provider'], config['model_endpoint']])
        from research_app.collaboration import CaseStore
        case_id = CaseStore(task['actor'])._link_snapshot(conn, task, {}, target_case,
            'Investigation submitted for this case')
        conn.execute('''INSERT INTO investigation_commands(id,investigation_id,actor,kind,payload)
            VALUES (%s,%s,%s,'start',%s)''', [str(uuid4()), task['id'], task['actor'], Jsonb({'submitted_by_email': task.get('submitted_by_email', task['actor'])})])
    dispatch()
    return case_id


def enqueue(investigation_id, actor, kind, payload=None, expected_revision=None, command_id=None):
    if kind not in ('resume', 'finalize'):
        raise ValueError('Choose a supported investigation command.')
    with connection() as conn, conn.transaction():
        task = conn.execute('SELECT * FROM investigation_tasks WHERE id=%s AND actor=%s FOR UPDATE',
                            [investigation_id, actor]).fetchone()
        if not task:
            raise ValueError('Investigation not found.')
        if expected_revision is not None and task['revision'] != expected_revision:
            raise ConflictError('Investigation changed. Reload before submitting review.')
        if task['status'] != 'awaiting_review':
            raise ConflictError('Investigation is not awaiting review.')
        if conn.execute("SELECT 1 FROM investigation_commands WHERE investigation_id=%s AND status IN ('queued','running')", [investigation_id]).fetchone():
            raise ConflictError('An investigation command is already queued or running.')
        key = command_id or str(uuid4())
        conn.execute('''INSERT INTO investigation_commands(id,investigation_id,actor,kind,payload)
            VALUES (%s,%s,%s,%s,%s)''', [key, investigation_id, actor, kind, Jsonb(payload or {})])
        conn.execute("UPDATE investigation_tasks SET status='queued',stage=%s,error=NULL,revision=revision+1 WHERE id=%s", [kind, investigation_id])
    dispatch()
    return key


def enqueue_publication(case_id, revision, actor):
    # Approval ownership and case visibility are checked by CaseStore before this call.
    key = f'publish:{case_id}:{revision}'
    with connection() as conn:
        queued = conn.execute('''INSERT INTO investigation_commands(id,actor,kind,payload) VALUES (%s,%s,'publish',%s)
            ON CONFLICT (id) DO UPDATE SET status='queued',error=NULL
            WHERE investigation_commands.status IN ('failed','interrupted') RETURNING id ''',
                     [key, actor, Jsonb({'case_id': case_id, 'revision': revision})]).fetchone()
    if queued:
        dispatch()
    return key


def get_task(investigation_id, actor):
    with read_connection() as conn:
        task = conn.execute(TASK_TIMING + ' WHERE t.id=%s AND t.actor=%s', [investigation_id, actor]).fetchone()
        if not task:
            raise ValueError('Investigation not found.')
        return task


def set_status(task_id, actor, status):
    with connection() as conn:
        conn.execute('UPDATE investigation_tasks SET status=%s WHERE id=%s AND actor=%s', [status, task_id, actor])


def list_tasks(actor):
    with read_connection() as conn:
        return conn.execute(TASK_TIMING + ' WHERE t.actor=%s ORDER BY t.created_at DESC', [actor]).fetchall()


def list_case_tasks(case_id):
    """All team runs for a case; saved legacy links remain visible without a task."""
    with read_connection() as conn:
        return conn.execute(f'''WITH timed AS ({TASK_TIMING})
            SELECT t.*, i.investigation_id AS id, coalesce(t.actor,i.owner) AS actor,
                coalesce((SELECT c.payload->>'submitted_by_email' FROM investigation_commands c
                    WHERE c.investigation_id=i.investigation_id AND c.kind='start' LIMIT 1),t.actor,i.owner) AS submitted_by_email,
                coalesce(t.query,i.snapshot->>'query','Saved investigation') AS query,
                coalesce(t.status,'saved') AS status, coalesce(t.created_at,i.linked_at) AS created_at
            FROM research_case_investigations i LEFT JOIN timed t ON t.id=i.investigation_id
            WHERE i.case_id=%s ORDER BY coalesce(t.created_at,i.linked_at) DESC, i.investigation_id DESC''', [case_id]).fetchall()


def get_case_task(investigation_id, case_id):
    with read_connection() as conn:
        task = conn.execute(TASK_TIMING + ''' JOIN research_case_investigations i ON i.investigation_id=t.id
            WHERE t.id=%s AND i.case_id=%s''', [investigation_id, case_id]).fetchone()
    if not task:
        raise ValueError('Investigation not found in this case.')
    return task
