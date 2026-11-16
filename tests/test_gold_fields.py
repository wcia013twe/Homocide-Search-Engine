import unittest

from research_app.gold_fields import HIGHLIGHTED_FIELDS, collect_claims


class GoldFieldTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"one": {"url": "https://example.org/one", "text": "The victim was 47."},
                        "two": {"url": "https://example.org/two", "text": "The victim was 48."}}
        self.claim = {"field": "Victim Age", "value": "47", "source_id": "one", "passage": "victim was 47"}

    def test_reports_evidence_and_keeps_other_fields_missing(self):
        fields = collect_claims([self.claim], self.sources)
        self.assertEqual(len(HIGHLIGHTED_FIELDS), 19)
        self.assertEqual(fields["Victim Age"]["value"], "47")
        self.assertEqual(fields["Victim Age"]["claims"][0]["url"], self.sources["one"]["url"])
        self.assertEqual(fields["Victim Race"]["status"], "missing")

    def test_conflict_keeps_both_claims_and_no_value(self):
        other = {**self.claim, "source_id": "two", "value": "48", "passage": "victim was 48"}
        field = collect_claims([self.claim, other], self.sources)["Victim Age"]
        self.assertEqual(field["status"], "conflicting")
        self.assertIsNone(field["value"])
        self.assertEqual(len(field["claims"]), 2)

    def test_rejects_wrong_field_and_fabricated_passage(self):
        for claim in ({**self.claim, "field": "Charges"}, {**self.claim, "passage": "invented"}):
            with self.assertRaises(ValueError):
                collect_claims([claim], self.sources)


if __name__ == "__main__":
    unittest.main()
