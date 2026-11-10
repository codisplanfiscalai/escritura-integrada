"""Chromium acceptance of import revisions; synthetic temporary installation only."""
from pathlib import Path
import io, json, os, socket, subprocess, sys, tempfile, time, urllib.request, zipfile
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/browser-import-review'

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
                page.get_by_label('Selecionar arquivo de importação').set_input_files({'name':'lote-sintetico.zip','mimeType':'application/zip','buffer':output.getvalue()})
                page.get_by_role('button', name='Analisar e gerar prévia', exact=True).click()
                expect(page.get_by_label('Data de escrituração do documento 1', exact=True)).to_be_visible()
                expect(page.get_by_label('Confirmar importação', exact=True)).to_be_enabled()
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
                page.get_by_label('Confirmar importação', exact=True).click()
                page.get_by_role('dialog', name='Confirmar importação?', exact=True).get_by_role('button', name='Voltar', exact=True).click()
                expect(date).to_have_value('16/11/2026')
                page.get_by_label('Confirmar importação', exact=True).click()
                page.get_by_role('dialog').get_by_role('button', name='Importar registros', exact=True).click()
                expect(page.get_by_text('Importação confirmada', exact=True)).to_be_visible()
                docs = page.request.get(url+scope+'/documents?year=2026').json()
                doc = next(d for d in docs if d['key']=='99999999999999999999999999999999999999999999')
                assert doc['posting_date']=='2026-11-16' and doc['issue_date']=='2026-01-15'
                assert doc['items'][0]['master_id'] and doc['participant_id']
                page.screenshot(path=str(OUT/'confirmed.png'), full_page=True)
                report['checks'].append('Cancel preserves revision; confirm books edited date and links participant/product')
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
