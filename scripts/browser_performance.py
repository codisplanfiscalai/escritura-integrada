"""Blocking Chromium regression on a disposable 22,597-account / 183-title fixture.

Run after building frontend/dist. This uses a fresh synthetic demo database only,
never an existing application, browser profile, or production data. --baseline
records timings against --root without applying optimized request budgets.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]


def record_error(report, stage, error):
    report.setdefault('secondary_errors', []).append({
        'stage': stage, 'error': str(error),
        'traceback': ''.join(traceback.format_exception(error)),
    })


def best_effort(report, stage, operation):
    try:
        operation()
    except BaseException as error:
        record_error(report, stage, error)
        return error
    return None


def capture_failure(page, report, output):
    """Capture each available artifact before browser/context teardown."""
    if page is None:
        return
    output = Path(output)
    for suffix, operation in (
        ('.failure.png', lambda path: page.screenshot(path=str(path), full_page=True, timeout=5000)),
        ('.failure.html', lambda path: path.write_text(page.content(), encoding='utf-8')),
        ('.failure.txt', lambda path: path.write_text(page.locator('body').inner_text(timeout=5000), encoding='utf-8')),
    ):
        path = output.with_suffix(suffix)
        if best_effort(report, f'capture{suffix}', lambda: operation(path)) is None:
            report.setdefault('failure_evidence', []).append(path.name)


@contextmanager
def evidence_guard(report, output, cleanups, page):
    """Never let capture/cleanup errors replace the original exception."""
    primary = None
    try:
        yield
    except BaseException as error:
        primary = error
        report.update(ok=False, error=str(error), traceback=''.join(traceback.format_exception(error)))
        best_effort(report, 'failure_capture', lambda: capture_failure(page(), report, output))
        raise
    finally:
        errors = []
        for stage, operation in reversed(cleanups):
            error = best_effort(report, stage, operation)
            if error is not None:
                errors.append(error)
        if errors:
            report['ok'] = False
        try:
            Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        except BaseException as error:
            record_error(report, 'write_report', error)
            report['ok'] = False
            print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
            errors.append(error)
        if primary is None and errors:
            raise errors[0]


def stop_server(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def scenario(page, url, fixture, report, baseline=False):
    from playwright.sync_api import expect

    requests = report['requests']
    started = {}

    def finished(request):
        if '/api/' not in request.url:
            return
        response = request.response()
        requests.append({'path': urlparse(request.url).path, 'url': request.url,
                         'method': request.method, 'status': response.status if response else None,
                         'decoded_bytes': len(response.body()) if response else 0,
                         'elapsed_ms': round((time.perf_counter() - started.pop(request, time.perf_counter())) * 1000, 2)})

    page.on('request', lambda request: started.__setitem__(request, time.perf_counter()))
    page.on('requestfinished', finished)
    page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
    page.on('requestfailed', lambda request: report.setdefault('request_failures', []).append({'url': request.url, 'error': request.failure}) if '/api/' in request.url else None)
    page.set_default_timeout(20000 if not baseline else 60000)
    expect.set_options(timeout=20000 if not baseline else 60000)
    page.goto(url)
    page.get_by_role('button', name='Entrar na demonstração').click()
    expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
    page.wait_for_load_state('networkidle')
    session = page.request.get(url + '/api/session').json()
    assert session['active_company_id'] == fixture['company_id']
    main = page.locator('main#workspace-panel')

    def nav(label):
        button = page.get_by_role('navigation', name='Navegação principal').get_by_role('button', name=label, exact=True, include_hidden=True)
        details = button.locator('xpath=ancestor::details')
        if details.count() and details.get_attribute('open') is None:
            details.locator('summary').click()
        button.click()
        expect(page.get_by_role('tab', name=label, exact=True)).to_have_attribute('aria-selected', 'true')

    def measure(name, label, ready, response_suffix=None):
        offset = len(requests)
        begin = time.perf_counter()
        if response_suffix:
            # An empty fixture must not be mistaken for ready before its read.
            with page.expect_response(lambda response: urlparse(response.url).path.endswith(response_suffix) and response.status == 200) as pending:
                nav(label)
            pending.value.finished()
        else:
            nav(label)
        ready()
        elapsed = round((time.perf_counter() - begin) * 1000, 2)
        page.wait_for_load_state('networkidle')
        current = requests[offset:]
        report['measurements'][name] = {'ready_ms': elapsed, 'requests': current}
        return current

    def no_catalogs(current):
        assert not any(r['path'].endswith(('/accounts', '/cost-centers', '/renegotiations', '/masters/participant')) or '/documents' in r['path'] for r in current), current

    current = measure('payables', 'Contas a pagar', lambda: expect(main.get_by_text('183 títulos', exact=True)).to_be_visible())
    if not baseline:
        no_catalogs(current)
        expect(main.locator('tbody tr')).to_have_count(50)
        descriptions = main.locator('tbody tr td:nth-child(3) strong')
        seen = descriptions.all_text_contents()
        for count in (50, 50, 33):
            previous = descriptions.first.inner_text()
            main.get_by_role('button', name='Próxima', exact=True).click()
            expect(main.locator('tbody tr')).to_have_count(count)
            expect(descriptions.first).not_to_have_text(previous)
            seen.extend(descriptions.all_text_contents())
        assert len(seen) == len(set(seen)) == 183, seen
        assert set(seen) == {f'Título sintético {i:03}' for i in range(183)}, seen
        expect(main.get_by_role('button', name='Próxima', exact=True)).to_be_disabled()
        expect(main.get_by_text('Página 4 de 4', exact=True)).to_be_visible()
    main.get_by_label('Pesquisar títulos', exact=True).fill('Título sintético 182')
    expect(main.locator('tbody tr')).to_have_count(1)
    main.get_by_role('button', name='Histórico', exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('dialog').get_by_role('button', name='Fechar', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    main.get_by_label('Pesquisar títulos', exact=True).fill('')
    offset = len(requests)
    main.get_by_role('button', name='Novo título', exact=True).click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role('button', name='Salvar título', exact=True)).to_be_enabled()
    page.wait_for_load_state('networkidle')
    if not baseline:
        modal_paths = [r['path'] for r in requests[offset:]]
        assert any(path.endswith('/documents') for path in modal_paths), modal_paths
        assert any(path.endswith('/masters/participant') for path in modal_paths), modal_paths
        assert not any(path.endswith('/accounts') for path in modal_paths), modal_paths
    dialog.get_by_role('button', name='Cancelar', exact=True).click()
    expect(dialog).to_have_count(0)

    current = measure('accounts', 'Plano de contas', lambda: expect(main.locator('table tbody tr')).to_have_count(50))
    if not baseline:
        account_reads = [r for r in current if r['path'].endswith('/accounts')]
        assert len(account_reads) == 1 and 'page=1' in account_reads[0]['url'], current
        assert account_reads[0]['decoded_bytes'] < 100000, account_reads
        assert not any(r['path'].endswith(('/journals', '/cost-centers', '/masters/history')) for r in current), current
    expect(main.get_by_text(f"{fixture['account_count']} registros", exact=True).first).to_be_visible()
    main.get_by_label('Pesquisar contabilidade', exact=True).fill(fixture['accent_search'])
    expect(main.locator('table tbody tr')).to_have_count(1)
    expect(main.locator('table tbody tr').first).to_contain_text(fixture['last_access_code'])
    main.get_by_label('Pesquisar contabilidade', exact=True).fill('')
    expect(main.locator('table tbody tr')).to_have_count(50)
    codes = main.locator('table tbody tr td:first-child')
    first_codes = codes.all_text_contents()
    if baseline:
        main.get_by_role('button', name='Próxima', exact=True).click()
        expect(codes.first).not_to_have_text(first_codes[0])
    else:
        with page.expect_response(lambda response: urlparse(response.url).path.endswith('/accounts') and parse_qs(urlparse(response.url).query).get('page') == ['2']) as pending:
            main.get_by_role('button', name='Próxima', exact=True).click()
        response = pending.value
        assert response.status == 200
        payload = response.json()
        assert payload['page'] == 2 and payload['total'] == fixture['account_count'] and len(payload['items']) == 50, payload
        expected_codes = [row['access_code'] for row in payload['items']]
        assert expected_codes != first_codes and not set(expected_codes).intersection(first_codes), expected_codes
        expect(codes).to_have_text(expected_codes)
    expect(main.get_by_text('Página 2 de 452', exact=True)).to_be_visible()
    expect(main.locator('table tbody tr')).to_have_count(50)

    current = measure('participants', 'Participantes, produtos e serviços', lambda: expect(main.locator('tbody tr')).to_have_count(fixture['participant_count']), '/masters/participant')
    if not baseline:
        assert not any(r['path'].endswith(('/accounts', '/cost-centers', '/global-account-plans')) for r in current), current
    current = measure('payables_return', 'Contas a pagar', lambda: expect(main.locator('tbody tr')).to_have_count(50 if not baseline else 183))
    if not baseline:
        no_catalogs(current)
        assert not any('/global-account-plans' in r['path'] for r in current), current
    assert not report['console_errors'], report['console_errors']
    assert not report.get('request_failures'), report.get('request_failures')
    assert all(r['status'] is not None and r['status'] < 400 for r in requests), requests
    report['checks'].extend(['183 payables, filter, history and cancel without mutations', '22597 accounts, accent search, second page', 'no hidden-screen or unrelated catalog loads'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/performance/browser-after.json')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'baseline': args.baseline, 'measurements': {}, 'requests': [], 'console_errors': [], 'checks': [],
              'source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
              'network': {'latency_ms': 80, 'download_bytes_per_second': 524288, 'upload_bytes_per_second': 524288}}
    cleanups, page = [], None
    with evidence_guard(report, output, cleanups, lambda: page):
        sys.path.insert(0, str(root))
        spec = importlib.util.spec_from_file_location('performance_fixture', ROOT / 'scripts/benchmark_workspace.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture_manager = module.fixture_workspace()
        folder, fixture = fixture_manager.__enter__()
        cleanups.append(('fixture_cleanup', lambda: fixture_manager.__exit__(None, None, None)))
        report['fixture'] = fixture
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        log = output.with_suffix('.server.log').open('w')
        cleanups.append(('close_server_log', log.close))
        process = subprocess.Popen([sys.executable, 'scripts/run_preview.py', '--port', str(port)], cwd=root,
                                   env=dict(os.environ, ESCRITURA_DATA_DIR=folder, ESCRITURA_DEMO='1'), stdout=log, stderr=log)
        cleanups.append(('stop_server', lambda: stop_server(process)))
        for _ in range(100):
            try:
                with urllib.request.urlopen(url + '/api/health', timeout=1):
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError('Servidor sintético não iniciou.')
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        cleanups.append(('stop_playwright', playwright.stop))
        options = {'executable_path': os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}
        browser = playwright.chromium.launch(headless=True, **options)
        cleanups.append(('close_browser', browser.close))
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        cleanups.append(('close_context', context.close))
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send('Network.enable')
        cdp.send('Network.emulateNetworkConditions', {'offline': False, 'latency': 80, 'downloadThroughput': 524288, 'uploadThroughput': 524288})
        scenario(page, url, fixture, report, args.baseline)
        page.screenshot(path=str(output.with_suffix('.png')), full_page=True)
        report['ok'] = True
    print(json.dumps({'ok': True, 'output': str(output), 'measurements': report['measurements']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
