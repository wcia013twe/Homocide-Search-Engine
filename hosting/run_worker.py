"""Databricks Job entry point. Arguments contain configuration, never tokens."""
import argparse
import base64
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(globals().get('__file__', sys.argv[0])).resolve().parents[1]))


def configure(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lakebase-endpoint', required=True)
    parser.add_argument('--db-host', required=True)
    parser.add_argument('--db-name', required=True)
    parser.add_argument('--db-user', required=True)
    parser.add_argument('--audit-volume', required=True)
    parser.add_argument('--warehouse-id', required=True)
    parser.add_argument('--model-endpoint', required=True)
    parser.add_argument('--secret-scope', default='homicide-research-dev')
    args = parser.parse_args(argv)
    values = {
        'HR_LAKEBASE_ENDPOINT': args.lakebase_endpoint,
        'PGHOST': args.db_host, 'PGDATABASE': args.db_name, 'PGUSER': args.db_user,
        'HR_SEARCH_AUDIT_VOLUME': args.audit_volume,
        'HR_SEARCH_AUDIT_WAREHOUSE_ID': args.warehouse_id,
        'HR_RESEARCH_MODEL_ENDPOINT': args.model_endpoint,
    }
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient()
    for key in ('EXA_API_KEY', 'BRAVE_API_KEY'):
        secret = client.secrets.get_secret(scope=args.secret_scope, key=key)
        if not secret.value:
            raise ValueError('Provider secret is empty: ' + key)
        values[key] = base64.b64decode(secret.value, validate=True).decode('utf-8')
    os.environ.update(values)


if __name__ == '__main__':
    configure()
    from research_app.worker import drain
    drain()
