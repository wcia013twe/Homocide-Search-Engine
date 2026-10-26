import tempfile
import unittest
from pathlib import Path

from research_app.data import seed_workspace, validate_workspace
from research_app.repository import ConflictError, Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runtime" / "workspace.sqlite3"

    def test_user_isolation_and_restart_persistence(self):
        alice = Repository(self.path, "alice")
        workspace, revision = alice.load()
        workspace["projects"][0]["name"] = "Alice's research"
        self.assertEqual(alice.save(workspace, revision), 1)
        self.assertEqual(Repository(self.path, "alice").load()[0]["projects"][0]["name"], "Alice's research")
        bob_workspace, bob_revision = Repository(self.path, "bob").load()
        self.assertEqual(bob_revision, 0)
        self.assertNotEqual(bob_workspace["projects"][0]["name"], "Alice's research")

    def test_stale_session_cannot_overwrite_correction(self):
        first, second = Repository(self.path, "alice"), Repository(self.path, "alice")
        workspace, version = first.load()
        stale, stale_version = second.load()
        workspace["incidents"][0]["review_status"] = "In review"
        workspace["reviews"].append({"id": "review-test", "incident_id": "incident-001", "field": "review_status", "previous_value": "Verified", "new_value": "In review", "reason": "Check citation", "reviewer": "alice", "reviewed_at": "2026-10-26T10:00:00Z"})
        first.save(workspace, version)
        stale["incidents"][0]["review_status"] = "Needs review"
        with self.assertRaises(ConflictError):
            second.save(stale, stale_version)
        current, current_version = second.load()
        self.assertEqual(current_version, 1)
        self.assertEqual(current["incidents"][0]["review_status"], "In review")
        self.assertEqual(len(current["reviews"]), 1)

    def test_reset_preserves_monotonic_revision_and_rejects_stale_reset(self):
        repository = Repository(self.path, "alice")
        workspace, version = repository.load()
        workspace["projects"][0]["name"] = "Changed"
        repository.save(workspace, version)
        with self.assertRaises(ConflictError):
            repository.reset(version)
        self.assertEqual(repository.reset(1), 2)
        self.assertEqual(repository.load(), (seed_workspace(), 2))

    def test_failed_serialization_leaves_saved_workspace_intact(self):
        repository = Repository(self.path, "alice")
        workspace, version = repository.load()
        workspace["usage_events"][0]["cost_usd"] = float("nan")
        with self.assertRaises(ValueError):
            repository.save(workspace, version)
        self.assertEqual(repository.load(), (seed_workspace(), 0))

    def test_invalid_imports_reject_broken_links_types_and_membership(self):
        mutations = [
            lambda w: w["incidents"][0]["source_ids"].append("missing-source"),
            lambda w: w["incidents"][0]["fields"]["victim_age"].update(value="34"),
            lambda w: w["datasets"][0]["incident_ids"].clear(),
            lambda w: w["sources"].append(w["sources"][0]),
            lambda w: w["incidents"][0]["fields"]["victim_age"].update(status=[]),
            lambda w: w["incidents"][0]["fields"]["victim_age"].update(value=None),
            lambda w: w["incidents"][0]["fields"]["victim_age"].update(evidence_ids=[]),
            lambda w: w["incidents"][0]["fields"].pop("victim_age"),
            lambda w: w["incidents"][1].update(review_status="Verified"),
            lambda w: w["sources"][0].update(url="javascript:alert(1)"),
            lambda w: w["sources"][0].update(url="file:///etc/passwd"),
            lambda w: w["sources"][0].update(url="https://user:secret@example.invalid"),
            lambda w: w["sources"][0].update(url="https://example.invalid/\npath"),
        ]
        validate_workspace(seed_workspace())
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                workspace = seed_workspace()
                mutate(workspace)
                with self.assertRaises(ValueError):
                    validate_workspace(workspace)

    def test_field_correction_and_its_audit_save_atomically(self):
        repository = Repository(self.path, "alice")
        workspace, version = repository.load()
        field = workspace["incidents"][1]["fields"]["victim_age"]
        workspace["reviews"].append({
            "id": "review-age", "incident_id": "incident-002", "field": "victim_age",
            "previous_value": None, "new_value": 29, "reason": "Selected follow-up report; conflict retained in source history.",
            "reviewer": "alice", "reviewed_at": "2026-10-26T10:00:00Z", "previous_status": "Unclear", "new_status": "Reported",
            "previous_evidence_ids": list(field["evidence_ids"]), "new_evidence_ids": ["source-009"], "codebook_version": "demo-1.0",
        })
        field.update(value=29, status="Reported", evidence_ids=["source-009"])
        repository.save(workspace, version)
        persisted, _ = repository.load()
        self.assertEqual(persisted["incidents"][1]["fields"]["victim_age"]["value"], 29)
        self.assertEqual(persisted["reviews"][0]["previous_evidence_ids"], ["source-002", "source-009"])
        self.assertIn("27", persisted["sources"][1]["text"])

    def test_field_review_requires_evidence_history(self):
        workspace = seed_workspace()
        workspace["reviews"].append({"id": "review-incomplete", "incident_id": "incident-002", "field": "victim_age", "previous_value": None, "new_value": 29, "reason": "Review", "reviewer": "alice", "reviewed_at": "2026-10-26T10:00:00Z"})
        with self.assertRaises(ValueError):
            validate_workspace(workspace)

    def test_seed_links_are_consistent_and_conflicts_retain_both_sources(self):
        workspace = seed_workspace()
        sources = {source["id"]: source for source in workspace["sources"]}
        datasets = {dataset["id"]: dataset for dataset in workspace["datasets"]}
        for incident in workspace["incidents"]:
            for source_id in incident["source_ids"]:
                self.assertIn(incident["id"], sources[source_id]["incident_ids"])
            for dataset_id in incident["dataset_ids"]:
                self.assertIn(incident["id"], datasets[dataset_id]["incident_ids"])
            for field in incident["fields"].values():
                self.assertTrue(set(field["evidence_ids"]).issubset(incident["source_ids"]))
                if field["status"] == "Unclear":
                    self.assertIsNone(field["value"])
                    self.assertEqual(len(field["evidence_ids"]), 2)
        for source in sources.values():
            self.assertEqual(source["url"], "")
            self.assertIn("FICTIONAL", source["text"])


if __name__ == "__main__":
    unittest.main()
