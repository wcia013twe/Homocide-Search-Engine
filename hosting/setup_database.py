"""Explicit deployment migration step, run as the Lakebase project owner."""
import argparse
from run_worker import configure

parser = argparse.ArgumentParser()
parser.add_argument('--app-role', required=True)
args, remaining = parser.parse_known_args()
configure(remaining)

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from research_app.investigation_tasks import connection, setup as setup_queue
from research_app.collaboration import setup as setup_cases
from research_app.evidence_registry import setup as setup_evidence

with connection(prepare_threshold=0) as conn:
    PostgresSaver(conn).setup()
setup_queue()
setup_cases()
setup_evidence()
with connection() as conn, conn.transaction():
    role = sql.Identifier(args.app_role)
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(role))
    tables = ('checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'investigation_tasks',
              'investigation_commands', 'research_usage_settings', 'research_usage_calls', 'research_model_prices', 'research_cases', 'research_case_identifiers',
              'research_case_investigations', 'research_case_history', 'research_case_publications',
              'evidence_documents', 'evidence_document_versions', 'evidence_source_aliases',
              'evidence_search_links', 'evidence_passages', 'evidence_claims', 'evidence_field_assignments')
    for table in tables:
        conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON TABLE public.{} TO {}').format(sql.Identifier(table), role))
    for sequence in ('research_case_history_id_seq', 'evidence_field_assignments_sequence_id_seq'):
        conn.execute(sql.SQL('GRANT USAGE, SELECT ON SEQUENCE public.{} TO {}').format(sql.Identifier(sequence), role))
print('Checkpoint, queue, evidence, and case migrations completed; app grants applied.')
