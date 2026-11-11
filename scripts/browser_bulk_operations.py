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

from openpyxl import load_workbook
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
                        page.screenshot(path=str(OUT / name), full_page=True, animations='disabled')
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

                    auto_preview = {}

                    def open_bulk(action='delete'):
                        with page.expect_response(lambda r: '/bulk-operations/preview' in r.url and r.request.method == 'POST') as result:
                            page.get_by_role('button', name='Operar selecionados', exact=True).click()
                        assert result.value.ok, result.value.text()
                        auto_preview.clear()
                        auto_preview.update(result.value.json())
                        dialog.get_by_label(re.compile(r'^Operação')).select_option(action)
                        expect(dialog).to_be_visible()

                    def prepare():
                        if preview.is_visible():
                            # The initial preview is sufficient; no second preview step.
                            expect(dialog.get_by_role('button', name='Atualizar prévia', exact=True)).to_have_count(0)
                            return dict(auto_preview)
                        button = dialog.get_by_role('button', name=re.compile(r'^(Atualizar prévia|Conferir alteração)$'))
                        expect(button).to_be_enabled()
                        with page.expect_response(lambda r: '/bulk-operations/preview' in r.url and r.request.method == 'POST') as result:
                            button.click()
                        assert result.value.ok, result.value.text()
                        payload = result.value.json()
                        expect(preview).to_be_visible()
                        return payload

                    def confirm(delete=False):
                        action = dialog.get_by_label(re.compile(r'^Operação')).input_value()
                        assert delete == (action == 'delete')
                        labels = {'update': 'Aplicar alteração', 'review': 'Marcar selecionados como conferidos',
                                  'book': 'Escriturar selecionados'}
                        button = dialog.get_by_role('button', name=re.compile(r'^Excluir definitivamente') if delete else labels[action], exact=not delete)
                        expect(button).to_be_enabled()
                        with page.expect_response(lambda r: '/bulk-operations/confirm' in r.url and r.request.method == 'POST') as result:
                            button.click()
                        assert result.value.ok, result.value.text()
                        assert result.value.json()['completed']
                        assert result.value.json()['action'] == action
                        expect(dialog).to_have_count(0)
                        expect(page.get_by_role('button', name='Operar selecionados', exact=True)).to_be_disabled()

                    def export_search(expected_count):
                        for size in ('1000', '5000'):
                            page.get_by_label('Registros por página', exact=True).select_option(size)
                        link = page.get_by_role('link', name=f'Exportar Excel ({expected_count})', exact=True)
                        with page.expect_download() as downloaded:
                            link.click()
                        saved = Path(data) / downloaded.value.suggested_filename
                        downloaded.value.save_as(saved)
                        workbook = load_workbook(saved)
                        assert workbook['Dados'].max_row == expected_count + 1
                        report['checks'].append(f'Excel downloaded with all {expected_count} filtered records; pages 1000 and 5000 available')

                    def fill_reason():
                        details = dialog.locator('details.operation-details')
                        if details.get_attribute('open') is None:
                            details.locator('summary').first.click()
                        dialog.get_by_label('Observação (opcional)', exact=True).fill('Aceitação Chromium exclusivamente sintética')
                        details.locator('summary').first.click()

                    def gates(payload):
                        button = dialog.get_by_role('button', name=re.compile(r'^Excluir definitivamente'))
                        expect(button).to_be_enabled()
                        details = dialog.locator('details.operation-details')
                        assert details.get_attribute('open') is None
                        expect(dialog.get_by_text('Permissões:', exact=False)).not_to_be_visible()
                        expect(dialog.get_by_role('button', name='Atualizar prévia', exact=True)).to_have_count(0)
                        expect(dialog.get_by_label('Observação (opcional)', exact=True)).to_have_value('')
                        assert dialog.get_by_label(re.compile(r'^Digite exatamente:')).count() == 0
                        expect(preview).to_contain_text(str(payload['selected_count']))

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
                        # This regression flow explicitly opts into strict monthly locks.
                        policy = read(scope + '/operational-settings')
                        configured = page.request.put(url + scope + '/operational-settings',
                            data={'version': policy['version'], 'settings': policy['settings'] | {'enforce_period_locks': True}},
                            headers={'X-CSRF-Token': read('/api/session')['csrf_token']})
                        assert configured.ok, configured.text()
                        page.reload()
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
                        export_search(4)
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
                        expect(preview).to_be_visible()
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
                        report['checks'].append('Individual selection, automatic preview and single clear confirmation without mandatory reason or phrase; cancel, clear, filter, navigation and company change have zero business effects')
                        # Company-wide scope ignores the current query and selection, but cancel never mutates data.
                        with page.expect_response(lambda r: '/bulk-operations/preview' in r.url and r.request.method == 'POST') as cleanup:
                            page.get_by_role('button', name='Limpar tudo neste módulo', exact=True).click()
                        assert cleanup.value.ok, cleanup.value.text()
                        cleanup_payload = cleanup.value.json()
                        assert cleanup_payload['scope'] == 'company'
                        cleanup_dialog = page.get_by_role('dialog', name='Limpar todos os movimentos do módulo', exact=True)
                        expect(cleanup_dialog).to_contain_text('todos os exercícios')
                        expect(cleanup_dialog).to_contain_text('Ignora filtros, página e seleção')
                        assert cleanup_dialog.locator('details.operation-details').get_attribute('open') is None
                        shot('company-cleanup-desktop.png')
                        page.set_viewport_size({'width': 390, 'height': 844})
                        shot('company-cleanup-mobile.png')
                        assert page.evaluate('document.documentElement.scrollWidth') <= 391
                        page.set_viewport_size({'width': 1440, 'height': 1000})
                        cleanup_dialog.get_by_role('button', name='Cancelar', exact=True).click()
                        assert snapshot(cid) == before and snapshot(other) == other_before
                        report['checks'].append('Company-wide cleanup auto-previews all exercises with a clear scope; cancel preserves every movement')


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
                        export_search(3)

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
                        expect(dialog.get_by_role('button', name=re.compile(r'^Excluir definitivamente'))).to_be_disabled()
                        assert snapshot(cid) == closed_before
                        shot('closed-period-desktop.png')
                        dialog.get_by_role('button', name='Cancelar', exact=True).click()
                        report['checks'].append('Closed accounting period blocks deletion without bypass through the simplified confirmation; preview leaves all business rows unchanged')
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
