"""Gates de empacotamento independentes de Qt; não simulam execução Windows."""
import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from app.desktop import DesktopSmokeReport
from app.maintenance import SCHEMA_VERSION
from scripts.build_windows import frontend_assets, pe_details, version_resource, write_version_info, maintenance_bundle_args
from scripts.smoke_windows import extract_bundle


class WindowsPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_semver_preserved_when_numeric_revision_exceeds_windows_range(self):
        value = version_resource("0.4.1-dev.70000+commit.a12")
        self.assertEqual(value["numeric"], (0, 4, 1, 65535))
        self.assertEqual(value["revision_original"], 70000)
        self.assertTrue(value["revision_capped"])
        path = self.root / "version.txt"
        write_version_info(path, value)
        self.assertIn("0.4.1-dev.70000+commit.a12", path.read_text())
        self.assertEqual(version_resource("0.4.0")["numeric"], (0, 4, 0, 0))

    def test_invalid_or_out_of_range_version_rejected(self):
        for value in ("01.4.0", "0.4.0-dev.01", "0.4.0-", "65536.0.0", "v0.4.0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_resource(value)

    def make_pe(self, *, machine=0x8664, magic=0x20B, subsystem=2):
        data = bytearray(512)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<H", data, 132, machine)
        struct.pack_into("<H", data, 148, 240)
        struct.pack_into("<H", data, 152, magic)
        struct.pack_into("<H", data, 220, subsystem)
        path = self.root / "header-fixture.exe"
        path.write_bytes(data)
        return path

    def test_entrypoint_requires_real_pe_gui_x64_header(self):
        self.assertTrue(pe_details(self.make_pe(), gui=True)["gui"])
        with self.assertRaisesRegex(ValueError, "gráfico"):
            pe_details(self.make_pe(subsystem=3), gui=True)
        with self.assertRaisesRegex(ValueError, "AMD64"):
            pe_details(self.make_pe(machine=0x14C, magic=0x10B), gui=True)
        path = self.root / "not-pe.exe"
        path.write_text("this is not a Windows executable")
        with self.assertRaises(ValueError):
            pe_details(path)

    def make_frontend(self, extra=""):
        (self.root / "index.html").write_text('<script src="/app.js"></script><link rel="stylesheet" href="/app.css">' + extra)
        for name in ("app.js", "app.css", "brand.svg"):
            (self.root / name).write_text("asset")

    def test_frontend_cannot_rely_on_external_or_missing_assets(self):
        self.make_frontend()
        self.assertEqual(frontend_assets(self.root), ["app.css", "app.js"])
        self.make_frontend('<script src="https://cdn.example.invalid/app.js"></script>')
        with self.assertRaisesRegex(ValueError, "externo"):
            frontend_assets(self.root)
        self.make_frontend('<script src="/missing.js"></script>')
        with self.assertRaisesRegex(ValueError, "ausente"):
            frontend_assets(self.root)

    def test_archive_rejects_path_traversal_before_extracting(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("EscrituraIntegrada/EscrituraIntegrada.exe", b"fixture")
            output.writestr("EscrituraIntegrada/../../outside", b"must not extract")
        with self.assertRaises(ValueError):
            extract_bundle(archive, self.root / "extract")
        self.assertFalse((self.root / "extract").exists())

    def test_smoke_only_approves_verified_ui_and_graceful_shutdown(self):
        path = self.root / "smoke.json"
        smoke = DesktopSmokeReport(path)
        smoke.record("ui_rendered", ui_verified=True)
        self.assertFalse(json.loads(path.read_text())["ok"])
        self.assertEqual(smoke.complete(False, 0), 1)
        self.assertFalse(json.loads(path.read_text())["ok"])
        self.assertEqual(smoke.complete(True, 0), 0)
        self.assertTrue(json.loads(path.read_text())["shutdown_complete"])
        smoke = DesktopSmokeReport(path)
        self.assertEqual(smoke.complete(True, 0), 1, "Fechar sem renderização não aprova")

    def test_native_smoke_migration_assertions_require_current_schema(self):
        # Evaluate the actual platform-script comparisons without importing
        # winreg or executing an installer on this test host.
        root = Path(__file__).resolve().parents[1]
        for script, variable, mismatch in (
            ('smoke_macos.py', 'after', False),
            ('smoke_installer_windows.py', 'new_counts', True),
        ):
            tree = ast.parse((root / 'scripts' / script).read_text())
            comparisons = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)
                           and isinstance(node.left, ast.Subscript)
                           and isinstance(node.left.value, ast.Name)
                           and node.left.value.id == variable
                           and isinstance(node.left.slice, ast.Constant)
                           and node.left.slice.value == 'schema_version']
            self.assertEqual(len(comparisons), 1, script)
            expression = compile(ast.Expression(comparisons[0]), script, 'eval')
            for schema, expected in ((SCHEMA_VERSION, not mismatch), (SCHEMA_VERSION - 1, mismatch)):
                with self.subTest(script=script, schema=schema):
                    self.assertEqual(eval(expression, {'SCHEMA_VERSION': SCHEMA_VERSION,
                                                       variable: {'schema_version': schema}}), expected)
        mac = (root / 'scripts/smoke_macos.py').read_text()
        self.assertIn("glob(f'antes-schema-{SCHEMA_VERSION}-*.sqlite3')", mac)

    def test_both_native_maintenance_helpers_bundle_the_migration_data(self):
        root = Path(__file__).resolve().parents[1]
        arguments = maintenance_bundle_args()
        self.assertEqual(arguments, ['--paths', str(root), '--add-data',
                                    f'{root / "app" / "data"}{os.pathsep}app/data'])
        self.assertTrue((root / 'app/data/cfop-carga-tabcfop-20261109.json').is_file())
        for filename in ('build_installer_windows.py', 'build_macos.py'):
            tree = ast.parse((root / 'scripts' / filename).read_text())
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.List)
                     and any(isinstance(v, ast.Constant) and v.value == 'EscrituraMaintenance' for v in node.elts)]
            self.assertEqual(len(calls), 1, filename)
            self.assertTrue(any(isinstance(v, ast.Starred) and isinstance(v.value, ast.Call)
                                and isinstance(v.value.func, ast.Name)
                                and v.value.func.id == 'maintenance_bundle_args' for v in calls[0].elts), filename)

    def test_installer_console_preserves_unicode_diagnostics_on_cp1252(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'scripts/smoke_installer_windows.py').read_text())
        prints = [node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                  and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                  and node.value.func.id == 'print' and node.value.args
                  and isinstance(node.value.args[0], ast.Call)
                  and isinstance(node.value.args[0].func, ast.Attribute)
                  and node.value.args[0].func.attr == 'dumps']
        self.assertEqual(len(prints), 1)
        report = {'ok': False, 'error': '\ufeffErro de instalação: João / 漢'}
        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding='cp1252', errors='strict')
        try:
            with redirect_stdout(console):
                exec(compile(ast.Module(body=prints, type_ignores=[]), 'native-smoke-print', 'exec'),
                     {'json': json, 'report': report})
            console.flush()
            self.assertEqual(json.loads(raw.getvalue().decode('cp1252')), report)
        finally:
            console.detach()


if __name__ == "__main__":
    unittest.main()
