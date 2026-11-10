"""Chromium acceptance of publication, shared usage and own adaptation.

Runs only in a fresh temporary demo database with synthetic input.
"""
from pathlib import Path
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts'/'browser-account-plans'/'global'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report={'ok':False,'checks':[],'console_errors':[]}
    process=None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-global-plan-ui-') as data:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            with (OUT/'server.log').open('w') as log:
                process=subprocess.Popen([sys.executable,'scripts/run_preview.py','--port',str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1'),stdout=log,stderr=log)
                for _ in range(100):
                    try:urllib.request.urlopen(url+'/api/health',timeout=1);break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Servidor de teste não iniciou.')
                with sync_playwright() as playwright:
                    browser=playwright.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000)
                    page.on('pageerror',lambda exc:report['console_errors'].append(str(exc)))
                    try:
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        session=page.request.get(url+'/api/session').json();cid=session['active_company_id']
                        nav=page.get_by_role('navigation',name='Navegação principal')
                        button=nav.get_by_role('button',name='Plano de contas',exact=True,include_hidden=True)
                        parent=button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                        button.click()
                        panel=page.get_by_role('region',name='Intercâmbio de plano de contas')
                        library=page.get_by_role('region',name='Plano global compartilhado')
                        expect(library.get_by_text('Nenhum plano global publicado.',exact=False)).to_be_visible()
                        plan=json.loads((ROOT/'app/data/account-plan-default.json').read_text())
                        plan['accounts']=[dict(plan['accounts'][3],access_code='00101',prosoft_code='00101',name='Subconta ficticia A'),dict(plan['accounts'][3],access_code='00102',prosoft_code='00102',name='Subconta ficticia B')]
                        fixture=Path(data)/'synthetic-plan.json';fixture.write_text(json.dumps(plan))
                        panel.get_by_role('button',name='Abrir ferramentas').click()
                        panel.get_by_label('Arquivo de origem',exact=False).set_input_files(fixture)
                        panel.get_by_role('button',name='Gerar prévia',exact=True).click()
                        expect(panel.get_by_role('region',name='Prévia do plano de contas')).to_be_visible()
                        panel.get_by_label(re.compile('^Destino do lote')).select_option('global')
                        panel.get_by_label('Nome da versão global *',exact=True).fill('Plano global sintético')
                        panel.get_by_label('Motivo da importação *',exact=True).fill('Publicação sintética pelo Chromium')
                        panel.get_by_label('Revisei as propriedades',exact=False).check()
                        publish=panel.get_by_role('button',name='Publicar versão global',exact=True)
                        expect(publish).to_be_disabled()
                        panel.get_by_label('Autorizo disponibilizar o conteúdo integral',exact=False).check()
                        publish.click();expect(panel.get_by_role('status')).to_contain_text('2 contas')
                        report['checks'].append('Publicação UI conserva duas contas sob o mesmo classificador e exige consentimento global separado.')
                        select=library.get_by_label(re.compile('^Plano e versão'))
                        expect(select.locator('option')).to_have_count(2);select.select_option(index=1)
                        library.get_by_role('button',name='Preparar uso na empresa').click()
                        expect(library.get_by_text('Prévia da versão',exact=False)).to_be_visible()
                        library.get_by_label('Motivo da operação',exact=True).fill('Uso compartilhado sintético')
                        library.get_by_label('Revisei a máscara, a hierarquia',exact=False).check()
                        library.get_by_role('button',name='Confirmar uso nesta empresa').click()
                        expect(library.get_by_role('status')).to_contain_text('protegido contra edição local')
                        accounts=page.request.get(url+f'/api/companies/{cid}/accounts').json()
                        shared=[a for a in accounts if a['access_code'] in {'00101','00102'}]
                        assert len(shared)==2 and shared[0]['classifier']==shared[1]['classifier']
                        assert all(a['id']<0 for a in shared)
                        headers={'X-CSRF-Token':session['csrf_token']}
                        posted=page.request.post(url+f'/api/companies/{cid}/journals',headers=headers,data={'date':'2026-11-06','document':'SYNTHETIC','history':'Synthetic shared journal','idempotency_key':'global-plan-browser','lines':[{'account_id':shared[0]['id'],'debit':'10.00','credit':'0.00'},{'account_id':shared[1]['id'],'debit':'0.00','credit':'10.00'}]})
                        assert posted.status==201
                        ids={line['account_id'] for line in posted.json()['lines']}
                        assert all(aid>0 for aid in ids)
                        r=page.request.put(url+f"/api/companies/{cid}/accounts/{shared[0]['id']}",headers=headers,data=shared[0]|{'name':'Mutação proibida'})
                        assert r.status==409
                        report['checks'].append('Plano compartilhado operacional cria contas de IDs distintos e bloqueia mutação local no servidor.')
                        library.get_by_role('button',name='Duplicar vínculo para plano próprio').click()
                        expect(library.get_by_role('status')).to_contain_text('Identificadores e lançamentos foram preservados')
                        owned=next(a for a in page.request.get(url+f'/api/companies/{cid}/accounts').json() if a['access_code']==shared[0]['access_code'])
                        r=page.request.put(url+f"/api/companies/{cid}/accounts/{shared[0]['id']}",headers=headers,data=owned|{'name':'Adaptação sintética isolada'})
                        assert r.status==200
                        current=page.request.get(url+f'/api/companies/{cid}/accounts').json()
                        assert ids=={a['id'] for a in current if a['access_code'] in {'00101','00102'}}
                        library.get_by_role('button',name='Consultar contas',exact=True).click()
                        expect(library.get_by_text('Subconta ficticia A',exact=True)).to_be_visible()
                        report['checks'].append('Duplicação própria preserva IDs, permite adaptação isolada e mantém definição global intacta.')
                        library.get_by_role('button',name='Cancelar',exact=True).click()
                        expect(library.get_by_text('Subconta ficticia A',exact=True)).to_have_count(0)
                        # Reuse the same definition in a fresh company. A used-only
                        # fork must report zero, then full remains an explicit choice.
                        from app.core import cnpj_digits
                        base='TEST00090001'
                        other=page.request.post(url+'/api/companies',headers=headers,data={'code':'GLOBAL-UI-2','name':'Synthetic global fork company','tax_id':base+cnpj_digits(base),'regime':'outros','state':'SP','create_default_accounts':False})
                        assert other.status==201
                        other_id=other.json()['id']
                        switched=page.request.post(url+'/api/context',headers=headers,data={'company_id':other_id,'period':'2026-11','module':'accounting'})
                        assert switched.status==200
                        page.reload()
                        nav=page.get_by_role('navigation',name='Navegação principal')
                        button=nav.get_by_role('button',name='Plano de contas',exact=True,include_hidden=True)
                        parent=button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                        button.click()
                        select=library.get_by_label(re.compile('^Plano e versão'));expect(select.locator('option')).to_have_count(2);select.select_option(index=1)
                        library.get_by_label(re.compile('^Uso nesta empresa')).select_option('own')
                        library.get_by_label(re.compile('^Escopo da cópia própria')).select_option('used')
                        library.get_by_role('button',name='Preparar uso na empresa').click()
                        expect(library.get_by_text('0 contas usadas e 0 contas sintéticas',exact=False)).to_be_visible()
                        library.get_by_label('Motivo da operação',exact=True).fill('Only used accounts requested, none used')
                        library.get_by_label('Revisei a máscara, a hierarquia',exact=False).check()
                        library.get_by_role('button',name='Confirmar uso nesta empresa').click()
                        expect(library.get_by_role('status')).to_contain_text('Nenhuma conta global foi copiada')
                        assert not page.request.get(url+f'/api/companies/{other_id}/accounts').json()
                        library.get_by_label(re.compile('^Escopo da cópia própria')).select_option('all')
                        library.get_by_role('button',name='Preparar uso na empresa').click()
                        library.get_by_label('Revisei a máscara, a hierarquia',exact=False).check()
                        library.get_by_role('button',name='Confirmar uso nesta empresa').click()
                        expect(library.get_by_role('status')).to_contain_text('integral')
                        assert len(page.request.get(url+f'/api/companies/{other_id}/accounts').json())==2
                        report['checks'].append('Mesma versão reutilizada em outra empresa: opção usadas comunica cópia zero; opção integral permanece disponível e copia as duas contas.')
                        page.set_viewport_size({'width':390,'height':844})
                        assert page.evaluate('document.documentElement.scrollWidth')<=391
                        report['checks'].append('Cancelar limpa seleção/prévia e layout móvel não transborda.')
                        assert not report['console_errors'],report['console_errors']
                        report['ok']=True;report['browser_version']=browser.version
                    finally:browser.close()
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['ok']:raise SystemExit(1)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
