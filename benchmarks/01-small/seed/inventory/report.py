"""Stock reports.

Run as ``python3 -m inventory.report [--format text] STORE.json``.
"""

import argparse
import sys

from .pricing import calc_total, discounted_total, line_total
from .store import Store


def rows(store):
    """One (sku, name, qty, unit_price, line_total) tuple per item, by sku."""
    return [(i.sku, i.name, i.qty, i.unit_price, float(line_total(i))) for i in store.items()]


def to_text(store):
    lines = [f"{'SKU':<8} {'NAME':<20} {'QTY':>5} {'PRICE':>9} {'TOTAL':>10}"]
    for sku, name, qty, price, total in rows(store):
        lines.append(f"{sku:<8} {name:<20} {qty:>5} {price:>9.2f} {total:>10.2f}")
    items = store.items()
    lines.append(f"{'':<8} {'TOTAL':<20} {'':>5} {'':>9} {calc_total(items):>10.2f}")
    lines.append(f"{'':<8} {'AFTER DISCOUNT':<20} {'':>5} {'':>9} {discounted_total(items):>10.2f}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="inventory.report")
    parser.add_argument("store")
    parser.add_argument("--format", choices=["text"], default="text")
    args = parser.parse_args(argv)
    store = Store.load(args.store)
    sys.stdout.write(to_text(store))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
