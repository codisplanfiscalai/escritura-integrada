"""Fiscal batch posting and later correction, through the real Vue interface."""
from pathlib import Path
import re
from playwright.sync_api import expect


def run(page, url, cid, nav, check, shot):
    root = Path(__file__).resolve().parents[1]
    company = next(c for c in page.request.get(url+'/api/companies').json() if c['id'] == cid)
    before_journals = len(page.request.get(url+f'/api/companies/{cid}/journals?year=2026').json())
    before_titles = len(page.request.get(url+f'/api/companies/{cid}/titles').json())
    nav('CFOP e associações')
    page.get_by_role('textbox', name='Pesquisar CFOP').fill('1102')
    official_rows = page.get_by_role('table', name='Referência oficial de CFOP', exact=True).locator('tbody tr')
    expect(official_rows).to_have_count(1)
    expect(official_rows.first).to_contain_text('Compra para comercialização')
    page.get_by_role('button', name='Nota explicativa', exact=True).click()
    expect(page.get_by_role('dialog')).to_contain_text('compras de mercadorias para serem comercializadas')
    page.keyboard.press('Escape')
    page.set_viewport_size({'width':1440, 'height':768});shot('cfop-1440x768.png')
    page.set_viewport_size({'width':390, 'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    shot('cfop-390.png');page.set_viewport_size({'width':1440, 'height':1000})
    page.get_by_role('button', name='Carga de referência', exact=True).click()
    with page.expect_response('**/cfop-source-loads/preview') as prepared:
        page.get_by_label('Selecionar carga CFOP JSON', exact=True).set_input_files(root/'app/data/cfop-carga-tabcfop-20261109.json')
    assert prepared.value.ok
    expect(page.get_by_role('button', name='Importar carga na empresa', exact=True)).to_be_enabled()
    page.get_by_label('Pesquisar registros da carga CFOP', exact=True).fill('1102')
    page.get_by_role('button', name='Ver parâmetros 1102', exact=True).click()
    expect(page.get_by_role('dialog')).to_contain_text('Desativada · parâmetros a revisar')
    expect(page.get_by_role('dialog')).to_contain_text('Não informada na origem')
    shot('cfop-parametros-origem-1440.png');page.keyboard.press('Escape')
    page.get_by_role('button', name='Importar carga na empresa', exact=True).click()
    page.get_by_label('Motivo da carga', exact=True).fill('Importação de referência para teste, sem ativar regras tributárias')
    page.get_by_role('button', name='Importar carga', exact=True).click()
    expect(page.get_by_role('button', name='Carga já importada nesta empresa', exact=True)).to_be_disabled()
    loads=page.request.get(url+f'/api/companies/{cid}/cfop-source-loads').json()
    assert len(loads)==1 and loads[0]['comparison']['record_count']==779 and not loads[0]['parameters_active']
    page.get_by_label('Cargas preservadas nesta empresa', exact=True).select_option(str(loads[0]['id']))
    page.get_by_label('Pesquisar registros da carga CFOP', exact=True).fill('111')
    expect(page.get_by_role('button', name='Ver parâmetros 111', exact=True)).to_be_visible()
    shot('cfop-carga-importada-1440.png')
    page.set_viewport_size({'width':390, 'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    shot('cfop-carga-390.png');page.set_viewport_size({'width':1440,'height':1000})
    check('Carga CFOP: JSON com 779 registros, parâmetros preservados sem ativação, tabela oficial completada sem sobrepor cadastros e consulta dos códigos antigos')
    page.get_by_role('button', name='Associações de importação', exact=True).click()
    page.get_by_role('button', name='Nova associação', exact=True).click()
    page.get_by_label('CFOP da origem *', exact=True).fill('5102')
    page.get_by_label('CFOP de escrituração *', exact=True).fill('1102')
    page.locator('label').filter(has_text=re.compile(r'^Início da vigência')).locator('input.date-input-field').fill('01012026')
    page.get_by_label('Fundamento da associação *', exact=True).fill('Associação sintética de teste, sem enquadramento tributário real')
    page.get_by_role('button', name='Salvar associação', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    expect(page.get_by_role('table', name='Associações de CFOP desta empresa', exact=True).locator('tbody tr')).to_contain_text('5102 → 1102')
    shot('cfop-associacao-1440.png')
    nav('Importações fiscais')
    raw = (root/'tests/fixtures/nfe_ficticia.xml').read_bytes().replace(b'12345678000195', company['tax_id'].encode())
    raw = raw.replace(b'35261187654321000198550010000000421000000420', b'8'*44).replace(b'<nNF>42</nNF>', b'<nNF>84008</nNF>').replace(b'<tpAmb>2</tpAmb>', b'<tpAmb>1</tpAmb>')
    raw = raw.replace(b'2026-11-05T10:30:00', b'2026-04-05T10:30:00')  # November is finalized by an earlier gate.
    def upload(name):
        page.get_by_label('Selecionar arquivo de importação', exact=True).set_input_files({'name':name, 'mimeType':'text/xml', 'buffer':raw})
        page.get_by_role('button', name='Analisar e gerar prévia', exact=True).click()
        # Issue-date fallback is only a proposal for purchases, not proof of receipt.
        expect(page.get_by_label('Selecionar documento 84008', exact=True)).not_to_be_checked()
        page.get_by_label('Confirmei a entrada/competência', exact=True).check()
        page.get_by_role('button', name='Validar revisão e selecionar aptos', exact=True).click()
        expect(page.get_by_label('Selecionar documento 84008', exact=True)).to_be_checked()
        expect(page.get_by_role('combobox', name='Modo de escrituração da importação', exact=True)).to_have_value('book')
        expect(page.get_by_text('Pronto para escrituração fiscal direta', exact=False)).to_be_visible()
        page.get_by_role('button', name='Confirmar importação', exact=True).click()
        page.get_by_role('button', name='Importar registros', exact=True).click()
        expect(page.get_by_role('button', name='Abrir escrituração', exact=True)).to_be_visible()
    upload('nfe-direta-sintetica.xml')
    shot('fiscal-importacao-escriturada-1440.png')
    page.get_by_role('button', name='Abrir escrituração', exact=True).click()
    page.get_by_label('Competência da consulta', exact=True).select_option('')
    page.get_by_role('textbox', name='Pesquisar documentos', exact=True).fill('84008')
    row = page.locator('tbody tr').filter(has_text='84008')
    expect(row).to_contain_text('Escriturado')
    row.get_by_role('button', name='Editar documento 84008', exact=True).click()
    page.get_by_label('Motivo da alteração da escrituração *', exact=True).fill('Correção sintética posterior, com origem preservada')
    page.get_by_label('CFOP informado', exact=True).fill('1101')
    page.get_by_role('button', name='Itens e tributos', exact=True).click()
    page.get_by_label('CFOP do item 1', exact=True).fill('1101')
    page.set_viewport_size({'width':1440, 'height':768});shot('fiscal-edicao-escriturada-1440x768.png')
    page.get_by_role('button', name='Salvar documento', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    expect(row).to_contain_text('1101');expect(row).to_contain_text('Escriturado')
    page.set_viewport_size({'width':1440, 'height':1000})
    rows = page.request.get(url+f'/api/companies/{cid}/documents?year=2026').json()
    doc = next(d for d in rows if d['number']=='84008')
    assert doc['items'][0]['source_cfop']=='5102' and doc['items'][0]['cfop']=='1101'
    assert doc['import_posting']['review_pending'] and doc['reviewed_by'] is None
    assert len(page.request.get(url+f'/api/companies/{cid}/journals?year=2026').json())==before_journals
    assert len(page.request.get(url+f'/api/companies/{cid}/titles').json())==before_titles
    nav('Importações fiscais');upload('mesmo-xml-sintetico-renomeado.xml')
    page.get_by_role('button', name='Abrir escrituração', exact=True).click()
    row = page.locator('tbody tr').filter(has_text='84008')
    expect(row).to_have_count(1);expect(row).to_contain_text('1101')
    row.get_by_role('button', name='Conferir', exact=True).click()
    page.get_by_label('Observação da conferência', exact=True).fill('Conferência sintética da correção')
    page.get_by_role('button', name='Marcar como conferido', exact=True).click()
    expect(row.get_by_role('button', name='Conferir', exact=True)).to_have_count(0)
    shot('fiscal-escrituracao-editavel-1440.png')
    check('Fiscal: CFOP oficial e associação por empresa; XML importado já escriturado, edição motivada, reimportação sem desfazer correções e conferência posterior, sem títulos/partidas implícitos')
    _purchase_payables(page, url, cid, nav, check, shot, company)


def _purchase_payables(page, url, cid, nav, check, shot, company):
    """Explicit source billing and optional purchase terms in the real UI."""
    root = Path(__file__).resolve().parents[1]
    scope = url + f'/api/companies/{cid}'
    original = (root/'tests/fixtures/nfe_ficticia.xml').read_bytes()
    original = original.replace(b'12345678000195', company['tax_id'].encode())
    original = original.replace(b'<tpAmb>2</tpAmb>', b'<tpAmb>1</tpAmb>')
    original = original.replace(b'2026-11-05T10:30:00', b'2026-04-05T10:30:00')
    initial_journals = page.request.get(scope+'/journals?year=2026').json()

    def source(number, billing):
        raw = original.replace(b'<nNF>42</nNF>', f'<nNF>{number}</nNF>'.encode())
        raw = raw.replace(b'35261187654321000198550010000000421000000420', (f'7{number:043d}').encode())
        if not billing:
            start, end = raw.index(b'<cobr>'), raw.index(b'</cobr>') + len(b'</cobr>')
            raw = raw[:start] + raw[end:]
        return raw

    def imported(number):
        docs = page.request.get(scope+'/documents?year=2026').json()
        matches = [d for d in docs if d['number'] == str(number)]
        assert len(matches) == 1, matches
        return matches[0]

    def linked(document):
        return [t for t in page.request.get(scope+'/titles').json() if t['document_id'] == document['id']]

    def upload(number, billing, repeat=False):
        nav('Importações fiscais')
        raw = source(number, billing)
        page.get_by_label('Selecionar arquivo de importação', exact=True).set_input_files({
            'name': f'compra-{number}-{"repetida" if repeat else "nova"}.xml',
            'mimeType': 'text/xml', 'buffer': raw})
        page.get_by_role('button', name='Analisar e gerar prévia', exact=True).click()
        select = page.get_by_label(f'Selecionar documento {number}', exact=True)
        expect(select).not_to_be_checked()
        page.get_by_label('Confirmei a entrada/competência', exact=True).check()
        expect(page.get_by_label('Gerar contas a pagar das parcelas do XML', exact=True)).not_to_be_checked()
        if billing:
            page.get_by_label('Gerar contas a pagar das parcelas do XML', exact=True).check()
        else:
            page.get_by_label('Gerar uma parcela por compra sem cobrança no XML', exact=True).check()
            expect(page.get_by_label('Prazo em dias', exact=True)).to_have_value('30')
            expect(page.get_by_label('Base do vencimento', exact=True)).to_have_value('')
            page.get_by_label('Base do vencimento', exact=True).select_option('receipt')
            page.get_by_label('Responsável', exact=True).fill('Operador sintético')
            page.get_by_label('Motivo / referência', exact=True).fill('Condição sintética de compra, sem pagamento')
            page.get_by_label('Gerar uma parcela para esta compra sem cobrança', exact=True).check()
            page.get_by_role('button', name='Validar revisão e selecionar aptos', exact=True).click()
            expect(page.get_by_role('button', name='Confirmar importação', exact=True)).to_be_disabled()
        arrival = page.get_by_label(f'Entrada efetiva do documento {number}', exact=True)
        arrival.fill('10042026'); arrival.press('Tab')
        posting = page.get_by_label(f'Data de escrituração do documento {number}', exact=True)
        posting.fill('11042026'); posting.press('Tab')
        page.get_by_role('button', name='Validar revisão e selecionar aptos', exact=True).click()
        expect(select).to_be_checked()
        confirm = page.get_by_role('button', name='Confirmar importação', exact=True)
        expect(confirm).to_be_enabled()
        if not billing:
            expect(page.get_by_role('heading', name='Parcela proposta pela regra do usuário (não consta no XML)', exact=True)).to_be_visible()
            if not repeat:
                shot('fiscal-parcela-opcional-revisada-1440.png')
                confirm.click()
                page.get_by_role('dialog', name='Confirmar importação?', exact=True).get_by_role('button', name='Voltar', exact=True).click()
                expect(arrival).to_have_value('10/04/2026')
                expect(page.get_by_label('Base do vencimento', exact=True)).to_have_value('receipt')
        confirm.click()
        page.get_by_role('dialog').get_by_role('button', name='Importar registros', exact=True).click()
        expect(page.get_by_role('button', name='Abrir escrituração', exact=True)).to_be_visible()
        return imported(number)

    billed = upload(84009, True)
    xml_titles = linked(billed)
    assert len(xml_titles) == 1 and xml_titles[0]['document'] == '001'
    assert xml_titles[0]['due_date'] == '2026-12-05' and xml_titles[0]['amount_cents'] == 10000
    assert not xml_titles[0]['settlements']
    assert billed['issue_date'] == '2026-04-05' and billed['receipt_date'] == '2026-04-10' and billed['posting_date'] == '2026-04-11'
    assert linked(upload(84009, True, repeat=True)) == xml_titles

    generated = upload(84010, False)
    generated_titles = linked(generated)
    assert len(generated_titles) == 1
    assert generated_titles[0]['due_date'] == '2026-05-10' and generated_titles[0]['amount_cents'] == 10000
    assert generated_titles[0]['source_key'] == f"generated-billing:{generated['id']}:single"
    assert not generated_titles[0]['settlements']
    assert generated['generated_payment_terms']['date_basis'] == 'receipt'
    assert linked(upload(84010, False, repeat=True)) == generated_titles

    nav('Escrituração e documentos')
    page.get_by_label('Competência da consulta', exact=True).select_option('')
    page.get_by_role('textbox', name='Pesquisar documentos', exact=True).fill('84010')
    page.get_by_role('button', name='Editar documento 84010', exact=True).click()
    page.get_by_label('Motivo da alteração da escrituração *', exact=True).fill('Correção sintética de chegada, sem mudar a parcela')
    arrival = page.get_by_role('dialog').get_by_label('Entrada efetiva da mercadoria', exact=False)
    arrival.fill('12042026'); arrival.press('Tab')
    page.get_by_role('button', name='Salvar documento', exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    edited = imported(84010)
    assert edited['receipt_date'] == '2026-04-12' and edited['posting_date'] == '2026-04-11'
    assert edited['issue_date'] == '2026-04-05' and linked(edited) == generated_titles
    assert page.request.get(scope+'/journals?year=2026').json() == initial_journals
    shot('fiscal-compra-com-parcela-preservada-1440.png')
    check('Cobrança XML e parcela opcional: consentimento explícito, falta de chegada bloqueia sem fallback, D+30 da entrada, cancelamento preservado, reimportação idempotente e edição de chegada sem alterar títulos ou criar pagamentos/partidas')
