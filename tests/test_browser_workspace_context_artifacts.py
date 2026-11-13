"""Failure evidence contracts, without launching Chromium or a real server."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import browser_workspace_context as smoke


class WorkspaceContextArtifactsTests(unittest.TestCase):
    def run_smoke(self, **patches):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            out = Path(directory) / 'evidence'
            stack.enter_context(patch.object(smoke, 'OUT', out))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for name, value in patches.items():
                stack.enter_context(patch.object(smoke, name, value))
            result = smoke.main()
            return result, json.loads((out / 'report.json').read_text())

    def test_missing_playwright_still_reports(self):
        result, report = self.run_smoke(load_browser=Mock(side_effect=ModuleNotFoundError('playwright')))
        self.assertEqual(result, 1)
        self.assertEqual(report['stage'], 'dependencies')
        self.assertIn('playwright', report['error'])

    def test_git_failure_still_reports(self):
        with patch.object(smoke.subprocess, 'check_output', side_effect=RuntimeError('git unavailable')):
            result, report = self.run_smoke(load_browser=Mock(return_value=(Mock(), Mock())))
        self.assertEqual(result, 1)
        self.assertEqual(report['stage'], 'source')

    def test_server_spawn_failure_still_reports(self):
        with patch.object(smoke.subprocess, 'check_output', return_value='abc'), \
             patch.object(smoke.socket, 'socket'), \
             patch.object(smoke.subprocess, 'Popen', side_effect=OSError('spawn denied')):
            result, report = self.run_smoke(load_browser=Mock(return_value=(Mock(), Mock())))
        self.assertEqual(result, 1)
        self.assertEqual(report['stage'], 'server')
        self.assertIn('spawn denied', report['error'])

    def test_server_health_and_cleanup_timeout_still_report(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('server', 5)
        with patch.object(smoke.subprocess, 'check_output', return_value='abc'), \
             patch.object(smoke.socket, 'socket'), \
             patch.object(smoke.subprocess, 'Popen', return_value=process), \
             patch.object(smoke.urllib.request, 'urlopen', side_effect=OSError('offline')), \
             patch.object(smoke.time, 'sleep'):
            result, report = self.run_smoke(load_browser=Mock(return_value=(Mock(), Mock())))
        self.assertEqual(result, 1)
        self.assertIn('did not start', report['error'])
        self.assertTrue(report['cleanup_errors'])
        process.kill.assert_called_once()

    def test_timeout_kills_and_reaps_server(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired('server', 15), 0]
        report = {'ok': True}
        smoke.stop_server(process, report)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertTrue(report['ok'])

    def test_terminate_failure_marks_run_failed(self):
        process = Mock()
        process.terminate.side_effect = OSError('terminate failed')
        report = {'ok': True}
        smoke.stop_server(process, report)
        self.assertFalse(report['ok'])
        self.assertEqual(report['cleanup_errors'], ['terminate failed'])


if __name__ == '__main__':
    unittest.main()
