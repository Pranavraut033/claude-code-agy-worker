import os
import tempfile
import unittest

from inventory.models import Item
from inventory.store import Store
from tests.helpers import sample_store


class StoreTests(unittest.TestCase):
    def test_sorted_items(self):
        self.assertEqual([i.sku for i in sample_store().items()], ["A100", "B200", "C300"])

    def test_duplicate_rejected(self):
        store = Store([Item("A", "a", 1.0)])
        with self.assertRaises(KeyError):
            store.add(Item("A", "again", 2.0))

    def test_save_load(self):
        store = sample_store()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            store.save(path)
            loaded = Store.load(path)
        self.assertEqual(loaded.items(), store.items())


if __name__ == "__main__":
    unittest.main()
