import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import browser_fiscal_series as smoke

class SeriesEvidenceTests(unittest.TestCase):
    def test_success_report_is_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'new'
            def run(report,path):self.assertTrue(path.is_dir());report['checks'].append('synthetic')
            with patch.object(smoke,'run',side_effect=run):smoke.main(out)
            report=json.loads((out/'report.json').read_text());self.assertTrue(report['ok']);self.assertEqual(['synthetic'],report['checks'])
    def test_failure_report_is_preserved_and_failure_propagates(self):
        with tempfile.TemporaryDirectory() as folder:
            def run(report,path):report['stage']='browser';raise RuntimeError('synthetic failure')
            with patch.object(smoke,'run',side_effect=run):
                with self.assertRaisesRegex(RuntimeError,'synthetic failure'):smoke.main(folder)
            report=json.loads((Path(folder)/'report.json').read_text());self.assertFalse(report['ok']);self.assertEqual('browser',report['stage']);self.assertIn('Traceback',report['traceback'])
