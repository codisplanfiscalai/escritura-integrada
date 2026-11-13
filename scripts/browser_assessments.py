"""Synthetic Chromium assessment workflow; does not access production data."""
from datetime import date
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser-assessments'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'stage':'dependencies','checks':[],'console_errors':[],'screenshots':[],'production_touched':False}
    process=None
    try:
        from playwright.sync_api import sync_playwright,expect
        with tempfile.TemporaryDirectory(prefix='escritura-assessments-') as data:
            report['stage']='server'
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            with (OUT/'server.log').open('w') as log:
                process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url+'/api/health',timeout=1):break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Servidor sintético não iniciou.')
                report['stage']='browser'
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel':'chromium'}))
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                    def shot(name):
                        page.screenshot(path=str(OUT/name),full_page=True);report['screenshots'].append(name)
                    try:
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        session=page.request.get(url+'/api/session').json();headers={'X-CSRF-Token':session['csrf_token']}
                        def post(path,payload):
                            r=page.request.post(url+'/api'+path,data=payload,headers=headers)
                            assert r.ok,r.text()
                            return r.json()
                        report['stage']='fixture'
                        company=post('/companies',{'code':'APURTEST','name':'Apuração sintética Chromium','tax_id':'TEST0001000120','regime':'outros','state':'SP'})
                        cid=company['id'];period=date.today().strftime('%Y-%m');day=period+'-01'
                        post('/context',{'company_id':cid,'period':period,'module':'fiscal'})
                        base=f'/companies/{cid}'
                        def document(number,taxes=None,book=True):
                            d=post(base+'/documents',{'direction':'incoming','number':number,'series':'1','model':'55','issue_date':day,'posting_date':day,'partner_name':'Fornecedor sintético','cfop':'1102','total':'100.00','taxes':taxes or {},'items':[]})
                            if book:
                                d=post(base+f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Teste sintético'})
                                post(base+f"/documents/{d['id']}/book",{'version':d['version'],'reason':'Teste sintético','idempotency_key':'book-'+number,'generate_titles':False,'lines':[]})
                            return d
                        document('BASE',{'ICMSTot.vBC':'40.05'});document('SEM-BASE')
                        post(base+'/rules',{'name':'Regra sintética 10%','tax':'ICMS','rate':'10','valid_from':period[:4]+'-01-01','status':'validated','source':'Fonte sintética sem efeito normativo','responsible':'Teste','direction':'incoming'})
                        page.reload();nav=page.get_by_role('navigation',name='Navegação principal');button=nav.get_by_role('button',name='Apurações e ajustes',exact=True,include_hidden=True)
                        parent=button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                        button.click();panel=page.locator('.assessments-view');start=panel.get_by_role('button',name='Preparar apuração',exact=True)
                        expect(start).to_be_enabled();start.click();dialog=page.get_by_role('dialog',name='Preparar apuração',exact=True)
                        expect(dialog.locator('.assessment-entry')).to_have_count(2)
                        bases=dialog.get_by_role('textbox',name='Base conferida (R$)',exact=True)
                        assert sorted(bases.nth(i).input_value() for i in range(bases.count()))==['','40,05']
                        report['checks'].append('base declarada sugerida; total da nota não virou base')
                        dialog.get_by_label('Fundamentação / fonte normativa *',exact=True).fill('Cenário sintético revisado')
                        dialog.get_by_label('Responsável pela conferência *',exact=True).fill('Teste')
                        dialog.get_by_label('Natureza comum',exact=True).select_option('credit');dialog.get_by_label('Fundamento comum',exact=True).fill('Base sintética conferida')
                        dialog.get_by_role('button',name='Aplicar às bases selecionadas').click()
                        for i in range(bases.count()):
                            if bases.nth(i).input_value()=='':bases.nth(i).fill('0,00')
                        report['stage']='preview'
                        dialog.get_by_role('button',name='Conferir cálculo').click();save=dialog.get_by_role('button',name='Salvar memória conferida')
                        expect(save).to_be_enabled();assert page.request.get(url+'/api'+base+f'/assessments?period={period}').json()==[]
                        shot('preview-desktop.png');report['checks'].append('prévia não grava memória')
                        bases.first.fill('1,00');expect(save).to_be_disabled();dialog.get_by_role('button',name='Conferir cálculo').click();expect(save).to_be_enabled()
                        document('CONCORRENTE',book=False);save.click();expect(dialog.get_by_role('alert')).to_contain_text('mudaram');assert page.request.get(url+'/api'+base+f'/assessments?period={period}').json()==[]
                        dialog.get_by_role('button',name='Conferir cálculo').click();expect(save).to_be_enabled();save.click();expect(dialog).to_have_count(0)
                        detail=page.get_by_role('dialog',name='Memória de cálculo',exact=True);expect(detail).to_be_visible();detail.get_by_role('button',name='Fechar',exact=True).click()
                        assert len(page.request.get(url+'/api'+base+f'/assessments?period={period}').json())==1
                        report['checks'].append('edição invalida prévia; novo documento bloqueia salvar; nova prévia permite salvar sem finalizar')
                        report['stage']='balance_only'
                        expect(start).to_be_enabled();start.click();dialog.get_by_role('button',name='Só ajustes e saldo anterior').click()
                        confirmation=page.get_by_role('dialog',name='Usar somente ajustes e saldo anterior?',exact=True)
                        confirmation.get_by_role('button',name='Retirar bases do rascunho',exact=True).click();expect(dialog.locator('.assessment-entry')).to_have_count(0)
                        expect(dialog.get_by_role('checkbox',name='Confirmei a ausência de bases neste cenário; apurar somente ajustes e saldo anterior.')).not_to_be_checked()
                        dialog.get_by_role('button',name='Cancelar',exact=True).click();discard=page.get_by_role('dialog',name='Descartar edição?',exact=True);discard.get_by_role('button',name='Descartar',exact=True).click();expect(dialog).to_have_count(0)
                        assert len(page.request.get(url+'/api'+base+f'/assessments?period={period}').json())==1
                        report['checks'].append('só saldo limpa apenas rascunho; descartar não cria memória nem exclui documentos')
                        shot('final-desktop.png');assert not report['console_errors'],report['console_errors'];report.update(ok=True,stage='completed')
                    except Exception:
                        try:shot('failure.png')
                        except Exception:pass
                        raise
                    finally:browser.close()
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
