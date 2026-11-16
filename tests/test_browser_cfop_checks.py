"""Smoke assertions must reject HTTP failures and inconsistent persisted data."""
from copy import deepcopy
import json
import unittest
from scripts.browser_cfop_checks import checked_source_loads


class Response:
    def __init__(self, payload=None, status=200, malformed=False):
        self.payload, self.status, self.malformed = payload, status, malformed
        self.ok = 200 <= status < 300

    def text(self): return 'synthetic HTTP ' + str(self.status)

    def json(self):
        if self.malformed: raise json.JSONDecodeError('synthetic malformed JSON', '', 0)
        return deepcopy(self.payload)


class BrowserCfopChecksTests(unittest.TestCase):
    def setUp(self):
        self.imported = Response({'id': 17})
        self.rows = [{'id':17,'comparison':{'record_count':779},'parameters_active':False}]

    def test_accepts_one_persisted_inactive_load_matching_the_import(self):
        self.assertEqual(self.rows, checked_source_loads(self.imported, Response(self.rows)))

    def test_http_errors_in_either_response_remain_failures(self):
        for status in [401, 403, 404, 409, 500, 503]:
            with self.subTest(status=status, phase='import'), self.assertRaisesRegex(AssertionError, str(status)):
                checked_source_loads(Response({'id':17},status), Response(self.rows))
            with self.subTest(status=status, phase='read'), self.assertRaisesRegex(AssertionError, str(status)):
                checked_source_loads(self.imported, Response(self.rows,status))

    def test_empty_or_multiple_loads_remain_failures(self):
        for rows in [[], self.rows * 2]:
            with self.subTest(rows=len(rows)), self.assertRaises(AssertionError):
                checked_source_loads(self.imported, Response(rows))

    def test_different_count_or_activated_parameters_remain_failures(self):
        for fields in [{'comparison':{'record_count':778}}, {'parameters_active':True}]:
            with self.subTest(fields=fields), self.assertRaises(AssertionError):
                checked_source_loads(self.imported, Response([self.rows[0] | fields]))

    def test_old_load_cannot_pass_for_the_newly_imported_one(self):
        with self.assertRaisesRegex(AssertionError, 'recém-importada'):
            checked_source_loads(self.imported, Response([self.rows[0] | {'id':16}]))

    def test_malformed_or_missing_json_is_not_silently_accepted(self):
        with self.assertRaises(json.JSONDecodeError):
            checked_source_loads(self.imported, Response(malformed=True))
        with self.assertRaises(KeyError):
            checked_source_loads(self.imported, Response([{'id':17}]))


if __name__ == '__main__': unittest.main()
