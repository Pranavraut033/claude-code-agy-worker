"""Seed the three T3 bugs into a copy of seed/ (argv[1]). Run before git init."""
import pathlib, sys
root = pathlib.Path(sys.argv[1])
def sub(rel, old, new):
    p = root / rel; s = p.read_text()
    assert s.count(old) == 1, (rel, old); p.write_text(s.replace(old, new))
sub("inventory/pricing.py", "        if total >= threshold:", "        if total > threshold:")
sub("inventory/pricing.py",
    '    return float(sum((line_total(i) for i in items), Decimal("0")))',
    '    return round(sum(i.unit_price * i.qty for i in items), 2)')
sub("inventory/models.py", "qty=0, tags=None):", "qty=0, tags=[]):")
sub("inventory/models.py", "        self.tags = tags if tags is not None else []", "        self.tags = tags")
