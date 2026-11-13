"""Synthetic Chromium acceptance for context shortcuts, suggested month and scrolling."""
from datetime import date
import json, os, socket, subprocess, sys, tempfile, time, traceback, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser-workspace-context'

def load_browser():
    from playwright.sync_api import expect, sync_playwright
    return expect, sync_playwright

def stop_server(process, report):
    if process is None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except Exception as exc:
        report['ok'] = False
        report.setdefault('cleanup_errors', []).append(str(exc))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'checks':[],'console_errors':[],'screenshots':[],'source_sha':None,'stage':'dependencies'}
    process=None
    try:
        expect, sync_playwright = load_browser()
        report['stage'] = 'source'
        report['source_sha'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        report['stage'] = 'server'
        with tempfile.TemporaryDirectory(prefix='escritura-context-') as data:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            with (OUT/'server.log').open('w') as log:
                process=subprocess.Popen([os.environ.get('ESCRITURA_TEST_PYTHON',sys.executable),'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url+'/api/health',timeout=1):break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Synthetic server did not start')
                report['stage'] = 'browser'
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel':'chromium'}))
                    page=browser.new_page(viewport={'width':1440,'height':720});page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                    def shot(name):page.screenshot(path=str(OUT/name),full_page=True);report['screenshots'].append(name)
                    def nav(name):
                        button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name=name,exact=True,include_hidden=True)
                        group=button.locator('xpath=ancestor::details')
                        if group.count() and group.get_attribute('open') is None:group.locator('summary').click()
                        button.click()
                    try:
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        headers={'X-CSRF-Token':page.request.get(url+'/api/session').json()['csrf_token']}
                        def post(path,payload):
                            response=page.request.post(url+'/api'+path,data=payload,headers=headers)
                            assert response.ok,response.text()
                            return response.json()
                        cid=post('/companies',{'code':'00123','name':'Contexto sintético','tax_id':'TEST0001000120','regime':'outros','state':'SP'})['id']
                        year=str(date.today().year);post('/context',{'company_id':cid,'module':'fiscal','period':year+'-09'})
                        for i in range(24):post(f'/companies/{cid}/documents',{'direction':'incoming','number':str(1000+i),'model':'55','series':'1','issue_date':year+'-09-01','posting_date':year+'-09-01','partner_name':'Fornecedor sintético','cfop':'1102','total':'10.00'})
                        page.reload()
                        # reload only waits for navigation; session hydration mounts the shortcut listener later.
                        expect(page.locator('#active-company')).to_have_value(str(cid))
                        expect(page.get_by_role('button',name='Fixar empresa, ano e competência (F8)',exact=True)).to_be_enabled()
                        page.keyboard.press('F8')
                        dialog=page.get_by_role('dialog',name='Empresa, ano e competência')
                        expect(dialog).to_be_visible();dialog.get_by_label('Buscar empresa por código, nome ou CNPJ').fill('123');dialog.get_by_role('button',name='Localizar empresa').click()
                        expect(dialog.get_by_label('Empresa',exact=True)).to_have_value(str(cid))
                        dialog.get_by_label('Ano a fixar (opcional)').fill(year);dialog.get_by_label('Competência a fixar (opcional)').select_option('09')
                        dialog.get_by_role('button',name='Aplicar contexto').click();expect(dialog).to_have_count(0)
                        nav('Escrituração e documentos');month=page.get_by_label('Competência da consulta',exact=True);expect(month).to_have_value('09')
                        table=page.locator('.table-scroll').first;expect(table.locator('tbody tr')).to_have_count(24)
                        main=page.locator('.main-content');main.evaluate('(el)=>el.scrollTop=0');table.hover(position={'x':100,'y':50});before=main.evaluate('(el)=>el.scrollTop');page.mouse.wheel(0,500)
                        page.wait_for_function('(before)=>document.querySelector(".main-content").scrollTop>before',arg=before)
                        report['checks'].append('F8 code with leading zeros, suggested September, table wheel reaches page scrolling')
                        main.evaluate('(el)=>el.scrollTop=0');month.select_option('07');nav('Visão geral');nav('Escrituração e documentos');expect(month).to_have_value('07')
                        page.get_by_role('button',name='Novo documento',exact=True).click();editor=page.get_by_role('dialog');expect(editor).to_have_count(1)
                        page.keyboard.press('F9');expect(page.locator('#active-company')).to_have_value(str(cid));page.keyboard.press('F8');expect(page.get_by_role('dialog',name='Empresa, ano e competência')).to_have_count(0)
                        editor.get_by_label('Número *',exact=True).fill('999999')
                        page.keyboard.press('Escape')
                        discard=page.get_by_role('dialog',name='Descartar edição?')
                        expect(discard).to_be_visible()
                        page.keyboard.press('F9');expect(page.locator('#active-company')).to_have_value(str(cid))
                        page.keyboard.press('F8');expect(dialog).to_have_count(0)
                        discard.get_by_role('button',name='Descartar',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        report['checks'].append('manual July survives navigation; F8 and F9 are blocked while editing')
                        navigation=page.get_by_role('navigation',name='Navegação principal');navigation.evaluate('(el)=>{for(const d of el.querySelectorAll("details"))d.open=true;el.scrollTop=0;}');navigation.focus();navigation.press('End');page.wait_for_function('()=>document.querySelector(".sidebar nav").scrollTop>0')
                        assert navigation.evaluate('(el)=>getComputedStyle(el).scrollbarWidth')=='thin'
                        report['checks'].append('sidebar scrolls by keyboard with thin scrollbar')
                        page.keyboard.press('F9');expect(page.locator('#active-company')).to_have_value('');expect(page.locator('#active-period')).to_have_value('')
                        session=page.request.get(url+'/api/session').json();assert session['active_company_id'] is None
                        page.keyboard.press('F8');expect(dialog.get_by_label('Ano a fixar (opcional)')).to_have_value('');expect(dialog.get_by_label('Competência a fixar (opcional)')).to_have_value('');dialog.get_by_role('button',name='Cancelar',exact=True).click()
                        report['checks'].append('F9 clears company and persisted year/month without deleting records')
                        shot('workspace-context.png');assert not report['console_errors'],report['console_errors'];report['ok']=True;report['stage']='complete'
                    except Exception:
                        try:shot('failure.png')
                        except Exception as exc:report['screenshot_error']=str(exc)
                        raise
                    finally:
                        try:browser.close()
                        except Exception as exc:
                            report['ok']=False
                            report.setdefault('cleanup_errors',[]).append(str(exc))
    except Exception as exc:report['error']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        stop_server(process, report)
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
