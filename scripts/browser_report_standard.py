"""QA sintético da consulta bancária e prévia compacta; nunca maximiza."""
from pathlib import Path
import os, socket, subprocess, sys, tempfile, time, urllib.request, json
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'report-standard';OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='report-standard-demo-') as data:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    with (OUT/'browser-server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'scripts/run_preview.py','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(url+'/api/health',timeout=1).close();break
                except OSError:time.sleep(.2)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('ESCRITURA_TEST_BROWSER','/usr/bin/chromium'))
                page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name='Livros e demonstrações',exact=True,include_hidden=True)
                parent=button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                button.click();controls=page.locator('form.report-controls')
                controls.get_by_role('combobox',name='Relatório',exact=True).select_option('bank-movements')
                controls.get_by_role('button',name='Gerar relatório',exact=True).click()
                expect(page.locator('.report-output')).to_be_visible()
                expect(page.locator('.report-output')).to_contain_text('Movimentação bancária')
                page.locator('.report-output').get_by_role('button',name='Visualizar PDF').click()
                region=page.get_by_role('region',name='Prévia do relatório')
                expect(region.locator('iframe')).to_have_attribute('src',__import__('re').compile('^blob:'))
                page.wait_for_timeout(1200)
                page.screenshot(path=str(OUT/'bank-inline.png'),full_page=True)
                assert page.get_by_role('dialog').count()==0
                region.get_by_role('button',name='Fechar prévia',exact=True).click()
                controls.get_by_role('textbox',name='Conta bancária').fill('SEM-CONTA-SINTETICA')
                expect(page.get_by_text('Filtros alterados.',exact=False)).to_be_visible()
                controls.get_by_role('button',name='Gerar relatório',exact=True).click()
                expect(page.locator('.report-output')).to_contain_text('Nenhum registro para a seleção informada.')
                page.screenshot(path=str(OUT/'bank-empty.png'),full_page=True)
                page.emulate_media(media='print');page.pdf(path=str(OUT/'browser-print.pdf'),format='A4')
                assert not errors,errors
                (OUT/'browser-checks.json').write_text(json.dumps({'ok':True,'checks':['bank catalog in accounting','inline blob PDF without maximization','changed filter warning','empty exact account','print media PDF'],'page_errors':errors},indent=2))
                browser.close()
        finally:process.terminate();process.wait(timeout=20)
