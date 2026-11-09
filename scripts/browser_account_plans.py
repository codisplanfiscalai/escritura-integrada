"""Real Chromium acceptance of account plans; isolated synthetic demo data only."""
from pathlib import Path
import json, os, socket, subprocess, sys, tempfile, time, traceback, urllib.request
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser-account-plans'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'checks':[],'console_errors':[],'screenshots':[]}
    process=None
    try:
      with tempfile.TemporaryDirectory(prefix='escritura-plan-ui-') as data:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        with (OUT/'server.log').open('w') as log:
          process=subprocess.Popen([sys.executable,'scripts/run_preview.py','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
          for _ in range(100):
            try:urllib.request.urlopen(url+'/api/health',timeout=1);break
            except OSError:time.sleep(.2)
          else:raise RuntimeError('Preview server did not start')
          with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
            page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000)
            page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
            page.on('console',lambda m:report['console_errors'].append(m.text) if m.type=='error' else None)
            def shot(name):page.screenshot(path=str(OUT/name),full_page=True);report['screenshots'].append(name)
            def check(name):report['checks'].append(name)
            def download(locator,name):
              with page.expect_download() as d:locator.click()
              dest=OUT/name;d.value.save_as(dest);return dest.read_bytes()
            try:
              page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
              expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
              cid=page.request.get(url+'/api/session').json()['active_company_id']
              def accounts(company=cid):return page.request.get(url+f'/api/companies/{company}/accounts').json()
              original=accounts();assert len(original)==6
              nav=page.get_by_role('navigation',name='Navegação principal');button=nav.get_by_role('button',name='Plano de contas',exact=True,include_hidden=True)
              parent=button.locator('xpath=ancestor::details')
              if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
              button.click()
              panel=page.get_by_role('region',name='Intercâmbio de plano de contas')
              panel.get_by_role('button',name='Abrir ferramentas').click()
              panel.get_by_label('Operação',exact=True).select_option('default')
              panel.get_by_role('button',name='Gerar prévia',exact=True).click()
              preview=page.get_by_role('region',name='Prévia do plano de contas')
              expect(preview.get_by_text('73 registros no total',exact=True)).to_be_visible()
              confirm=panel.get_by_role('button',name='Confirmar ativação de contas',exact=True)
              expect(confirm).to_be_disabled()
              panel.get_by_label('Motivo da importação *',exact=True).fill('Teste sintético Chromium: adicionar padrão sem substituir legado')
              expect(confirm).to_be_disabled()
              panel.get_by_label('Revisei as propriedades',exact=False).check()
              expect(confirm).to_be_enabled();shot('template-preview-desktop.png');confirm.click()
              expect(panel.get_by_role('status')).to_contain_text('contas existentes preservadas')
              after=accounts();assert len(after)==73
              assert all(row in after for row in original)
              check('Template de 73 contas aplicado pela UI; motivo e revisão obrigatórios; seis contas legadas idênticas')
              panel.get_by_role('button',name='Gerar prévia',exact=True).click()
              expect(preview).to_contain_text('0 a criar · 73 existentes preservados')
              panel.get_by_label('Revisei as propriedades',exact=False).check();confirm.click()
              expect(panel.get_by_role('status')).to_be_visible();assert accounts()==after
              check('Repetição do template não duplica nem altera contas')
              panel.get_by_label('Operação',exact=True).select_option('export')
              panel.get_by_role('button',name='Gerar prévia',exact=True).click()
              export=panel.get_by_role('button',name='Confirmar e baixar arquivo',exact=True)
              expect(export).to_be_disabled();panel.get_by_label('Conferi o formato',exact=False).check()
              native=json.loads(download(export,'active-native.json'))
              assert len(native['accounts'])==73 and native['schema']=='escritura-account-plan/v1'
              check('Exportação JSON nativa: confirmação de destino e download real das 73 contas')
              # Deliberately repeated classifier, distinct access code, plus opaque metadata.
              fixture=json.loads(json.dumps(native));fixture['future']={'synthetic':'preserved'}
              duplicate=dict(fixture['accounts'][0],access_code='99000',prosoft_code='99000',name='Duplicada sintética de referência')
              fixture['accounts'].append(duplicate)
              raw=json.dumps(fixture,ensure_ascii=False).encode();source=Path(data)/'reference-synthetic.json';source.write_bytes(raw)
              panel.get_by_label('Operação',exact=True).select_option('import');panel.get_by_label('Arquivo de origem',exact=False).set_input_files(source)
              panel.get_by_role('button',name='Gerar prévia',exact=True).click()
              expect(preview.get_by_text('Ativação de contas bloqueada',exact=False)).to_be_visible();expect(confirm).to_be_disabled()
              panel.get_by_label('Destino do lote',exact=True).select_option('reference')
              panel.get_by_label('Motivo da importação *',exact=True).fill('Preservar lote sintético integral sem ativação')
              refconfirm=panel.get_by_role('button',name='Guardar referência sem ativar contas',exact=True)
              expect(refconfirm).to_be_disabled();panel.get_by_label('Revisei as propriedades',exact=False).check()
              shot('reference-preview-desktop.png')
              page.set_viewport_size({'width':390,'height':844});shot('reference-preview-mobile.png')
              assert page.evaluate('document.documentElement.scrollWidth')<=391
              page.set_viewport_size({'width':1440,'height':1000});refconfirm.click()
              expect(panel.get_by_role('status')).to_contain_text('74 registros preservados como referência')
              assert accounts()==after
              saved=json.loads(download(panel.get_by_role('link',name='Baixar carga completa em JSON nativo',exact=True),'reference-native.json'))
              assert saved['accounts']==fixture['accounts'] and saved['future']==fixture['future']
              panel.get_by_role('button',name='Consultar histórico',exact=True).click()
              row=panel.locator('tr').filter(has_text='reference-synthetic.json')
              expect(row).to_contain_text('Referência · sem contas ativas')
              assert download(row.get_by_role('link',name='Baixar original',exact=True),'reference-original.json')==raw
              assert json.loads(download(row.get_by_role('link',name='Baixar JSON nativo completo',exact=True),'reference-history-native.json'))['accounts']==fixture['accounts']
              check('Classificador duplicado bloqueia ativação; referência preserva 74 registros e metadados, original byte a byte e JSON completo; plano ativo intacto')
              check('Desktop 1440 e mobile 390: evidências capturadas e sem overflow horizontal')
              panel.get_by_role('button',name='Cancelar',exact=True).click()
              expect(panel.get_by_role('button',name='Abrir ferramentas')).to_be_visible()
              panel.get_by_role('button',name='Abrir ferramentas').click()
              expect(panel.get_by_label('Arquivo de origem',exact=False)).to_have_value('')
              expect(preview).to_have_count(0)
              expect(panel.get_by_role('button',name='Gerar prévia',exact=True)).to_be_disabled()
              check('Cancelar limpa arquivo, prévia e confirmação; reabertura exige nova seleção')
              # Delay a real preview response until after company context changes.
              panel.get_by_label('Operação',exact=True).select_option('default')
              held=[]
              def hold(route):held.append((route,route.fetch()))
              page.route('**/account-plans/preview',hold)
              panel.get_by_role('button',name='Gerar prévia',exact=True).click()
              for _ in range(50):
                if held:break
                page.wait_for_timeout(100)
              assert held
              companies=page.request.get(url+'/api/companies').json();other=next(c['id'] for c in companies if c['id']!=cid)
              page.locator('#active-company').select_option(str(other))
              expect(panel.get_by_role('button',name='Abrir ferramentas')).to_be_visible()
              held[0][0].fulfill(response=held[0][1]);page.unroute('**/account-plans/preview',hold)
              page.wait_for_timeout(300);panel.get_by_role('button',name='Abrir ferramentas').click()
              expect(preview).to_have_count(0);expect(panel.get_by_role('status')).to_have_count(0)
              assert len(accounts(other))==6
              shot('context-switched-desktop.png')
              check('Troca de empresa durante prévia pendente descarta resposta tardia, limpa estado e preserva seis contas da outra empresa')
              assert not report['console_errors'],report['console_errors']
              report['ok']=True;report['browser_version']=browser.version
            except Exception:
              shot('failure.png');(OUT/'failure-visible.txt').write_text(page.locator('body').inner_text());raise
            finally:browser.close()
    except Exception as e:report['error']=str(e);report['traceback']=traceback.format_exc()
    finally:
      if process:process.terminate();process.wait(timeout=15)
      (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
