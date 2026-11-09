"""Real Chromium report acceptance with isolated synthetic demo data.

Run after npm run build with ESCRITURA_TEST_BROWSER=/usr/bin/chromium.
Network race tests delay delivery of real server responses, never replace data.
"""
from pathlib import Path
from io import BytesIO
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from urllib.parse import urlparse, parse_qs
from zipfile import ZipFile
from pypdf import PdfReader
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'browser-reports'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'stage': 'setup', 'checks': [], 'console_errors': [], 'downloads': [], 'screenshots': []}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-reports-ui-') as data:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            with (OUT / 'server.log').open('w') as log:
                process = subprocess.Popen([sys.executable, 'scripts/run_preview.py', '--port', str(port)],
                    cwd=ROOT, env=dict(os.environ, ESCRITURA_DATA_DIR=data, ESCRITURA_DEMO='1'), stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        urllib.request.urlopen(url + '/api/health', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError('Preview server did not start')
                with sync_playwright() as playwright:
                    report['stage'] = 'failed-before-launch'
                    browser = playwright.chromium.launch(headless=True, **(
                        {'executable_path': os.environ['ESCRITURA_TEST_BROWSER']}
                        if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel': 'chromium'}))
                    report['stage'] = 'browser-acceptance'
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
                    page.set_default_timeout(15000)
                    page.add_init_script("window.reportPolicyViolations=[];document.addEventListener('securitypolicyviolation',e=>window.reportPolicyViolations.push({directive:e.effectiveDirective,blocked:e.blockedURI}));")
                    page.on('pageerror', lambda e: report['console_errors'].append(str(e)))
                    page.on('console', lambda m: report['console_errors'].append(m.text) if m.type == 'error' else None)
                    output = page.locator('.report-output')
                    controls = page.locator('.report-controls')
                    kind = controls.get_by_label('Relatório', exact=True)
                    model = controls.get_by_label('Modelo de impressão', exact=True)

                    def shot(name):
                        page.screenshot(path=str(OUT / name), full_page=True)
                        report['screenshots'].append(name)

                    def read(path):
                        response = page.request.get(url + path)
                        assert response.ok, response.text()
                        return response.json()

                    def navigate(name):
                        nav = page.get_by_role('navigation', name='Navegação principal')
                        button = nav.get_by_role('button', name=name, exact=True, include_hidden=True)
                        parent = button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:
                            parent.locator('summary').click()
                        button.click()

                    def run():
                        with page.expect_response(lambda r: '/business-reports/' in r.url and 'format=' not in r.url) as response:
                            controls.get_by_role('button', name='Gerar relatório', exact=True).click()
                        r = response.value
                        assert r.ok, r.text()
                        expect(output).to_be_visible()
                        expect(output.locator('table')).to_have_count(1)
                        return r.json(), r.url

                    def export(label, fmt):
                        with page.expect_download() as event:
                            output.get_by_role('link', name=label, exact=True).click()
                        download = event.value
                        assert download.failure() is None
                        payload = Path(download.path()).read_bytes()
                        assert payload
                        if fmt == 'pdf':
                            assert payload.startswith(b'%PDF-')
                            assert len(PdfReader(BytesIO(payload)).pages) >= 1
                        elif fmt == 'xlsx':
                            with ZipFile(BytesIO(payload)) as archive:
                                assert 'xl/workbook.xml' in archive.namelist()
                        else:
                            assert '<html' not in payload.decode('utf-8-sig')[:100].lower()
                        target = OUT / f'{kind.input_value()}-{download.suggested_filename}'
                        download.save_as(target)
                        report['downloads'].append({'kind': kind.input_value(), 'format': fmt, 'bytes': len(payload), 'filename': download.suggested_filename})

                    def preview_cycle():
                        assert page.evaluate('navigator.pdfViewerEnabled'), 'Chromium has no real embedded PDF viewer'
                        with page.expect_response(lambda r: '/business-reports/' in r.url and 'format=pdf' in r.url) as response:
                            output.get_by_role('button', name='Visualizar PDF', exact=True).click()
                        assert response.value.ok and response.value.headers['content-type'].startswith('application/pdf')
                        assert len(PdfReader(BytesIO(response.value.body())).pages) >= 1
                        section = page.get_by_role('region', name='Prévia do relatório')
                        expect(section.locator('iframe')).to_be_visible()
                        expect(section.locator('iframe')).to_have_attribute('src', re.compile(r'^blob:'))
                        assert not page.evaluate('window.reportPolicyViolations'), page.evaluate('window.reportPolicyViolations')
                        section.get_by_role('button', name='Maximizar prévia').click()
                        dialog = page.get_by_role('dialog')
                        expect(dialog).to_be_visible()
                        box = dialog.bounding_box()
                        assert box['width'] > 1300 and box['height'] > 900
                        shot('preview-maximized.png')
                        dialog.get_by_role('button', name='Restaurar prévia').click()
                        expect(dialog).to_have_count(0)
                        expect(section.locator('iframe')).to_be_visible()
                        section.get_by_role('button', name='Maximizar prévia').click()
                        page.keyboard.press('Escape')
                        expect(dialog).to_have_count(0)
                        section.get_by_role('button', name='Maximizar prévia').click()
                        dialog.get_by_role('button', name='Fechar janela', exact=True).click()
                        expect(dialog).to_have_count(0)
                        section.get_by_role('button', name='Fechar prévia', exact=True).click()
                        expect(section).to_have_count(0)
                        output.get_by_role('button', name='Visualizar PDF', exact=True).click()
                        expect(section.locator('iframe')).to_be_visible()
                        section.get_by_role('button', name='Fechar prévia', exact=True).click()
                        report['checks'].append('Real PDF response/blob iframe; maximize, restore, Escape, close button and second opening')

                    try:
                        page.goto(url)
                        page.get_by_role('button', name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
                        page.locator('#active-period').fill('2026')
                        page.locator('#active-period').press('Tab')
                        expect(page.locator('#active-period')).to_be_enabled()
                        expect(page.locator('#active-period')).to_have_value('2026')
                        cid = read('/api/session')['active_company_id']
                        other = next(c['id'] for c in read('/api/companies') if c['id'] != cid)
                        catalog = read(f'/api/companies/{cid}/report-models')
                        areas = [('accounting', 'Livros e demonstrações'), ('fiscal', 'Livros e relatórios fiscais'), ('financial', 'Consultas e relatórios financeiros')]
                        for area, name in areas:
                            navigate(name)
                            expect(kind).to_have_value({'accounting': 'trial-balance', 'fiscal': 'fiscal-documents', 'financial': 'financial'}[area])
                            expect(controls.get_by_role('button', name='Gerar relatório', exact=True)).to_be_enabled()
                            options = kind.locator('option').evaluate_all('(xs)=>xs.map(x=>x.value)')
                            for value in options:
                                kind.select_option(value)
                                # Wait for asynchronous model catalog before taking options.
                                expect(page.locator('.model-catalog')).to_be_visible()
                                expected_models = [m for m in catalog if m['kind'] == value and m.get('supported', True)]
                                expect(model.locator('option')).to_have_count(1 + len(expected_models))
                                choices = model.locator('option').evaluate_all('(xs)=>xs.map(x=>x.value)')
                                chosen = choices[-1]
                                model.select_option('internal')
                                expect(controls.get_by_label('Folha inicial')).to_be_disabled()
                                model.select_option(chosen)
                                if chosen != 'internal':
                                    expect(controls.get_by_label('Folha inicial')).to_be_enabled()
                                payload, report_url = run()
                                assert payload['kind'] == value and payload['company_id'] == cid
                                export('PDF', 'pdf')
                                report['checks'].append(f'{area}/{value}: selected {chosen}, real table + downloaded parseable PDF')
                            for label, fmt in [('Exportar CSV','csv'),('Excel','xlsx')]:
                                export(label, fmt)
                            shot(f'{area}-report.png')
                            if area == 'accounting':
                                preview_cycle()
                                # Export and preview must keep the generated snapshot when filters change.
                                old_href = output.get_by_role('link', name='PDF', exact=True).get_attribute('href')
                                controls.get_by_label('Folha inicial').fill('8')
                                expect(output.get_by_role('status')).to_contain_text('Filtros alterados')
                                assert output.get_by_role('link', name='PDF', exact=True).get_attribute('href') == old_href
                                report['checks'].append('Changing unsubmitted filters preserves export snapshot and shows stale-filter warning')

                        navigate('Livros e relatórios fiscais')
                        kind.select_option('fiscal-documents')
                        controls.get_by_label('Situação', exact=True).select_option('pending')
                        controls.get_by_label('Operação', exact=True).select_option('outgoing')
                        controls.get_by_label('CFOP', exact=True).fill('5102')
                        controls.get_by_label('NCM', exact=True).fill('12345678')
                        controls.get_by_label('Documento, participante ou histórico').fill('synthetic-query')
                        kind.select_option('fiscal-entries')
                        expect(controls.get_by_label('Situação', exact=True)).to_have_count(0)
                        expect(controls.get_by_label('Operação', exact=True)).to_have_count(0)
                        expect(controls.get_by_label('CFOP', exact=True)).to_have_value('')
                        payload, requested = run()
                        q = parse_qs(urlparse(requested).query)
                        assert not q.get('status') and not q.get('direction')
                        assert all(r.get('direction') in (None, 'incoming') for r in payload['rows'])
                        kind.select_option('fiscal-assessments')
                        for label in ('Situação','Operação','CFOP','NCM','Documento, participante ou histórico'):
                            expect(controls.get_by_label(label, exact=True)).to_have_count(0)
                        _, requested = run()
                        q = parse_qs(urlparse(requested).query)
                        assert not any(q.get(k) for k in ('status','direction','cfop','ncm','query'))
                        report['checks'].append('Entry book fixed status/direction, type changes clear filters; assessments hide and omit all document filters')

                        # Capture real responses and change context before fulfilling their delivery.
                        for change in ('kind','company'):
                            kind.select_option('fiscal-documents')
                            captured = []
                            def delayed(route):
                                response = route.fetch()
                                assert response.ok
                                # Keep the actual route pending; interact outside its callback.
                                captured.append((route, response))
                            page.route('**/business-reports/fiscal-documents?*', delayed)
                            controls.get_by_role('button', name='Gerar relatório', exact=True).click()
                            deadline = time.monotonic() + 15
                            while not captured and time.monotonic() < deadline:
                                page.wait_for_timeout(50)
                            assert len(captured) == 1, 'Real report request was not intercepted once'
                            route, response = captured[0]
                            if change == 'kind':
                                kind.select_option('fiscal-items')
                                expect(kind).to_have_value('fiscal-items')
                            else:
                                page.locator('#active-company').select_option(str(other))
                                expect(page.locator('#active-company')).to_have_value(str(other))
                                expect(page.locator('#active-company')).to_be_enabled()
                            expect(output).to_have_count(0)
                            with page.expect_response(lambda r: r.url == route.request.url) as delivered:
                                route.fulfill(response=response)
                            assert delivered.value.ok
                            delivered.value.finished()
                            # Drain browser tasks after the response's fetch/JSON continuation.
                            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                            expect(output).to_have_count(0)
                            expect(controls.get_by_role('button', name='Gerar relatório', exact=True)).to_be_enabled()
                            page.unroute('**/business-reports/fiscal-documents?*', delayed)
                            report['checks'].append(f'Late real response after {change} change cannot repopulate stale report')
                        page.locator('#active-company').select_option(str(cid))
                        page.set_viewport_size({'width':390,'height':844})
                        expect(kind).to_be_visible()
                        shot('mobile-controls.png')
                        assert page.evaluate('document.documentElement.scrollWidth') <= 391
                        assert not report['console_errors'], report['console_errors']
                        assert not page.evaluate('window.reportPolicyViolations'), page.evaluate('window.reportPolicyViolations')
                        report['browser_version'] = browser.version
                        report['ok'] = True
                        report['stage'] = 'completed'
                    except Exception:
                        shot('failure.png')
                        (OUT / 'failure-visible.txt').write_text(page.locator('body').inner_text())
                        raise
                    finally:
                        browser.close()
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
    finally:
        if process:
            process.terminate()
            process.wait(timeout=15)
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
