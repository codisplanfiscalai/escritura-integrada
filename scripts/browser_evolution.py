"""Aceitação 0.7 no navegador real; somente dados sintéticos."""
import re
from pathlib import Path
from playwright.sync_api import expect


def run(page,browser,url,cid,csrf,nav,check,shot):
    root=Path(__file__).resolve().parents[1]
    def post(path,data):
        r=page.request.post(url+'/api'+path,data=data,headers={'X-CSRF-Token':csrf})
        assert r.ok,r.text()
        return r.json()
    def scope(path):return f'/companies/{cid}'+path
    def keyboard(field,value):
        field.focus();field.press('ControlOrMeta+A');field.press_sequentially(value)
    def date_field(label):return page.locator('label').filter(has_text=re.compile('^'+re.escape(label))).locator('input.date-input-field')
    companies=page.request.get(url+'/api/companies').json()
    company=next(c for c in companies if c['id']==cid)
    # A permissão e a sessão são exclusivamente contábeis.
    post('/users',{'username':'contabil-import-ui','password':'Senha-contabil-2026!','role':'custom','company_ids':[cid],
        'permissions':[{'company_id':cid,'routine':routine,'action':'*','effect':'allow'} for routine in ('accounting.imports','accounting.journals','accounting.accounts')]})
    for module in ('accounting','fiscal'):
        post(scope('/periods/close'),{'period':'2026-03','module':module,'reason':'Teste sintético de lote misto','version':0})
    ctx=browser.new_context(viewport={'width':1440,'height':1000})
    try:
        session=ctx.request.post(url+'/api/login',data={'username':'contabil-import-ui','password':'Senha-contabil-2026!'}).json()
        r=ctx.request.post(url+'/api/context',data={'company_id':cid,'module':'accounting','period':'2026-11'},headers={'X-CSRF-Token':session['csrf_token']});assert r.ok,r.text()
        p=ctx.new_page();p.goto(url)
        navigation=p.get_by_role('navigation',name='Navegação principal')
        expect(navigation.get_by_text('Fiscal',exact=True)).to_have_count(0)
        button=navigation.get_by_role('button',name='Importações contábeis',exact=True,include_hidden=True)
        parent=button.locator('xpath=ancestor::details')
        if parent.get_attribute('open') is None:parent.locator('summary').click()
        button.click()
        p.get_by_label('Leiaute',exact=True).select_option('journals-v1')
        csv='id;date;document;history;account;debit;credit;cost_center\n'
        for key,day in [('FEV','2026-02-01'),('MAR','2026-03-01'),('ANT','2025-12-31')]:
            csv+=f'{key};{day};CSV-UI-{key};Importação sintética;3;10.00;0;\n{key};{day};CSV-UI-{key};Importação sintética;5;0;10.00;\n'
        p.get_by_label('Arquivo CSV UTF-8',exact=True).set_input_files({'name':'contabil.csv','mimeType':'text/csv','buffer':csv.encode()})
        p.get_by_role('button',name='Gerar prévia',exact=True).click()
        expect(p.get_by_label('Selecionar registro 0')).to_be_checked()
        expect(p.get_by_label('Selecionar registro 1')).to_be_disabled()
        expect(p.get_by_label('Selecionar registro 2')).to_be_disabled()
        p.get_by_role('button',name='Confirmar selecionados',exact=True).click()
        expect(p.get_by_text('1 processados · 2 não selecionados',exact=True)).to_be_visible()
        assert ctx.request.get(url+'/api'+scope('/documents')).status==403
        assert len([j for j in ctx.request.get(url+'/api'+scope('/journals?year=2026')).json() if j['document'].startswith('CSV-UI-')])==1
        p.screenshot(path=str(root/'artifacts/browser/importacao-contabil-independente.png'),full_page=True)
    finally:ctx.close()
    check('Usuário só contábil: menu próprio, CSV com mês aberto/fechado/outro ano, seleção explícita e Fiscal recusado')
    # Teclado: rejeição conserva o formulário, salvar e novo limpa a identidade.
    nav('Lançamentos contábeis')
    page.get_by_role('button',name='Novo lançamento',exact=True).focus();page.keyboard.press('Enter')
    keyboard(date_field('Data do lançamento *'),'01032026')
    page.keyboard.press('Tab');expect(page.get_by_role('button',name='Abrir calendário',exact=True)).to_be_focused()
    page.keyboard.press('Tab');expect(page.get_by_label('Documento',exact=True)).to_be_focused()
    page.keyboard.press('Shift+Tab');expect(page.get_by_role('button',name='Abrir calendário',exact=True)).to_be_focused()
    page.keyboard.press('Tab')
    keyboard(page.get_by_label('Documento',exact=True),'TECLA-C1')
    keyboard(page.get_by_label('Histórico *',exact=True),'Lançamento por teclado')
    for line,code in [(1,'3'),(2,'5')]:
        select=page.get_by_label(f'Conta da partida {line}',exact=True);select.focus();select.press(code);select.press('Enter')
    keyboard(page.get_by_label('Débito da partida 1',exact=True),'12,34')
    keyboard(page.get_by_label('Crédito da partida 2',exact=True),'12,34')
    page.keyboard.press('Alt+s')
    expect(page.get_by_role('alert')).to_contain_text('fechada')
    expect(page.get_by_label('Documento',exact=True)).to_have_value('TECLA-C1')
    keyboard(date_field('Data do lançamento *'),'01022026')
    page.keyboard.press('Alt+n')
    expect(page.get_by_label('Documento',exact=True)).to_have_value('')
    expect(page.get_by_label('Conta da partida 1',exact=True)).to_have_value('')
    keyboard(page.get_by_label('Documento',exact=True),'TECLA-C2')
    keyboard(page.get_by_label('Histórico *',exact=True),'Segundo lançamento por teclado')
    for line,code in [(1,'3'),(2,'5')]:
        select=page.get_by_label(f'Conta da partida {line}',exact=True);select.focus();select.press(code);select.press('Enter')
    keyboard(page.get_by_label('Débito da partida 1',exact=True),'25,00')
    keyboard(page.get_by_label('Crédito da partida 2',exact=True),'25,00')
    page.keyboard.press('Alt+s');page.keyboard.press('Alt+s')
    expect(page.get_by_role('dialog')).to_have_count(0)
    actual=page.request.get(url+'/api'+scope('/journals?year=2026')).json()
    assert len([j for j in actual if j['document'].startswith('TECLA-C')])==2
    check('Contabilidade por teclado: Tab, erro de mês fechado preservado, Alt+N/Alt+S, dois lançamentos sem duplicação')
    nav('Escrituração e documentos')
    page.get_by_role('button',name='Novo documento',exact=True).focus();page.keyboard.press('Enter')
    keyboard(page.get_by_label('Número *',exact=True),'TECLA-F1')
    keyboard(date_field('Emissão *'),'31122025')
    keyboard(date_field('Escrituração *'),'01022026')
    keyboard(page.get_by_label('Total (R$) *',exact=True),'45,00')
    keyboard(page.get_by_label('Participante *',exact=True),'Participante sintético')
    page.keyboard.press('Alt+n')
    expect(page.get_by_label('Número *',exact=True)).to_have_value('')
    keyboard(page.get_by_label('Número *',exact=True),'TECLA-F2')
    keyboard(page.get_by_label('Total (R$) *',exact=True),'65,00')
    keyboard(page.get_by_label('Participante *',exact=True),'Segundo participante sintético')
    page.keyboard.press('Alt+s');page.keyboard.press('Alt+s')
    expect(page.get_by_role('dialog')).to_have_count(0)
    docs=page.request.get(url+'/api'+scope('/documents?year=2026')).json()
    assert len([d for d in docs if d['number'].startswith('TECLA-F')])==2
    assert all(d['issue_date']=='2025-12-31' for d in docs if d['number'].startswith('TECLA-F'))
    check('Fiscal por teclado: emissão anterior preservada, escrituração em fevereiro, salvar e novo sem duplicação')
    nav('Auditorias, achados e relatórios')
    before={p:page.request.get(url+'/api'+scope(p)).json() for p in ('/documents?year=2026','/titles','/journals?year=2026')}
    page.get_by_role('button',name='Auditoria avulsa',exact=True).click()
    raw=(root/'tests/fixtures/auditor_demo.xml').read_bytes().replace(b'99999999999901',company['tax_id'].encode())
    page.get_by_label('XML, PDF auxiliar ou ZIP de XML/PDF',exact=True).set_input_files({'name':'auditoria.xml','mimeType':'text/xml','buffer':raw})
    page.get_by_role('button',name='Iniciar auditoria',exact=True).click()
    expect(page.get_by_role('heading',name=re.compile(r'Auditoria #\d+ · completed'))).to_be_visible(timeout=45000)
    page.get_by_role('button',name='Relatórios',exact=True).click()
    for name,signature in [('Exportar PDF',b'%PDF'),('Exportar Excel',b'PK')]:
        with page.expect_download() as download:page.get_by_role('link',name=name,exact=True).click()
        assert Path(download.value.path()).read_bytes().startswith(signature)
    page.get_by_role('button',name='Documentos',exact=True).click()
    page.locator('.audit-finding summary').first.click()
    page.get_by_role('button',name='Gerar DANFE em Python',exact=True).click()
    expect(page.get_by_role('link',name=re.compile('DANFE gerado'))).to_be_visible()
    shot('auditor-documentos-1440.png')
    after={p:page.request.get(url+'/api'+scope(p)).json() for p in before}
    assert before==after,'Auditoria alterou a escrituração'
    page.get_by_role('button',name='Auditoria da escrituração',exact=True).click()
    page.get_by_role('button',name='Iniciar auditoria',exact=True).click()
    expect(page.get_by_role('heading',name=re.compile(r'Auditoria #\d+ · completed'))).to_be_visible(timeout=45000)
    shot('auditor-interno-1440.png')
    check('Auditor avulso/interno no mesmo login: originais, DANFE Python, PDF/Excel e ausência de efeitos na escrituração')
    nav('Arquivos e backup')
    with page.expect_download() as download:page.get_by_role('link',name='Backup integral do ambiente',exact=True).click()
    assert Path(download.value.path()).read_bytes().startswith(b'PK')
    check('Backup integral baixado pela interface administrativa')
