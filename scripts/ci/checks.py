"""Gate Linux: manifests, suite de testes, sintaxe e interface compilada."""
from __future__ import annotations

import argparse
import compileall
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from .release import sha, write_json
from .versioning import verify_local
from scripts.build_windows import frontend_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/linux-checks.json'))
    args = parser.parse_args()
    started = time.monotonic()
    report = {'schema_version': 1, 'ok': False, 'version': args.version, 'source_sha': sha(args.source_sha), 'platform': 'linux', 'started_at': datetime.now(timezone.utc).isoformat()}
    log = io.StringIO()
    try:
        verify_local(Path.cwd(), args.version)
        actual = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
        if actual != args.source_sha:
            raise ValueError('O checkout não corresponde ao commit planejado.')
        if not all(compileall.compile_dir(path, quiet=1) for path in ('app', 'scripts', 'tests')):
            raise ValueError('Falha de compilação sintática Python.')
        report['frontend_assets'] = frontend_assets(Path('frontend/dist'))
        frontend_command = ['node', '--test', *[p.as_posix() for p in sorted(Path('frontend/tests').glob('*.test.js'))]]
        frontend = subprocess.run(frontend_command, capture_output=True, text=True, timeout=60)
        log.write(frontend.stdout + frontend.stderr + '\n')
        report['frontend_tests'] = {'command': ' '.join(frontend_command), 'ok': frontend.returncode == 0}
        if frontend.returncode:
            raise ValueError('Os testes da interface falharam.')
        with tempfile.TemporaryDirectory(prefix='escritura-ci-tests-') as data:
            os.environ['ESCRITURA_DATA_DIR'] = data
            os.environ['ESCRITURA_DEMO'] = '0'
            suite = unittest.defaultTestLoader.discover('tests')
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        report.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped), ok=result.wasSuccessful())
        if not result.testsRun:
            raise ValueError('Nenhum teste encontrado; publicação bloqueada.')
    except Exception as exc:
        report.update(ok=False, error=type(exc).__name__ + ': ' + str(exc))
    finally:
        report['duration_seconds'] = round(time.monotonic() - started, 3)
        write_json(args.output, report)
        args.output.with_suffix('.log').write_text(log.getvalue(), encoding='utf-8')
        print(log.getvalue())
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
