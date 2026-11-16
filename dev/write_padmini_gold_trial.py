"""Write the manually reviewed, source-supported subset of one Padmini trial."""
import json
import os
from pathlib import Path

from research_app.gold_fields import HIGHLIGHTED_FIELDS
from research_app.search_audit import SearchAuditStore

TRIAL = "6432dcd2-0616-43d7-9b83-df0def82648d"
SOURCE_ID = "a41a3bae-93f3-4704-9646-4378358ff750:2"
VALUES = {"Offender Name_First": "Scott", "Offender Name_Last": "Waldron",
          "Offender Gender": "Male", "Offender Age": "49",
          "Incident Information_Choice": "murder-suicide"}


def main():
    os.environ["DATABRICKS_CONFIG_PROFILE"] = "pc"
    payload = json.loads(Path(f"local-audit/gold-trial-{TRIAL}.json").read_text(encoding="utf-8"))
    source = payload["sources"][SOURCE_ID]
    passage = ("After extensive investigation into the deaths of Scott Waldron, 49 and Padmini Waldron, 47, "
               "at 9097 Cape Cod Road, DeLand, FL the DeLand Police Department Criminal Investigation Division "
               "has concluded that this was a case of murder-suicide. In this incident it has been concluded that "
               "Scott Waldron shot and killed his wife Padmini Waldron and then took his own life.")
    gender_passage = "a deceased male, later identified as Scott Waldron, 49"
    if passage not in source["text"] or gender_passage not in source["text"]:
        raise ValueError("Reviewed evidence no longer matches the saved excerpt")
    store = SearchAuditStore("/Volumes/homicide_research/research/sources_documents", "a5e11b7fe2c6dbbc")
    with store._connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM homicide_research.research.homicide_gold")
        if cursor.fetchone()[0] != 0:
            raise ValueError("Gold table is not empty; refusing a duplicate or ambiguous insert.")
        audit_path = store.record_profile(payload["searches"][-1]["run_id"], {
            "trial_id": TRIAL, "kind": "manual_review_before_gold_write", "values": VALUES,
            "source_id": SOURCE_ID, "source_url": source["url"], "passages": [passage, gender_passage],
            "rejected": "Mauritian is not established ethnicity; other conflicting or uncertain fields left empty.",
        })
        columns = ", ".join("`" + name.replace("`", "``") + "`" for name in HIGHLIGHTED_FIELDS)
        placeholders = ", ".join("?" for _ in HIGHLIGHTED_FIELDS)
        cursor.execute(f"INSERT INTO homicide_research.research.homicide_gold ({columns}) SELECT {placeholders} WHERE NOT EXISTS (SELECT 1 FROM homicide_research.research.homicide_gold)",
                       [VALUES.get(name) for name in HIGHLIGHTED_FIELDS])
        cursor.execute("SELECT COUNT(*) FROM homicide_research.research.homicide_gold")
        print(json.dumps({"row_count": cursor.fetchone()[0], "review_artifact": audit_path, "values": VALUES}))


if __name__ == "__main__":
    main()
