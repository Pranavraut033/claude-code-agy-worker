"""A JSON-file backed store of items, keyed by sku."""

import json

from .models import Item


class Store:
    def __init__(self, items=None):
        self._items = {}
        for item in items or []:
            self.add(item)

    def add(self, item):
        if item.sku in self._items:
            raise KeyError(f"duplicate sku {item.sku}")
        self._items[item.sku] = item

    def get(self, sku):
        return self._items[sku]

    def remove(self, sku):
        del self._items[sku]

    def items(self):
        """All items, sorted by sku."""
        return [self._items[k] for k in sorted(self._items)]

    def __len__(self):
        return len(self._items)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([i.to_dict() for i in self.items()], fh, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(Item.from_dict(d) for d in json.load(fh))
