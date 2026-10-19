from inventory.models import Item
from inventory.store import Store


def sample_store():
    return Store([
        Item("B200", "Bolt, steel", 0.35, 300, ["hardware"]),
        Item("A100", "Anvil", 120.0, 1),
        Item("C300", 'Cable "red"', 2.675, 2),
    ])
