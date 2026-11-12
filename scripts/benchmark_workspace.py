"""Reproducible HTTP workspace benchmark using disposable synthetic data only.

Run on this revision and a baseline checkout with the same script and machine::

    python scripts/benchmark_workspace.py --output artifacts/workspace-after.json
    python scripts/benchmark_workspace.py --repo /path/to/baseline --label before \
        --output artifacts/workspace-before.json

Browser acceptance can use ``with fixture_workspace() as (data_dir, metadata)``
then start run_preview.py with ESCRITURA_DATA_DIR=data_dir and ESCRITURA_DEMO=1.
The fixture has 22,591 shared + six local accounts and 183 financial titles.
No browser is started by this benchmark; TestClient includes HTTP serialization
and middleware but not a real network, rendering, or end-user latency.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def seed_workspace(core, global_count=22591, title_count=183):
    """Add a large shared plan to a newly seeded demo database, never real data.

    Prefer fixture_workspace(), which owns the empty temporary directory. This
    lower-level helper rejects non-demo databases and existing benchmark plans.
    It does not require a session/admin and does not allocate any shared refs.
    """
    from app.account_plans import FIELDS, default_plan
    from app.core import digest, now, pack

    if not core.demo:
        raise ValueError('Workspace fixture requires an isolated demo database.')
    if not isinstance(global_count, int) or global_count < 1 or title_count < 4:
        raise ValueError('Use at least one global account and four demo titles.')
    with core.db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM meta WHERE key='demo_seeded'").fetchone():
            raise ValueError('Missing synthetic demo marker.')
        companies = list(conn.execute('SELECT id,code FROM companies ORDER BY id'))
        if [row['code'] for row in companies] != ['DEMO001', 'DEMO002']:
            raise ValueError('Fixture requires the two original synthetic demo companies.')
        if conn.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] != 12 or conn.execute('SELECT COUNT(*) FROM titles').fetchone()[0] != 4:
            raise ValueError('Fixture requires an untouched synthetic demo dataset.')
        if conn.execute('SELECT 1 FROM global_account_plans LIMIT 1').fetchone():
            raise ValueError('Refusing to modify a database with existing global plans.')
        cid, other = (row['id'] for row in companies)
        plan = json.loads(json.dumps(default_plan()))
        sample = plan['accounts'][3]
        plan['accounts'] = [dict(sample, access_code=f'P{i:05}', classifier=f'9.{(i-1)//2:05}',
                                 name=f'Conta sintética {i:05}', prosoft_code='',
                                 analytical=i % 11 != 0, requires_cost_center=i % 7 == 0,
                                 active=i % 13 != 0) for i in range(1, global_count + 1)]
        plan['accounts'][-1]['name'] = 'Última ação sintética 100%_literal\\fim Straße'
        plan['warnings'] = ['Fixture sintética; não usar em obrigações fiscais.']
        raw = pack(plan).encode('utf-8')
        checksum, created = digest(raw), now()
        batch_id = conn.execute('''INSERT INTO account_plan_batches
            (company_id,filename,format,sha256,original,options_json,plan_json,preview_hash,state_hash,status,created_at,created_by)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, 'benchmark-synthetic.json', 'native', checksum, raw, '{}', raw.decode(),
             'synthetic-preview', 'synthetic-state', 'reference', created, 'benchmark')).lastrowid
        plan_id = conn.execute('''INSERT INTO global_account_plans
            (name,description,source_company_id,source_batch_id,parent_id,plan_json,filename,format,original,sha256,created_at,created_by)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            ('Plano sintético de desempenho', 'Dados fictícios descartáveis', cid, batch_id, None,
             raw.decode(), 'benchmark-synthetic.json', 'native', raw, checksum, created, 'benchmark')).lastrowid
        conn.executemany(f"INSERT INTO global_account_entries(global_plan_id,{','.join(FIELDS)},prosoft_json,extras_json) VALUES({','.join('?' for _ in range(len(FIELDS)+3))})",
                         [(plan_id, *(account[key] for key in FIELDS), pack(account.get('prosoft', {})), '{}') for account in plan['accounts']])
        conn.execute('''INSERT INTO company_account_plan_bindings(company_id,global_plan_id,mode,attached_at,attached_by)
            VALUES(?,?,'shared',?,'benchmark')''', (cid, plan_id, created))
        # Standardize the four pre-existing demo titles too, so the financial
        # payable table has precisely 50/50/50/33 rows across four UI pages.
        partner = 'Parceiro sintético de desempenho'
        demo_titles = list(conn.execute('SELECT id FROM titles WHERE company_id=? ORDER BY id', (cid,)))
        if len(demo_titles) != 4:
            raise ValueError('Expected four titles in the first demo company.')
        conn.executemany('''UPDATE titles SET kind='payable',description=?,partner_name=?,document=?,
            issue_date='2026-11-01',due_date='2026-11-30',amount_cents=10000 WHERE id=? AND company_id=?''',
            [(f'Título sintético {i:03}', partner, f'PERF-{i:03}', row['id'], cid)
             for i, row in enumerate(demo_titles)])
        conn.executemany('''INSERT INTO titles(company_id,kind,description,partner_name,document,issue_date,due_date,amount_cents,created_at)
            VALUES(?,'payable',?,?,?,'2026-11-01','2026-11-30',10000,?)''',
            [(cid, f'Título sintético {i:03}', partner, f'PERF-{i:03}', created) for i in range(4, title_count)])
        actual_titles = conn.execute("SELECT COUNT(*) FROM titles WHERE company_id=? AND kind='payable'", (cid,)).fetchone()[0]
        if actual_titles != title_count:
            raise AssertionError('Synthetic payable count does not match the requested volume.')
        participant_count = conn.execute("SELECT COUNT(*) FROM masters WHERE company_id=? AND kind='participant'", (cid,)).fetchone()[0]
        if list(conn.execute('PRAGMA foreign_key_check')):
            raise AssertionError('Synthetic fixture foreign keys are invalid.')
    return {'company_id': cid, 'other_company_id': other, 'global_plan_id': plan_id,
            'global_count': global_count, 'account_count': global_count + 6, 'title_count': actual_titles,
            'title_partner': partner, 'title_amount_cents': 10000, 'titles_total_cents': title_count * 10000,
            'participant_count': participant_count,
            'last_access_code': f'P{global_count:05}', 'last_name': plan['accounts'][-1]['name'],
            'accent_search': 'ultima acao', 'literal_search': '%_literal\\fim', 'period': '2026-11'}


@contextmanager
def fixture_workspace(global_count=22591, title_count=183):
    """Yield (data_dir, metadata); delete only this newly created directory."""
    from app.business import BusinessCore
    from app.db import Database

    with tempfile.TemporaryDirectory(prefix='escritura-workspace-synthetic-') as folder:
        core = BusinessCore(Database(folder), demo=True)
        yield folder, seed_workspace(core, global_count, title_count)


def measure(client, url, repetitions):
    elapsed = []
    sizes = []
    count = None
    shape = None
    # Warm once; report each measured run and median rather than a single sample.
    for run in range(repetitions + 1):
        started = time.perf_counter()
        response = client.get(url)
        duration = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        payload = response.json()
        current_shape = 'array' if isinstance(payload, list) else 'object'
        current_count = len(payload) if isinstance(payload, list) else len(payload.get('items', payload.get('plans', [])))
        if shape is not None and (shape, count) != (current_shape, current_count):
            raise AssertionError('Response changed across benchmark repetitions.')
        shape, count = current_shape, current_count
        if run:
            elapsed.append(round(duration, 3))
            sizes.append(len(response.content))
    return {'url': url, 'shape': shape, 'returned_rows': count, 'response_bytes': sizes[0],
            'response_bytes_samples': sizes, 'median_ms': round(statistics.median(elapsed), 3),
            'samples_ms': elapsed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT, help='Checkout to import and measure, e.g. the unchanged baseline.')
    parser.add_argument('--label', default='after')
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error('--repetitions must be positive')
    repo = args.repo.resolve()
    if not (repo / 'app' / 'api.py').is_file():
        parser.error('--repo must contain app/api.py')
    sys.path.insert(0, str(repo))
    # app.api also constructs its module-level app at import time. Point that
    # instance at a separate disposable folder before importing any API code.
    with tempfile.TemporaryDirectory(prefix='escritura-benchmark-bootstrap-') as bootstrap:
        os.environ['ESCRITURA_DATA_DIR'] = bootstrap
        os.environ['ESCRITURA_DEMO'] = '0'
        from fastapi.testclient import TestClient
        from app.api import create_app
        with fixture_workspace() as (folder, fixture):
            application = create_app(folder, demo=True)
            with TestClient(application) as client:
                login = client.post('/api/demo-login')
                login.raise_for_status()
                client.headers['X-CSRF-Token'] = login.json()['csrf_token']
                context = client.post('/api/context', json={'company_id': fixture['company_id'], 'period': fixture['period']})
                context.raise_for_status()
                base = f"/api/companies/{fixture['company_id']}"
                paths = {
                    'accounts_legacy': base + '/accounts',
                    'accounts_page_1': base + '/accounts?page=1&per_page=50',
                    'accounts_page_20': base + '/accounts?page=20&per_page=50',
                    'accounts_page_452': base + '/accounts?page=452&per_page=50',
                    'accounts_page_999': base + '/accounts?page=999&per_page=50',
                    'accounts_page_5000': base + '/accounts?page=1&per_page=5000',
                    'accounts_search_last': base + '/accounts?page=1&per_page=50&search=ultima%20acao',
                    'global_library': base + '/global-account-plans',
                    'financial_titles': base + '/titles',
                }
                report = {'schema_version': 1, 'label': args.label, 'fixture': fixture,
                          'scope': 'Synthetic in-process HTTP including middleware and JSON serialization; no browser or network timings.',
                          'repository': str(repo), 'repetitions': args.repetitions,
                          'source_sha': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                          'results': {name: measure(client, url, args.repetitions) for name, url in paths.items()}}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + '\n', encoding='utf-8')
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
