import os
import tempfile
import unittest
from io import StringIO

from inventory.cli import main
from inventory.pricing import calc_total
from inventory.store import Store


class CliTests(unittest.TestCase):
    def test_add_list_total(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            main([path, "add", "A1", "Hammer", "25.5", "4"], out=StringIO())
            main([path, "add", "B2", "Nails", "0.1", "3", "--tag", "bulk"], out=StringIO())
            out = StringIO()
            main([path, "list"], out=out)
            self.assertEqual(out.getvalue(), "A1\tHammer\t4\nB2\tNails\t3\n")
            out = StringIO()
            main([path, "total"], out=out)
            self.assertEqual(out.getvalue(), "gross 102.30\nnet 97.19\n")
            self.assertEqual(calc_total(Store.load(path).items()), 102.3)


if __name__ == "__main__":
    unittest.main()
