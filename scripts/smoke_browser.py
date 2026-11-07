"""Aceitação real em Chromium, com instalação temporária e dados sintéticos."""
from __future__ import annotations
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

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'browser'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'version':(ROOT/'VERSION').read_text().strip(),
        'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'console_errors':[],'checks':[],'screenshots':[],'lookup_fixture':True}
    process=None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-browser-') as folder:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            env=dict(os.environ,ESCRITURA_DATA_DIR=folder,ESCRITURA_DEMO='1')
            with (OUT/'server.log').open('w') as logfile:
                process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=logfile,stderr=logfile)
                for _ in range(60):
                    try:
                        with urllib.request.urlopen(url+'/api/health',timeout=1):break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Servidor de teste não iniciou.')
                with sync_playwright() as playwright:
                    browser=playwright.chromium.launch(headless=True)
                    report['browser_version']=browser.version
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                    page.set_default_timeout(15000)
                    def shot(name):
                        page.screenshot(path=str(OUT/name),full_page=True,animations='disabled');report['screenshots'].append(name)
                    def nav(label):
                        page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name=label,exact=True).click()
                    def check(name):report['checks'].append(name)
                    def date_field(label):return page.locator('label').filter(has_text=re.compile('^'+re.escape(label))).locator('input.date-input-field')
                    try:
                        page.goto(url)
                        page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        session=page.request.get(url+'/api/session').json();cid=session['active_company_id'];csrf=session['csrf_token']
                        def post(path,payload):
                            response=page.request.post(url+'/api'+path,data=payload,headers={'X-CSRF-Token':csrf})
                            assert response.ok, response.text()
                            return response.json()
                        check('Login e contexto por sessão')
                        shot('dashboard-1440.png')
                        nav('Empresas')
                        # Edit the other company without activating it.
                        company_rows=page.locator('tbody tr');other=company_rows.filter(has_not=page.locator('.badge.success')).first
                        other.get_by_role('button',name='Editar empresa',exact=False).click()
                        page.get_by_label('Nome fantasia / apelido',exact=True).fill('Outra empresa — teste de edição')
                        page.get_by_role('button',name='Salvar empresa',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        assert page.request.get(url+'/api/session').json()['active_company_id']==cid
                        check('Editar outra empresa mantém a empresa ativa')
                        nav('Cadastros auxiliares')
                        page.get_by_role('button',name='Novo cadastro',exact=True).click()
                        page.get_by_label('Código *',exact=True).fill('P-UI')
                        page.get_by_label('Nome / razão social *',exact=True).fill('Fornecedor digitado — sintético')
                        page.get_by_label('CPF/CNPJ',exact=True).fill('11222333000181')
                        fixture={'status':'ok','provider':'cnpjws','fetched_at':'2026-11-07T00:00:00+00:00','cached':False,'stale':False,'message':'Dados sintéticos de teste: revise os campos.',
                            'fields':{'name':'Fornecedor consultado — sintético','tax_id':'11222333000181','state':'SP','city':'Município de teste','cnae':'4711302','profile':{'ie_status':'registered','state_registrations':[{'state':'SP','number':'TESTE-IE1','active':True,'source':'fixture'},{'state':'BA','number':'TESTE-IE2','active':False,'source':'fixture'}]}}}
                        page.route('**/api/lookups/cnpj/**',lambda route:route.fulfill(json=fixture))
                        page.get_by_role('button',name='Consultar CNPJ',exact=True).click()
                        expect(page.get_by_text('Fornecedor consultado — sintético',exact=True)).to_be_visible()
                        expect(page.get_by_label('Nome / razão social *',exact=True)).to_have_value('Fornecedor digitado — sintético')
                        page.get_by_label('Aplicar Razão social',exact=True).check()
                        page.get_by_label('Aplicar Situação da IE',exact=True).check()
                        page.get_by_role('button',name='Aplicar campos selecionados',exact=True).click()
                        expect(page.get_by_label('Nome / razão social *',exact=True)).to_have_value('Fornecedor consultado — sintético')
                        shot('cadastro-assistido-1440.png')
                        page.get_by_role('button',name='Salvar cadastro',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        check('CNPJ: consulta simulada, comparação, aplicação seletiva e persistência de múltiplas IEs')
                        accounts=page.request.get(url+f'/api/companies/{cid}/accounts').json();aid={a['access_code']:str(a['id']) for a in accounts}
                        participants=page.request.get(url+f'/api/companies/{cid}/masters/participant').json();participant=next(p for p in participants if p['code']=='P-UI')
                        assert len(participant['data']['profile']['state_registrations'])==2
                        nav('Documentos fiscais')
                        page.get_by_role('button',name='Novo documento',exact=True).click()
                        page.get_by_label('Número *',exact=True).fill('UI001')
                        date_field('Emissão *').fill('06112026')
                        date_field('Escrituração *').fill('06112026')
                        page.get_by_label('CFOP informado',exact=True).fill('1102')
                        page.get_by_label('Total (R$) *',exact=True).fill('100,00')
                        page.get_by_label('Participante cadastrado',exact=False).select_option(str(participant['id']))
                        page.get_by_role('button',name='Salvar documento',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        row=page.locator('tbody tr').filter(has_text='UI001')
                        row.get_by_role('button',name='Conferir',exact=True).click()
                        page.get_by_label('Observação da conferência').fill('Conferência sintética de ponta a ponta')
                        page.get_by_role('button',name='Marcar como conferido',exact=True).click()
                        row.get_by_role('button',name='Escriturar',exact=True).click()
                        page.get_by_label('Observação da escrituração *',exact=True).fill('Escrituração sintética de teste')
                        page.get_by_label('Contabilizar junto com o documento',exact=False).check()
                        page.get_by_label('Conta a debitar *',exact=False).select_option(aid['3'])
                        page.get_by_label('Conta a creditar *',exact=False).select_option(aid['5'])
                        page.get_by_label('Gerar títulos financeiros vinculados',exact=False).check()
                        page.get_by_label('Quantidade de parcelas',exact=True).fill('2')
                        date_field('Primeiro vencimento').fill('10112026')
                        page.get_by_role('button',name='Distribuir mensalmente',exact=True).click()
                        shot('escrituracao-integrada-1440.png')
                        page.get_by_role('button',name='Confirmar escrituração',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        titles=page.request.get(url+f'/api/companies/{cid}/titles').json();created=[t for t in titles if t['document']=='UI001']
                        assert len(created)==2 and sum(t['amount_cents'] for t in created)==10000
                        check('Documento → conferência → contabilidade + duas parcelas em transação única')
                        nav('Financeiro')
                        page.get_by_role('textbox',name='Pesquisar títulos').fill('UI001')
                        page.locator('tbody tr').first.get_by_role('button',name='Baixar',exact=True).click()
                        date_field('Data da baixa *').fill('10112026')
                        page.get_by_label('Principal (R$) *',exact=True).fill('20,00')
                        page.get_by_label('Juros (R$)',exact=True).fill('2,00')
                        page.get_by_label('Desconto (R$)',exact=True).fill('1,00')
                        page.get_by_label('Histórico *',exact=True).fill('Baixa parcial sintética')
                        shot('baixa-parcial-1440.png')
                        page.get_by_role('button',name='Confirmar baixa',exact=True).click()
                        expect(page.get_by_role('dialog')).to_have_count(0)
                        page.locator('tbody tr').first.get_by_role('button',name='Histórico',exact=True).click()
                        date_field('Data para eventual estorno').fill('11112026')
                        page.get_by_role('button',name='Estornar baixa',exact=True).click()
                        page.get_by_label('Justificativa',exact=True).fill('Reversão sintética')
                        page.get_by_role('dialog').last.get_by_role('button',name='Estornar baixa',exact=True).click()
                        expect(page.get_by_text('Estornada em 11/11/2026',exact=False)).to_be_visible()
                        page.get_by_role('button',name='Fechar',exact=True).click()
                        check('Baixa parcial com juros/desconto e estorno pela interface')
                        nav('Importações')
                        page.locator('input[type=file]').set_input_files(str(ROOT/'tests/fixtures/extrato_ficticio.csv'))
                        page.get_by_label('Conta bancária do extrato',exact=False).fill('Banco sintético UI')
                        page.get_by_role('button',name='Analisar e gerar prévia',exact=True).click()
                        expect(page.get_by_role('button',name='Confirmar importação',exact=True)).to_be_visible()
                        shot('importacao-previa-1440.png')
                        page.get_by_role('button',name='Confirmar importação',exact=True).click()
                        page.get_by_role('button',name='Importar registros',exact=True).click()
                        expect(page.get_by_role('button',name='Abrir conciliação',exact=True)).to_be_visible()
                        assert page.request.get(url+'/api/session').json()['authenticated']
                        with page.expect_download() as download:
                            page.get_by_role('link',name='Baixar original',exact=True).click()
                        assert Path(download.value.path()).read_bytes()==(ROOT/'tests/fixtures/extrato_ficticio.csv').read_bytes()
                        check('Importação CSV pela interface preserva autenticação e confirmação')
                        nav('Livros e relatórios')
                        page.get_by_label(re.compile('^Relatório')).select_option('trial-balance')
                        page.get_by_role('button',name='Gerar relatório',exact=True).click()
                        expect(page.get_by_role('heading',name='Balancete',exact=True)).to_be_visible()
                        shot('balancete-1440.png')
                        assert page.locator('.report-output tbody tr').count()>0
                        page.locator('.report-output tbody tr .text-button').first.click()
                        expect(page.get_by_role('heading',name='Lançamento de origem',exact=True)).to_be_visible()
                        assert page.get_by_role('dialog').locator('tbody tr').count()>=2
                        page.get_by_role('button',name='Fechar',exact=True).click()
                        check('Relatório com totais e acesso às partidas de origem')
                        for width,height in [(1024,768),(390,844)]:
                            page.set_viewport_size({'width':width,'height':height})
                            assert page.evaluate('document.documentElement.scrollWidth')<=width+1,'Overflow da página'
                            shot(f'relatorios-{width}.png')
                        check('Layout em 1440, 1024 e 390 px sem transbordamento horizontal da página')
                    except Exception:
                        shot('failure.png')
                        (OUT/'failure-visible.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                        raise
                    browser.close()
                process.terminate();process.wait(timeout=15);process=None
        assert not report['console_errors'],report['console_errors']
        report['ok']=True
    except Exception as exc:
        report['error']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        if process:process.terminate();process.wait(timeout=15)
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
