"""Data models for the inventory library.

An ``Item`` is one stock-keeping unit. Order totals are computed by
``inventory.pricing.calc_total``; models stay free of pricing logic.
"""


class Item:
    """One stock-keeping unit held in the store."""

    def __init__(self, sku, name, unit_price, qty=0, tags=None):
        if not sku:
            raise ValueError("sku is required")
        if unit_price < 0:
            raise ValueError("unit_price must be >= 0")
        if qty < 0:
            raise ValueError("qty must be >= 0")
        self.sku = sku
        self.name = name
        self.unit_price = unit_price
        self.qty = qty
        self.tags = tags if tags is not None else []

    def add_tag(self, tag):
        if tag not in self.tags:
            self.tags.append(tag)

    def to_dict(self):
        return {
            "sku": self.sku,
            "name": self.name,
            "unit_price": self.unit_price,
            "qty": self.qty,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data["sku"],
            data["name"],
            data["unit_price"],
            data.get("qty", 0),
            list(data.get("tags", [])),
        )

    def __eq__(self, other):
        return isinstance(other, Item) and self.to_dict() == other.to_dict()

    def __repr__(self):
        return f"Item({self.sku!r}, {self.name!r}, {self.unit_price!r}, qty={self.qty!r})"
