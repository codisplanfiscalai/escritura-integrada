"""Browser acceptance entry points must resolve the application outside cwd."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class BrowserScriptBootstrapTests(unittest.TestCase):
    def test_global_plan_bootstrap_resolves_app_without_repository_on_path(self):
        root = Path(__file__).resolve().parents[1]
        # No browser is launched. Stub only the optional Playwright dependency;
        # app.core and the CNPJ helper are imported from the real checkout.
        probe = """
import runpy, sys, types
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
api = types.ModuleType('playwright.sync_api')
api.sync_playwright = api.expect = None
sys.modules['playwright'] = types.ModuleType('playwright')
sys.modules['playwright.sync_api'] = api
if sys.argv[2] == 'direct':
    runpy.run_path(str(root / 'scripts/browser_global_account_plans.py'), run_name='bootstrap_probe')
else:
    import browser_global_account_plans
from app.core import cnpj_digits
assert len(cnpj_digits('TEST00090001')) == 2
print('bootstrap-ok')
"""
        with tempfile.TemporaryDirectory(prefix='browser-bootstrap-') as data:
            for mode in ('direct', 'imported'):
                with self.subTest(mode=mode):
                    result = subprocess.run(
                        [sys.executable, '-I', '-c', probe, str(root), mode],
                        cwd=data, env=dict(os.environ, ESCRITURA_DATA_DIR=data, ESCRITURA_DEMO='0'),
                        text=True, capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('bootstrap-ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
