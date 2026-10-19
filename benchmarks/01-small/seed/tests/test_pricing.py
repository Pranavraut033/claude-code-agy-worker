import unittest
from decimal import Decimal

from inventory.models import Item
from inventory.pricing import calc_total, discount_rate, discounted_total
from tests.helpers import sample_store


class PricingTests(unittest.TestCase):
    def test_calc_total(self):
        # 0.35*300 = 105.00, 120.00, 2.675*2 = 5.35
        self.assertEqual(calc_total(sample_store().items()), 230.35)

    def test_half_up_rounding(self):
        self.assertEqual(calc_total([Item("R", "r", 1.005, 1)]), 1.01)

    def test_discount_tiers(self):
        self.assertEqual(discount_rate(99.99), Decimal("0"))
        self.assertEqual(discount_rate(100), Decimal("0.05"))
        self.assertEqual(discount_rate(500), Decimal("0.10"))
        self.assertEqual(discount_rate(1000), Decimal("0.15"))

    def test_discounted_total(self):
        self.assertEqual(discounted_total(sample_store().items()), 218.83)


if __name__ == "__main__":
    unittest.main()
