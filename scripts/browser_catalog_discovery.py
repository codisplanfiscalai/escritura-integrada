"""Regression: imported draft is visible in both audit modes, never silently published."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='catalog-browser-') as data:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    with open(Path(data)/'server.log','w') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url+'/api/health',timeout=1);break
                except OSError:time.sleep(.2)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel':'chromium'}))
                page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                session=page.request.get(url+'/api/session').json();cid=session['active_company_id'];headers={'X-CSRF-Token':session['csrf_token']}
                r=page.request.post(url+f'/api/companies/{cid}/auditor/catalogs/reference',data={'name':'Referência importada','valid_from':'2026-01-01','valid_to':'2026-12-31'},headers=headers);assert r.ok,r.text()
                nav=page.get_by_role('navigation',name='Navegação principal')
                button=nav.get_by_role('button',name='Auditorias, achados e relatórios',exact=True,include_hidden=True)
                parent=button.locator('xpath=ancestor::details')
                if parent.get_attribute('open') is None:parent.locator('summary').click()
                button.click();main=page.locator('main')
                for mode in ('Auditoria da escrituração','Auditoria avulsa'):
                    main.get_by_role('button',name=mode,exact=True).click()
                    expect(main.get_by_text('Catálogo importado não é catálogo ausente.',exact=False)).to_be_visible()
                    option=main.get_by_label('Catálogo publicado',exact=True).locator('option').filter(has_text='Referência importada')
                    expect(option).to_have_js_property('disabled',True)
                    expect(option).to_contain_text('4 erros para revisar')
                    main.get_by_role('button',name='Revisar catálogo',exact=True).click()
                    expect(main.get_by_role('button',name='Publicar após revisão',exact=True)).to_be_disabled()
                    expect(main.get_by_text('Este catálogo está salvo como rascunho',exact=False)).to_be_visible()
                assert not errors,errors
                browser.close()
                print('PASS: both modes discover draft; diagnostics and review navigation work; no silent publication; no JS errors')
        finally:
            process.terminate();process.wait(timeout=15)
