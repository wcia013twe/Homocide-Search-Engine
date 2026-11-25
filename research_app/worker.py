"""Drain durable commands from a Databricks Job; never replay uncertain research."""
import logging
from contextlib import contextmanager
from threading import Event, Thread

from research_app import investigation_tasks as tasks
from research_app.hosted_session import open_hosted_session, scoped_session_id

LOG = logging.getLogger(__name__)
def command_lock(command):
    return 'homicide-research-command:' + command['id']


def release(conn, command):
    conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s, 0))', [command_lock(command)])


def recover_interrupted(conn):
    # A live runner holds its command lock, even between node heartbeats.
    with conn.transaction():
        running = conn.execute("SELECT * FROM investigation_commands WHERE status='running' FOR UPDATE SKIP LOCKED").fetchall()
        for command in running:
            if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked', [command_lock(command)]).fetchone()['locked']:
                continue
            try:
                conn.execute("UPDATE investigation_commands SET status='interrupted',error='Worker stopped; inspect saved evidence before retrying.',finished_at=now() WHERE id=%s", [command['id']])
                conn.execute("UPDATE investigation_tasks SET status='interrupted',error='Worker stopped; automatic replay is disabled.',revision=revision+1 WHERE id=%s", [command['investigation_id']])
            finally:
                release(conn, command)


def claim(conn):
    with conn.transaction():
        command = conn.execute("SELECT * FROM investigation_commands WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if command:
            if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked', [command_lock(command)]).fetchone()['locked']:
                return None
            conn.execute("UPDATE investigation_commands SET status='running',started_at=now(),heartbeat_at=now() WHERE id=%s", [command['id']])
            if command['investigation_id']:
                conn.execute("UPDATE investigation_tasks SET status='running',stage=%s,heartbeat_at=now(),error=NULL WHERE id=%s", [command['kind'], command['investigation_id']])
        return command


@contextmanager
def heartbeat(command):
    stop = Event()
    def beat():
        while not stop.wait(15):
            try:
                with tasks.connection() as conn:
                    conn.execute("UPDATE investigation_commands SET heartbeat_at=now() WHERE id=%s AND status='running'", [command['id']])
                    conn.execute('UPDATE investigation_tasks SET heartbeat_at=now() WHERE id=%s', [command['investigation_id']])
            except Exception:
                LOG.exception('Worker heartbeat failed')
    thread = Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def persist_progress(investigation_id, actor, snapshot):
    from research_app.evidence_registry import persist_state
    state = persist_state(investigation_id, snapshot.values, actor=actor)
    stage = snapshot.next[0] if snapshot.next else state.get('status', 'finished')
    with tasks.connection() as conn:
        conn.execute('UPDATE investigation_tasks SET stage=%s,heartbeat_at=now() WHERE id=%s AND actor=%s', [stage, investigation_id, actor])
    return state


def execute(command):
    actor, payload = command['actor'], command['payload']
    if command['kind'] == 'publish':
        from research_app.collaboration import CaseStore
        if not CaseStore(actor).publish(payload['case_id'], payload['revision']):
            raise RuntimeError('Publication failed; its approved snapshot remains saved.')
        return 'published'
    task = tasks.get_task(command['investigation_id'], actor)
    key = scoped_session_id(task['id'], actor)
    def report_stage(stage):
        with tasks.connection() as conn:
            conn.execute('UPDATE investigation_tasks SET stage=%s,heartbeat_at=now() WHERE id=%s AND actor=%s',
                         [stage, task['id'], actor])
    with open_hosted_session(key, report_stage=report_stage, investigation_id=task['id'], model_endpoint=task.get('model_endpoint')) as session:
        def progress(snapshot):
            persist_progress(task['id'], actor, snapshot)
        session.progress = progress
        if command['kind'] == 'start':
            session.start(key, actor, task['query'], task.get('search_provider') or 'Exa', automatic_searches=True)
        elif command['kind'] == 'resume':
            session.resume(key, actor, payload)
        elif command['kind'] == 'finalize':
            session.finalize(key, actor, payload)
        else:
            raise ValueError('Unsupported command.')
        snapshot = session.inspect(key, actor)
        state = persist_progress(task['id'], actor, snapshot)
    # Projection uses durable evidence identifiers and does not alter execution state.
    from research_app.collaboration import CaseStore
    CaseStore(actor).link_snapshot(task, state)
    return 'awaiting_review' if any(item.interrupts for item in snapshot.tasks) else 'finished'


def finish(conn, command, status, error=None):
    with conn.transaction():
        conn.execute('UPDATE investigation_commands SET status=%s,error=%s,finished_at=now() WHERE id=%s',
                     ['failed' if error else 'succeeded', error, command['id']])
        if command['investigation_id']:
            conn.execute('''UPDATE investigation_tasks SET status=%s,error=%s,heartbeat_at=now(),revision=revision+1
                WHERE id=%s AND actor=%s''', [status, error, command['investigation_id'], command['actor']])


def drain():
    with tasks.connection() as conn:
        recover_interrupted(conn)
        while command := claim(conn):
            try:
                try:
                    with heartbeat(command):
                        status = execute(command)
                    finish(conn, command, status)
                except Exception as exc:
                    LOG.exception('Command failed: %s', command['id'])
                    diagnostic_ref = ''
                    try:
                        import os
                        from databricks.sdk import WorkspaceClient
                        from research_app.issue_reporting import diagnostic, report_path, write_json
                        detail = diagnostic(exc, 'worker.' + command['kind'])
                        detail.update(command_id=command['id'], investigation_id=command['investigation_id'])
                        write_json(WorkspaceClient(), report_path(os.environ['HR_SEARCH_AUDIT_VOLUME'], command['id'], 'worker-errors'), detail)
                        diagnostic_ref = ' Diagnostic: ' + command['id']
                    except Exception:
                        LOG.warning('Private diagnostic could not be saved for command %s', command['id'])
                    finish(conn, command, 'failed', 'Command failed. Inspect saved state and backend logs before retrying.' + diagnostic_ref)
            finally:
                release(conn, command)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    drain()
