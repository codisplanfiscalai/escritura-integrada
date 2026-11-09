"""Real Chromium bulk acceptance; only disposable synthetic demo data.

API writes create fixtures only. Every bulk preview/confirmation is clicked in UI.
No fallback browser, mocked UI, skipped assertions, or production data paths.
"""
from pathlib import Path
import json
import os
import re
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
OUT = ROOT / 'artifacts' / 'browser-bulk-operations'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'checks': [], 'console_errors': [], 'screenshots': []}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-bulk-ui-') as data:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            with (OUT / 'server.log').open('w') as log:
                process = subprocess.Popen(
                    [sys.executable, 'scripts/run_preview.py', '--port', str(port)],
                    cwd=ROOT, env=dict(os.environ, ESCRITURA_DATA_DIR=data, ESCRITURA_DEMO='1'),
                    stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        urllib.request.urlopen(url + '/api/health', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError('Preview server did not start')
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, **(
                        {'executable_path': os.environ['ESCRITURA_TEST_BROWSER']}
                        if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda e: report['console_errors'].append(str(e)))
                    page.on('console', lambda m: report['console_errors'].append(m.text) if m.type == 'error' else None)

                    def shot(name):
                        page.screenshot(path=str(OUT / name), full_page=True)
                        report['screenshots'].append(name)

                    def read(path):
                        response = page.request.get(url + path)
                        assert response.ok, response.text()
                        return response.json()

                    def fixture(path, payload):
                        assert '/bulk-operations/' not in path
                        session = read('/api/session')
                        response = page.request.post(url + path, data=payload,
                                                     headers={'X-CSRF-Token': session['csrf_token']})
                        assert response.ok, (path, response.status, response.text())
                        return response.json()

                    def sql(query, params=()):
                        # Read-only database access, always under our TemporaryDirectory.
                        with sqlite3.connect(f'file:{Path(data) / "escritura.sqlite3"}?mode=ro', uri=True) as conn:
                            conn.row_factory = sqlite3.Row
                            return [dict(row) for row in conn.execute(query, params)]

                    def snapshot(company):
                        return {table: sql(f'SELECT * FROM {table} WHERE company_id=? ORDER BY id', (company,))
                                for table in ('documents', 'document_sources', 'journals', 'journal_lines', 'titles')}

                    def navigate(name):
                        nav = page.get_by_role('navigation', name='Navegação principal')
                        button = nav.get_by_role('button', name=name, exact=True, include_hidden=True)
                        parent = button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:
                            parent.locator('summary').click()
                        button.click()

                    dialog = page.get_by_role('dialog', name='Operação nos registros selecionados', exact=True)
                    preview = dialog.get_by_role('region', name='Prévia da operação')

                    def select_documents(docs):
                        for doc in docs:
                            page.get_by_role('checkbox', name=f'Selecionar documento {doc["number"]} (#{doc["id"]})', exact=True).check()

                    def open_bulk(action='delete'):
                        page.get_by_role('button', name='Operar selecionados', exact=True).click()
                        dialog.get_by_label(re.compile(r'^Operação')).select_option(action)
                        expect(dialog.get_by_role('button', name='Excluir definitivamente' if action == 'delete' else 'Confirmar operação', exact=True)).to_be_disabled()

                    def prepare():
                        with page.expect_response(lambda r: '/bulk-operations/preview' in r.url and r.request.method == 'POST') as result:
                            dialog.get_by_role('button', name='Gerar prévia', exact=True).click()
                        assert result.value.ok, result.value.text()
                        payload = result.value.json()
                        expect(preview).to_be_visible()
                        return payload

                    def confirm(delete=False):
                        with page.expect_response(lambda r: '/bulk-operations/confirm' in r.url and r.request.method == 'POST') as result:
                            dialog.get_by_role('button', name='Excluir definitivamente' if delete else 'Confirmar operação', exact=True).click()
                        assert result.value.ok, result.value.text()
                        assert result.value.json()['completed']
                        expect(dialog).to_have_count(0)
                        expect(page.get_by_role('button', name='Operar selecionados', exact=True)).to_be_disabled()

                    def fill_reason():
                        dialog.get_by_label('Motivo da operação *', exact=True).fill('Aceitação Chromium exclusivamente sintética')

                    def gates(payload):
                        button = dialog.get_by_role('button', name='Excluir definitivamente', exact=True)
                        expect(button).to_be_disabled()
                        fill_reason()
                        expect(button).to_be_disabled()
                        dialog.get_by_label('Entendo que a exclusão física', exact=False).check()
                        expect(button).to_be_disabled()
                        phrase = dialog.get_by_label(re.compile(r'^Digite exatamente:'))
                        phrase.fill('FRASE INCORRETA')
                        expect(button).to_be_disabled()
                        phrase.fill(payload['confirmation_phrase'])
                        expect(button).to_be_enabled()

                    try:
                        page.goto(url)
                        page.get_by_role('button', name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
                        page.locator('#active-period').fill('2026')
                        page.locator('#active-period').press('Tab')
                        expect(page.locator('#active-period')).to_have_value('2026')
                        cid = read('/api/session')['active_company_id']
                        other = next(c['id'] for c in read('/api/companies') if c['id'] != cid)
                        scope = f'/api/companies/{cid}'
                        other_before = snapshot(other)
                        original = snapshot(cid)
                        docs = [fixture(scope + '/documents', {
                            'direction': 'incoming', 'number': f'BULK-UI-{i}', 'series': '1', 'model': '55',
                            'issue_date': '2026-11-06', 'posting_date': '2026-11-06',
                            'partner_name': 'Fornecedor sintético Chromium', 'cfop': '1102',
                            'total': '100.00', 'taxes': {}, 'items': [],
                            'source': {'file': f'synthetic-{i}.xml'}, 'source_hash': f'bulk-ui-{i}'}) for i in range(4)]
                        accounts = {a['access_code']: a['id'] for a in read(scope + '/accounts')}
                        journals = [fixture(scope + '/journals', {
                            'date': date, 'document': f'BULK-UI-J-{i}', 'history': 'Histórico sintético original',
                            'idempotency_key': f'bulk-ui-j-{i}', 'lines': [
                                {'account_id': accounts['3'], 'debit': '123.45', 'credit': '0.00'},
                                {'account_id': accounts['5'], 'debit': '0.00', 'credit': '123.45'}]})
                            for i, date in enumerate(['2026-11-06', '2026-11-07', '2026-01-06'])]
                        fixture(scope + '/periods/close', {'period': '2026-01', 'module': 'accounting', 'reason': 'Fixture sintética fechada'})
                        before = snapshot(cid)
                        navigate('Escrituração e documentos')
                        search = page.get_by_role('textbox', name='Pesquisar documentos', exact=True)
                        search.fill('BULK-UI-')
                        select_documents([docs[0]])
                        open_bulk()
                        payload = prepare()
                        assert payload['can_confirm'] and payload['selected_count'] == 1
                        assert snapshot(cid) == before, 'Preview must not mutate business rows'
                        gates(payload)
                        shot('delete-preview-desktop.png')
                        page.set_viewport_size({'width': 390, 'height': 844})
                        shot('delete-preview-mobile.png')
                        assert page.evaluate('document.documentElement.scrollWidth') <= 391
                        page.set_viewport_size({'width': 1440, 'height': 1000})
                        dialog.get_by_role('button', name='Cancelar', exact=True).click()
                        assert snapshot(cid) == before
                        open_bulk()
                        expect(preview).to_have_count(0)
                        dialog.get_by_role('button', name='Cancelar', exact=True).click()
                        page.get_by_role('button', name='Limpar seleção', exact=True).click()
                        expect(page.get_by_role('button', name='Operar selecionados', exact=True)).to_be_disabled()
                        select_documents([docs[0]])
                        search.fill('BULK-UI-0')
                        expect(page.get_by_role('button', name='Operar selecionados', exact=True)).to_be_disabled()
                        search.fill('BULK-UI-')
                        select_documents([docs[0]])
                        navigate('Visão geral')
                        navigate('Escrituração e documentos')
                        expect(page.get_by_role('button', name='Operar selecionados', exact=True)).to_be_disabled()
                        search.fill('BULK-UI-')
                        select_documents([docs[0]])
                        page.locator('#active-company').select_option(str(other))
                        expect(page.get_by_role('button', name='Operar selecionados', exact=True)).to_be_disabled()
                        page.locator('#active-company').select_option(str(cid))
                        search.fill('BULK-UI-')
                        assert snapshot(cid) == before and snapshot(other) == other_before
                        report['checks'].append('Individual selection, mandatory preview/reason/ack/exact phrase; cancel, clear, filter, navigation and company change have zero business effects')

                        # Single safe header edit, then two-record review/book via UI only.
                        select_documents([docs[0]])
                        open_bulk('update')
                        dialog.get_by_label('Novo CFOP', exact=True).fill('1101')
                        assert prepare()['can_confirm']
                        fill_reason()
                        confirm()
                        row = next(d for d in read(scope + '/documents?year=2026') if d['id'] == docs[0]['id'])
                        assert row['cfop'] == '1101' and row['total_cents'] == 10000
                        for action, expected_status in [('review', 'reviewed'), ('book', 'booked')]:
                            select_documents(docs[:2])
                            open_bulk(action)
                            assert prepare()['can_confirm']
                            fill_reason()
                            confirm()
                            rows = read(scope + '/documents?year=2026')
                            assert all(next(d for d in rows if d['id'] == target['id'])['status'] == expected_status for target in docs[:2])
                        assert snapshot(cid)['journals'] == before['journals']
                        assert snapshot(cid)['journal_lines'] == before['journal_lines']
                        assert snapshot(cid)['titles'] == before['titles']
                        report['checks'].append('CFOP header update, two-record review and fiscal booking preserve amounts and create no journals or financial titles')
                        select_documents(docs[:2])
                        open_bulk()
                        payload = prepare()
                        assert payload['selected_count'] == 2 and payload['can_confirm']
                        assert payload['affected_counts']['document_sources'] == 2
                        gates(payload)
                        confirm(delete=True)
                        ids = [d['id'] for d in docs[:2]]
                        assert not any(d['id'] in ids for d in read(scope + '/documents?year=2026'))
                        for table, key in [('documents', 'id'), ('document_sources', 'document_id')]:
                            assert not sql(f'SELECT * FROM {table} WHERE {key} IN (?, ?)', ids)
                        for untouched in docs[2:]:
                            assert sql('SELECT * FROM documents WHERE id=?', (untouched['id'],))[0] == next(r for r in before['documents'] if r['id'] == untouched['id'])
                        report['checks'].append('Physical batch deletion removes documents and child source rows; nonselected records remain byte-for-byte identical')

                        navigate('Lançamentos contábeis')
                        journal_search = page.get_by_role('textbox', name='Pesquisar contabilidade', exact=True)
                        journal_search.fill('BULK-UI-J-')

                        def select_journals(items):
                            for journal in items:
                                checkbox = page.get_by_role('checkbox', name=f'Selecionar lançamento {journal.get("number") or journal["id"]} (#{journal["id"]})', exact=True)
                                expect(checkbox).to_have_count(1)
                                checkbox.check()

                        select_journals(journals[:2])
                        lines_before = sql('SELECT * FROM journal_lines WHERE company_id=? ORDER BY id', (cid,))
                        for field, value in [('history', 'Histórico sintético alterado'), ('document', 'BULK-UI-J-ALTERADO')]:
                            open_bulk('update')
                            dialog.get_by_label(re.compile(r'^Campo a substituir')).select_option(field)
                            dialog.get_by_label('Novo conteúdo', exact=True).fill(value)
                            assert prepare()['can_confirm']
                            fill_reason()
                            confirm()
                            for journal in journals[:2]:
                                current = read(scope + f'/journals/{journal["id"]}')
                                assert current[field] == value and current['total_cents'] == journal['total_cents']
                                journal[field] = value
                            assert sql('SELECT * FROM journal_lines WHERE company_id=? ORDER BY id', (cid,)) == lines_before
                            if field == 'history':
                                select_journals(journals[:2])
                        # After both references become identical, select exact visible checkboxes by ID/number.
                        journal_search.fill('BULK-UI-J-ALTERADO')
                        page.get_by_role('button', name=re.compile(r'^Selecionar somente os 2 visíveis')).click()
                        open_bulk()
                        payload = prepare()
                        assert payload['selected_count'] == 2 and payload['affected_counts']['journal_lines'] == 4
                        gates(payload)
                        confirm(delete=True)
                        for journal in journals[:2]:
                            assert not sql('SELECT * FROM journals WHERE id=?', (journal['id'],))
                            assert not sql('SELECT * FROM journal_lines WHERE journal_id=?', (journal['id'],))
                        report['checks'].append('Bulk accounting history/reference updates preserve values and all lines; physical deletion removes two journals and four child lines')
                        journal_search.fill('BULK-UI-J-2')
                        select_journals([journals[2]])
                        closed_before = snapshot(cid)
                        open_bulk()
                        payload = prepare()
                        assert not payload['can_confirm'] and payload['blockers']
                        expect(preview.get_by_role('alert')).to_contain_text('Operação bloqueada')
                        fill_reason()
                        dialog.get_by_label('Entendo que a exclusão física', exact=False).check()
                        dialog.get_by_label(re.compile(r'^Digite exatamente:')).fill(payload['confirmation_phrase'])
                        expect(dialog.get_by_role('button', name='Excluir definitivamente', exact=True)).to_be_disabled()
                        assert snapshot(cid) == closed_before
                        shot('closed-period-desktop.png')
                        dialog.get_by_role('button', name='Cancelar', exact=True).click()
                        report['checks'].append('Closed accounting period blocks deletion even with all confirmation fields; preview leaves all business rows unchanged')
                        navigate('Competências contábeis')
                        january = page.locator('article.month-card').filter(has=page.get_by_role('heading', name='Janeiro', exact=True))
                        january.get_by_role('button', name='Reabrir', exact=True).click()
                        reopen = page.get_by_role('dialog', name='Reabrir competência', exact=True)
                        reopen.get_by_label('Justificativa *', exact=True).fill('Reabertura autorizada da fixture sintética Chromium')
                        with page.expect_response(lambda r: '/periods/reopen' in r.url and r.request.method == 'POST') as reopened:
                            reopen.get_by_role('button', name='Confirmar reabertura', exact=True).click()
                        assert reopened.value.ok, reopened.value.text()
                        expect(reopen).to_have_count(0)
                        navigate('Lançamentos contábeis')
                        journal_search.fill('BULK-UI-J-2')
                        select_journals([journals[2]])
                        open_bulk()
                        payload = prepare()
                        assert payload['can_confirm'] and payload['selected_count'] == 1
                        gates(payload)
                        confirm(delete=True)
                        assert not sql('SELECT * FROM journals WHERE id=?', (journals[2]['id'],))
                        assert not sql('SELECT * FROM journal_lines WHERE journal_id=?', (journals[2]['id'],))
                        report['checks'].append('Explicit UI reopening allows a fresh preview and physical individual deletion, including child journal lines')
                        assert snapshot(other) == other_before
                        final = snapshot(cid)
                        for table, rows in original.items():
                            assert all(row in final[table] for row in rows), f'Pre-existing demo rows changed: {table}'
                        assert not sql('PRAGMA foreign_key_check')
                        assert list(sql('PRAGMA integrity_check')[0].values()) == ['ok']
                        assert not report['console_errors'], report['console_errors']
                        report['checks'].append('Other company and every original demo business row unchanged; SQLite foreign keys/integrity valid; no console/page errors')
                        report['browser_version'] = browser.version
                        report['ok'] = True
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
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
