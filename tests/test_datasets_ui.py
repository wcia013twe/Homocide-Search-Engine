"""AppTest exercises forms through the actual SQLite validation boundary."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from research_app.repository import Repository


class DatasetUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {"HR_DATA_DIR": self.directory.name, "HR_REQUIRE_PROXY_IDENTITY": "false"})
        environment.start()
        self.addCleanup(environment.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.app.radio(key="nav_page").set_value("Datasets").run()
        self.assertFalse(self.app.exception)

    def widget(self, kind, label):
        return next(widget for widget in getattr(self.app, kind) if widget.label == label)

    def click(self, label):
        self.widget("button", label).click().run()
        self.assertFalse(self.app.exception)

    def saved(self):
        return Repository(Path(self.directory.name) / "workspaces.sqlite3", self.app.session_state["research_user"]).load()[0]

    def test_review_persists_typed_value_and_audit(self):
        self.app.text_input(key="ds_value_incident-008_victim_age").set_value("64")
        self.app.text_area(key="ds_reason_incident-008").set_value("Corrected after checking source.")
        self.click("Save review")
        self.assertFalse(self.app.error)
        saved = self.saved()
        incident = next(i for i in saved["incidents"] if i["id"] == "incident-008")
        self.assertEqual(incident["fields"]["victim_age"]["value"], 64)
        audit = next(r for r in saved["reviews"] if r["field"] == "victim_age")
        self.assertEqual(audit["previous_value"], 63)
        self.assertEqual(audit["new_value"], 64)
        self.assertEqual(audit["new_evidence_ids"], ["source-008"])
        self.assertEqual(audit["reviewer"], self.app.session_state["research_user"])

    def test_review_without_reason_does_not_persist(self):
        self.app.text_input(key="ds_value_incident-008_victim_age").set_value("64")
        self.click("Save review")
        self.assertTrue(self.app.error)
        self.assertEqual(self.saved()["reviews"], [])

    def test_reported_field_without_evidence_does_not_persist(self):
        self.app.multiselect(key="ds_evidence_incident-008_victim_age").set_value([])
        self.app.text_area(key="ds_reason_incident-008").set_value("Attempt unsupported correction.")
        self.click("Save review")
        self.assertTrue(self.app.error)
        self.assertEqual(self.saved()["reviews"], [])

    def test_create_dataset_and_edit_settings(self):
        self.widget("text_input", "Dataset name").set_value("New research collection")
        self.widget("text_area", "Research scope").set_value("Scope for an empty collection.")
        self.click("Create dataset")
        self.assertFalse(self.app.error)
        created = next(d for d in self.saved()["datasets"] if d["name"] == "New research collection")
        self.assertEqual(created["incident_ids"], [])
        self.widget("text_input", "Name").set_value("Renamed research collection")
        self.click("Save settings")
        self.assertFalse(self.app.error)
        self.assertTrue(any(d["name"] == "Renamed research collection" for d in self.saved()["datasets"]))

    def test_edit_variable_definition_retains_history(self):
        self.widget("text_area", "Definition and coding instructions").set_value("Age explicitly reported in the original document.")
        self.widget("text_input", "New codebook version").set_value("demo-1.1")
        self.click("Save codebook definition")
        self.assertFalse(self.app.error)
        variable = self.saved()["variables"][0]
        self.assertEqual(variable["codebook_version"], "demo-1.1")
        self.assertEqual(variable["history"][0]["codebook_version"], "demo-1.0")
        saved = self.saved()
        self.assertFalse(any(i["review_status"] == "Verified" for i in saved["incidents"]))
        self.assertEqual(len(saved["reviews"]), 2)

    def test_create_incident_preserves_reciprocal_source_links(self):
        dataset_id = "dataset-texas-2023"
        self.app.text_input(key=f"ds_new_incident_title_{dataset_id}").set_value("New source-backed incident")
        self.app.text_input(key=f"ds_new_incident_county_{dataset_id}").set_value("Cedar County (fictional)")
        self.app.text_input(key=f"ds_new_incident_state_{dataset_id}").set_value("TX")
        self.app.multiselect(key=f"ds_new_incident_sources_{dataset_id}").set_value(["source-001"])
        self.click("Create incident")
        self.assertFalse(self.app.error)
        saved = self.saved()
        incident = next(i for i in saved["incidents"] if i["title"] == "New source-backed incident")
        self.assertEqual(incident["review_status"], "Needs review")
        self.assertEqual(incident["date"], "")
        self.assertIn(incident["id"], saved["datasets"][0]["incident_ids"])
        self.assertIn(incident["id"], saved["sources"][0]["incident_ids"])
        self.assertTrue(all(f == {"value": None, "status": "Not Reported", "evidence_ids": []} for f in incident["fields"].values()))

    def test_create_incident_requires_evidence(self):
        self.app.text_input(key="ds_new_incident_title_dataset-texas-2023").set_value("Unsupported incident")
        self.click("Create incident")
        self.assertTrue(self.app.error)
        self.assertEqual(len(self.saved()["incidents"]), 8)

    def test_create_variable_initializes_existing_incidents(self):
        self.app.text_input(key="ds_new_variable_key").set_value("weapon_type")
        self.app.text_input(key="ds_new_variable_label").set_value("Weapon type")
        self.app.selectbox(key="ds_new_variable_type").set_value("category")
        self.app.text_area(key="ds_new_variable_categories").set_value("Firearm\nOther")
        self.app.text_area(key="ds_new_variable_definition").set_value("Weapon explicitly identified by the cited source.")
        self.click("Add variable")
        self.assertFalse(self.app.error)
        saved = self.saved()
        variable = next(v for v in saved["variables"] if v["key"] == "weapon_type")
        self.assertEqual(variable["allowed_values"], ["Firearm", "Other"])
        for incident in saved["incidents"]:
            self.assertEqual(incident["fields"]["weapon_type"], {"value": None, "status": "Not Reported", "evidence_ids": []})
            self.assertNotEqual(incident["review_status"], "Verified")
        self.assertEqual(len(saved["reviews"]), 2)
        self.assertTrue(all(r["previous_value"] == "Verified" and r["new_value"] == "Needs review" for r in saved["reviews"]))


if __name__ == "__main__":
    unittest.main()
