from datetime import datetime, timezone
import unittest

from research_app.investigation_progress import submitted_text


class SubmissionTimeTests(unittest.TestCase):
    def test_submission_time_uses_eastern_with_daylight_saving(self):
        self.assertEqual(
            submitted_text({'created_at': datetime(2026, 7, 1, 16, 5, tzinfo=timezone.utc), 'status': 'finished'}),
            'Submitted Jul 01, 2026 at 12:05:00 PM EDT',
        )
        self.assertEqual(
            submitted_text({'created_at': datetime(2026, 11, 17, 16, 5, tzinfo=timezone.utc), 'status': 'saved'}),
            'Linked Nov 17, 2026 at 11:05:00 AM EST',
        )
