"""Run the UI and worker against isolated local Postgres and live Databricks services."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault('DATABRICKS_CONFIG_PROFILE', 'magneto')
os.environ['HR_RESEARCH_CHECKPOINT_DSN'] = 'postgresql://localhost:55439/postgres'
os.environ.setdefault('HR_SEARCH_AUDIT_VOLUME', '/Volumes/homicide_research/research/sources_documents')
os.environ.setdefault('HR_SEARCH_AUDIT_WAREHOUSE_ID', 'a5e11b7fe2c6dbbc')
os.environ.setdefault('HR_RESEARCH_MODEL_ENDPOINT', 'databricks-gpt-oss-20b')
os.environ.pop('HR_RESEARCH_WORKER_JOB_ID', None)
os.environ.pop('HR_LAKEBASE_ENDPOINT', None)

from databricks.sdk import WorkspaceClient

if not os.environ.get('EXA_API_KEY'):
    secret = WorkspaceClient().secrets.get_secret(scope='homicide-research-dev', key='EXA_API_KEY')
    os.environ['EXA_API_KEY'] = base64.b64decode(secret.value, validate=True).decode('utf-8')

from langgraph.checkpoint.postgres import PostgresSaver
from research_app.investigation_tasks import connection, setup as setup_queue
from research_app.collaboration import setup as setup_cases
from research_app.evidence_registry import setup as setup_evidence

with connection(prepare_threshold=0) as conn:
    PostgresSaver(conn).setup()
setup_queue()
setup_cases()
setup_evidence()

stop = threading.Event()
def run_worker():
    from research_app.worker import drain
    while not stop.is_set():
        try:
            drain()
        except Exception:
            import logging
            logging.exception('Local worker failed')
        stop.wait(3)

threading.Thread(target=run_worker, daemon=True).start()
print('Local UI: http://127.0.0.1:8501 (Ctrl-C to stop)', flush=True)
try:
    subprocess.run([sys.executable, '-m', 'streamlit', 'run', 'app.py',
                    '--server.address', '127.0.0.1', '--server.port', '8501'], check=True)
finally:
    stop.set()
