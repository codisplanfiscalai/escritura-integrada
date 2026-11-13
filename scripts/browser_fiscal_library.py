"""Chromium acceptance for fiscal libraries, with isolated synthetic data only."""
from pathlib import Path
import json,os,re,socket,subprocess,sys,tempfile,time,traceback,urllib.request
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser-fiscal-library'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'checks':[],'console_errors':[],'screenshots':[]};process=None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-fiscal-library-') as data:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            with (OUT/'server.log').open('w') as log:
                process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
                for _ in range(100):
                    try:urllib.request.urlopen(url+'/api/health',timeout=1);break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Preview server did not start')
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True,executable_path=os.environ.get('ESCRITURA_TEST_BROWSER','/usr/bin/chromium'))
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                    def shot(name):page.screenshot(path=str(OUT/name),full_page=True);report['screenshots'].append(name)
                    def nav(label):
                        button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name=label,exact=True,include_hidden=True)
                        parent=button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                        button.click()
                    try:
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        cid=page.request.get(url+'/api/session').json()['active_company_id']
                        companies=page.request.get(url+'/api/companies').json();company=next(c for c in companies if c['id']==cid);other=next(c['id'] for c in companies if c['id']!=cid)
                        def get(path,company=cid):return page.request.get(url+f'/api/companies/{company}'+path).json()
                        other_rules=get('/rules',other)
                        nav('CFOP e associações')
                        panel=page.locator('details.fiscal-library');panel.locator('summary').click()
                        panel.get_by_role('textbox',name='Pesquisar biblioteca fiscal global').fill('1102')
                        expect(panel.locator('tbody tr')).to_have_count(1)
                        original=get('/global-fiscal-catalogs?search=1102')['rows'][0]
                        panel.get_by_role('button',name='Editar global',exact=True).click()
                        dialog=page.get_by_role('dialog',name='Editar tabela global')
                        dialog.get_by_label('Alíquotas informativas, separadas por ponto e vírgula').fill('17,25; 0')
                        dialog.get_by_label('Motivo da alteração global *').fill('Conferência sintética Chromium')
                        dialog.get_by_role('button',name='Salvar global').click();expect(dialog).to_have_count(0)
                        edited=get('/global-fiscal-catalogs?search=1102')['rows'][0]
                        assert edited['rates_declared']==['17.25','0'];assert edited['source_rates_declared']==original['source_rates_declared']
                        panel.get_by_role('button',name='Histórico',exact=True).click()
                        history=page.get_by_role('dialog',name='Histórico global preservado');expect(history).to_contain_text('Versão 2');expect(history).to_contain_text('Versão 1');history.get_by_role('button',name='Fechar',exact=True).click()
                        panel.get_by_role('button',name='Editar global',exact=True).click();dialog.get_by_label('Alíquotas informativas, separadas por ponto e vírgula').fill('99')
                        page.keyboard.press('Escape');page.get_by_role('dialog',name='Descartar alterações?').get_by_role('button',name='Descartar',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0);assert get('/global-fiscal-catalogs?search=1102')['rows'][0]['rates_declared']==['17.25','0']
                        report['checks'].append('CFOP global editável; valores originais e versões preservados; Escape/descartar não salva nem mantém modal')
                        shot('cfop-informativo.png')
                        nav('Parametrizações fiscais');panel=page.locator('details.fiscal-library');panel.locator('summary').click()
                        panel.get_by_role('button',name='Publicar padrão global',exact=True).click();dialog=page.get_by_role('dialog',name='Publicar padrão fiscal global')
                        dialog.get_by_label('Estrutura inicial opcional').select_option(company['regime']+'-commerce')
                        dialog.get_by_label('Motivo da alteração global *').fill('Estrutura sintética para revisão por empresa')
                        dialog.get_by_role('button',name='Salvar global').click();expect(dialog).to_have_count(0)
                        pattern=get('/fiscal-patterns')['rows'][0];assert all(r['rate'] is None for r in pattern['rules'])
                        panel.get_by_role('button',name='Derivar global',exact=True).click()
                        derived_dialog=page.get_by_role('dialog',name='Publicar padrão fiscal global')
                        derived_dialog.get_by_label('Atividade declarada',exact=True).fill('Farmácia')
                        derived_dialog.get_by_label('Motivo da alteração global *').fill('Especializar estrutura sem presumir tributação')
                        derived_dialog.get_by_role('button',name='Salvar global').click();expect(derived_dialog).to_have_count(0)
                        derived=next(r for r in get('/fiscal-patterns')['rows'] if r['id']!=pattern['id'])
                        assert derived['derived_from']['id']==pattern['id'] and derived['derived_from']['version']==1
                        assert derived['activity']=='Farmácia' and all(r['rate'] is None for r in derived['rules'])
                        report['checks'].append('Derivação global rastreável com especialização Farmácia e sem alíquotas presumidas')
                        before=get('/rules')
                        for attempt in range(2):
                            panel.get_by_role('button',name='Importar na empresa',exact=True).first.click();dialog=page.get_by_role('dialog',name='Importar padrão como rascunho inativo')
                            confirm=dialog.get_by_role('button',name='Confirmar importação inativa');expect(confirm).to_be_disabled()
                            dialog.get_by_label('Segmento confirmado da empresa *').select_option('commerce')
                            dialog.get_by_label('Responsável pela revisão *').fill('Revisor sintético')
                            dialog.get_by_label('Motivo da importação *').fill('Teste de cópia inativa independente')
                            dialog.get_by_role('button',name='Conferir prévia').click();expect(confirm).to_be_enabled()
                            if not attempt:
                                shot('padrao-previa-inativa.png')
                                dialog.get_by_label('Motivo da importação *').fill('Motivo alterado após prévia');expect(confirm).to_be_disabled()
                                dialog.get_by_role('button',name='Conferir prévia').click();expect(confirm).to_be_enabled()
                            confirm.click();expect(dialog).to_have_count(0)
                        after=get('/rules');new=[r for r in after if r['id'] not in {r['id'] for r in before}]
                        assert len(new)==len(pattern['rules']);assert all(not r['active'] and r['status']=='draft' for r in new)
                        assert other_rules==get('/rules',other)
                        report['checks'].append('Publicação de estrutura sem alíquotas, prévia obrigatória invalidada por edição, cópias inativas e repetição idempotente; outra empresa preservada')
                        page.locator('#active-company').select_option(str(other));expect(panel).to_be_visible();assert get('/rules',other)==other_rules
                        report['checks'].append('Troca de empresa após conclusão não altera cópias existentes nem replica regras automaticamente')
                        shot('biblioteca-global-desktop.png');page.set_viewport_size({'width':390,'height':844});shot('biblioteca-global-mobile.png')
                        assert not report['console_errors'],report['console_errors'];report['ok']=True
                    except Exception:
                        shot('failure.png');(OUT/'failure-visible.txt').write_text(page.locator('body').inner_text());raise
                    finally:browser.close()
    except Exception as exc:report['error']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        if process:process.terminate();process.wait(timeout=15)
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
