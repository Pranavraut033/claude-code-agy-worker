import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from inventory.report import main, rows, to_text
from tests.helpers import sample_store


class ReportTests(unittest.TestCase):
    def test_rows(self):
        self.assertEqual(rows(sample_store())[0], ("A100", "Anvil", 1, 120.0, 120.0))

    def test_text_totals(self):
        text = to_text(sample_store())
        self.assertIn("230.35", text)
        self.assertIn("218.83", text)

    def test_main_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            sample_store().save(path)
            buf = StringIO()
            with redirect_stdout(buf):
                self.assertEqual(main([path]), 0)
        self.assertEqual(buf.getvalue(), to_text(sample_store()))


if __name__ == "__main__":
    unittest.main()
