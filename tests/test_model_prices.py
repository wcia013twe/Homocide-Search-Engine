import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from research_app.usage import model_cost_label
from research_app.usage_store import save_model_price


class ModelEstimateTests(unittest.TestCase):
    def test_recorded_tokens_use_endpoint_rates_and_mark_partial(self):
        row = {'model_endpoint': 'endpoint', 'model_calls': 2, 'metered_calls': 2,
               'input_tokens': 1_000_000, 'output_tokens': 500_000}
        prices = {'endpoint': {'input_price': Decimal('0.15'), 'output_price': Decimal('0.60')}}
        self.assertEqual(model_cost_label(row, prices), '$0.4500')
        self.assertEqual(model_cost_label({**row, 'model_calls': 3}, prices), '$0.4500 (partial)')
        self.assertEqual(model_cost_label(row, {}), 'Unavailable')
        self.assertEqual(model_cost_label({**row, 'metered_calls': 0}, prices), 'Unavailable')

    def test_invalid_prices_do_not_write(self):
        with patch('research_app.usage_store.connection') as connection:
            for invalid in ('NaN', 'Infinity', '-1', '', 'abc'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    save_model_price('alice', 'endpoint', invalid, '0')
            with self.assertRaises(ValueError):
                save_model_price('alice', ' ', '0', '0')
            connection.assert_not_called()

    def test_price_save_is_scoped_to_actor_and_endpoint(self):
        conn = MagicMock()
        with patch('research_app.usage_store.connection') as connection:
            connection.return_value.__enter__.return_value = conn
            save_model_price('alice', ' endpoint ', '0', '0.60')
        query, values = conn.execute.call_args.args
        self.assertIn('ON CONFLICT(actor,endpoint)', query)
        self.assertEqual(values, ['alice', 'endpoint', Decimal('0'), Decimal('0.60')])
