import os, subprocess, sys, tempfile, unittest
from inventory.models import Item
from inventory.store import Store
from inventory.report import to_csv

def store():
    return Store([Item("B200", "Bolt, steel", 0.35, 300), Item("A100", "Anvil", 120.0, 1),
                  Item("C300", 'Cable "red"', 2.675, 2)])
EXPECTED = ('sku,name,qty,unit_price,line_total\n'
            'A100,Anvil,1,120.00,120.00\n'
            'B200,"Bolt, steel",300,0.35,105.00\n'
            'C300,"Cable ""red""",2,2.68,5.35\n'
            'TOTAL,,,,230.35\n')

class Hidden(unittest.TestCase):
    def test_exact(self): self.assertEqual(to_csv(store()), EXPECTED)
    def test_empty(self): self.assertEqual(to_csv(Store()), "sku,name,qty,unit_price,line_total\nTOTAL,,,,0.00\n")
    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json"); store().save(p)
            r = subprocess.run([sys.executable, "-m", "inventory.report", "--format", "csv", p],
                               capture_output=True, text=True, cwd=os.getcwd())
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout, EXPECTED)
    def test_text_default_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json"); store().save(p)
            r = subprocess.run([sys.executable, "-m", "inventory.report", p], capture_output=True, text=True)
        self.assertTrue(r.stdout.startswith("SKU"))

if __name__ == "__main__": unittest.main()
