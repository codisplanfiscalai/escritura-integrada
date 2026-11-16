"""Diagnose PDF endpoint versus browser viewer capability with synthetic demo data only."""
import io
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urljoin, urlsplit
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='pdf-probe-synthetic-') as data:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        env={**os.environ,'ESCRITURA_DATA_DIR':data,'ESCRITURA_DEMO':'1'}
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(url+'/api/health',timeout=1).close();break
                except OSError:time.sleep(.1)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('ESCRITURA_TEST_BROWSER','/usr/bin/chromium'))
                page=browser.new_page()
                assert page.request.post(url+'/api/demo-login',data={}).ok
                page.goto(url)
                nav=page.get_by_role('navigation',name='Navegação principal')
                button=nav.get_by_role('button',name='Livros e relatórios fiscais',exact=True,include_hidden=True)
                parent=button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                button.click()
                page.get_by_label(re.compile('^Relatório')).select_option('fiscal-documents')
                page.get_by_role('button',name='Gerar relatório',exact=True).click()
                page.get_by_role('button',name='Visualizar PDF',exact=True).click()
                preview=page.get_by_role('region',name='Prévia do relatório',exact=True)
                link=preview.get_by_role('link',name='Abrir PDF / imprimir',exact=True)
                response=page.request.get(urljoin(url,link.get_attribute('href')))
                content=response.body()
                report={'endpoint_status':response.status,'content_type':response.headers.get('content-type'),
                        'disposition':response.headers.get('content-disposition','').split(';')[0],
                        'pdf_pages':len(PdfReader(io.BytesIO(content)).pages),
                        'pdf_viewer_enabled':page.evaluate('navigator.pdfViewerEnabled === true'),'browser':browser.version,
                        'events':[]}
                def opened(popup):
                    popup.on('download',lambda _:report['events'].append({'download':True}))
                    popup.on('domcontentloaded',lambda:report['events'].append({'domcontentloaded':True}))
                    popup.on('requestfailed',lambda request:report['events'].append({'request_failed':request.failure}))
                page.context.on('page',opened)
                with page.expect_popup() as info:link.click()
                popup=info.value
                # Bounded observation window is diagnostic, not a pass assertion for the viewer.
                page.wait_for_timeout(3000)
                report['popup_path']=urlsplit(popup.url).path
                report['popup_closed']=popup.is_closed()
                report['pdf_endpoint_valid']=response.ok and content.startswith(b'%PDF') and report['pdf_pages']>0
                print(json.dumps(report,indent=2))
                browser.close()
        finally:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
