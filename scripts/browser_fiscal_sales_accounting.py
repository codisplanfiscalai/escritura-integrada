"""Integrated UI/API acceptance; only generated fixtures and disposable SQLite."""
from datetime import date
import hashlib
import json
import os
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
OUT = ROOT / 'artifacts' / 'browser-fiscal-sales-accounting'


def snapshot(folder, cid, tables=('documents', 'journals', 'journal_lines', 'titles', 'audit')):
    with sqlite3.connect(f'file:{Path(folder) / "escritura.sqlite3"}?mode=ro', uri=True) as conn:
        return {t: hashlib.sha256(repr(conn.execute(f'SELECT * FROM {t} WHERE company_id=? ORDER BY id', (cid,)).fetchall()).encode()).hexdigest() for t in tables}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'synthetic_only': True, 'checks': [], 'console_errors': []}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-sales-ui-') as folder:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            year = str(date.today().year)
            with (OUT / 'server.log').open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT,
                    env=dict(os.environ, ESCRITURA_DATA_DIR=folder, ESCRITURA_DEMO='1'), stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url + '/api/health', timeout=1): break
                    except OSError: time.sleep(.2)
                else: raise RuntimeError('Synthetic server did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, **({'executable_path': os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                    report['browser_version'] = browser.version
                    page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
                    try:
                        page.goto(url); page.get_by_role('button', name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
                        csrf = page.request.get(url + '/api/session').json()['csrf_token']
                        def post(path, data):
                            r = page.request.post(url + '/api' + path, data=data, headers={'X-CSRF-Token': csrf})
                            assert r.ok, r.text()
                            return r.json()
                        def get(path):
                            r = page.request.get(url + '/api' + path); assert r.ok, r.text(); return r.json()
                        def nav(name):
                            b = page.get_by_role('navigation', name='Navegação principal').get_by_role('button', name=name, exact=True, include_hidden=True)
                            group = b.locator('xpath=ancestor::details')
                            if group.count() and group.get_attribute('open') is None: group.locator('summary').click()
                            b.click()
                        def section(name):
                            tab=page.get_by_role('tablist',name='Seções da integração contábil').get_by_role('tab',name=name,exact=True)
                            tab.click();expect(tab).to_have_attribute('aria-selected','true')
                        def enter():
                            nav('Integração Contábil')
                            expect(page.get_by_role('heading', name='Integração Contábil', exact=True)).to_be_visible()
                            expect(page.get_by_label('Sentido da integração')).to_be_enabled()
                        def context(cid):
                            page.keyboard.press('F8'); d = page.get_by_role('dialog', name='Empresa, ano e competência')
                            d.get_by_label('Empresa', exact=True).select_option(str(cid)); d.get_by_label('Ano a fixar (opcional)').fill(year)
                            d.get_by_label('Competência a fixar (opcional)').select_option('11')
                            d.get_by_role('button', name='Aplicar contexto').click(); expect(d).to_have_count(0)
                            expect(page.locator('#active-company')).to_have_value(str(cid))
                            expect(page.get_by_label('Sentido da integração')).to_be_enabled()
                        def save_mode(value):
                            section('Parâmetros e ajuda')
                            page.get_by_label('Geração de lançamentos').select_option(value)
                            page.get_by_role('button', name='Salvar modo da empresa').click()
                            expect(page.get_by_text('Modo salvo: ' + ('diário' if value == 'daily' else 'individual'), exact=True)).to_be_visible()
                            section('Notas e seleção')
                        def apply_model(mid):
                            section('Contabilizar')
                            details=page.locator('.sales-optional-model')
                            if details.get_attribute('open') is None:details.locator('summary').click()
                            page.get_by_label('Modelo comum para as selecionadas').select_option(str(mid))
                            page.get_by_role('button', name='Aplicar modelo às selecionadas').click()
                        def documents(cid): return get(f'/companies/{cid}/documents?year={year}')
                        def journals(cid): return get(f'/companies/{cid}/journals?year={year}')
                        def sale(cid, number, total='10.00', day='06', cfop='5102', book=True, titles=False):
                            d = post(f'/companies/{cid}/documents', {'direction':'outgoing','number':number,'series':'1','model':'55',
                                'issue_date':year+'-10-30','posting_date':f'{year}-11-{day}','partner_name':'Cliente exclusivamente sintético','cfop':cfop,'total':total})
                            if book:
                                body = {'version':d['version'],'reason':'Fixture sintética de interface'}
                                if titles: body.update(generate_titles=True, installments=[{'amount':total,'due_date':year+'-12-06'}])
                                d = post(f'/companies/{cid}/documents/{d["id"]}/book', body)['document']
                            return d
                        def setup(cid, prefix):
                            post('/context', {'company_id':cid,'module':'fiscal','period':year+'-11'})
                            accounts = {a['access_code']:a['id'] for a in get(f'/companies/{cid}/accounts')}
                            def model(code, credit):
                                return post(f'/companies/{cid}/masters/accounting_model', {'code':code,'name':code,'data':{
                                    'debit_account_id':accounts['3'],'credit_account_id':accounts[credit],'direction':'outgoing',
                                    'valid_from':year+'-01-01','status':'validated','history':'Venda fictícia','source':'Fixture sintética','responsible':'Teste'}})['id']
                            return model(prefix+'-VENDA','5'), model(prefix+'-OUTRA','4')
                        a = post('/companies', {'code':'SYN-SALES-A','name':'Integração sintética A','tax_id':'TEST0001000120','regime':'outros','state':'SP','create_default_accounts':True})['id']
                        b = post('/companies', {'code':'SYN-SALES-B','name':'Integração sintética B','tax_id':'TEST0002000175','regime':'outros','state':'SP','create_default_accounts':True})['id']
                        ma, other = setup(a, 'A')
                        originals = [sale(a,'A-01','0.01',titles=True),sale(a,'A-02','10.02'),sale(a,'A-03','20.03',day='07'),sale(a,'A-04','1.04',cfop='6102'),sale(a,'A-05','5.05')]
                        legacy = sale(a,'A-LEGACY','7.07')
                        old_journal = post(f'/companies/{a}/documents/{legacy["id"]}/account', {'version':legacy['version'],'model_id':ma,'idempotency_key':'synthetic-old-account'})['journal']
                        for i in range(50): sale(a,f'A-PENDING-{i:02}',book=False)
                        mb, _ = setup(b, 'B'); sale(b,'B-01','3.01'); sale(b,'B-02','4.02')
                        post('/context', {'company_id':a,'module':'fiscal','period':year+'-11'})
                        page.reload(); enter(); save_mode('daily')
                        page.get_by_role('heading',name='Integração Contábil',exact=True).scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT/'configuration.png'),full_page=True)
                        before_read = snapshot(folder,a)
                        expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(50)
                        page.get_by_role('button',name='Página seguinte').click()
                        expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(6)
                        page.get_by_label('Situação contábil').select_option('eligible')
                        expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(5)
                        for value in ('12','11','10','11'): page.get_by_label('Competência da escrituração').select_option(value)
                        page.get_by_label('Pesquisar notas').fill('NO-MATCH'); expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(0)
                        page.get_by_label('Pesquisar notas').fill(''); expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(5)
                        nav('Visão geral'); enter(); expect(page.get_by_label('Situação contábil')).to_have_value('eligible')
                        report['read_only_hashes']={'before':before_read,'after':snapshot(folder,a)}
                        assert report['read_only_hashes']['before']==report['read_only_hashes']['after'], 'Filters/navigation changed business tables'
                        report['checks'].append('Pagination, empty/combined/rapid filters and KeepAlive navigation are read-only')
                        for number in ('A-01','A-02'): page.get_by_label('Contabilizar nota '+number,exact=True).check()
                        section('Contabilizar')
                        direct_accounts={x['access_code']:x['id'] for x in get(f'/companies/{a}/accounts')}
                        page.get_by_label('Conta a debitar na integração',exact=True).select_option(str(direct_accounts['3']))
                        page.get_by_label('Conta a creditar na integração',exact=True).select_option(str(direct_accounts['5']))
                        page.get_by_label('Histórico do lançamento (opcional)',exact=True).fill('Venda sintética com contas diretas')
                        subguide_requests=[]
                        references=('/fiscal-sales-accounting/settings','/documents','/masters/accounting_model','/accounts','/cost-centers')
                        page.on('request',lambda r:subguide_requests.append(r.url) if r.method=='GET' and f'/api/companies/{a}/' in r.url and any(r.url.split('?')[0].endswith(p) for p in references) else None)
                        for _ in range(3):
                            section('Notas e seleção')
                            for number in ('A-01','A-02'):expect(page.get_by_label('Contabilizar nota '+number,exact=True)).to_be_checked()
                            section('Parâmetros e ajuda');section('Contabilizar')
                        expect(page.get_by_label('Conta a debitar na integração',exact=True)).to_have_value(str(direct_accounts['3']))
                        expect(page.get_by_label('Histórico do lançamento (opcional)',exact=True)).to_have_value('Venda sintética com contas diretas')
                        section('Notas e seleção')
                        tabs=page.get_by_role('tablist',name='Seções da integração contábil')
                        tabs.get_by_role('tab',name='Notas e seleção',exact=True).focus();page.keyboard.press('End')
                        expect(tabs.get_by_role('tab',name='Parâmetros e ajuda',exact=True)).to_be_focused()
                        page.keyboard.press('Home');expect(tabs.get_by_role('tab',name='Notas e seleção',exact=True)).to_be_focused()
                        page.keyboard.press('ArrowRight');expect(tabs.get_by_role('tab',name='Contabilizar',exact=True)).to_be_focused()
                        section('Notas e seleção');page.locator('.sales-accounting-view .view-heading').scroll_into_view_if_needed()
                        expect(page.get_by_label('Geração de lançamentos')).to_be_hidden()
                        table_top=page.locator('.sales-notes table').bounding_box()['y']
                        report['desktop_notes_table_top']=table_top
                        assert table_top<700,'Notes are still buried beneath permanent configuration/warnings'
                        expect(page.get_by_role('button',name='Contabilizar seleção (2)',exact=True)).to_be_visible()
                        page.screenshot(path=str(OUT/'notes-desktop.png'),full_page=True)
                        page.get_by_role('button',name='Contabilizar seleção (2)',exact=True).click()
                        expect(tabs.get_by_role('tab',name='Contabilizar',exact=True)).to_have_attribute('aria-selected','true')
                        page.set_viewport_size({'width':390,'height':844})
                        if page.locator('.sidebar.visible').count():page.get_by_role('button',name='Fechar navegação',exact=True).click()
                        expect(page.locator('.sidebar')).not_to_be_in_viewport()
                        page.locator('.sales-generation').scroll_into_view_if_needed()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        assert page.locator('.sales-generation').evaluate("el=>[...el.querySelectorAll('input,select,button')].filter(n=>n.getBoundingClientRect().width).every(n=>n.getBoundingClientRect().right<=innerWidth+1&&n.getBoundingClientRect().left>=0)")
                        page.screenshot(path=str(OUT/'accounting-mobile.png'),full_page=True)
                        section('Notas e seleção');page.locator('.sales-accounting-view .view-heading').scroll_into_view_if_needed();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(OUT/'notes-mobile.png'),full_page=True)
                        page.set_viewport_size({'width':1600,'height':1100});section('Contabilizar')
                        assert subguide_requests==[],f'Subguide navigation reloaded references: {subguide_requests}'
                        report['subguide_read_request_count']=len(subguide_requests)
                        report['checks'].append('Compact notes/actions, repeated subguides and keyboard retain selection/accounts/history with zero extra reads; desktop and 390px layouts stay contained')
                        before_cancel=snapshot(folder,a)
                        network=page.context.new_cdp_session(page);network.send('Network.enable')
                        network.send('Network.emulateNetworkConditions',{'offline':False,'latency':500,'downloadThroughput':-1,'uploadThroughput':-1})
                        page.get_by_role('button',name='Consultar prévia contábil',exact=True).click()
                        page.get_by_role('button',name='Cancelar consulta da prévia',exact=True).click()
                        network.send('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
                        expect(page.get_by_role('region',name='Prévia contábil',exact=True)).to_have_count(0)
                        expect(page.get_by_role('button',name='Cancelar consulta da prévia',exact=True)).to_have_count(0)
                        assert before_cancel==snapshot(folder,a)
                        section('Notas e seleção')
                        for number in ('A-01','A-02'):expect(page.get_by_label('Contabilizar nota '+number,exact=True)).to_be_checked()
                        section('Contabilizar')
                        report['checks'].append('Canceling a read-only preview under latency preserves selection and data; a fresh preview remains available')
                        before_direct_preview=snapshot(folder,a)
                        page.get_by_role('button',name='Consultar prévia contábil',exact=True).click()
                        direct_preview=page.get_by_role('region',name='Prévia contábil',exact=True)
                        expect(direct_preview.get_by_text('1 lançamento(s) previsto(s)',exact=False)).to_be_visible()
                        assert before_direct_preview==snapshot(folder,a)
                        page.get_by_role('button',name='Fechar prévia',exact=True).click()
                        page.get_by_role('heading',name='Integração Contábil',exact=True).scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT/'direct-accounts.png'),full_page=True)
                        page.locator('.sales-generation').scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT/'direct-accounts-controls.png'),full_page=True)
                        mutations=[]
                        page.on('request',lambda r: mutations.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/fiscal-sales-accounting/generate') else None)
                        def commit_then_drop(route):
                            response=route.fetch(); assert response.ok,response.text(); route.abort('failed')
                        page.route('**/fiscal-sales-accounting/generate',commit_then_drop,times=1)
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('button',name='Repetir a mesma solicitação')).to_be_visible()
                        assert len(journals(a))==2, 'First request must have committed exactly one aggregate'
                        assert any(j['history']=='Venda sintética com contas diretas' for j in journals(a))
                        after_commit=snapshot(folder,a)
                        section('Notas e seleção');section('Parâmetros e ajuda');section('Notas e seleção')
                        page.get_by_role('button',name='Rever solicitação',exact=True).click()
                        expect(page.get_by_role('tablist',name='Seções da integração contábil').get_by_role('tab',name='Contabilizar',exact=True)).to_have_attribute('aria-selected','true')
                        page.get_by_role('button',name='Repetir a mesma solicitação').click()
                        expect(page.get_by_role('heading',name='Solicitação já processada')).to_be_visible()
                        assert all('model_id' not in e for e in mutations[0]['entries'])
                        assert len(mutations)==2 and mutations[0]==mutations[1], 'Retry changed the frozen intent/key'
                        report['replay_hashes']={'before':after_commit,'after':snapshot(folder,a)}
                        assert report['replay_hashes']['before']==report['replay_hashes']['after'], 'Idempotent replay changed business tables'
                        result=page.get_by_role('region',name='Resultado da contabilização')
                        result.get_by_role('button',name='Notas do lançamento',exact=False).click()
                        modal=page.get_by_role('dialog',name='Rastreabilidade contábil fiscal')
                        expect(modal.locator('.sales-source')).to_have_count(2)
                        expect(modal.get_by_text('Contas informadas diretamente nesta integração.',exact=True)).to_have_count(2)
                        modal.get_by_role('button',name='Consultar nota A-01',exact=True).click();expect(modal.locator('.sales-source')).to_have_count(1)
                        modal.get_by_role('button',name='Fechar rastreabilidade').click()
                        assert after_commit==snapshot(folder,a), 'Tracing changed business tables'
                        page.screenshot(path=str(OUT/'daily-replayed.png'),full_page=True)
                        report['checks'].append('Daily direct accounts, optional model regression preserved: 0.01 + 10.02 => one balanced 10.03 journal; lost response after commit and exact-key retry do not duplicate; both sources traced')
                        save_mode('individual')
                        page.get_by_role('button',name='Selecionar aptas da consulta').click();apply_model(ma)
                        section('Notas e seleção')
                        page.get_by_label('Modelo contábil da nota A-05',exact=True).select_option(str(other))
                        section('Contabilizar')
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('heading',name='Resultado da contabilização',exact=True)).to_be_visible()
                        assert len(journals(a))==5
                        assert next(j for j in journals(a) if j['id']==old_journal['id'])==old_journal
                        context(b);expect(page.get_by_text('Saídas individuais',exact=True)).to_be_visible()
                        page.get_by_label('Situação contábil').select_option('eligible');page.get_by_role('button',name='Selecionar aptas da consulta').click();apply_model(mb)
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('heading',name='Resultado da contabilização',exact=True)).to_be_visible()
                        assert len(journals(b))==2
                        context(a);expect(page.get_by_text('Saídas individuais',exact=True)).to_be_visible()
                        old_movements=snapshot(folder,a,('documents','journals','journal_lines','titles'))
                        save_mode('daily');assert old_movements==snapshot(folder,a,('documents','journals','journal_lines','titles'))
                        page.get_by_label('Situação contábil').select_option('accounted')
                        expect(page.get_by_label('Contabilizar nota A-01',exact=True)).to_be_disabled()
                        report['checks'].append('Individual: three notes/dates/CFOP/accounts => three journals; company B has two independent journals; saved company mode and previous movements preserved')
                        current=documents(a)
                        for original in originals:
                            new=next(d for d in current if d['id']==original['id'])
                            assert {k:v for k,v in new.items() if k!='journal_id'}=={k:v for k,v in original.items() if k!='journal_id'}
                        titles=get(f'/companies/{a}/titles');assert len(titles)==1 and titles[0]['amount_cents']==1 and not titles[0]['cancelled']
                        before_report=snapshot(folder,a)
                        for _ in range(2):
                            summary=get(f'/companies/{a}/business-reports/consolidated-diary?start={year}-11-01&end={year}-11-30')
                            assert summary['totals']['debit_cents']==summary['totals']['credit_cents']==4322
                        report['report_hashes']={'before':before_report,'after':snapshot(folder,a)}
                        assert report['report_hashes']['before']==report['report_hashes']['after']
                        report['checks'].append('Fiscal fields, original single journal and receivable preserved; independent daily report read-only and balanced at 43.22')
                        sale(a,'A-REOPEN','2.01')
                        post(f'/companies/{a}/periods/close',{'module':'accounting','period':year+'-11','reason':'Fechamento sintético'})
                        page.reload();enter();page.get_by_label('Situação contábil').select_option('eligible')
                        page.get_by_label('Contabilizar nota A-REOPEN',exact=True).check();apply_model(ma)
                        expect(page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True)).to_be_disabled()
                        expect(page.get_by_text('A competência '+year+'-11 está fechada',exact=False)).to_be_visible()
                        post(f'/companies/{a}/periods/reopen',{'module':'accounting','period':year+'-11','reason':'Reabertura sintética'})
                        page.reload();enter();page.get_by_label('Situação contábil').select_option('eligible');page.get_by_label('Contabilizar nota A-REOPEN',exact=True).check();apply_model(ma)
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('heading',name='Resultado da contabilização',exact=True)).to_be_visible()
                        assert len(journals(a))==6
                        with sqlite3.connect(Path(folder)/'escritura.sqlite3') as conn:
                            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
                            assert not conn.execute('SELECT j.id FROM journals j JOIN journal_lines l ON l.journal_id=j.id GROUP BY j.id HAVING SUM(l.debit_cents)<>SUM(l.credit_cents)').fetchall()
                        report['checks'].append('Closed accounting month refuses UI generation even with permissive legacy defaults; reopening permits it; FK and all journals balanced')
                        page.screenshot(path=str(OUT/'reopened.png'),full_page=True)
                        # Both approved menus reuse the same engine. Purchases stay individual
                        # even when this company's saved sales mode is daily.
                        incoming_accounts = {x['access_code']:x['id'] for x in get(f'/companies/{a}/accounts')}
                        for number,amount in (('E-01','0.01'),('E-02','10.02')):
                            d=post(f'/companies/{a}/documents',{'direction':'incoming','number':number,'series':'1','model':'55',
                                'issue_date':year+'-10-30','posting_date':year+'-11-06','partner_name':'Fornecedor sintético','cfop':'1102','total':amount})
                            post(f'/companies/{a}/documents/{d["id"]}/book',{'version':d['version'],'reason':'Fixture sintética'})
                        nav('Integração Fiscal')
                        expect(page.get_by_role('heading',name='Integração Fiscal',exact=True)).to_be_visible()
                        page.get_by_label('Sentido da integração').select_option('incoming')
                        expect(page.get_by_text('Entradas individuais',exact=True)).to_be_visible()
                        page.get_by_label('Situação contábil').select_option('eligible')
                        expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(2)
                        page.get_by_role('button',name='Selecionar aptas da consulta').click()
                        section('Contabilizar')
                        page.get_by_label('Conta a debitar na integração',exact=True).select_option(str(incoming_accounts['6']))
                        page.get_by_label('Conta a creditar na integração',exact=True).select_option(str(incoming_accounts['4']))
                        before_preview=snapshot(folder,a)
                        page.get_by_role('button',name='Consultar prévia contábil',exact=True).click()
                        preview=page.get_by_role('region',name='Prévia contábil',exact=True)
                        expect(preview.get_by_text('2 lançamento(s) previsto(s)',exact=False)).to_be_visible()
                        after_preview=snapshot(folder,a)
                        assert before_preview==after_preview,'Preview wrote business data'
                        preview.scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT/'incoming-preview.png'),full_page=True)
                        page.get_by_role('button',name='Fechar prévia',exact=True).click();expect(preview).to_have_count(0)
                        assert len(journals(a))==6,'Closing preview generated movements'
                        incoming_mutations=[]
                        page.on('request',lambda r: incoming_mutations.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/fiscal-purchases-accounting/generate') else None)
                        page.route('**/fiscal-purchases-accounting/generate',commit_then_drop,times=1)
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('button',name='Repetir a mesma solicitação')).to_be_visible()
                        assert len(journals(a))==8,'Incoming notes were consolidated or duplicated'
                        incoming_committed=snapshot(folder,a)
                        page.get_by_role('button',name='Repetir a mesma solicitação').click()
                        expect(page.get_by_role('heading',name='Solicitação já processada')).to_be_visible()
                        assert len(incoming_mutations)==2 and incoming_mutations[0]==incoming_mutations[1]
                        assert all('model_id' not in e for e in incoming_mutations[0]['entries'])
                        assert incoming_committed==snapshot(folder,a),'Incoming retry wrote business data'
                        result=page.get_by_role('region',name='Resultado da contabilização')
                        result.get_by_role('button',name='Notas do lançamento',exact=False).first.click()
                        incoming_trace=page.get_by_role('dialog',name='Rastreabilidade contábil fiscal')
                        expect(incoming_trace.locator('.sales-source')).to_have_count(1)
                        incoming_trace.get_by_role('button',name='Fechar rastreabilidade').click()
                        page.get_by_role('heading',name='Integração Fiscal',exact=True).scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT/'accounting-access-desktop.png'),full_page=True)
                        nav('Integração Contábil')
                        page.get_by_label('Sentido da integração').select_option('incoming')
                        page.get_by_label('Situação contábil').select_option('accounted')
                        expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(2)
                        expect(page.get_by_label('Contabilizar nota E-01',exact=True)).to_be_disabled()
                        assert incoming_committed==snapshot(folder,a),'Alternate menu changed accounting data'
                        assert get(f'/companies/{a}/fiscal-sales-accounting/settings')['mode']=='daily'
                        with sqlite3.connect(Path(folder)/'escritura.sqlite3') as conn:
                            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
                            assert not conn.execute('SELECT j.id FROM journals j JOIN journal_lines l ON l.journal_id=j.id GROUP BY j.id HAVING SUM(l.debit_cents)<>SUM(l.credit_cents)').fetchall()
                        report['incoming_preview_hashes']={'before':before_preview,'after':after_preview}
                        report['incoming_replay_hashes']={'before':incoming_committed,'after':snapshot(folder,a)}
                        report['checks'].append('Both menus share direct-account integration without required models: incoming preview/close read-only; daily sales setting preserved; two purchases remain individual; lost-response exact retry and alternate menu do not duplicate; origins/FK/balance preserved')
                        # A fresh company has no accounting models: both directions work directly.
                        c=post('/companies',{'code':'SYN-DIRECT-C','name':'Empresa sintética sem modelos','tax_id':'TEST0003000110','regime':'outros','state':'SP','create_default_accounts':True})['id']
                        post('/context',{'company_id':c,'module':'fiscal','period':year+'-11'})
                        for number,flow,total in [('C-S1','outgoing','0.01'),('C-S2','outgoing','10.02'),('C-E1','incoming','0.01'),('C-E2','incoming','10.02')]:
                            d=post(f'/companies/{c}/documents',{'direction':flow,'number':number,'series':'1','model':'55','issue_date':year+'-10-30','posting_date':year+'-11-06','partner_name':'Contraparte sintética','cfop':'5102' if flow=='outgoing' else '1102','total':total})
                            post(f'/companies/{c}/documents/{d["id"]}/book',{'version':d['version'],'reason':'Fixture sintética'})
                        assert get(f'/companies/{c}/masters/accounting_model')==[]
                        refs={x['access_code']:x['id'] for x in get(f'/companies/{c}/accounts')}
                        page.reload();enter();save_mode('daily')
                        page.get_by_label('Situação contábil').select_option('eligible')
                        page.get_by_role('button',name='Selecionar aptas da consulta').click()
                        section('Contabilizar')
                        page.get_by_label('Conta a debitar na integração',exact=True).select_option(str(refs['3']))
                        page.get_by_label('Conta a creditar na integração',exact=True).select_option(str(refs['5']))
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('heading',name='Resultado da contabilização',exact=True)).to_be_visible()
                        assert len(journals(c))==1 and journals(c)[0]['total_cents']==1003
                        page.get_by_label('Sentido da integração').select_option('incoming')
                        expect(page.locator('.sales-accounting-view tbody tr')).to_have_count(2)
                        page.get_by_role('button',name='Selecionar aptas da consulta').click()
                        section('Contabilizar')
                        page.get_by_label('Conta a debitar na integração',exact=True).select_option(str(refs['6']))
                        page.get_by_label('Conta a creditar na integração',exact=True).select_option(str(refs['4']))
                        page.get_by_role('button',name='Gerar lançamentos da seleção',exact=True).click()
                        expect(page.get_by_role('heading',name='Resultado da contabilização',exact=True)).to_be_visible()
                        assert len(journals(c))==3 and get(f'/companies/{c}/masters/accounting_model')==[]
                        for j in journals(c):
                            origin=get(f'/companies/{c}/fiscal-sales-accounting/journals/{j["id"]}/sources')
                            assert all(s['entry_method']=='direct' and s['model_snapshot'] is None for s in origin['sources'])
                            assert sum(l['debit_cents'] for l in j['lines'])==sum(l['credit_cents'] for l in j['lines'])
                        with sqlite3.connect(Path(folder)/'escritura.sqlite3') as conn:
                            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
                        report['no_models_company_journals']=len(journals(c))
                        report['checks'].append('Fresh company C has no accounting models: two direct sales consolidate at 10.03; two direct purchases stay individual; all origins and balances preserved without creating models')
                        section('Notas e seleção');page.get_by_label('Situação contábil').select_option('accounted')
                        before_month=snapshot(folder,c)
                        for selected_month,expected_count in [('10',0),('11',2)]:
                            page.keyboard.press('F8');month_dialog=page.get_by_role('dialog',name='Empresa, ano e competência')
                            month_dialog.get_by_label('Competência a fixar (opcional)').select_option(selected_month)
                            month_dialog.get_by_role('button',name='Aplicar contexto').click();expect(month_dialog).to_have_count(0)
                            expect(page.get_by_label('Competência da escrituração')).to_have_value(selected_month)
                            expect(page.locator('.sales-notes tbody tr')).to_have_count(expected_count)
                            expect(page.get_by_role('tablist',name='Seções da integração contábil').get_by_role('tab',name='Notas e seleção',exact=True)).to_have_attribute('aria-selected','true')
                        assert before_month==snapshot(folder,c)
                        report['workspace_month_hashes']={'before':before_month,'after':snapshot(folder,c)}
                        report['checks'].append('F8 competence changes return to notes, apply the current month and preserve all accounting/fiscal data; both access headings match their modules')
                        page.set_viewport_size({'width':1100,'height':900})
                        page.get_by_role('heading',name='Integração Contábil',exact=True).scroll_into_view_if_needed()
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                        page.screenshot(path=str(OUT/'narrow-configuration.png'),full_page=True)
                        report['checks'].append('Configuration and controls remain within the 1100px viewport; wide table scroll is contained')
                        assert not report['console_errors'],report['console_errors']
                        report['final_journals']={'A':len(journals(a)),'B':len(journals(b)),'C':len(journals(c))}
                        report['ok']=True
                    except Exception:
                        page.screenshot(path=str(OUT/'failure.png'),full_page=True)
                        (OUT/'failure.txt').write_text(page.locator('body').inner_text())
                        raise
                    finally: browser.close()
    except Exception as error:
        report['error']=str(error);report['traceback']=traceback.format_exc()
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
