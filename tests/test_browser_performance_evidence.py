"""Failure evidence tests do not launch a browser or server."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from scripts.browser_performance import evidence_guard, stop_server


class PerformanceEvidenceTests(unittest.TestCase):
    def test_primary_error_survives_capture_and_all_cleanup_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'result.json'
            events, report = [], {'ok': True}
            original = AssertionError('original assertion')
            page = Mock()
            def screenshot(**kwargs):
                events.append('capture')
                raise RuntimeError('screenshot failed')
            page.screenshot.side_effect = screenshot
            page.content.return_value = '<html>still open</html>'
            page.locator.return_value.inner_text.return_value = 'still open'
            def cleanup():
                events.append('cleanup')
                raise RuntimeError('cleanup failed')
            with self.assertRaises(AssertionError) as raised:
                with evidence_guard(report, out, [('fixture', cleanup), ('server', cleanup), ('browser', cleanup)], lambda: page):
                    raise original
            self.assertIs(raised.exception, original)
            self.assertEqual(events, ['capture', 'cleanup', 'cleanup', 'cleanup'])
            saved = json.loads(out.read_text())
            self.assertFalse(saved['ok'])
            self.assertIn('original assertion', saved['traceback'])
            self.assertEqual(len(saved['secondary_errors']), 4)
            self.assertEqual(out.with_suffix('.failure.html').read_text(), '<html>still open</html>')
            self.assertEqual(out.with_suffix('.failure.txt').read_text(), 'still open')

    def test_cleanup_only_error_blocks_success(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'result.json'
            report = {'ok': True}
            cleanup = Mock(side_effect=RuntimeError('not cleaned'))
            with self.assertRaisesRegex(RuntimeError, 'not cleaned'):
                with evidence_guard(report, out, [('fixture', cleanup)], lambda: None):
                    pass
            self.assertFalse(json.loads(out.read_text())['ok'])

    def test_server_timeout_is_killed_then_waited(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('server', 15), 0]
        stop_server(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual([call.kwargs for call in process.wait.call_args_list], [{'timeout': 15}, {'timeout': 5}])
