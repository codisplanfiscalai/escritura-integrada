"""Synthetic browser acceptance for series parameters and explicit correction."""
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

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser-fiscal-series'

def run(report,out):
    report['stage']='dependencies'
    from playwright.sync_api import sync_playwright,expect
    with tempfile.TemporaryDirectory(prefix='escritura-series-') as data:
        process=None
        with (out/'server.log').open('w') as log:
            try:
                report['stage']='server'
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                url=f'http://127.0.0.1:{port}'
                process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url+'/api/health',timeout=1):break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Synthetic server did not start')
                report['stage']='browser'
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel':'chromium'}))
                    page=browser.new_page(viewport={'width':1280,'height':900});page.set_default_timeout(15000)
                    page.on('pageerror',lambda exc:report['console_errors'].append(str(exc)))
                    try:
                        report['stage']='fixture'
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        session=page.request.get(url+'/api/session').json();headers={'X-CSRF-Token':session['csrf_token']}
                        def post(path,payload):
                            r=page.request.post(url+'/api'+path,data=payload,headers=headers);assert r.ok,r.text();return r.json()
                        c=post('/companies',{'code':'SERIES-SMOKE','name':'Séries sintéticas','tax_id':'SERIE001000180','regime':'outros','state':'SP'})
                        cid=c['id'];post('/context',{'company_id':cid,'period':'2026-11','module':'fiscal'});page.reload()
                        expect(page.locator('#active-company')).to_have_value(str(cid))
                        base=f'/companies/{cid}'
                        assert page.request.get(url+'/api'+base+'/documents').json()==[]
                        doc=post(base+'/documents',{'direction':'incoming','number':'SERIES-SMOKE','model':'55','series':'1','issue_date':'2026-11-05','posting_date':'2026-11-05','partner_name':'Sintético','total':'10.00','cfop':'1102'})
                        did=doc['id']
                        def stored():
                            with sqlite3.connect(Path(data)/'escritura.sqlite3') as conn:return conn.execute('SELECT series FROM documents WHERE id=? AND company_id=?',(did,cid)).fetchone()[0]
                        with sqlite3.connect(Path(data)/'escritura.sqlite3') as conn:conn.execute("UPDATE documents SET series='1' WHERE id=? AND company_id=?",(did,cid))
                        button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name='Parametrizações fiscais',exact=True,include_hidden=True)
                        parent=button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                        button.click();page.get_by_role('button',name='Configurar série e corrigir existentes').click()
                        dialog=page.get_by_role('dialog',name='Padronização de séries fiscais');expect(dialog).to_be_visible()
                        report['stage']='settings'
                        dialog.get_by_label('Dígitos mínimos da série').fill('4');dialog.get_by_role('button',name='Salvar parâmetro',exact=True).click()
                        expect(dialog.get_by_role('button',name='Salvar parâmetro',exact=True)).to_be_disabled();assert stored()=='1'
                        report['checks'].append('save_does_not_migrate')
                        report['stage']='preview'
                        dialog.get_by_role('button',name='Gerar prévia da correção').click();expect(dialog.get_by_role('table',name='Prévia da correção de séries')).to_contain_text('0001')
                        assert stored()=='1';page.screenshot(path=str(out/'preview.png'),full_page=True)
                        dialog.get_by_role('button',name='Fechar',exact=True).click();expect(dialog).to_have_count(0);assert stored()=='1'
                        report['checks'].append('preview_and_cancel_preserve_rows')
                        report['stage']='confirm'
                        page.get_by_role('button',name='Configurar série e corrigir existentes').click();dialog.get_by_role('button',name='Gerar prévia da correção').click()
                        dialog.get_by_role('button',name='Confirmar 1 correções nesta empresa').click();expect(dialog.get_by_role('button',name='Confirmar 1 correções nesta empresa')).to_have_count(0);assert stored()=='0001'
                        dialog.get_by_role('button',name='Gerar prévia da correção').click();expect(dialog.get_by_role('button',name='Confirmar 0 correções nesta empresa')).to_be_disabled()
                        report['checks'].append('explicit_confirmation_and_repeat_noop')
                        dialog.get_by_role('button',name='Fechar',exact=True).click();page.get_by_role('button',name='Configurar série e corrigir existentes').click()
                        report['stage']='discard'
                        dialog.get_by_label('Dígitos mínimos da série').fill('5');dialog.get_by_role('button',name='Fechar',exact=True).click()
                        question=page.get_by_role('dialog',name='Descartar parâmetro não salvo?');question.get_by_role('button',name='Cancelar',exact=True).click()
                        expect(dialog.get_by_label('Dígitos mínimos da série')).to_have_value('5');dialog.get_by_role('button',name='Fechar',exact=True).click();question.get_by_role('button',name='Descartar',exact=True).click();expect(dialog).to_have_count(0)
                        assert not report['console_errors'],report['console_errors'];report['checks'].append('unsaved_cancel_and_discard')
                        page.screenshot(path=str(out/'final.png'),full_page=True)
                    finally:browser.close()
            finally:
                if process:
                    process.terminate()
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

def main(output=None):
    out=Path(output) if output is not None else OUT;out.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'stage':'initializing','checks':[],'console_errors':[],'production_touched':False}
    try:run(report,out);report.update(ok=True,stage='completed')
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc());raise
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
