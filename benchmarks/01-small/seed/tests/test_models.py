import unittest

from inventory.models import Item


class ItemTests(unittest.TestCase):
    def test_round_trip(self):
        item = Item("X1", "Widget", 1.5, 3, ["a"])
        self.assertEqual(Item.from_dict(item.to_dict()), item)

    def test_validation(self):
        with self.assertRaises(ValueError):
            Item("", "No sku", 1.0)
        with self.assertRaises(ValueError):
            Item("X", "Neg", -1.0)

    def test_tags_are_per_item(self):
        a = Item("A", "a", 1.0)
        b = Item("B", "b", 1.0)
        a.add_tag("sale")
        self.assertEqual(b.tags, [])


if __name__ == "__main__":
    unittest.main()
