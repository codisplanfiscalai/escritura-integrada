"""Failure evidence tests do not launch a browser or server."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.browser_performance import RequestMetrics, assert_account_page_read, evidence_guard, stop_server


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


class RequestMetricTests(unittest.TestCase):
    def request(self, url='http://synthetic/api/companies/1/accounts?page=1&per_page=50'):
        request = Mock(url=url, method='GET')
        response = Mock(status=200)
        response.body.return_value = b'x' * 12748
        request.response.return_value = response
        return request, response

    def test_finished_callback_never_calls_playwright_rpc_and_collect_fills_same_entry(self):
        records = []
        metrics = RequestMetrics(records)
        request, response = self.request()
        with patch('scripts.browser_performance.time.perf_counter', side_effect=[10, 10.125]):
            metrics.start(request)
            metrics.finish(request)
        request.response.assert_not_called()
        response.body.assert_not_called()
        self.assertEqual(1, len(records))
        self.assertIsNone(records[0]['decoded_bytes'])
        snapshot = records[:]
        metrics.collect()
        self.assertIs(snapshot[0], records[0])
        self.assertEqual(12748, snapshot[0]['decoded_bytes'])
        self.assertEqual(125, snapshot[0]['elapsed_ms'])
        self.assertEqual(200, snapshot[0]['status'])
        response.finished.assert_not_called()
        metrics.collect()
        response.body.assert_called_once()
        assert_account_page_read(snapshot)

    def test_body_decode_can_dispatch_other_events_without_losing_or_duplicating_reads(self):
        records = []
        metrics = RequestMetrics(records)
        first, response = self.request()
        second, other = self.request('http://synthetic/api/companies/1/periods')
        metrics.start(first)
        metrics.finish(first)

        def body():
            self.assertEqual(1, len(records))
            metrics.start(second)
            metrics.finish(second)
            return b'x' * 12748

        response.body.side_effect = body
        metrics.collect()
        self.assertEqual(2, len(records))
        self.assertEqual([12748, 12748], [x['decoded_bytes'] for x in records])
        self.assertFalse(metrics.started)
        self.assertFalse(metrics.completed)
        assert_account_page_read(records)

    def test_pending_duplicate_request_counts_even_before_body_is_collected(self):
        records = []
        metrics = RequestMetrics(records)
        first, _ = self.request()
        second, _ = self.request()
        metrics.start(first)
        metrics.finish(first)
        metrics.collect()
        metrics.start(second)
        with self.assertRaises(AssertionError):
            assert_account_page_read(records)
        self.assertEqual(2, len(records))
        self.assertIsNone(records[1]['decoded_bytes'])

    def test_account_gate_still_rejects_absence_duplicates_unpaged_wrong_page_and_over_budget(self):
        valid = {
            'path': '/api/companies/1/accounts',
            'url': 'http://synthetic/api/companies/1/accounts?page=1&per_page=50',
            'method': 'GET', 'status': 200, 'decoded_bytes': 12748, 'elapsed_ms': 10,
        }
        assert_account_page_read([valid])
        cases = [
            [], [valid, dict(valid)],
            [dict(valid, url='http://synthetic/api/companies/1/accounts')],
            [dict(valid, url='http://synthetic/api/companies/1/accounts?page=10')],
            [dict(valid, url='http://synthetic/api/companies/1/accounts?page=2')],
            [dict(valid, decoded_bytes=100000)], [dict(valid, decoded_bytes=0)],
            [dict(valid, decoded_bytes=None)], [dict(valid, status=500)],
            [dict(valid, method='POST')],
        ]
        cases += [
            [valid, dict(valid, path='/api/companies/1/' + path)]
            for path in ('journals', 'cost-centers', 'masters/history')
        ]
        for i, current in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(AssertionError):
                assert_account_page_read(current)

    def test_failed_body_read_is_not_silenced_or_replaced_by_an_empty_success(self):
        records = []
        metrics = RequestMetrics(records)
        request, response = self.request()
        response.body.side_effect = RuntimeError('synthetic decode failure')
        metrics.start(request)
        metrics.finish(request)
        with self.assertRaisesRegex(RuntimeError, 'synthetic decode failure'):
            metrics.collect()
        self.assertIsNone(records[0]['decoded_bytes'])
        with self.assertRaises(AssertionError):
            assert_account_page_read(records)
