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
from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'browser-reports'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'stage': 'setup', 'checks': [], 'console_errors': [], 'downloads': [], 'screenshots': [], 'preview_boxes': [], 'preview_evidence': []}
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
                    # get_by_label(exact=True) includes option text for wrapping <label><select>.
                    # Role accessible names correctly exclude the nested control's option text.
                    controls = page.locator('form.report-controls')
                    kind = controls.get_by_role('combobox', name='Relatório', exact=True)
                    model = controls.get_by_role('combobox', name='Modelo de impressão', exact=True)

                    def shot(name):
                        page.screenshot(path=str(OUT / name), full_page=True, animations='disabled')
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

                    def wait_maximized(dialog):
                        viewport = page.viewport_size
                        deadline = time.monotonic() + 15
                        box = previous = None
                        while time.monotonic() < deadline:
                            box = dialog.bounding_box()
                            if box and box == previous and box['width'] > viewport['width'] * .94 and box['height'] > viewport['height'] * .90:
                                break
                            previous = box
                            page.wait_for_timeout(100)
                        report['preview_boxes'].append({'box': box, 'viewport': viewport})
                        assert box and box['width'] > viewport['width'] * .94 and box['height'] > viewport['height'] * .90, report['preview_boxes'][-1]

                    def wait_pdf_pixels(frame_locator, name):
                        """Observe real compositor pixels, not merely iframe/load/PDF bytes.

                        Plugin internals vary by Chromium version, so capture them as
                        diagnostics; the rendering gate requires both paper and ink.
                        Pillow is already a ReportLab runtime dependency.
                        """
                        expect(frame_locator).to_be_visible()
                        expect(frame_locator).to_have_attribute('src', re.compile(r'^blob:'))
                        frame_locator.scroll_into_view_if_needed()
                        deadline = time.monotonic() + 25
                        evidence = {'name': name, 'rendered': False}
                        last_png = None
                        stable = 0
                        while time.monotonic() < deadline:
                            last_png = frame_locator.screenshot(animations='disabled')
                            with Image.open(BytesIO(last_png)) as image:
                                # Exclude viewer toolbar, scrollbar and peripheral dark canvas.
                                w, h = image.size
                                sample = image.crop((int(w*.25), int(h*.14), int(w*.75), int(h*.80))).convert('L')
                                sample.thumbnail((480, 480))
                                width, height = sample.size
                                pixels = sample.load()
                                white = sum(v > 235 for v in sample.getdata()) / (width * height)
                                # Ink must be surrounded by paper, not the dark viewer background.
                                ink = sum(1 for y in range(3, height-3) for x in range(3, width-3)
                                          if pixels[x,y] < 160 and
                                          ((pixels[x-3,y] > 235 and pixels[x+3,y] > 235) or
                                           (pixels[x,y-3] > 235 and pixels[x,y+3] > 235)))
                            evidence.update(white_fraction=white, ink_pixels=ink)
                            stable = stable + 1 if white > .20 and ink >= 20 else 0
                            if stable >= 2:
                                evidence['rendered'] = True
                                break
                            page.wait_for_timeout(250)
                        frames = []
                        for frame in page.frames:
                            try:
                                info = frame.evaluate("""() => ({url:location.href, ready:document.readyState,
                                    pdfEmbed:!!document.querySelector('embed[type="application/pdf"], embed[type="application/x-google-chrome-pdf"]'),
                                    viewer:!!document.querySelector('pdf-viewer'),
                                    loading:document.querySelector('pdf-viewer')?.loadState ?? null})""")
                                if info['pdfEmbed'] or info['viewer'] or info['url'].startswith(('blob:', 'chrome-extension:')):
                                    frames.append(info)
                            except Exception as error:
                                frames.append({'url': frame.url, 'inspection_error': str(error)[:200]})
                        evidence['frames'] = frames
                        evidence['policy_violations'] = page.evaluate('window.reportPolicyViolations')
                        report['preview_evidence'].append(evidence)
                        if last_png:
                            (OUT / (name + '-frame.png')).write_bytes(last_png)
                            report['screenshots'].append(name + '-frame.png')
                        assert evidence['rendered'], f'PDF page paper/ink did not render: {evidence}'
                        assert not evidence['policy_violations'], evidence['policy_violations']
                        shot(name + '.png')

                    def preview_cycle():
                        assert page.evaluate('navigator.pdfViewerEnabled'), 'Chromium has no real embedded PDF viewer'
                        with page.expect_response(lambda r: '/business-reports/' in r.url and 'format=pdf' in r.url) as response:
                            output.get_by_role('button', name='Visualizar PDF', exact=True).click()
                        assert response.value.ok and response.value.headers['content-type'].startswith('application/pdf')
                        assert len(PdfReader(BytesIO(response.value.body())).pages) >= 1
                        section = page.get_by_role('region', name='Prévia do relatório')
                        expect(section.locator('iframe')).to_be_visible()
                        expect(section.locator('iframe')).to_have_attribute('src', re.compile(r'^blob:'))
                        wait_pdf_pixels(section.locator('iframe'), 'preview-inline')
                        section.get_by_role('button', name='Maximizar prévia').click()
                        dialog = page.get_by_role('dialog')
                        expect(dialog).to_be_visible()
                        wait_maximized(dialog)
                        wait_pdf_pixels(dialog.locator('iframe'), 'preview-maximized')
                        dialog.get_by_role('button', name='Restaurar prévia').click()
                        expect(dialog).to_have_count(0)
                        wait_pdf_pixels(section.locator('iframe'), 'preview-restored')
                        section.get_by_role('button', name='Maximizar prévia').click()
                        page.keyboard.press('Escape')
                        expect(dialog).to_have_count(0)
                        section.get_by_role('button', name='Maximizar prévia').click()
                        dialog.get_by_role('button', name='Fechar janela', exact=True).click()
                        expect(dialog).to_have_count(0)
                        section.get_by_role('button', name='Fechar prévia', exact=True).click()
                        expect(section).to_have_count(0)
                        output.get_by_role('button', name='Visualizar PDF', exact=True).click()
                        wait_pdf_pixels(section.locator('iframe'), 'preview-second-opening')
                        section.get_by_role('button', name='Fechar prévia', exact=True).click()
                        report['checks'].append('Real PDF response and observed paper/ink compositor pixels inline, maximized, restored and reopened; Escape and close controls')

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
                            expect(page.get_by_role('tab', name=name, exact=True)).to_have_attribute('aria-selected', 'true')
                            expect(controls).to_have_count(1)
                            expect(controls).to_be_visible()
                            expect(kind).to_have_value({'accounting': 'trial-balance', 'fiscal': 'fiscal-documents', 'financial': 'financial'}[area])
                            expect(controls.get_by_role('button', name='Gerar relatório', exact=True)).to_be_enabled()
                            if area == 'accounting':
                                # Fixture preparation only in this process's isolated demo directory.
                                # First prove the domain rejects incomplete classifications unchanged.
                                assert Path(data).is_dir() and Path(data).name.startswith('escritura-reports-ui-')
                                companies = read('/api/companies')
                                assert next(c for c in companies if c['id'] == cid)['code'] == 'DEMO001'
                                other_accounts = read(f'/api/companies/{other}/accounts')
                                precondition = page.request.get(
                                    url + f'/api/companies/{cid}/business-reports/balance-sheet'
                                    '?start=2026-01-01&end=2026-12-31')
                                assert precondition.status == 409, precondition.text()
                                assert precondition.json().get('code') == 'unmapped_accounts', precondition.text()
                                report['checks'].append('Unclassified disposable demo balance sheet returns 409/unmapped_accounts before fixture setup')
                                groups = {'1': 'asset', '2': 'asset', '3': 'asset',
                                          '4': 'liability', '5': 'revenue', '6': 'expense'}
                                accounts = read(f'/api/companies/{cid}/accounts')
                                assert {a['access_code'] for a in accounts} == set(groups)
                                csrf = read('/api/session')['csrf_token']
                                for account in accounts:
                                    response = page.request.put(
                                        url + f'/api/companies/{cid}/accounts/{account["id"]}',
                                        data={'version': account['version'],
                                              'report_group': groups[account['access_code']]},
                                        headers={'X-CSRF-Token': csrf})
                                    assert response.ok, response.text()
                                    saved = response.json()
                                    assert saved['report_group'] == groups[account['access_code']]
                                    assert saved['version'] == account['version'] + 1
                                    for field in ('access_code', 'classifier', 'name', 'nature',
                                                  'analytical', 'requires_cost_center', 'active'):
                                        assert saved[field] == account[field], (field, saved, account)
                                assert read(f'/api/companies/{other}/accounts') == other_accounts
                                report['checks'].append('Explicit versioned/CSRF account-group fixture for DEMO001 only; account identity, nature, flags and other company unchanged')
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
                                expect(controls.get_by_role('spinbutton', name='Folha inicial', exact=True)).to_be_disabled()
                                model.select_option(chosen)
                                if chosen != 'internal':
                                    expect(controls.get_by_role('spinbutton', name='Folha inicial', exact=True)).to_be_enabled()
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
                                controls.get_by_role('spinbutton', name='Folha inicial', exact=True).fill('8')
                                expect(output.get_by_role('status')).to_contain_text('Filtros alterados')
                                assert output.get_by_role('link', name='PDF', exact=True).get_attribute('href') == old_href
                                report['checks'].append('Changing unsubmitted filters preserves export snapshot and shows stale-filter warning')

                        navigate('Livros e relatórios fiscais')
                        kind.select_option('fiscal-documents')
                        controls.get_by_role('combobox', name='Situação', exact=True).select_option('pending')
                        controls.get_by_role('combobox', name='Operação', exact=True).select_option('outgoing')
                        controls.get_by_role('textbox', name='CFOP', exact=True).fill('5102')
                        controls.get_by_role('textbox', name='NCM', exact=True).fill('12345678')
                        controls.get_by_role('textbox', name='Documento, participante ou histórico', exact=True).fill('synthetic-query')
                        kind.select_option('fiscal-entries')
                        book_status = controls.get_by_role('combobox', name='Situação', exact=True)
                        expect(book_status).to_be_visible()
                        expect(book_status).to_have_value('')
                        assert book_status.locator('option').evaluate_all('(xs)=>xs.map(x=>x.value)') == ['', 'cancelled']
                        expect(controls.get_by_role('combobox', name='Operação', exact=True)).to_have_count(0)
                        expect(controls.get_by_role('textbox', name='CFOP', exact=True)).to_have_value('')
                        # Explicit fixture in this disposable demo only. The new
                        # documentary filter must select a real zero-valued row,
                        # not merely be present or silently ignored.
                        def fixture_post(path, payload):
                            response = page.request.post(url + f'/api/companies/{cid}' + path,
                                data=payload, headers={'X-CSRF-Token': read('/api/session')['csrf_token']})
                            assert response.ok, response.text()
                            return response.json()
                        cancellation = fixture_post('/documents', {
                            'direction':'incoming','model':'55','series':'1','number':'90298',
                            'issue_date':'2026-11-06','posting_date':'2026-11-06',
                            'partner_name':'Emitente sintético do filtro','partner_tax_id':'11111111111',
                            'total':'0.00','items':[],'taxes':{},
                            'book_cancellation':{'source':'Livro sintético de filtros, página 1',
                                'responsible':'Revisor sintético','reason':'Cancelamento documental conferido'}})
                        cancellation = fixture_post(f"/documents/{cancellation['id']}/review",
                            {'version':cancellation['version'],'reason':'Conferência sintética do filtro'})
                        fixture_post(f"/documents/{cancellation['id']}/book",
                            {'version':cancellation['version'],'reason':'Linha zero no livro sintético'})
                        payload, requested = run()
                        q = parse_qs(urlparse(requested).query)
                        assert not q.get('status') and not q.get('direction')
                        assert all(r.get('direction') in (None, 'incoming') for r in payload['rows'])
                        book_status.select_option('cancelled')
                        payload, requested = run()
                        assert parse_qs(urlparse(requested).query).get('status') == ['cancelled']
                        assert payload['filters']['status'] == 'cancelled'
                        assert len(payload['rows']) == 1 and payload['rows'][0]['document_id'] == cancellation['id']
                        assert payload['rows'][0]['document_state'] == 'cancelled' and payload['rows'][0]['status'] == 'booked'
                        assert payload['totals']['total_cents'] == 0
                        shot('fiscal-book-cancelled-filter.png')
                        kind.select_option('fiscal-assessments')
                        for label, role in [('Situação', 'combobox'), ('Operação', 'combobox'), ('CFOP', 'textbox'), ('NCM', 'textbox'), ('Documento, participante ou histórico', 'textbox')]:
                            expect(controls.get_by_role(role, name=label, exact=True)).to_have_count(0)
                        _, requested = run()
                        q = parse_qs(urlparse(requested).query)
                        assert not any(q.get(k) for k in ('status','direction','cfop','ncm','query'))
                        report['checks'].append('Entry book fixes booked lifecycle/direction, offers only explicit cancelled documentary filter selecting a zero row; type changes clear filters and assessments omit document filters')

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
                        (OUT / 'failure-dom.html').write_text(page.content())
                        (OUT / 'failure-aria.txt').write_text(page.locator('body').aria_snapshot())
                        (OUT / 'failure-controls.json').write_text(json.dumps(page.locator('form').evaluate_all(
                            '(forms) => forms.map(f => ({className:f.className, visible:!!f.getClientRects().length, labels:[...f.querySelectorAll("label")].map(l=>({text:l.textContent, html:l.outerHTML}))}))'
                        ), ensure_ascii=False, indent=2))
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
