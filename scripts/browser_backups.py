"""Real Chromium + synthetic FastAPI + stub uploader. No cloud traffic."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='backup-browser-fixture-') as fixture:
        data = str(Path(fixture)/'data')
        keyring = Path(fixture)/'keys'; keyring.mkdir(mode=0o700)
        subprocess.run([sys.executable,'-m','app.backup_crypto','keygen',str(keyring/'primary.key')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        env={**os.environ,'ESCRITURA_DATA_DIR':data,'ESCRITURA_BACKUP_KEYRING_DIR':str(keyring),'ESCRITURA_DEMO':'0','ESCRITURA_BACKUP_FIXTURE':'{"access_token":"synthetic-only"}'}
        code="from app.api import app; import uvicorn; app.state.backups.uploader=lambda *args: {'verified':True}; uvicorn.run(app,host='127.0.0.1',port="+str(port)+",log_level='error')"
        process=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url+'/api/health',timeout=1).close();break
                except OSError:time.sleep(.1)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True,executable_path=os.environ.get('ESCRITURA_TEST_BROWSER','/usr/bin/chromium'))
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.set_default_timeout(15000)
                result=page.request.post(url+'/api/setup',data={'username':'fixture','password':'Synthetic-only-12345!'})
                assert result.ok,result.text()
                page.goto(url)
                navigation=page.get_by_role('navigation',name='Navegação principal')
                button=navigation.get_by_role('button',name='Backups remotos',exact=True,include_hidden=True)
                parent=button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None:parent.locator('summary').click()
                button.click()
                expect(page.get_by_role('heading',name='Backups remotos',exact=True)).to_be_visible()
                page.get_by_label('Referência da credencial').fill('ESCRITURA_BACKUP_FIXTURE')
                for provider in ('drive','s3','minio','dropbox'):
                    page.get_by_label('Provedor',exact=True).select_option(provider)
                    if provider=='drive':expect(page.get_by_label('ID da pasta Drive')).to_be_visible()
                    if provider in ('s3','minio'):expect(page.get_by_label('Bucket',exact=True)).to_be_visible()
                    if provider=='minio':expect(page.get_by_label('Endpoint HTTPS')).to_be_visible()
                page.get_by_label('Agendamento ativo').check()
                page.get_by_role('button',name='Salvar configuração',exact=True).click()
                expect(page.get_by_text('Agendamento desativado',exact=False)).to_have_count(0)
                page.get_by_role('button',name='Executar backup agora',exact=True).click()
                page.get_by_role('dialog').get_by_role('button',name='Voltar',exact=True).click()
                expect(page.get_by_text('Nenhum backup registrado.',exact=True)).to_be_visible()
                page.get_by_role('button',name='Executar backup agora',exact=True).click()
                page.get_by_role('dialog').get_by_role('button',name='Executar backup',exact=True).click()
                expect(page.get_by_text('Enviado e verificado',exact=True)).to_be_visible(timeout=25000)
                page.get_by_role('button',name='Validar e extrair cópia isolada',exact=True).click()
                page.get_by_role('dialog').get_by_role('button',name='Validar e extrair',exact=True).click()
                expect(page.get_by_text('Cópia validada em',exact=False)).to_be_visible()
                page.get_by_role('button',name='Validar e extrair cópia isolada',exact=True).click()
                page.get_by_role('dialog').get_by_role('button',name='Validar e extrair',exact=True).click()
                expect(page.get_by_role('alert')).to_contain_text('já existe')
                page.set_viewport_size({'width':390,'height':844})
                expect(page.get_by_role('heading',name='Backups remotos',exact=True)).to_be_visible()
                assert not errors,errors
                browser.close()
                print(json.dumps({'ok':True,'checks':['four provider forms','save schedule','cancel confirmation','manual backup','isolated restore','restore repetition refused','mobile layout','no JS errors']}))
        finally:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
