"""The large-workspace browser exercise must gate PR and release publication."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PerformanceWorkflowTests(unittest.TestCase):
    def test_browser_performance_is_blocking_and_preserves_its_own_evidence(self):
        for name in ('ci.yml', 'release.yml'):
            with self.subTest(workflow=name):
                workflow = (ROOT / '.github' / 'workflows' / name).read_text(encoding='utf-8')
                linux = workflow.split('\n  linux:\n', 1)[1].split('\n  windows:\n', 1)[0]
                steps = re.split(r'(?m)^      - ', linux)[1:]
                checks = [step for step in steps if 'run: python scripts/browser_performance.py\n' in step]
                self.assertEqual(len(checks), 1)
                check = checks[0]
                self.assertIn('        if: success() || failure()\n', check)
                self.assertNotIn('continue-on-error', check)
                self.assertNotIn('continue-on-error', linux)
                self.assertNotIn('|| true', check)
                self.assertNotIn('set +e', check)
                evidence = [step for step in steps if '          name: browser-performance\n' in step]
                self.assertEqual(len(evidence), 1)
                upload = evidence[0]
                self.assertIn('uses: actions/upload-artifact@', upload)
                self.assertIn('        if: always()\n', upload)
                self.assertIn('          path: artifacts/performance/\n', upload)
                self.assertIn('          if-no-files-found: error\n', upload)
                self.assertLess(steps.index(check), steps.index(upload))
                legacy = [step for step in steps if '          name: browser-evidence\n' in step]
                self.assertEqual(len(legacy), 1)
                self.assertNotIn('artifacts/performance', legacy[0])


class RebuiltWorkflowTests(unittest.TestCase):
    def test_rebuilt_suites_are_blocking_and_upload_in_linux(self):
        for name in ('ci.yml','release.yml'):
            workflow=(ROOT/'.github/workflows'/name).read_text()
            before,rest=workflow.split('\n  linux:\n',1);linux=rest.split('\n  windows:\n',1)[0]
            self.assertIn('timeout-minutes: 30',linux)
            steps=re.split(r'(?m)^      - ',linux)[1:]
            for script,artifact in [('browser_workspace_context.py','browser-workspace-context'),('browser_assessments.py','browser-assessments'),('browser_fiscal_series.py','browser-fiscal-series')]:
                self.assertNotIn('name: '+artifact+'\n',before)
                runs=[s for s in steps if 'run: python scripts/'+script+'\n' in s]
                self.assertEqual(1,len(runs));self.assertIn('if: success() || failure()',runs[0])
                self.assertNotIn('continue-on-error',runs[0]);self.assertNotIn('|| true',runs[0])
                uploads=[s for s in steps if 'name: '+artifact+'\n' in s]
                self.assertEqual(1,len(uploads));self.assertIn('if: always()',uploads[0])
                self.assertIn('path: artifacts/'+artifact+'/',uploads[0]);self.assertIn('if-no-files-found: error',uploads[0])
                self.assertLess(steps.index(runs[0]),steps.index(uploads[0]))
                legacy=[s for s in steps if 'name: browser-evidence\n' in s]
                self.assertEqual(1,len(legacy));self.assertNotIn('artifacts/'+artifact,legacy[0])

if __name__ == '__main__':
    unittest.main()
