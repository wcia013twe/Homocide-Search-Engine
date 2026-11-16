"""Add a case key and backfill the single reviewed Padmini trial row."""
import os
from pathlib import Path
from uuid import uuid4
from databricks.sdk import WorkspaceClient
from research_app.search_audit import SearchAuditStore

os.environ["DATABRICKS_CONFIG_PROFILE"] = "pc"
client = WorkspaceClient(profile="pc")
table = "homicide_research.research.homicide_gold"
store = SearchAuditStore("/Volumes/homicide_research/research/sources_documents", "a5e11b7fe2c6dbbc")
with store._connection() as connection:
    cursor = connection.cursor()
    if "case_id" not in [c.name for c in client.tables.get(table).columns]:
        cursor.execute(Path("sql/005_gold_case_id.sql").read_text())
    cursor.execute(f"SELECT case_id FROM {table} WHERE `Offender Name_First` = ? AND `Offender Name_Last` = ?", ["Scott", "Waldron"])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError("Expected exactly one reviewed trial row")
    case_id = rows[0][0] or str(uuid4())
    artifact = store.record_profile("dfbda171-6373-421c-b2ef-ea1ec8a5d3cb", {"case_id": case_id, "trial_id": "6432dcd2-0616-43d7-9b83-df0def82648d", "action": "assign_case_id"})
    cursor.execute(f"UPDATE {table} SET case_id = ? WHERE `Offender Name_First` = ? AND `Offender Name_Last` = ? AND case_id IS NULL", [case_id, "Scott", "Waldron"])
    cursor.execute(f"SELECT case_id FROM {table}")
    assert [r[0] for r in cursor.fetchall()] == [case_id]
    print("Verified case_id:", case_id)
    print("Audit:", artifact)
