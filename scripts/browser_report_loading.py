"""Local synthetic browser timings; loopback, no production or network emulation."""
import argparse, hashlib, os, socket, subprocess, tempfile, urllib.request
from contextlib import ExitStack
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import browser_performance as runner
from playwright.sync_api import expect


def scenario(page,url,fixture,report,baseline):
    report['network']={'scope':'local loopback; CDP throttling disabled; not production'}
    page.context.new_cdp_session(page).send('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
    page.set_default_timeout(20000);expect.set_options(timeout=20000)
    page.on('pageerror',lambda error:report['console_errors'].append(str(error)))
    page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
    expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible();page.wait_for_load_state('networkidle')
    page.keyboard.press('F8');dialog=page.get_by_role('dialog');dialog.get_by_label('Ano a fixar (opcional)').fill('2026');dialog.get_by_label('Competência a fixar (opcional)').select_option('09');dialog.get_by_role('button',name='Aplicar contexto').click();expect(dialog).to_have_count(0)
    def nav(label):
        button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name=label,exact=True,include_hidden=True)
        details=button.locator('xpath=ancestor::details')
        if details.count() and details.get_attribute('open') is None:details.locator('summary').click()
        button.click()
    for key,label,ready in [('fiscal_open','Escrituração e documentos','.table-footer'),('accounting_open','Lançamentos contábeis','.table-footer'),('reports_open','Livros e demonstrações','.report-controls')]:
        samples=[]
        for i in range(6):
            nav('Visão geral');page.reload();expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible();page.wait_for_load_state('networkidle')
            page.evaluate('performance.clearResourceTimings()');begin=time.perf_counter()
            suffixes=['/accounts']+(['/documents?year=2026'] if key=='fiscal_open' else ['/journals?year=2026'] if key=='accounting_open' else [])
            with ExitStack() as stack:
                pending=[stack.enter_context(page.expect_response(lambda r,suffix=suffix:'/api/companies/1'+suffix in r.url and r.status==200)) for suffix in suffixes]
                nav(label)
            for response in pending:response.value.body()
            page.wait_for_load_state('networkidle');expect(page.locator('main').locator(ready).first).to_be_visible()
            if key=='reports_open':expect(page.locator('.account-select select option')).to_have_count(201)
            else:expect(page.locator('main tbody tr')).to_have_count(50)
            elapsed=(time.perf_counter()-begin)*1000
            if i:samples.append(round(elapsed,3))
        resources=page.evaluate("performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/')).map(x=>({url:x.name.split('/api/')[1],duration_ms:x.duration,decoded_bytes:x.decodedBodySize}))")
        report['measurements'][key]={'samples_ms':samples,'resources':resources,'dom_rows':page.locator('main tbody tr').count(),'scope':'navigation through explicit account/movement responses and populated controls; includes networkidle heuristic'}
        print(key,samples,flush=True)
    controls=page.locator('.report-controls');controls.get_by_role('combobox',name='Relatório',exact=True).select_option('ledger')
    controls.locator('label').filter(has_text='Data inicial').locator('input[type=text]').fill('01/09/2026')
    controls.locator('label').filter(has_text='Data final').locator('input[type=text]').fill('30/09/2026')
    samples=[]
    for i in range(6):
        begin=time.perf_counter()
        with page.expect_response(lambda r:'/business-reports/ledger?' in r.url and 'format=' not in r.url,timeout=120000) as pending:
            controls.get_by_role('button',name='Gerar relatório',exact=True).click()
        assert pending.value.status==200;pending.value.body()
        expect(controls.get_by_role('button',name='Gerar relatório',exact=True)).to_be_enabled()
        expect(page.locator('.report-output tbody tr')).to_have_count(50)
        if i:samples.append(round((time.perf_counter()-begin)*1000,3))
        print('ledger',i,flush=True)
    report['measurements']['ledger_render']={'samples_ms':samples,'rows':500,'visible_rows':50}
    output=page.locator('.report-output');expect(output.locator('.table-footer')).to_contain_text('500 linhas')
    first=output.locator('tbody').inner_text();output.get_by_role('button',name='Próxima',exact=True).click();expect(output.locator('tbody')).not_to_have_text(first)
    export=page.request.get(url+output.get_by_role('link',name='Exportar CSV',exact=True).get_attribute('href'))
    assert export.status==200 and len(export.text().splitlines())==501
    controls.get_by_label('Documento, participante ou histórico',exact=True).fill('SYN-2026-09-249');controls.get_by_role('button',name='Gerar relatório',exact=True).click()
    expect(output.locator('.table-footer')).to_contain_text('2 linhas');expect(output.locator('tbody tr')).to_have_count(2)
    report['checks'].append('Ledger 500 rows, 50 per page, next page, full CSV and search preserving two counterpart lines')
    assert not report['console_errors'],report['console_errors']
    report['checks'].append('Synthetic large account plan; five measured cold navigations after one warmup per view')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'measurements':{},'console_errors':[],'checks':[],'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    sys.path.insert(0,str(ROOT))
    from app.business import BusinessCore
    from app.db import Database
    from benchmark_report_loading import seed_movements
    from benchmark_workspace import seed_workspace
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix='report-browser-synthetic-') as folder:
        core=BusinessCore(Database(folder),demo=True);seed_movements(core);fixture=seed_workspace(core)
        def hashes():
            with core.db.read() as conn:
                return {t:hashlib.sha256(repr([tuple(r) for r in conn.execute(f'SELECT * FROM {t} ORDER BY id')]).encode()).hexdigest() for t in ['documents','journals','journal_lines','titles','audit']}
        before=hashes()
        report['fixture']=fixture|{'journals_added':750,'documents_added':3000}
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        with args.output.with_suffix('.server.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'scripts/run_preview.py','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=folder,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(url+'/api/health',timeout=1).close();break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Synthetic server did not start')
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True,executable_path=os.environ['ESCRITURA_TEST_BROWSER'])
                    report['browser_version']=browser.version
                    try:
                        page=browser.new_page(viewport={'width':1440,'height':1000})
                        scenario(page,url,fixture,report,False);assert hashes()==before;report['checks'].append('Movement and audit hashes unchanged');report['ok']=True
                    finally:browser.close()
            finally:
                runner.stop_server(process);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__=='__main__':main()
