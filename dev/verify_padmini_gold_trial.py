import os
from research_app.gold_fields import HIGHLIGHTED_FIELDS
from research_app.search_audit import SearchAuditStore
from dev.write_padmini_gold_trial import VALUES

os.environ["DATABRICKS_CONFIG_PROFILE"] = "pc"
store = SearchAuditStore("/Volumes/homicide_research/research/sources_documents", "a5e11b7fe2c6dbbc")
columns = ", ".join("`" + field + "`" for field in HIGHLIGHTED_FIELDS)
with store._connection() as connection:
    cursor = connection.cursor()
    cursor.execute(f"SELECT {columns} FROM homicide_research.research.homicide_gold")
    rows = cursor.fetchall()
    if len(rows) != 1 or list(rows[0]) != [VALUES.get(field) for field in HIGHLIGHTED_FIELDS]:
        raise ValueError("Stored row did not match reviewed values")
    print("Verified one row, five reviewed values, and fourteen null fields.")
