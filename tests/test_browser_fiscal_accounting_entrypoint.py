"""The CI entrypoint must not depend on a caller-provided project PYTHONPATH."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FiscalAccountingEntrypointTests(unittest.TestCase):
    def test_fixture_imports_work_from_isolated_interpreter_outside_checkout(self):
        code = '''import runpy, sys
runpy.run_path(sys.argv[1])
from app.importers import _xml_snapshot
from app.core import cnpj_digits
from xml.etree.ElementTree import fromstring
assert _xml_snapshot(fromstring('<pag><vTroco>0.00</vTroco></pag>'))['children'][0]['text'] == '0.00'
assert len(cnpj_digits('TEST00040001')) == 2
'''
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT / 'scripts/browser_fiscal_sales_accounting.py')],
                                    cwd=cwd, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
