import unittest
from decimal import Decimal
from inventory.models import Item
from inventory.pricing import calc_total, discount_rate, discounted_total

class Hidden(unittest.TestCase):
    def test_tier_boundaries(self):
        self.assertEqual(discount_rate(500.0), Decimal("0.10"))
        self.assertEqual(discounted_total([Item("H", "h", 50.0, 2)]), 95.0)
    def test_line_rounding(self):
        # per-line half-up: 2.68 + 0.29 = 2.97 (rounding only the sum gives 2.96)
        self.assertEqual(calc_total([Item("x", "x", 2.675, 1), Item("y", "y", 0.285, 1)]), 2.97)
    def test_default_tags_not_shared(self):
        a, b = Item("A", "a", 1.0), Item("B", "b", 1.0)
        self.assertIsNot(a.tags, b.tags); a.add_tag("t"); self.assertEqual(Item("C", "c", 1.0).tags, [])

if __name__ == "__main__": unittest.main()
