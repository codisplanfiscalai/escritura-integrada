"""Integrated document-card regression using Chromium and a disposable SQLite database."""
from datetime import date
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'browser-document-summary'


def snapshot(folder):
    # Read only the disposable fixture, including linked movements and audit events.
    with sqlite3.connect(f'file:{Path(folder) / "escritura.sqlite3"}?mode=ro', uri=True) as conn:
        return {table: hashlib.sha256(repr(conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()).encode()).hexdigest()
                for table in ('documents', 'journals', 'journal_lines', 'titles', 'audit')}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'checks': [], 'console_errors': [], 'synthetic_only': True}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-summary-') as folder:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            with (OUT / 'server.log').open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT,
                    env=dict(os.environ, ESCRITURA_DATA_DIR=folder, ESCRITURA_DEMO='1'), stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url + '/api/health', timeout=1): break
                    except OSError: time.sleep(.2)
                else: raise RuntimeError('Disposable server did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, **({'executable_path': os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                    report['browser_version'] = browser.version
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
                    try:
                        page.goto(url); page.get_by_role('button', name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
                        csrf = page.request.get(url + '/api/session').json()['csrf_token']
                        def post(path, payload):
                            response = page.request.post(url + '/api' + path, data=payload, headers={'X-CSRF-Token': csrf})
                            assert response.ok, response.text()
                            return response.json()
                        a = post('/companies', {'code': 'SYN-A', 'name': 'Resumo sintético A', 'tax_id': 'TEST0001000120', 'regime': 'outros', 'state': 'SP'})['id']
                        b = post('/companies', {'code': 'SYN-B', 'name': 'Resumo sintético B', 'tax_id': 'TEST0002000175', 'regime': 'outros', 'state': 'SP'})['id']
                        year = str(date.today().year)
                        post('/context', {'company_id': a, 'module': 'fiscal', 'period': year + '-09'})
                        for i in range(53):
                            outgoing = i == 51
                            month = '08' if i == 52 else '09'
                            doc = post(f'/companies/{a}/documents', {'direction': 'outgoing' if outgoing else 'incoming', 'number': f'SYN-{i:03}', 'model': '55', 'series': '1', 'issue_date': f'{year}-{month}-01', 'posting_date': f'{year}-{month}-01', 'partner_name': 'Cliente sintético' if outgoing else 'Fornecedor sintético', 'cfop': '5102' if outgoing else '1102', 'total': '20.00' if outgoing else '10.00'})
                            if outgoing:
                                post(f'/companies/{a}/documents/{doc["id"]}/book', {'version': doc['version'], 'reason': 'Fixture sintética', 'idempotency_key': 'summary-book', 'generate_titles': False})
                        post(f'/companies/{a}/exercises', {'module': 'fiscal', 'year': int(year) + 1})
                        before = snapshot(folder)
                        page.reload(); expect(page.locator('#active-company')).to_have_value(str(a))
                        def context(cid, selected_year=year):
                            page.keyboard.press('F8')
                            dialog = page.get_by_role('dialog', name='Empresa, ano e competência')
                            dialog.get_by_label('Empresa', exact=True).select_option(str(cid))
                            dialog.get_by_label('Ano a fixar (opcional)').fill(selected_year)
                            dialog.get_by_label('Competência a fixar (opcional)').select_option('09')
                            dialog.get_by_role('button', name='Aplicar contexto').click(); expect(dialog).to_have_count(0)
                        def nav(name):
                            button = page.get_by_role('navigation', name='Navegação principal').get_by_role('button', name=name, exact=True, include_hidden=True)
                            parent = button.locator('xpath=ancestor::details')
                            if parent.count() and parent.get_attribute('open') is None: parent.locator('summary').click()
                            button.click()
                        def cards(documents, review, booked, total):
                            values = page.locator('.view:visible .summary-strip strong')
                            expect(values).to_have_text([str(documents), str(review), str(booked), total])
                        context(a); nav('Escrituração e documentos')
                        month = page.get_by_label('Competência da consulta', exact=True)
                        expect(month).to_have_value('09'); cards(52, 51, 1, 'R$ 530,00')
                        expect(page.locator('.view:visible .table-scroll tbody tr')).to_have_count(50)
                        page.get_by_role('button', name='Próxima', exact=True).click(); expect(page.locator('.view:visible .table-scroll tbody tr')).to_have_count(2); cards(52, 51, 1, 'R$ 530,00')
                        month.select_option('08'); cards(1, 1, 0, 'R$ 10,00')
                        month.select_option('10'); cards(0, 0, 0, 'R$ 0,00')
                        expect(page.get_by_role('link', name='Exportar Excel (0)', exact=True)).to_have_attribute('href', re.compile('month=10'))
                        page.screenshot(path=str(OUT / 'empty-month.png'), full_page=True)
                        report['checks'].append('September: 52 documents across two pages; August: 1; October: zero cards/grid/export count')
                        month.select_option('09'); page.get_by_label('Filtrar operação', exact=True).select_option('outgoing'); cards(1, 0, 1, 'R$ 20,00')
                        page.get_by_label('Filtrar estado fiscal', exact=True).select_option('pending'); cards(0, 0, 0, 'R$ 0,00')
                        page.get_by_label('Filtrar estado fiscal', exact=True).select_option('booked'); cards(1, 0, 1, 'R$ 20,00')
                        page.get_by_role('textbox', name='Pesquisar documentos').fill('NO-MATCH'); cards(0, 0, 0, 'R$ 0,00')
                        page.get_by_role('textbox', name='Pesquisar documentos').fill('SYN-051'); cards(1, 0, 1, 'R$ 20,00')
                        page.screenshot(path=str(OUT / 'filtered-september.png'), full_page=True)
                        page.get_by_role('textbox', name='Pesquisar documentos').fill(''); page.get_by_label('Filtrar operação', exact=True).select_option(''); page.get_by_label('Filtrar estado fiscal', exact=True).select_option('')
                        for value in ['08', '09', '10', '09']: month.select_option(value)
                        cards(52, 51, 1, 'R$ 530,00'); nav('Visão geral'); nav('Escrituração e documentos'); expect(month).to_have_value('09'); cards(52, 51, 1, 'R$ 530,00')
                        report['checks'].append('Combined operation/status/search, rapid month changes and KeepAlive navigation retain correct cards')
                        context(b); cards(0, 0, 0, 'R$ 0,00'); context(a); cards(52, 51, 1, 'R$ 530,00')
                        context(a, str(int(year) + 1)); cards(0, 0, 0, 'R$ 0,00'); context(a); cards(52, 51, 1, 'R$ 530,00')
                        report['checks'].append('Company B and next exercise empty; returning to A/current exercise restores September')
                        assert before == snapshot(folder), 'Read-only UI checks changed documents, journals, titles or audit rows'
                        report['checks'].append('Documents, journals, journal lines, titles and audit hashes unchanged after UI filtering/navigation')
                        assert not report['console_errors'], report['console_errors']
                        report['ok'] = True
                    except Exception:
                        page.screenshot(path=str(OUT / 'failure.png'), full_page=True)
                        (OUT / 'failure.txt').write_text(page.locator('body').inner_text())
                        raise
                    finally: browser.close()
    except Exception as error:
        report['error'] = str(error); report['traceback'] = traceback.format_exc()
    finally:
        if process:
            process.terminate()
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
