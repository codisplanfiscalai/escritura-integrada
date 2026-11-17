"""Synthetic lifecycle regressions, no network/browser or production data."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from scripts.browser_process import managed_process

class PreviewProcessTests(unittest.TestCase):
    def test_writer_stops_before_directory_cleanup_on_success_and_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                proc = None
                try:
                    with tempfile.TemporaryDirectory() as folder:
                        target = Path(folder)
                        code = "import pathlib,signal,sys,time\np=pathlib.Path(sys.argv[1])\ndef stop(*a):\n (p/'shutdown').write_text('done');sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\n(p/'ready').touch()\nwhile True: (p/'writer').write_text('active');time.sleep(.005)"
                        try:
                            with managed_process([sys.executable, '-c', code, folder]) as proc:
                                deadline = time.monotonic() + 5
                                while not (target/'ready').exists():
                                    if time.monotonic() > deadline: self.fail('writer did not start')
                                    time.sleep(.01)
                                if fail: raise ValueError('acceptance failure')
                        finally:
                            self.assertIsNotNone(proc.poll())
                            self.assertEqual('done', (target/'shutdown').read_text())
                except ValueError as exc:
                    self.assertTrue(fail)
                    self.assertEqual('acceptance failure', str(exc))
                self.assertFalse(target.exists())

    def test_timeout_is_reaped_and_propagated_not_suppressed(self):
        proc = Mock(); proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired('preview', 15), 0]
        with patch('scripts.browser_process.subprocess.Popen', return_value=proc):
            with self.assertRaises(subprocess.TimeoutExpired):
                with managed_process(['synthetic']): pass
        proc.terminate.assert_called_once(); proc.kill.assert_called_once()
        self.assertEqual(2, proc.wait.call_count)

    def test_already_exited_is_waited_without_signalling(self):
        proc = Mock(); proc.poll.return_value = 0
        with patch('scripts.browser_process.subprocess.Popen', return_value=proc):
            with managed_process(['synthetic']): pass
        proc.terminate.assert_not_called();proc.kill.assert_not_called()
        proc.wait.assert_called_once_with(timeout=15)

    def test_acceptance_scopes_keep_data_and_log_until_server_stops(self):
        for name in ('browser_account_plans.py', 'browser_global_account_plans.py'):
            tree = ast.parse((Path(__file__).parents[1]/'scripts'/name).read_text())
            temporary = next(n for n in ast.walk(tree) if isinstance(n,ast.With) and any(isinstance(i.context_expr,ast.Call) and isinstance(i.context_expr.func,ast.Attribute) and i.context_expr.func.attr=='TemporaryDirectory' for i in n.items))
            managed = [n for n in ast.walk(temporary) if isinstance(n,ast.With) and any(isinstance(i.context_expr,ast.Call) and isinstance(i.context_expr.func,ast.Name) and i.context_expr.func.id=='managed_process' for i in n.items)]
            self.assertEqual(1,len(managed),name)
            self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='sync_playwright' for n in ast.walk(managed[0])))

if __name__=='__main__':unittest.main()
