"""Chromium acceptance of Prosoft mapping/export UI, disposable synthetic data only."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from zipfile import ZipFile
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser-prosoft-export'


def snapshot(folder):
    with sqlite3.connect(f'file:{Path(folder)/"escritura.sqlite3"}?mode=ro',uri=True) as conn:
        result={table:hashlib.sha256(repr(conn.execute('SELECT * FROM '+table+' ORDER BY id').fetchall()).encode()).hexdigest()
                for table in ['documents','document_sources','journals','journal_lines','titles','accounts','cost_centers']}
        result['business_masters']=hashlib.sha256(repr(conn.execute("SELECT * FROM masters WHERE kind!='prosoft_export_settings' ORDER BY id").fetchall()).encode()).hexdigest()
        return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'synthetic_only':True,'checks':[],'console_errors':[],'screenshots':[]}
    process=None
    try:
      with tempfile.TemporaryDirectory(prefix='escritura-prosoft-ui-') as folder:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        with (OUT/'server.log').open('w') as log:
          process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,
              env=dict(os.environ,ESCRITURA_DATA_DIR=folder,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
          for _ in range(100):
            try:urllib.request.urlopen(url+'/api/health',timeout=1);break
            except OSError:time.sleep(.2)
          else:raise RuntimeError('Disposable server did not start')
          with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
            report['browser_version']=browser.version
            page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000)
            page.on('pageerror',lambda error:report['console_errors'].append(str(error)))
            def shot(name):page.screenshot(path=str(OUT/name),full_page=True);report['screenshots'].append(name)
            def check(value):report['checks'].append(value)
            def nav(name):
                button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name=name,exact=True,include_hidden=True)
                parent=button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                button.click()
            def download(link,name):
                with page.expect_download() as item:link.click()
                target=OUT/name;item.value.save_as(target);return target.read_bytes()
            try:
                page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                csrf=page.request.get(url+'/api/session').json()['csrf_token']
                def post(path,payload):
                    result=page.request.post(url+'/api'+path,data=payload,headers={'X-CSRF-Token':csrf})
                    assert result.ok,result.text();return result.json()
                def get(path):
                    result=page.request.get(url+'/api'+path);assert result.ok,result.text();return result.json()
                a=post('/companies',{'code':'SYN-PRO-A','name':'Empresa sintética Prosoft A','tax_id':'TEST0001000120','regime':'outros','state':'SP','create_default_accounts':True})['id']
                b=post('/companies',{'code':'SYN-PRO-B','name':'Empresa sintética Prosoft B','tax_id':'TEST0002000175','regime':'outros','state':'SP','create_default_accounts':True})['id']
                post('/context',{'company_id':a,'module':'fiscal','period':'2026-11'})
                for number,direction,model,total,book in [('100000001','incoming','55','100.01',True),('100000002','outgoing','65','50.02',True),('100000003','incoming','57','7.00',True),('100000004','incoming','55','3.00',False)]:
                    doc=post(f'/companies/{a}/documents',{'direction':direction,'number':number,'model':model,'series':'1','issue_date':'2026-10-30','posting_date':'2026-11-06',
                        'partner_name':'Contraparte sintética','cfop':'1102' if direction=='incoming' else '5102','total':total,'source':{'file':'synthetic.xml'},'source_hash':'synthetic-'+number})
                    if book:post(f'/companies/{a}/documents/{doc["id"]}/book',{'version':doc['version'],'reason':'Teste sintético','lines':[]})
                for number,direction,model in [('100000005','incoming','55'),('100000006','outgoing','65')]:
                    doc=post(f'/companies/{a}/documents',{'direction':direction,'number':number,'model':model,'series':'1',
                        'issue_date':'2026-10-30','posting_date':'2026-11-06','partner_name':'Contraparte sintética cancelada',
                        'partner_tax_id':'11222333000181','cfop':'1102' if direction=='incoming' else '5102','total':'0.00','taxes':{},'items':[],
                        'book_cancellation':{'source':'Livro sintético','responsible':'Teste','reason':'Conferência sintética'}})
                    doc=post(f'/companies/{a}/documents/{doc["id"]}/review',{'version':doc['version'],'reason':'Conferência sintética'})
                    post(f'/companies/{a}/documents/{doc["id"]}/book',{'version':doc['version'],'reason':'Teste sintético','lines':[]})
                accounts={row['access_code']:row['id'] for row in get(f'/companies/{a}/accounts')}
                center=post(f'/companies/{a}/cost-centers',{'code':'SYNCC','name':'Centro sintético'})
                party=post(f'/companies/{a}/masters/participant',{'code':'SYNP','name':'Terceiro sintético','tax_id':'11222333000181','data':{}})
                post(f'/companies/{a}/journals',{'date':'2026-11-06','document':'REFERENCIA CONTABIL SINTETICA LONGA','history':'Synthetic journal','idempotency_key':'synthetic-prosoft','lines':[
                    {'account_id':accounts['3'],'debit':'100.01','credit':'0','cost_center_id':center['id'],'participant_id':party['id']},
                    {'account_id':accounts['5'],'debit':'0','credit':'100.01'}]})
                post(f'/companies/{a}/exercises',{'module':'accounting','year':2027})
                post('/context',{'company_id':b,'module':'fiscal','period':'2026-11'})
                bdoc=post(f'/companies/{b}/documents',{'direction':'incoming','number':'200000001','model':'55','series':'1','issue_date':'2026-10-30','posting_date':'2026-11-06','partner_name':'Contraparte sintética B','cfop':'1102','total':'1.23'})
                post(f'/companies/{b}/documents/{bdoc["id"]}/book',{'version':bdoc['version'],'reason':'Teste sintético','lines':[]})
                post('/context',{'company_id':a,'module':'fiscal','period':'2026-11'})
                before=snapshot(folder)
                page.reload();expect(page.locator('#active-company')).to_have_value(str(a));nav('Exportação Prosoft fiscal')
                expect(page.get_by_role('heading',name='Exportação Prosoft fiscal',exact=True)).to_be_visible()
                code=page.get_by_label('Código da empresa na Prosoft',exact=True);expect(code).to_be_enabled();code.fill('99')
                page.get_by_label('Plano escolhido no destino',exact=False).fill('52')
                for model,species in [('55','NFE'),('65','NFCE')]:
                    page.get_by_label(f'Espécie Prosoft do modelo {model}',exact=True).fill(species)
                    page.get_by_label(f'Espécie do modelo {model} conferida no destino',exact=True).check()
                for cfop,access in [('1102','111'),('5102','222')]:
                    page.get_by_label('Adicionar CFOP',exact=True).fill(cfop);page.get_by_role('button',name='Adicionar mapeamento',exact=True).click()
                    page.get_by_label(f'Acesso Prosoft do CFOP {cfop}',exact=True).fill(access)
                    page.get_by_label(f'Conta do CFOP {cfop} conferida',exact=True).check()
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click()
                expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                assert get(f'/companies/{a}/prosoft-fiscal/settings')['settings']['plan_code']=='0052'
                page.reload();nav('Exportação Prosoft fiscal');expect(code).to_have_value('99');expect(page.get_by_label('Espécie Prosoft do modelo 55',exact=True)).to_have_value('NFE')
                check('Mapeamentos fiscais persistidos por empresa: plano escolhido, espécies 55/65 e contas por CFOP sobrevivem a reload')
                page.get_by_role('button',name='Gerar prévia',exact=True).click()
                preview=page.get_by_role('region',name='Prévia da exportação Prosoft');expect(preview).to_contain_text('Selecionados: 6 documentos')
                expect(preview).to_contain_text('Não exportados: 2');expect(preview).to_contain_text('Modelo não coberto')
                preview.get_by_text('Avisos informativos',exact=False).click();expect(preview).to_contain_text('Tratamento do livro ainda não informado')
                confirm=preview.get_by_role('button',name='Confirmar exportação',exact=True);expect(confirm).to_be_disabled()
                preview.get_by_label('Conferi a empresa, o plano e os mapeamentos no destino.',exact=True).check();expect(confirm).to_be_enabled();confirm.click()
                link=preview.get_by_role('link',name=re.compile('^Baixar (PROSOFT_|CTBLCTOS)'));expect(link).to_be_visible();first_url=link.get_attribute('href')
                raw=download(link,'synthetic-fiscal.zip')
                with ZipFile(BytesIO(raw)) as z:
                    assert [len(row) for row in z.read('ENTRADAS.TXT').splitlines()]==[2340,2340]
                    assert [len(row) for row in z.read('SAIDAS.TXT').splitlines()]==[2611,2611]
                    manifest=json.loads(z.read('manifest.json'));assert manifest['plan_code']=='0052'
                    assert manifest['totals']['incoming']['total_cents']==10001 and manifest['totals']['outgoing']['total_cents']==5002
                    assert len(manifest['skipped'])==2 and manifest['homologated_in_destination'] is False
                    assert all(manifest['totals'][direction]['cancelled_documents']==1 for direction in ('incoming','outgoing'))
                    assert [row[808:809] for row in z.read('ENTRADAS.TXT').splitlines()]==[b'0',b'1']
                    assert [row[929:930] for row in z.read('SAIDAS.TXT').splitlines()]==[b'0',b'1']
                confirm.click();expect(link).to_have_attribute('href',first_url)
                preview.get_by_text('Origem dos registros (4)',exact=True).click();expect(preview.get_by_role('cell',name='Cancelada no livro',exact=True)).to_have_count(2)
                shot('fiscal-preview-desktop.png');check('Prévia fiscal com totais reconciliados, emissão anterior, avisos não bloqueantes e não cobertos; download ZIP real e replay no mesmo lote')
                page.get_by_label('Tipo de exportação Prosoft',exact=True).select_option('outgoing_notes');expect(preview).to_have_count(0)
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click();expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                page.reload();nav('Exportação Prosoft fiscal');expect(page.get_by_label('Tipo de exportação Prosoft',exact=True)).to_have_value('outgoing_notes')
                page.get_by_role('button',name='Gerar prévia',exact=True).click();expect(preview).to_contain_text('Tipo/layout não selecionado')
                preview.get_by_label('Conferi a empresa, o plano e os mapeamentos no destino.',exact=True).check();confirm.click();expect(link).to_be_visible()
                with ZipFile(BytesIO(download(link,'synthetic-fiscal-only-output.zip'))) as z:assert set(z.namelist())=={'SAIDAS.TXT','manifest.json'}
                page.get_by_label('Tipo de exportação Prosoft',exact=True).select_option('both')
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click();expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                check('Escolha de layout fiscal persistida: somente saídas gera apenas SAIDAS.TXT; registros não selecionados têm motivo e retornar a ambas preserva intenção')
                page.get_by_label('Plano escolhido no destino',exact=False).fill('53');expect(preview).to_have_count(0)
                page.get_by_role('button',name=re.compile('^Recarregar salvos')).click();expect(page.get_by_label('Plano escolhido no destino',exact=False)).to_have_value('0052')
                # Hold an actual preview response while another company is activated.
                held=[]
                def hold(route):held.append((route,route.fetch()))
                page.route('**/prosoft-fiscal/preview',hold);page.get_by_role('button',name='Gerar prévia',exact=True).click()
                for _ in range(50):
                    if held:break
                    page.wait_for_timeout(100)
                assert held
                page.locator('#active-company').select_option(str(b));expect(code).to_have_value('')
                held[0][0].fulfill(response=held[0][1]);page.unroute('**/prosoft-fiscal/preview',hold);page.wait_for_timeout(200)
                expect(preview).to_have_count(0);assert get(f'/companies/{b}/prosoft-fiscal/settings')['version']==0
                page.locator('#active-company').select_option(str(a));expect(code).to_have_value('99')
                check('Editar campos remove prévia/download; troca de empresa descarta prévia atrasada e não leva mapeamentos à empresa B')
                nav('Integração Prosoft');expect(page.get_by_role('heading',name='Exportação Prosoft contábil',exact=True)).to_be_visible()
                expect(code).to_be_enabled();expect(code).to_have_value('');code.fill('99');page.get_by_label('Plano escolhido no destino',exact=False).fill('52')
                for account,access in [('3','111'),('5','222')]:
                    page.get_by_label(f'Acesso Prosoft da conta {account}',exact=True).fill(access);page.get_by_label(f'Confirmar conta {account}',exact=True).check()
                page.get_by_label('Tipo de exportação Prosoft',exact=True).select_option('journals_cta')
                page.get_by_label('Uso de terceiro da conta 3',exact=True).select_option('optional')
                page.get_by_text('Cadastro opcional CTA · conta 3',exact=True).click()
                page.get_by_label('Incluir CTA da conta 3: confirme que ela está ausente no destino',exact=True).check()
                page.get_by_label('Nome CTA da conta 3',exact=True).fill('Conta sintetica CTA')
                page.get_by_label('Política de centro CTA da conta 3',exact=True).select_option('1')
                page.get_by_label('Código Prosoft do centro SYNCC · Centro sintético',exact=True).fill('12')
                page.get_by_label('Centro SYNCC conferido no destino',exact=True).check()
                page.get_by_label('Código Prosoft do terceiro Terceiro sintético',exact=True).fill('000123')
                page.get_by_label('Terceiro Terceiro sintético conferido no destino',exact=True).check()
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click();expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                page.reload();nav('Integração Prosoft');expect(page.get_by_label('Acesso Prosoft da conta 3',exact=True)).to_have_value('111')
                page.get_by_role('button',name='Gerar prévia',exact=True).click();expect(preview).to_contain_text('CTA 1');expect(confirm).to_be_disabled()
                preview.get_by_label('Conferi a empresa, o plano e os mapeamentos no destino.',exact=True).check();confirm.click();expect(link).to_be_visible()
                txt=download(link,'synthetic-accounting.txt');rows=txt.splitlines();assert list(map(len,rows))==[208,448]
                assert rows[0][:3]==b'CTA' and rows[0][61:63]==b'21' and rows[1][73:87]==b'000123        '
                preview.get_by_text('Origem dos registros (1)',exact=True).click()
                expect(preview.get_by_text('REFERENCIA CONTABIL SINTETICA LONGA',exact=True)).to_be_visible()
                reference_map=json.loads(download(preview.get_by_role('link',name='Baixar mapa de referências',exact=True),'synthetic-accounting-manifest.json'))
                reference=reference_map['trace'][0]['document_reference']
                assert reference['original']=='REFERENCIA CONTABIL SINTETICA LONGA' and rows[1][20:30]==reference['exported'].encode('ascii')
                assert len(reference['exported'])==10 and get(f'/companies/{a}/journals?period=2026-11')[0]['document']==reference['original']
                check('Canceladas identificadas no TXT e na prévia; referência curta no LC1 com mapa imutável baixado e original preservada')
                shot('accounting-preview-desktop.png');check('Contábil preserva mapeamentos de contas, terceiros e centros e gera CTA/LC1 via UI, com download real e conferência de posições')
                page.get_by_label('Tipo de exportação Prosoft',exact=True).select_option('journals')
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click();expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                page.get_by_role('button',name='Gerar prévia',exact=True).click();expect(preview).to_contain_text('CTA 0')
                preview.get_by_label('Conferi a empresa, o plano e os mapeamentos no destino.',exact=True).check();confirm.click();expect(link).to_be_visible()
                assert list(map(len,download(link,'synthetic-accounting-no-cta.txt').splitlines()))==[448]
                page.get_by_label('Tipo de exportação Prosoft',exact=True).select_option('journals_cta')
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click();expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                check('Escolha contábil preservada: perfil LC1/LC2 exclui CTA configurado e perfil LC1/LC2+CTA o inclui sem apagar o cadastro')
                page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(400)
                if page.locator('.sidebar.visible').count():page.get_by_role('button',name='Fechar navegação',exact=True).click()
                while page.get_by_role('button',name='Fechar aviso',exact=True).count():page.get_by_role('button',name='Fechar aviso',exact=True).first.click()
                assert page.locator('.prosoft-view:visible').evaluate("el=>[...el.querySelectorAll('input,select,button')].filter(n=>!n.closest('.table-scroll')&&n.getBoundingClientRect().width).every(n=>n.getBoundingClientRect().right<=innerWidth+1&&n.getBoundingClientRect().left>=0)")
                page.locator('.prosoft-view:visible .view-heading').scroll_into_view_if_needed()
                shot('accounting-mobile.png');assert page.evaluate('document.documentElement.scrollWidth')<=391
                page.set_viewport_size({'width':1440,'height':1000})
                # Exercise changes invalidate a held response while company mappings remain reusable.
                held=[];page.route('**/prosoft/preview',hold);page.get_by_role('button',name='Gerar prévia',exact=True).click()
                for _ in range(50):
                    if held:break
                    page.wait_for_timeout(100)
                assert held
                page.keyboard.press('F8');dialog=page.get_by_role('dialog',name='Empresa, ano e competência')
                dialog.get_by_label('Ano a fixar (opcional)').fill('2027');dialog.get_by_role('button',name='Aplicar contexto').click();expect(dialog).to_have_count(0)
                expect(page.get_by_label('Competência da exportação',exact=True)).to_have_value('2027-11')
                held[0][0].fulfill(response=held[0][1]);page.unroute('**/prosoft/preview',hold);page.wait_for_timeout(200);expect(preview).to_have_count(0)
                page.keyboard.press('F8');dialog.get_by_label('Ano a fixar (opcional)').fill('2026');dialog.get_by_role('button',name='Aplicar contexto').click();expect(dialog).to_have_count(0)
                expect(page.get_by_label('Acesso Prosoft da conta 3',exact=True)).to_have_value('111')
                check('Desktop/mobile sem overflow; F8/exercício descarta resposta antiga, limpa confirmação e restaura mapeamentos da empresa no retorno')
                page.locator('#active-company').select_option(str(b));nav('Exportação Prosoft fiscal');expect(code).to_be_enabled();code.fill('88')
                page.get_by_label('Espécie Prosoft do modelo 55',exact=True).fill('NFE');page.get_by_label('Espécie do modelo 55 conferida no destino',exact=True).check()
                page.get_by_role('button',name='Salvar mapeamentos nesta empresa',exact=True).click();expect(page.locator('.prosoft-view:visible [role="status"]')).to_contain_text('Mapeamentos salvos nesta empresa')
                post(f'/companies/{b}/periods/close',{'period':'2026-11','module':'fiscal','reason':'Fechamento sintético'})
                page.get_by_role('button',name='Gerar prévia',exact=True).click();expect(preview).to_contain_text('Selecionados: 1 documentos')
                preview.get_by_label('Conferi a empresa, o plano e os mapeamentos no destino.',exact=True).check();confirm.click();expect(link).to_be_visible()
                with ZipFile(BytesIO(download(link,'synthetic-closed-period.zip'))) as z:assert len(z.read('ENTRADAS.TXT').splitlines())==1
                assert snapshot(folder)==before
                check('Exportação em competência fechada permitida; documentos/fontes/lançamentos/partidas/títulos/contas/centros/cadastros econômicos com hashes idênticos')
                assert not report['console_errors'],report['console_errors'];report['ok']=True
            except Exception:
                shot('failure.png');(OUT/'failure-visible.txt').write_text(page.locator('body').inner_text());raise
            finally:browser.close()
    except Exception as error:report['error']=str(error);report['traceback']=traceback.format_exc()
    finally:
        if process:process.terminate();process.wait(timeout=15)
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
