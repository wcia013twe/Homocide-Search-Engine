import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from research_app.data import seed_workspace, validate_workspace
from research_app.library import uploaded_source
from research_app.repository import Repository


class ResearchUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {"HR_DATA_DIR": self.directory.name, "HR_REQUIRE_PROXY_IDENTITY": "false"})
        env.start()
        self.addCleanup(env.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
        self.assert_clean()

    def assert_clean(self):
        self.assertEqual(len(self.app.exception), 0, str(self.app.exception))
        self.assertEqual(len(self.app.error), 0, str(self.app.error))
        validate_workspace(self.app.session_state.workspace)

    def assert_saved(self):
        self.assert_clean()
        repository = Repository(Path(self.directory.name) / "workspaces.sqlite3", self.app.session_state.research_user)
        saved, revision = repository.load()
        self.assertEqual(saved, self.app.session_state.workspace)
        self.assertEqual(revision, self.app.session_state.revision)

    def navigate(self, page):
        self.app.radio(key="nav_page").set_value(page).run()
        self.assert_clean()

    def test_collect_new_dataset_and_duplicate_collection(self):
        app = self.app
        app.text_input(key="search_discovery_query").set_value("Cedar").run()
        result_keys = [c.key for c in app.checkbox if c.key.startswith("search_pick_")]
        self.assertEqual(len(result_keys), 3)
        app.checkbox(key=result_keys[0]).check().run()
        app.text_input(key="search_dataset_name").set_value("Cedar evidence")
        app.button(key="search_collect").click().run()
        self.assert_saved()
        dataset = app.session_state.workspace["datasets"][-1]
        self.assertEqual(dataset["name"], "Cedar evidence")
        self.assertEqual(len(dataset["source_ids"]), 1)
        self.assertEqual(dataset["incident_ids"], [])
        app.selectbox(key="search_destination").set_value(dataset["id"]).run()
        app.button(key="search_collect").click().run()
        self.assert_saved()
        self.assertEqual(app.session_state.workspace["runs"][-1]["source_count"], 0)
        self.assertEqual(len(app.session_state.workspace["datasets"][-1]["source_ids"]), 1)
        app.selectbox(key="search_research_scope").set_value(dataset["id"]).run()
        self.assert_clean()

    def test_projects_create_group_and_export(self):
        self.navigate("Projects")
        app = self.app
        self.assertTrue(any(d.proto.label.startswith("Export project") and d.proto.url.endswith(".csv") for d in app.get("download_button")))
        app.text_input(key="proj_new_name").set_value("County study")
        app.text_area(key="proj_new_description").set_value("Compare evidence coverage")
        app.button(key="FormSubmitter:proj_create_form-Create project").click().run()
        self.assert_saved()
        project = app.session_state.workspace["projects"][-1]
        app.selectbox(key="proj_selected").set_value(project["id"]).run()
        app.multiselect(key=f"proj_datasets_{project['id']}").set_value(["dataset-texas-2023"])
        app.button(key=f"FormSubmitter:proj_datasets_form_{project['id']}-Save dataset selection").click().run()
        self.assert_saved()
        self.assertIn(project["id"], app.session_state.workspace["datasets"][0]["project_ids"])
        app.selectbox(key="proj_dimension").set_value("Year").run()
        self.assert_clean()
        self.assertTrue(any(d.proto.label.startswith("Export project") for d in app.get("download_button")))

    def test_library_filter_link_and_usage(self):
        self.navigate("Library")
        app = self.app
        app.text_input(key="lib_query").set_value("follow-up").run()
        self.assertEqual(len(app.selectbox(key="lib_preview").options), 2)
        app.text_input(key="lib_query").set_value("").run()
        app.selectbox(key="lib_preview").set_value("source-001").run()
        app.selectbox(key="lib_dataset_source-001").set_value("dataset-evidence-review")
        app.button(key="lib_link_source-001").click().run()
        self.assert_saved()
        self.assertIn("dataset-evidence-review", app.session_state.workspace["sources"][0]["dataset_ids"])
        self.navigate("Usage")
        self.assertEqual(app.dataframe[0].value.iloc[1]["Coverage"], "2 of 8")
        app.selectbox(key="usage_status").set_value("Completed").run()
        self.assert_clean()

    def test_upload_validation_and_repository_roundtrip(self):
        source = uploaded_source(b"\xef\xbb\xbfAn evidence transcript", "transcript.txt", "Transcript")
        workspace = seed_workspace()
        workspace["sources"].append(source)
        validate_workspace(workspace)
        repository = Repository(Path(self.directory.name) / "upload.sqlite3", "test")
        _, revision = repository.load()
        repository.save(workspace, revision)
        self.assertEqual(repository.load()[0]["sources"][-1]["text"], "An evidence transcript")
        for invalid in (b"\xff", b"  ", b"x" * (2 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                uploaded_source(invalid, "invalid.txt")


if __name__ == "__main__":
    unittest.main()
