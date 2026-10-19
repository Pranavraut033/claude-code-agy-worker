"""Command line: ``python3 -m inventory.cli STORE.json {list,add,total} ...``."""

import argparse
import os
import sys

from .models import Item
from .pricing import calc_total, discounted_total
from .store import Store


def _load(path):
    return Store.load(path) if os.path.exists(path) else Store()


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="inventory.cli")
    parser.add_argument("store")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    add = sub.add_parser("add")
    add.add_argument("sku")
    add.add_argument("name")
    add.add_argument("unit_price", type=float)
    add.add_argument("qty", type=int)
    add.add_argument("--tag", action="append", default=None)
    sub.add_parser("total")
    args = parser.parse_args(argv)

    store = _load(args.store)
    if args.cmd == "list":
        for item in store.items():
            out.write(f"{item.sku}\t{item.name}\t{item.qty}\n")
    elif args.cmd == "add":
        store.add(Item(args.sku, args.name, args.unit_price, args.qty, args.tag))
        store.save(args.store)
        out.write(f"added {args.sku}\n")
    elif args.cmd == "total":
        # calc_total gives the gross; discounted_total applies the volume tier.
        items = store.items()
        out.write(f"gross {calc_total(items):.2f}\nnet {discounted_total(items):.2f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
