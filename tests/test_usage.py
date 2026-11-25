import unittest
from decimal import Decimal

from research_app.usage import cost_label


class UsageCostTests(unittest.TestCase):
    def test_complete_reported_cost(self):
        self.assertEqual(cost_label([{'cost': Decimal('0.004'), 'calls': 1, 'priced_calls': 1}]), '$0.0040')

    def test_missing_cost_is_partial(self):
        self.assertEqual(cost_label([{'cost': Decimal('0.004'), 'calls': 2, 'priced_calls': 1}]), '$0.0040 (partial)')

    def test_unrecorded_is_unavailable(self):
        self.assertEqual(cost_label([{'cost': None, 'calls': 0, 'priced_calls': 0}]), 'Unavailable')
