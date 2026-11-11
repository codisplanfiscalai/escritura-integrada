"""Chromium acceptance of import revisions; synthetic temporary installation only."""
from pathlib import Path
import io, json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, zipfile
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/browser-import-review'

def check_book_cancellation(page, url, scope, report):
    """Exercise the actual form and read back only this temporary synthetic DB."""
    from openpyxl import load_workbook
    from pypdf import PdfReader
    def read(path):
        response = page.request.get(url + scope + path)
        assert response.ok, response.text()
        return response.json()
    before_titles = read('/titles')
    before_journals = read('/journals')
    nav = page.get_by_role('navigation', name='Navegação principal')
    button = nav.get_by_role('button', name='Escrituração e documentos', exact=True, include_hidden=True)
    parent = button.locator('xpath=ancestor::details')
    if parent.count() and parent.get_attribute('open') is None: parent.locator('summary').click()
    button.click()
    page.get_by_role('button', name='Novo documento', exact=True).click()
    dialog = page.get_by_role('dialog', name='Novo documento fiscal', exact=True)
    toggle = dialog.get_by_label('Registrar documento cancelado conforme livro fiscal validado')
    toggle.check()
    dialog.get_by_label('Fonte do livro e página *', exact=True).fill('Livro sintético UI, página 1')
    dialog.get_by_role('button', name='Cancelar', exact=True).click()
    page.get_by_role('dialog', name='Descartar edição?', exact=True).get_by_role('button', name='Descartar', exact=True).click()
    expect(dialog).to_have_count(0)
    page.get_by_role('button', name='Novo documento', exact=True).click()
    expect(toggle).not_to_be_checked()
    toggle.check()
    dialog.get_by_label('Fonte do livro e página *', exact=True).fill('Livro sintético UI, página 1')
    dialog.get_by_label('Responsável pela validação *', exact=True).fill('Revisor sintético UI')
    dialog.get_by_label('Motivo / evidência *', exact=True).fill('Cancelada no período sintético conferido')
    dialog.get_by_role('combobox', name='Operação', exact=True).select_option('outgoing')
    for label in ('Emissão *', 'Escrituração *'):
        field=dialog.locator('label').filter(has_text=re.compile('^'+re.escape(label))).locator('input.date-input-field')
        field.fill('06112026'); field.press('Tab')
        expect(field).to_have_value('06/11/2026')
    dialog.get_by_label('Número *', exact=True).fill('90299')
    dialog.get_by_label('Série', exact=True).fill('003')
    dialog.get_by_label('Participante *', exact=True).fill('Participante sintético UI')
    dialog.get_by_label('CFOP informado', exact=True).fill('5102')
    expect(dialog.get_by_label('Total (R$) *', exact=True)).to_be_disabled()
    expect(dialog.get_by_label('Total (R$) *', exact=True)).to_have_value('0.00')
    dialog.get_by_role('button', name='Salvar documento', exact=True).click()
    expect(dialog).to_have_count(0)
    row = page.get_by_role('row').filter(has=page.get_by_text('90299', exact=True))
    expect(row.get_by_text('Cancelado conforme livro validado', exact=True)).to_be_visible()
    row.get_by_role('button', name='Ver documento 90299', exact=True).click()
    consult = page.get_by_role('dialog', name='Consultar documento fiscal', exact=True)
    expect(consult.get_by_label('Número *', exact=True)).to_be_disabled()
    expect(consult.get_by_role('button', name='Salvar documento', exact=True)).to_have_count(0)
    consult.get_by_role('button', name='Fechar', exact=True).click()
    row.get_by_role('button', name='Marcar conferido', exact=True).click()
    review = page.get_by_role('dialog', name='Registrar conferência', exact=True)
    review.get_by_label('Observação da conferência', exact=True).fill('Conferência sintética UI do livro')
    review.get_by_role('button', name='Marcar como conferido', exact=True).click()
    expect(row.get_by_text('Conferido', exact=True)).to_be_visible()
    row.get_by_role('button', name='Escriturar', exact=True).click()
    book = page.get_by_role('dialog', name='Escriturar documento', exact=True)
    expect(book.get_by_label('Gerar títulos financeiros vinculados')).to_have_count(0)
    expect(book.get_by_label('Contabilizar junto com o documento')).to_have_count(0)
    book.get_by_label('Observação da escrituração *', exact=True).fill('Registro sintético de linha cancelada')
    book.get_by_role('button', name='Cancelar', exact=True).click()
    page.get_by_role('dialog', name='Descartar escrituração?', exact=True).get_by_role('button', name='Descartar', exact=True).click()
    expect(book).to_have_count(0)
    expect(row.get_by_text('Conferido', exact=True)).to_be_visible()
    row.get_by_role('button', name='Escriturar', exact=True).click()
    book.get_by_label('Observação da escrituração *', exact=True).fill('Registro sintético de linha cancelada')
    book.get_by_role('button', name='Escriturar documento', exact=True).click()
    expect(book).to_have_count(0)
    expect(row.get_by_text('Escriturado', exact=True)).to_be_visible()
    page.get_by_label('Filtrar estado fiscal', exact=True).select_option('cancelled')
    expect(page.locator('tbody tr')).to_have_count(1)
    expect(row.get_by_text('R$ 0,00', exact=True)).to_be_visible()
    export_link = page.get_by_role('link', name='Exportar Excel (1)', exact=True)
    export = page.request.get(url + export_link.get_attribute('href'))
    assert export.ok and export.body().startswith(b'PK'), export.text()
    doc = next(d for d in read('/documents?year=2026') if d['number']=='90299')
    assert doc['issue_date']=='2026-11-06' and doc['posting_date']=='2026-11-06'
    assert doc['status']=='booked' and doc['document_state']=='cancelled' and doc['total_cents']==0
    assert doc['source']['type']=='validated_fiscal_book' and 'authorization' not in doc
    assert doc['book_cancellation']['source']=='Livro sintético UI, página 1'
    trace = read(f"/documents/{doc['id']}/trace")
    assert trace['titles']==[] and trace['journals']==[]
    assert read('/titles')==before_titles and read('/journals')==before_journals
    endpoint='/business-reports/fiscal-outputs?start=2026-11-01&end=2026-11-30&status=cancelled'
    result=read(endpoint)
    assert len(result['rows'])==1 and result['totals']['total_cents']==0
    line=result['rows'][0]
    assert line['document_id']==doc['id'] and line['cancellation_source']=='Livro sintético UI, página 1'
    for key in ('total_cents','book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents'):
        assert line[key]==0, (key,line[key])
    pdf=page.request.get(url+scope+endpoint+'&format=pdf')
    assert pdf.ok and pdf.body().startswith(b'%PDF')
    text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.body())).pages)
    assert 'Canceladas conforme livro validado' in text and 'Livro sintético UI' in text
    xlsx=page.request.get(url+scope+endpoint+'&format=xlsx')
    assert xlsx.ok
    sheet=load_workbook(io.BytesIO(xlsx.body()))['Dados']
    assert 'Estado documental' in [c.value for c in sheet[1]]
    assert 'Livro sintético UI, página 1' in [c.value for r in sheet for c in r]
    page.screenshot(path=str(OUT/'cancelled-book.png'), full_page=True)
    report['checks'].append('Validated-book cancellation: discard/reopen, immutable record, review/book, zero filtered row, PDF/XLSX provenance, no journals or titles')

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'checks': [], 'console_errors': []}
    with tempfile.TemporaryDirectory(prefix='escritura-import-ui-') as folder:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        log = (OUT/'server.log').open('w')
        process = subprocess.Popen([sys.executable, 'scripts/run_preview.py', '--port', str(port)], cwd=ROOT,
            env=dict(os.environ, ESCRITURA_DATA_DIR=folder, ESCRITURA_DEMO='1'), stdout=log, stderr=log)
        try:
            for _ in range(100):
                try: urllib.request.urlopen(url+'/api/health', timeout=1).close(); break
                except OSError: time.sleep(.2)
            else: raise RuntimeError('Preview unavailable')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, **({'executable_path': os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                page.set_default_timeout(15000)
                page.on('pageerror', lambda e: report['console_errors'].append(str(e)))
                page.goto(url)
                page.get_by_role('button', name='Entrar na demonstração').click()
                expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
                session = page.request.get(url+'/api/session').json(); cid = session['active_company_id']
                scope = f'/api/companies/{cid}'
                # This acceptance suite explicitly exercises the optional extra
                # confirmation and cancellation flows, not the default UX.
                settings_response = page.request.get(url+scope+'/operational-settings')
                assert settings_response.ok, settings_response.text()
                settings = settings_response.json()
                configured = dict(settings['settings'], require_extra_confirmations=True)
                saved = page.request.put(url+scope+'/operational-settings', data={
                    'version': settings['version'], 'settings': configured},
                    headers={'X-CSRF-Token': session['csrf_token']})
                assert saved.ok, saved.text()
                assert saved.json()['settings'] == configured
                assert saved.json()['version'] == settings['version'] + 1
                with page.expect_response(url+'/api/session') as refreshed:
                    page.reload()
                assert refreshed.value.ok, refreshed.value.text()
                assert refreshed.value.json()['operational_settings']['require_extra_confirmations'] is True
                expect(page.get_by_role('navigation', name='Navegação principal')).to_be_visible()
                report['checks'].append('Optional extra confirmations enabled through versioned company settings; remaining rules preserved and session reloaded')
                company = next(c for c in page.request.get(url+'/api/companies').json() if c['id']==cid)
                # Complete printable synthetic fixture; production marker enables
                # direct-booking checks but does not turn this into a real XML.
                raw = (ROOT/'tests/fixtures/auditor_demo.xml').read_bytes().replace(b'99999999000191', company['tax_id'].encode()).replace(b'<tpAmb>2</tpAmb>', b'<tpAmb>1</tpAmb>')
                raw = raw.replace(b'<CPF>11111111111</CPF>', b'<CNPJ>11222333000181</CNPJ>')
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('nota.xml', raw); archive.writestr('danfe.pdf', b'%PDF-1.4\nSynthetic accessory\n%%EOF')
                nav = page.get_by_role('navigation', name='Navegação principal')
                button = nav.get_by_role('button', name='Importações fiscais', exact=True, include_hidden=True)
                parent = button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None: parent.locator('summary').click()
                button.click()
                expect(page.get_by_role('heading', name='Importações fiscais', exact=True)).to_be_visible()
                # Main action fits on a laptop without unrelated bank settings.
                page.set_viewport_size({'width':1920,'height':1000})
                page.screenshot(path=str(OUT/'import-start-1920x1000.png'), full_page=True)
                page.set_viewport_size({'width':1366,'height':768})
                expect(page.get_by_label('Conta bancária do extrato', exact=False)).to_have_count(0)
                expect(page.locator('.import-history')).not_to_be_visible()
                action = page.get_by_role('button', name='Analisar e gerar prévia', exact=True)
                expect(action).to_be_disabled()
                bounds = action.bounding_box()
                assert bounds and bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= 768, bounds
                page.screenshot(path=str(OUT/'import-start-1366x768.png'), full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(OUT/'import-start-390.png'), full_page=True)
                page.set_viewport_size({'width':1600,'height':1000})
                page.get_by_label('Selecionar arquivo de importação').set_input_files({'name':'lote-sintetico.zip','mimeType':'application/zip','buffer':output.getvalue()})
                expect(action).to_be_enabled()
                page.get_by_role('button', name='Opções avançadas de leitura', exact=False).click()
                expect(page.get_by_text('CSV bancário:', exact=False)).to_have_count(0)
                page.get_by_role('button', name='Opções avançadas de leitura', exact=False).click()
                report['checks'].append('Compact fiscal start at 1366x768 and 390px, primary action visible, bank controls absent')
                page.get_by_role('button', name='Analisar e gerar prévia', exact=True).click()
                expect(page.get_by_label('Data de escrituração do documento 1', exact=True)).to_be_visible()
                expect(page.get_by_label('Confirmar importação', exact=True)).to_be_enabled()
                expect(page.locator('.upload-panel')).to_have_count(0)
                expect(page.locator('.import-optional').first).not_to_have_attribute('open', '')
                assert not page.get_by_text('FORMAT_UNSUPPORTED', exact=True).count()
                report['checks'].append('ZIP XML+PDF reaches review without unsupported-format error')
                page.get_by_role('button', name='Visualizar DANFE', exact=True).click()
                expect(page.get_by_role('heading', name='DANFE · documento 1', exact=True)).to_be_visible()
                pdf_url = page.get_by_role('link', name='Abrir PDF / imprimir', exact=True).get_attribute('href')
                response = page.request.get(url+pdf_url)
                assert response.ok and response.body().startswith(b'%PDF'), response.text()
                page.screenshot(path=str(OUT/'danfe-preview.png'), full_page=True)
                page.get_by_role('button', name='Fechar prévia', exact=True).click()
                expect(page.get_by_role('heading', name='DANFE · documento 1', exact=True)).to_have_count(0)
                report['checks'].append('Real PDF generation and close preserve import review')
                date = page.get_by_label('Data de escrituração do documento 1', exact=True)
                date.fill('16112026'); date.press('Tab')
                page.get_by_label('CFOP do documento 1', exact=True).fill('5102')
                expect(page.get_by_label('Confirmar importação', exact=True)).to_be_disabled()
                page.get_by_role('button', name='Validar revisão e selecionar aptos', exact=True).click()
                expect(page.get_by_label('Confirmar importação', exact=True)).to_be_enabled()
                page.screenshot(path=str(OUT/'review-ready.png'), full_page=True)
                report['checks'].append('Editing date/CFOP invalidates preparation; explicit validation enables confirmation')
                page.get_by_role('button', name='Nova importação', exact=True).click()
                page.get_by_role('dialog', name='Deixar esta conferência?', exact=True).get_by_role('button', name='Voltar', exact=True).click()
                expect(date).to_have_value('16/11/2026')
                before_cancel = page.request.get(url+scope+'/documents?year=2026')
                assert before_cancel.ok, before_cancel.text()
                before_cancel = before_cancel.json()
                page.get_by_label('Confirmar importação', exact=True).click()
                page.get_by_role('dialog', name='Confirmar importação?', exact=True).get_by_role('button', name='Voltar', exact=True).click()
                expect(date).to_have_value('16/11/2026')
                assert page.request.get(url+scope+'/documents?year=2026').json() == before_cancel
                page.get_by_label('Confirmar importação', exact=True).click()
                page.get_by_role('dialog').get_by_role('button', name='Importar registros', exact=True).click()
                expect(page.get_by_text('Importação confirmada', exact=True)).to_be_visible()
                docs = page.request.get(url+scope+'/documents?year=2026').json()
                doc = next(d for d in docs if d['key']=='99999999999999999999999999999999999999999999')
                assert doc['posting_date']=='2026-11-16' and doc['issue_date']=='2026-01-15'
                assert doc['items'][0]['master_id'] and doc['participant_id']
                page.screenshot(path=str(OUT/'confirmed.png'), full_page=True)
                report['checks'].append('Cancel preserves revision; confirm books edited date and links participant/product')
                page.get_by_role('button', name='Nova importação', exact=True).click()
                expect(page.get_by_label('Selecionar arquivo de importação')).to_have_count(1)
                expect(page.get_by_role('button', name='Analisar e gerar prévia', exact=True)).to_be_disabled()
                page.get_by_role('button', name=re.compile(r'^Histórico de arquivos')).click()
                page.get_by_label('Buscar arquivo no histórico', exact=True).fill('lote-sintetico')
                page.locator('.history-list > button').filter(has_text='lote-sintetico.zip').click()
                expect(page.get_by_text('Importação confirmada', exact=True)).to_be_visible()
                expect(page.locator('.import-history')).not_to_be_visible()
                report['checks'].append('New-import cancellation preserves edits; completed reset and history resume preserve confirmation')
                check_book_cancellation(page, url, scope, report)
                assert not report['console_errors'], report['console_errors']
                report['ok'] = True
                browser.close()
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            process.terminate(); process.wait(timeout=15); log.close()
            (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
if __name__=='__main__': main()
