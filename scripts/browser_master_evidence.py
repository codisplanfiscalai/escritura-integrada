"""Browser acceptance of complete fiscal source details; disposable synthetic DB only."""
from pathlib import Path
import json, os, socket, subprocess, sys, tempfile, time, traceback, urllib.request
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.importers import parse_file
OUT=ROOT/'artifacts/browser-master-evidence'


def capture_failure(page, report, error, output=OUT):
    """Keep the original failure even when a diagnostic capture also fails."""
    report['ok'] = False
    report['error'] = f'{type(error).__name__}: {error}'
    report['traceback'] = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    def capture(label, action):
        try:
            return action()
        except Exception as capture_error:
            report.setdefault('evidence_errors', []).append(f'{label}: {type(capture_error).__name__}: {capture_error}')
            return None
    capture('traceback', lambda: (output/'failure-error.txt').write_text(report['traceback'], encoding='utf-8'))
    if page is None:
        return
    alive = capture('page state', lambda: not page.is_closed())
    if not alive:
        return
    capture('screenshot', lambda: page.screenshot(path=str(output/'failure.png'), full_page=True))
    capture('page text', lambda: (output/'failure.txt').write_text(page.locator('body').inner_text(), encoding='utf-8'))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'checks':[],'console_errors':[]}
    with tempfile.TemporaryDirectory(prefix='escritura-master-ui-') as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        with (OUT/'server.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'scripts/run_preview.py','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=folder,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:urllib.request.urlopen(url+'/api/health',timeout=1).close();break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Preview unavailable')
                with sync_playwright() as pw:
                    page=None
                    try:
                        browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                        page=browser.new_page(viewport={'width':1440,'height':1000})
                        page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        session=page.request.get(url+'/api/session').json();cid=session['active_company_id'];csrf=session['csrf_token'];scope=f'/api/companies/{cid}'
                        company=next(c for c in page.request.get(url+'/api/companies').json() if c['id']==cid)
                        def post(path,payload):
                            r=page.request.post(url+path,data=payload,headers={'X-CSRF-Token':csrf});assert r.ok,r.text();return r.json()
                        post('/api/context',{'company_id':cid,'module':'fiscal','period':'2026-11'})
                        raw=(ROOT/'tests/fixtures/nfe_ficticia.xml').read_bytes().replace(b'12345678000195',company['tax_id'].encode())
                        raw=raw.replace(b'</emit>',b'<IE>001234</IE><CRT>3</CRT><enderEmit><xLgr>Rua Teste</xLgr><xCpl>Bloco A</xCpl><UF>SP</UF></enderEmit></emit>')
                        raw=raw.replace(b'</prod>',b'<CEST>1234567</CEST><uTrib>CX</uTrib><qTrib>0.2500</qTrib><vUnTrib>400.0000000000</vUnTrib><cEANTrib>07891234567895</cEANTrib></prod>')
                        parsed=parse_file('source-ui.xml',raw,company);assert parsed['can_confirm'],parsed['issues']
                        doc=post(scope+'/documents',parsed['documents'][0]|{'posting_date':'2026-11-06'})
                        before=page.request.get(url+scope+'/documents').json()
                        page.reload()
                        def nav(label):
                            menu=page.get_by_role('navigation',name='Navegação principal');button=menu.get_by_role('button',name=label,exact=True,include_hidden=True);parent=button.locator('xpath=ancestor::details')
                            if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                            button.click()
                        nav('Escrituração e documentos')
                        page.get_by_role('button',name=f"Editar documento {doc['number']}",exact=True).click()
                        modal=page.get_by_role('dialog',name='Editar documento fiscal',exact=True)
                        modal.get_by_role('button',name='Dados do XML',exact=True).click()
                        modal.locator('summary').filter(has_text='Todos os campos XML').click()
                        fields=modal.get_by_label('Filtrar Árvore completa do XML preservado',exact=True)
                        fields.fill('vUnTrib');expect(modal.get_by_text('400.0000000000',exact=True)).to_be_visible()
                        page.screenshot(path=str(OUT/'xml-source.png'),full_page=True)
                        modal.get_by_role('button',name='Itens e tributos',exact=True).click()
                        modal.locator('summary').filter(has_text='Item 1').click()
                        expect(modal.get_by_text('400.0000000000',exact=True).first).to_be_visible()
                        modal.get_by_role('button',name='Cancelar',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        report['checks'].append('Complete XML and item detail retain lexical precision; closing read-only consultation causes no save/discard prompt')
                        nav('Participantes, produtos e serviços')
                        row=page.get_by_role('row').filter(has_text='Fornecedor Ficticio')
                        if not row.count():row=page.get_by_role('row').filter(has_text=doc['partner_name'])
                        row.get_by_role('button',name='Editar',exact=True).click()
                        modal=page.get_by_role('dialog',name='Editar cadastro',exact=True)
                        expect(modal.get_by_label('Número da inscrição',exact=True)).to_have_value('001234')
                        # Vue binds the unknown activity to null. Its native
                        # option value may be its text, not an empty string.
                        activity=modal.get_by_label('Situação da inscrição',exact=True)
                        expect(activity.locator('option:checked')).to_have_text('Não informada')
                        declared_status=modal.get_by_label('Situação declarada da inscrição',exact=True)
                        expect(declared_status.locator('option:checked')).to_have_text('Não informada')
                        expect(declared_status).to_have_value('')
                        response=page.request.get(url+scope+'/masters/participant')
                        assert response.ok,response.text()
                        participant=next(p for p in response.json() if p['id']==doc['participant_id'])
                        registrations=participant['data']['profile']['state_registrations']
                        assert len(registrations)==1,registrations
                        registration=registrations[0]
                        assert registration['state']=='SP' and registration['number']=='001234',registration
                        assert registration['active'] is None,registration
                        assert registration['status']=='',registration
                        expect(modal.get_by_label('Complemento',exact=True)).to_have_value('Bloco A')
                        page.screenshot(path=str(OUT/'party-ie-grid.png'),full_page=True)
                        modal.get_by_role('button',name='Cancelar',exact=True).click()
                        response=page.request.get(url+scope+'/masters/participant')
                        assert response.ok,response.text()
                        persisted=next(p for p in response.json() if p['id']==doc['participant_id'])
                        assert persisted==participant,'Consulting and cancelling must preserve unknown IE activity and the complete master'
                        page.get_by_label('Tipo de cadastro',exact=True).select_option('product')
                        product=page.get_by_role('row').filter(has_text='Produto ficticio')
                        if not product.count():product=page.get_by_role('row').filter(has_text=doc['items'][0]['description'])
                        product.get_by_role('button',name='Consultar dados e XMLs',exact=True).click()
                        modal=page.get_by_role('dialog')
                        expect(modal.get_by_text('Documentos e dados de origem',exact=True)).to_be_visible()
                        modal.locator('summary').filter(has_text=f"Documento {doc['number']}").click()
                        modal.get_by_role('button',name='Consultar XML original e detalhes completos',exact=True).click()
                        expect(modal.get_by_text('Origem preservada na importação.',exact=True)).to_be_visible()
                        modal.locator('summary').filter(has_text='Item 1').click()
                        expect(modal.get_by_text('400.0000000000',exact=True).first).to_be_visible()
                        page.screenshot(path=str(OUT/'product-history.png'),full_page=True)
                        modal.get_by_role('button',name='Fechar',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        assert before==page.request.get(url+scope+'/documents').json()
                        report['checks'].append('Party grid displays original IE and unknown activity; products expose company-owned source history without modifying documents')
                        # Exercise the same source controls with read-only permissions.
                        post('/api/users',{'username':'source-viewer','password':'Senha-sintetica-2026','role':'viewer','company_ids':[cid]})
                        ctx=browser.new_context(viewport={'width':1366,'height':768})
                        login=ctx.request.post(url+'/api/login',data={'username':'source-viewer','password':'Senha-sintetica-2026'}).json()
                        r=ctx.request.post(url+'/api/context',data={'company_id':cid,'module':'fiscal','period':'2026-11'},headers={'X-CSRF-Token':login['csrf_token']});assert r.ok,r.text()
                        page=ctx.new_page();page.on('pageerror',lambda e:report['console_errors'].append(str(e)));page.goto(url);nav('Escrituração e documentos')
                        page.get_by_role('button',name=f"Ver documento {doc['number']}",exact=True).click();modal=page.get_by_role('dialog',name='Consultar documento fiscal',exact=True)
                        expect(modal.get_by_label('Número *',exact=True)).to_be_disabled();modal.get_by_role('button',name='Dados do XML',exact=True).click()
                        modal.locator('summary').filter(has_text='Todos os campos XML').click();modal.get_by_label('Filtrar Árvore completa do XML preservado',exact=True).fill('vUnTrib')
                        expect(modal.get_by_text('400.0000000000',exact=True)).to_be_visible()
                        page.screenshot(path=str(OUT/'readonly-source.png'),full_page=True);modal.get_by_role('button',name='Fechar',exact=True).click()
                        report['checks'].append('Viewer can search XML values even while document fieldset is disabled')
                        assert not report['console_errors'],report['console_errors'];report['ok']=True;ctx.close();browser.close()
                    except Exception as error:
                        capture_failure(page, report, error)
                        raise
            except Exception as error:
                # Startup/teardown failures may occur outside the live browser.
                # Never access Playwright objects after its context has exited.
                if 'error' not in report:
                    capture_failure(None, report, error)
                raise
            finally:
                process.terminate();process.wait(timeout=15);(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
