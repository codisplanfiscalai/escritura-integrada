"""Synthetic acceptance of original PDF preview; disposable local DB only."""
import base64
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_document_preview import synthetic_xml
OUT = ROOT/'artifacts/document-preview'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'checks':[],'console_errors':[],'console_warnings':[]}
    with tempfile.TemporaryDirectory(prefix='escritura-pdf-ui-') as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        with (OUT/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'scripts/run_preview.py','--port',str(port)],cwd=ROOT,
                env=dict(os.environ,ESCRITURA_DATA_DIR=folder,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:urllib.request.urlopen(url+'/api/health',timeout=1).close();break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Local preview unavailable')
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('ESCRITURA_TEST_BROWSER','/usr/bin/chromium'),args=['--no-sandbox'])
                    page=browser.new_page(viewport={'width':1440,'height':1050})
                    page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                    page.on('console',lambda msg:report['console_warnings'].append(msg.text) if msg.type in ('warning','error') else None)
                    try:
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        session=page.request.get(url+'/api/session').json();cid=session['active_company_id'];csrf=session['csrf_token'];scope=f'/api/companies/{cid}'
                        companies=page.request.get(url+'/api/companies').json();company=next(c for c in companies if c['id']==cid)
                        def post(path,payload):
                            r=page.request.post(url+path,data=payload,headers={'X-CSRF-Token':csrf});assert r.ok,r.text();return r.json()
                        def get(path):
                            r=page.request.get(url+path);assert r.ok,r.text();return r.json()
                        post('/api/context',{'company_id':cid,'module':'fiscal','period':'2026-11'})
                        documents=[]
                        for fixture,label in [('auditor_demo','DANFE'),('auditor_nfce','DANFC-e'),('auditor_cte','DACTE'),('auditor_cte_long','DACTE'),('auditor_cte_stress','DACTE'),('auditor_long','DANFE')]:
                            raw=synthetic_xml(fixture,company['tax_id'])
                            batch=post(scope+'/imports/preview',{'filename':fixture+'.xml','period':'2026-11','options':{'posting_date':'2026-11-06'},'content_base64':base64.b64encode(raw).decode()})
                            assert batch['can_confirm'],batch['issues']
                            result=post(scope+f"/imports/{batch['id']}/confirm",{'preview_hash':batch['preview_hash'],'posting_mode':'pending'})
                            document=next(d for d in get(scope+'/documents') if d['id']==result['document_ids'][0])
                            documents.append((document,label))
                            response=page.request.get(url+scope+f"/documents/{document['id']}/auxiliary")
                            assert response.ok,response.text()
                            (OUT/(fixture+'.pdf')).write_bytes(response.body())
                            (OUT/(fixture+'.xml')).write_bytes(raw)
                        before=get(scope+'/documents');titles=get(scope+'/titles');journals=get(scope+'/journals')
                        page.reload()
                        menu=page.get_by_role('navigation',name='Navegação principal');button=menu.get_by_role('button',name='Escrituração e documentos',exact=True,include_hidden=True);parent=button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                        button.click()
                        for doc,label in documents:
                            trigger=page.get_by_role('button',name=f"Visualizar documento original {doc['number']}",exact=True)
                            # Existing fixtures can share a number across models.
                            row=page.get_by_role('row').filter(has=trigger).filter(has_text=doc['partner_name'])
                            trigger=trigger if trigger.count()==1 else row.get_by_role('button',name=f"Visualizar documento original {doc['number']}",exact=True).first
                            trigger.click()
                            modal=page.get_by_role('dialog',name=f"{label} · documento {doc['number']}",exact=True)
                            expect(modal.locator('canvas')).to_be_visible(timeout=30000)
                            expect(modal.get_by_text('Página 1 de',exact=False)).to_be_visible()
                            expect(modal.get_by_role('alert')).to_have_count(0)
                            if label == 'DACTE':
                                count=int(re.search(r'de (\d+)$',modal.locator('canvas').get_attribute('aria-label'))[1])
                                base_width=modal.locator('canvas').evaluate('c => parseFloat(c.style.width)')
                                for number in range(1,count+1):
                                    for zoom in ('0.75', '1', '1.25', '1.5'):
                                        modal.get_by_label('Zoom',exact=True).select_option(zoom)
                                        page.wait_for_function("width => Math.abs(parseFloat(document.querySelector('.document-pdf-pages canvas')?.style.width)-width)<0.1",arg=base_width*float(zoom))
                                        expect(modal.locator('.document-pdf-pages')).to_have_attribute('aria-busy','false')
                                        suffix='' if number==1 else f'-page-{number}'
                                        (OUT/(label+'-'+doc['number']+suffix+'-zoom-'+zoom+'.png')).write_bytes(base64.b64decode(modal.locator('canvas').evaluate("canvas => canvas.toDataURL('image/png').split(',')[1]")))
                                    if number<count:
                                        modal.get_by_role('button',name='Próxima página',exact=True).click()
                                        expect(modal.locator('canvas')).to_have_attribute('aria-label',re.compile(f'página {number+1} de'))
                                        expect(modal.locator('.document-pdf-pages')).to_have_attribute('aria-busy','false')
                                page.screenshot(path=str(OUT/(label+'-'+doc['number']+'-last-page-ui.png')),full_page=True)
                                for number in range(count-1,0,-1):
                                    modal.get_by_role('button',name='Página anterior',exact=True).click()
                                    expect(modal.locator('canvas')).to_have_attribute('aria-label',re.compile(f'página {number} de'))
                                    expect(modal.locator('.document-pdf-pages')).to_have_attribute('aria-busy','false')
                            modal.get_by_label('Zoom',exact=True).select_option('1.25')
                            expect(modal.locator('canvas')).to_be_visible()
                            if doc['number']=='81':
                                modal.get_by_role('button',name='Próxima página',exact=True).click()
                                expect(modal.get_by_text('Página 2 de',exact=False)).to_be_visible()
                                expect(modal.locator('canvas')).to_have_attribute('aria-label',re.compile('página 2 de'))
                            expect(modal.locator('.document-pdf-pages')).to_have_attribute('aria-busy','false')
                            (OUT/(label+'-'+doc['number']+'-canvas.png')).write_bytes(base64.b64decode(modal.locator('canvas').evaluate("canvas => canvas.toDataURL('image/png').split(',')[1]")))
                            page.screenshot(path=str(OUT/(label+'-'+doc['number']+'.png')),full_page=True)
                            if doc['number']=='99203224':
                                modal.get_by_role('button',name='Próxima página',exact=True).click()
                                expect(modal.locator('canvas')).to_have_attribute('aria-label',re.compile('página 2 de'))
                                expect(modal.locator('.document-pdf-pages')).to_have_attribute('aria-busy','false')
                                (OUT/'DACTE-long-page-2-canvas.png').write_bytes(base64.b64decode(modal.locator('canvas').evaluate("canvas => canvas.toDataURL('image/png').split(',')[1]")))
                                page.screenshot(path=str(OUT/'DACTE-long-page-2-ui.png'),full_page=True)

                            page.keyboard.press('Escape');expect(page.get_by_role('dialog')).to_have_count(0)
                            expect(trigger).to_be_focused()
                        report['checks'].append('DANFE, DANFC-e and DACTE: canvas rendered locally; zoom, Esc and focus return')
                        # Open from an edit dialog; closing only the preview keeps editor data.
                        doc,label=documents[0]
                        page.get_by_role('button',name=f"Editar documento {doc['number']}",exact=True).first.click()
                        editor=page.get_by_role('dialog',name='Editar documento fiscal',exact=True)
                        editor.get_by_role('button',name='Visualizar documento original',exact=True).click()
                        expect(page.get_by_role('dialog').last.locator('canvas')).to_be_visible(timeout=30000)
                        page.get_by_role('button',name='Fechar prévia · Esc',exact=True).click()
                        expect(editor).to_be_visible();page.keyboard.press('Escape');expect(page.get_by_role('dialog')).to_have_count(0)
                        report['checks'].append('Preview opened inside editor and closed without saving or losing editor context')
                        # Delayed request from A cannot paint over B after closing A.
                        first,first_label=documents[0];second,second_label=documents[1]
                        route_url=url+scope+f"/documents/{first['id']}/auxiliary"
                        held=[];page.route(route_url,lambda route:held.append(route))
                        page.get_by_role('button',name=f"Visualizar documento original {first['number']}",exact=True).first.click()
                        expect(page.get_by_text('Preparando documento original…')).to_be_visible()
                        page.wait_for_timeout(100);assert held
                        page.keyboard.press('Escape')
                        page.get_by_role('button',name=f"Visualizar documento original {second['number']}",exact=True).first.click()
                        expect(page.get_by_role('dialog').last.locator('canvas')).to_be_visible(timeout=30000)
                        for route in held:
                            try:route.fulfill(status=200,content_type='application/pdf',body=(OUT/'auditor_demo.pdf').read_bytes())
                            except Exception:pass  # Browser may already have aborted the old request.
                        expect(page.get_by_role('dialog',name=f"{second_label} · documento {second['number']}",exact=True)).to_be_visible()
                        page.keyboard.press('Escape');page.unroute(route_url)
                        report['checks'].append('Closing pending request then opening another model never displays the old document')
                        # Server diagnostic remains in the application and can be retried.
                        page.route(route_url,lambda route:route.fulfill(status=422,content_type='application/json',body=json.dumps({'detail':'XML original indisponível (simulação sintética de falha)'})))
                        page.get_by_role('button',name=f"Visualizar documento original {first['number']}",exact=True).first.click()
                        expect(page.get_by_role('alert')).to_contain_text('XML original indisponível')
                        expect(page.locator('.document-pdf-pages canvas')).to_have_count(0)
                        page.unroute(route_url);page.get_by_role('button',name='Tentar novamente',exact=True).click()
                        expect(page.get_by_role('dialog').last.locator('canvas')).to_be_visible(timeout=30000)
                        page.keyboard.press('Escape')
                        page.get_by_role('button',name=f"Visualizar documento original {first['number']}",exact=True).first.click()
                        expect(page.get_by_role('dialog').last.locator('canvas')).to_be_visible(timeout=30000)
                        other=next(c for c in companies if c['id']!=cid)
                        page.get_by_role('combobox',name='EMPRESA ATIVA',exact=True).select_option(str(other['id']))
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        expect(page.get_by_role('button',name=f"Visualizar documento original {first['number']}",exact=True)).to_have_count(0)
                        page.get_by_role('combobox',name='EMPRESA ATIVA',exact=True).select_option(str(cid))
                        expect(page.get_by_role('button',name=f"Visualizar documento original {first['number']}",exact=True)).to_be_visible()
                        report['checks'].append('Switching company closes preview and removes the previous company documents')
                        assert before==get(scope+'/documents');assert titles==get(scope+'/titles');assert journals==get(scope+'/journals')
                        after=get('/api/session');assert after['active_company_id']==cid;assert after['period']=='2026-11'
                        report['checks'].append('Failure and retry, repeated opens preserve documents, titles, journals, company and period')
                        assert not report['console_errors'],report['console_errors']
                        report['ok']=True
                    except Exception as error:
                        report['error']=str(error);report['traceback']=traceback.format_exc()
                        page.screenshot(path=str(OUT/'failure.png'),full_page=True)
                        (OUT/'failure.txt').write_text(page.locator('body').inner_text())
                    finally:browser.close()
            finally:
                server.terminate();server.wait(timeout=15)
                (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__=='__main__':sys.exit(main())
