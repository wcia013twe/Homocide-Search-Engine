"""Preview or apply only missing audit columns in the existing research schema."""
import argparse
from pathlib import Path
import re
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState


def missing_statements(client):
    source = (Path(__file__).resolve().parents[1] / "sql" / "003_extend_existing_search_tables.sql").read_text()
    changes = []
    for table, definition in re.findall(r"ALTER TABLE ([\w.]+) ADD COLUMNS \((.*?)\);", source, re.S):
        existing = {column.name for column in client.tables.get(table).columns}
        fields = re.findall(r"^\s*(\w+)\s+(STRING|TIMESTAMP|BIGINT|DECIMAL\(18,6\))\s*,?\s*$", definition, re.M)
        additions = [f"{name} {kind}" for name, kind in fields if name not in existing]
        if additions:
            changes.append(f"ALTER TABLE {table} ADD COLUMNS ({', '.join(additions)})")
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="pc")
    parser.add_argument("--warehouse", default="a5e11b7fe2c6dbbc")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = WorkspaceClient(profile=args.profile)
    statements = missing_statements(client)
    for statement in statements:
        print(statement, flush=True)
        if args.apply:
            execution = client.statement_execution.execute_statement(
                warehouse_id=args.warehouse, statement=statement, wait_timeout="10s",
            )
            print(f"Statement: {execution.statement_id}", flush=True)
            while execution.status.state in (StatementState.PENDING, StatementState.RUNNING):
                time.sleep(3)
                execution = client.statement_execution.get_statement(execution.statement_id)
            if execution.status.state != StatementState.SUCCEEDED:
                raise RuntimeError(f"Migration failed: {execution.status}")
    print("Schema verified." if args.apply and not missing_statements(client) else "Preview only." , flush=True)


if __name__ == "__main__":
    main()
