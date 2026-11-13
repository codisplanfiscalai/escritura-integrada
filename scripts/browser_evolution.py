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
    def select_account(line,code):
        select=page.get_by_label(f'Conta da partida {line}',exact=True)
        expect(select.locator('option').filter(has_text=re.compile('^'+re.escape(code)+' ·'))).to_have_count(1)
        options=select.locator('option').all_text_contents()
        index=next(i for i,label in enumerate(options) if label.startswith(code+' ·'))
        value=select.locator('option').nth(index).get_attribute('value')
        select.focus();select.press('Home')
        for _ in range(index):select.press('ArrowDown')
        select.press('Tab');expect(select).to_have_value(value)

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
        expect(navigation).to_be_visible()
        expect(navigation.get_by_text('Fiscal',exact=True)).to_have_count(0)
        button=navigation.get_by_role('button',name='Importações contábeis',exact=True,include_hidden=True)
        parent=button.locator('xpath=ancestor::details')
        if parent.get_attribute('open') is None:parent.locator('summary').click()
        button.click()
        expect(p.get_by_role('tab',name='Importações contábeis',exact=True)).to_have_attribute('aria-selected','true')
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
    except Exception:
        p.screenshot(path=str(root/'artifacts/browser/importacao-contabil-failure.png'),full_page=True)
        (root/'artifacts/browser/importacao-contabil-failure.txt').write_text(p.locator('body').inner_text(),encoding='utf-8')
        raise
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
        select_account(line,code)
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
        select_account(line,code)
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
    from io import BytesIO
    from pypdf import PdfReader
    from openpyxl import load_workbook
    import base64
    nav('Auditorias, achados e relatórios')
    main=page.locator('.main-content')
    before={p:page.request.get(url+'/api'+scope(p)).json() for p in ('/documents?year=2026','/titles','/journals?year=2026')}
    main.get_by_role('button',name='Auditoria avulsa',exact=True).click()
    raw=(root/'tests/fixtures/auditor_demo.xml').read_bytes().replace(b'99999999000191',company['tax_id'].encode())
    main.get_by_label('Nome da auditoria',exact=True).fill('Aceitação avulsa - original preservado')
    page.get_by_label('XML, PDF auxiliar ou ZIP de XML/PDF',exact=True).set_input_files({'name':'auditoria.xml','mimeType':'text/xml','buffer':raw})
    main.get_by_role('button',name='Iniciar auditoria',exact=True).click()
    expect(main.get_by_role('heading',name=re.compile(r'Auditoria #\d+ · Concluída'))).to_be_visible(timeout=45000)
    jid=int(re.search(r'#(\d+)',main.get_by_role('heading',name=re.compile(r'Auditoria #')).inner_text())[1])
    main.get_by_role('button',name='Relatórios',exact=True).click()
    for label,fmt in [('Exportar PDF','pdf'),('Exportar Excel','xlsx')]:
        with page.expect_download() as download:main.get_by_role('link',name=label,exact=True).click()
        data=Path(download.value.path()).read_bytes()
        target=root/f'artifacts/browser/auditoria-avulsa.{fmt}';target.write_bytes(data)
        if fmt=='pdf':
            reader=PdfReader(BytesIO(data));text=' '.join(p.extract_text() for p in reader.pages)
            assert '65.000,00' in text and 'Memória de cálculo' in text and len(reader.pages)>=6
        else:
            book=load_workbook(BytesIO(data),data_only=True)
            assert book['Notas - Sintético']['I2'].value==65000
            assert book['Itens - Analítico']['F2'].value=='87032100'
    with page.expect_popup() as popup:main.get_by_role('link',name='Visualizar / imprimir PDF',exact=True).click()
    pdfpage=popup.value;pdfpage.wait_for_load_state('domcontentloaded');pdfpage.wait_for_timeout(1200);assert '/report?format=pdf&purpose=print' in pdfpage.url
    shot('auditoria-pdf-aberto.png',pdfpage)
    (root/'artifacts/browser/pdf-viewer.html').write_text(pdfpage.content())
    pdfpage.close()
    main.get_by_role('button',name='Documentos',exact=True).click()
    main.get_by_role('button',name='Inspecionar documento 1',exact=True).click()
    inspector=page.get_by_role('dialog')
    inspector.get_by_role('button',name='DANFE',exact=True).click()
    inspector.get_by_role('button',name='Gerar DANFE',exact=True).click()
    auxiliary=inspector.get_by_role('link',name='Abrir PDF auxiliar',exact=True)
    expect(auxiliary).to_be_visible()
    danfe=page.request.get(url+auxiliary.get_attribute('href')).body()
    assert len(PdfReader(BytesIO(danfe)).pages)>=1
    (root/'artifacts/browser/danfe.pdf').write_bytes(danfe)
    with page.expect_popup() as popup:auxiliary.click()
    popup.value.wait_for_load_state('domcontentloaded');popup.value.wait_for_timeout(1200);shot('auditor-danfe-aberto.png',popup.value);popup.value.close()
    inspector.get_by_role('button',name='Auditoria e memória',exact=True).click()
    expect(inspector.get_by_role('heading',name='Valores comparados',exact=True)).to_be_visible()
    expect(inspector.get_by_role('heading',name='Itens e memória de cálculo',exact=True)).to_be_visible()
    shot('auditor-documentos-1440.png')
    inspector.get_by_role('button',name='Fechar consulta',exact=True).click()
    main.get_by_role('button',name='Achados',exact=True).click()
    main.get_by_role('button',name='Registrar tratamento',exact=True).first.click()
    dialog=page.get_by_role('dialog')
    dialog.get_by_label('Situação',exact=True).select_option('reviewing')
    dialog.get_by_label('Responsável',exact=True).fill('Revisor sintético')
    dialog.get_by_label('Tratamento e evidência',exact=True).fill('Conferido sem modificar a origem fiscal.')
    dialog.get_by_role('button',name='Salvar',exact=True).click();expect(dialog).to_have_count(0)
    expect(main.get_by_text('Revisor sintético · Conferido sem modificar a origem fiscal.',exact=True)).to_be_visible()
    shot('auditor-achados-1440.png')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Auditor transbordou a página'
    shot('auditor-achados-390.png');page.set_viewport_size({'width':1440,'height':1000})
    after={p:page.request.get(url+'/api'+scope(p)).json() for p in before}
    assert before==after,'Auditoria alterou a escrituração'
    check('Avulsa: XML, processamento, itens, achado tratado, PDF/Excel abertos e numericamente conferidos; DANFE aberto; origem inalterada')
    # Importação explícita pelo Fiscal, independente da auditoria anterior.
    preview=post(scope('/imports/preview'),{'filename':'origem-auditoria.xml','content_base64':base64.b64encode(raw).decode(),'period':'2026-02','options':{'posting_date':'2026-02-15'}})
    post(scope(f"/imports/{preview['id']}/confirm"),{'preview_hash':preview['preview_hash']})
    docs=page.request.get(url+'/api'+scope('/documents?year=2026')).json()
    internal=next(d for d in docs if d['key']=='9'*44)
    before={p:page.request.get(url+'/api'+scope(p)).json() for p in before}
    main.get_by_role('button',name='Auditoria da escrituração',exact=True).click()
    main.get_by_role('button',name='Consultar documentos da escrituração',exact=True).click()
    main.get_by_role('button',name='Limpar seleção',exact=True).click()
    main.get_by_label('Selecionar documento '+internal['number'],exact=True).check()
    main.get_by_role('button',name='Iniciar auditoria',exact=True).click()
    expect(main.get_by_role('heading',name=re.compile(r'Auditoria #\d+ · Concluída'))).to_be_visible(timeout=45000)
    internal_id=int(re.search(r'#(\d+)',main.get_by_role('heading',name=re.compile(r'Auditoria #')).inner_text())[1])
    job=page.request.get(url+'/api'+scope(f'/auditor/jobs/{internal_id}')).json()
    assert job['snapshot']['input']['document_ids']==[internal['id']]
    assert job['result']['documents'][0]['bookkeeping_id']==internal['id']
    main.get_by_role('button',name='Documentos',exact=True).click();main.get_by_role('button',name='Inspecionar documento 1',exact=True).click()
    inspector=page.get_by_role('dialog');inspector.get_by_role('button',name='Auditoria e memória',exact=True).click()
    expect(inspector.get_by_role('heading',name='Valores comparados',exact=True)).to_be_visible()
    shot('auditor-interno-1440.png')
    inspector.get_by_role('button',name='Fechar consulta',exact=True).click()
    for fmt in ('pdf','xlsx'):
        data=page.request.get(url+'/api'+scope(f'/auditor/jobs/{internal_id}/report?format={fmt}')).body()
        (root/f'artifacts/browser/auditoria-interna.{fmt}').write_bytes(data)
        if fmt=='pdf':assert 'Escriturado' in ' '.join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
        else:assert 'Escrituração original' in load_workbook(BytesIO(data)).sheetnames
    assert before=={p:page.request.get(url+'/api'+scope(p)).json() for p in before}
    page.reload();nav('Auditorias, achados e relatórios')
    main.locator('tbody tr').filter(has_text=f'#{internal_id} ·').get_by_role('button',name='Abrir',exact=True).click()
    expect(main.get_by_role('heading',name=f'Auditoria #{internal_id} · Concluída',exact=True)).to_be_visible()
    assert page.request.get(url+'/api'+scope(f'/auditor/jobs/{jid}')).json()['findings'][0]['status']=='reviewing'
    check('Interna: seleção do documento importado, XML vinculado, valores originais/escriturados, PDF/Excel abertos, persistência após recarga')
    main.get_by_role('button',name='Reprocessar em novo histórico',exact=True).click()
    dialog=page.get_by_role('dialog',name='Reprocessar auditoria',exact=True)
    expect(dialog.get_by_label('Catálogo do novo processamento',exact=True)).to_have_value('')
    dialog.get_by_role('button',name='Confirmar reprocessamento',exact=True).click()
    expect(dialog).to_have_count(0)
    expect(main.get_by_role('heading',name=re.compile(r'Auditoria #\d+ · Concluída'))).to_be_visible(timeout=45000)
    reprocessed_id=int(re.search(r'#(\d+)',main.get_by_role('heading',name=re.compile(r'Auditoria #')).inner_text())[1])
    assert reprocessed_id!=internal_id
    assert page.request.get(url+'/api'+scope(f'/auditor/jobs/{reprocessed_id}')).json()['parent_id']==internal_id
    assert before=={p:page.request.get(url+'/api'+scope(p)).json() for p in before}
    check('Reprocessamento pela interface: revisão explícita do catálogo, novo histórico, origem e resultados anteriores preservados')
    main.get_by_role('button',name='Catálogos',exact=True).click()
    main.get_by_role('button',name='Importar referência 1.2.2',exact=True).click()
    page.get_by_role('dialog').get_by_role('button',name='Salvar rascunho',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0,timeout=30000)
    expect(main.get_by_text(re.compile('15638 linhas · 11096 NCMs completos'))).to_be_visible()
    main.get_by_label('Situação',exact=True).select_option('error')
    expect(main.get_by_text('Página 1 · 3 resultados',exact=True)).to_be_visible()
    expect(main.get_by_role('button',name='Publicar após revisão',exact=True)).to_be_disabled()
    shot('auditor-catalogos-1440.png')
    check('Catálogo original: 15.638 linhas recuperadas; três linhas com erros visíveis; publicação impedida até revisão')
    for mode in ('Auditoria da escrituração','Auditoria avulsa'):
        main.get_by_role('button',name=mode,exact=True).click()
        expect(main.get_by_text('Catálogo importado não é catálogo ausente.',exact=False)).to_be_visible()
        draft=main.get_by_label('Catálogo publicado',exact=True).locator('option').filter(has_text='Referência histórica Auditor 1.2.2')
        expect(draft).to_be_disabled()
        expect(draft).to_contain_text('4 erros para revisar')
        main.get_by_role('button',name='Revisar catálogo',exact=True).click()
        expect(main.get_by_role('button',name='Publicar após revisão',exact=True)).to_be_disabled()
        expect(main.get_by_text('Este catálogo está salvo como rascunho',exact=False)).to_be_visible()
    check('Avulsa e escrituração mostram catálogo importado com diagnóstico e navegam à revisão sem publicar')
    import sys
    sys.path.insert(0,str(root/'tests'))
    from auditor_samples import sample_archive
    main.get_by_role('button',name='Auditoria avulsa',exact=True).click()
    main.get_by_label('Nome da auditoria',exact=True).fill('Conferência analítica: 8 notas e 24 itens')
    main.get_by_label('XML, PDF auxiliar ou ZIP de XML/PDF',exact=True).set_input_files({'name':'amostra-comparativa.zip','mimeType':'application/zip','buffer':sample_archive(company['tax_id'])})
    main.get_by_role('button',name='Iniciar auditoria',exact=True).click()
    expect(main.get_by_role('heading',name=re.compile(r'Auditoria #\d+ · Concluída'))).to_be_visible(timeout=45000)
    expect(main.get_by_role('heading',name='Auditorias do exercício',exact=True)).to_have_count(0)
    expect(main.locator('.audit-kpis article')).to_have_count(8)
    expect(main.locator('.audit-kpis')).to_contain_text('3.528,00')
    shot('auditor-painel-1440.png')
    main.get_by_role('button',name='Análise crítica',exact=True).click()
    expect(main.get_by_role('heading',name='Como a base de IBS/CBS foi formada',exact=True)).to_be_visible()
    expect(main.get_by_text(re.compile('mesmos 24 itens efetivamente recalculados'))).to_be_visible()
    shot('auditor-analise-1440.png')
    main.get_by_role('button',name='Documentos',exact=True).click()
    expect(main.locator('.audit-documents tbody tr')).to_have_count(8)
    main.get_by_role('button',name=re.compile('^Valor NF')).click()
    expect(main.locator('.audit-documents tbody tr').first).to_contain_text('1001')
    main.get_by_role('button',name=re.compile('^Valor NF')).click()
    expect(main.locator('.audit-documents tbody tr').first).to_contain_text('1008')
    main.get_by_label('Operação',exact=True).select_option('entrada')
    expect(main.locator('.audit-documents tbody tr')).to_have_count(4)
    shot('auditor-grade-1440.png')
    open_note=main.get_by_role('button',name='Inspecionar documento 1001',exact=True)
    open_note.focus();page.keyboard.press('Enter')
    inspector=page.get_by_role('dialog');expect(inspector).to_be_visible()
    for label,heading in [('Emitente','Dados do emitente'),('Destinatário','Dados do destinatário'),('Totais','Totais declarados no XML'),('Transporte','Transporte e volumes'),('Cobrança','Fatura e cobrança'),('Informações adicionais','Informações adicionais')]:
        inspector.get_by_role('button',name=label,exact=True).click();expect(inspector.get_by_role('heading',name=heading,exact=True)).to_be_visible()
    inspector.get_by_role('button',name='XML',exact=True).click();expect(inspector.locator('.xml-view')).to_contain_text('FORNECEDOR SINTÉTICO 1')
    inspector.get_by_role('button',name='Produtos e serviços (3)',exact=True).click()
    inspector.get_by_role('button',name='Inspecionar item 2',exact=True).click()
    expect(inspector.locator('.selected-item')).to_contain_text('PRODUTO SINTÉTICO 2')
    shot('auditor-inspecao-itens-1440.png')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    shot('auditor-inspecao-390.png');page.set_viewport_size({'width':1440,'height':1000})
    page.keyboard.press('Escape');expect(inspector).to_have_count(0);expect(open_note).to_be_focused()
    main.get_by_role('button',name='Relatórios',exact=True).click()
    expect(main.locator('.report-sections article')).to_have_count(6)
    with page.expect_response(lambda r:'/report?format=pdf&purpose=print' in r.url) as preview_response:
        main.get_by_role('button',name='Prévia do relatório nesta tela',exact=True).click()
    assert preview_response.value.status==200
    assert preview_response.value.headers['x-frame-options']=='SAMEORIGIN'
    expect(main.locator('iframe[title="Prévia do Relatório Analítico e Sintético"]')).to_be_visible()
    page.wait_for_timeout(1500)
    shot('auditor-relatorios-1440.png')
    for label,fmt in [('Exportar PDF','pdf'),('Exportar Excel','xlsx')]:
        with page.expect_download() as download:main.get_by_role('link',name=label,exact=True).click()
        data=Path(download.value.path()).read_bytes();(root/f'artifacts/browser/auditoria-comparativa.{fmt}').write_bytes(data)
        if fmt=='xlsx':
            workbook=load_workbook(BytesIO(data),data_only=True)
            assert workbook.active.title=='Resumo Executivo' and workbook.active['C5'].value==3528
        else:
            text=' '.join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
            assert 'Relatório analítico das entradas' in text and 'Relatório analítico das saídas' in text
    check('Experiência original: painel, prioridades, bases, grade ordenável, filtros, inspeção por teclado em onze abas, PDF na tela e Excel executivo; 8 notas / 24 itens / R$ 3.528,00')
    nav('Arquivos e backup')
    with page.expect_download() as download:page.get_by_role('link',name='Backup integral do ambiente',exact=True).click()
    assert Path(download.value.path()).read_bytes().startswith(b'PK')
    check('Backup integral baixado pela interface administrativa')
