"""UX acceptance with real web/API/socket and synthetic preparation receipts only.

No Docker daemon, image download, installation or deployed data is used.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from playwright.sync_api import sync_playwright,expect
from docker_update_executor import Executor,Refusal,make_server

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'application-updates'
TECH=r'(?i)docker|\bimagem\b|digest|container|develop|latest|\bUID\b|\bGID\b|executor|rollback|\bcanal\b|socket|\bhost\b|cutover'


class FixtureDocker:
    def __init__(self,path):
        self.path=path;self.resolved=[];self.pulls=0
        self.pull_gate=threading.Event();self.validation_gate=threading.Event()
    def config(self):return json.loads(self.path.read_text())
    def installed(self):
        cfg=self.config();channel=cfg.get('channel')
        if cfg['mode']=='unavailable':raise Refusal('Docker fixture indisponível; conferir instalação.','docker_unavailable')
        return {'container_id':'a'*64,'image_id':'sha256:'+'b'*64,'digest':'sha256:'+'c'*64,
                'version':'0.8.0' if channel=='latest' else '0.9.0-dev.17','uid_gid':'10001:10001',
                'configured_channel':channel,'configuration_hash':hashlib.sha256(str(channel).encode()).hexdigest()}
    def resolve(self,channel):
        self.resolved.append(channel)
        return {'digest':'sha256:'+'d'*64,'platform_digest':'sha256:'+'d'*64,'image_id':'sha256:'+'e'*64,
                'version':'0.8.1' if channel=='latest' else '0.9.0-dev.18','revision':'f'*40}
    def space(self):pass
    def pull(self,target,channel):
        self.pulls+=1
        if self.config()['mode']=='failure':raise Refusal('Docker download fixture falhou; conferir digest.','fixture_download_failed')
        if not self.pull_gate.wait(90):raise Refusal('Fixture timeout.','fixture_timeout')
        return {'version':target['version'],'revision':target['revision']}


class FixtureExecutor(Executor):
    def transition(self,jid,state,plan=None,error=None):
        super().transition(jid,state,plan,error)
        if state=='validating' and not self.docker.validation_gate.wait(90):raise Refusal('Fixture timeout.')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'synthetic_only':True,'real_download_tested':False,'checks':[]}
    executor=server=thread=process=None
    with tempfile.TemporaryDirectory(prefix='application-update-ux-') as temporary:
        root=Path(temporary);config=root/'fixture.json';config.write_text(json.dumps({'channel':'develop','mode':'normal'}))
        docker=FixtureDocker(config)
        try:
            executor=FixtureExecutor(root/'ledger.sqlite3',docker)
            control=root/'control.sock';server=make_server(executor,control,os.getuid())
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            with socket.socket() as available:available.bind(('127.0.0.1',0));port=available.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            env=dict(os.environ,ESCRITURA_DATA_DIR=str(root/'web-data'),ESCRITURA_DEMO='0',ESCRITURA_UPDATE_SOCKET=str(control))
            process=subprocess.Popen([sys.executable,'-m','uvicorn','app.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(100):
                try:
                    with urllib.request.urlopen(url+'/api/health',timeout=1):break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('Synthetic web server unavailable')
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(20000)
                errors=[];requests=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r))
                page.goto(url);page.get_by_label('Usuário',exact=True).fill('synthetic-admin');page.locator('input[type=password]').fill('Synthetic-only-12345!');page.get_by_role('button',name='Criar acesso e continuar').click()
                def enter():
                    navigation=page.get_by_role('navigation',name='Navegação principal');button=navigation.get_by_role('button',name='Atualização da aplicação',exact=True,include_hidden=True)
                    expect(button).to_be_attached();group=button.locator('xpath=ancestor::details')
                    if group.count() and group.get_attribute('open') is None:group.locator('summary').click()
                    button.click();expect(page.get_by_role('heading',name='Atualização da aplicação',exact=True)).to_be_visible()
                import re
                def common():
                    text=page.locator('body').inner_text()
                    assert not re.search(TECH,text),text
                    expect(page.locator('.view select')).to_have_count(0)
                    assert page.locator('.update-diagnostics').get_attribute('open') is None
                def refresh():page.get_by_role('button',name='Conferir andamento',exact=True).click();expect(page.get_by_role('button',name='Conferir andamento',exact=True)).to_be_enabled()
                def target(version):
                    page.get_by_role('button',name='Buscar versão disponível',exact=True).click();expect(page.get_by_text('Versão encontrada:',exact=False)).to_contain_text(version);common()
                def prompt():
                    page.get_by_role('button',name='Baixar versão',exact=True).click();dialog=page.get_by_role('dialog');expect(dialog).to_be_visible();common();return dialog
                enter();expect(page.get_by_role('button',name='Buscar versão disponível',exact=True)).to_be_enabled();common()
                target('0.9.0-dev.18');prompt().get_by_role('button',name='Voltar',exact=True).click();assert docker.pulls==0
                dialog=prompt()
                with page.expect_response(lambda r:r.url.endswith('/api/docker-updates/prepare') and r.request.method=='POST'):
                    dialog.get_by_role('button',name='Confirmar download',exact=True).evaluate('(el)=>{el.click();el.click();}')
                expect(page.get_by_text('Baixando a versão solicitada…',exact=True).first).to_be_visible(timeout=30000);common()
                assert len([r for r in requests if r.url.endswith('/api/docker-updates/prepare')])==1
                docker.pull_gate.set();expect(page.get_by_text('Conferindo o download…',exact=True).first).to_be_visible(timeout=30000);common()
                docker.validation_gate.set();done='Download concluído. A versão em uso ainda não foi alterada.'
                expect(page.get_by_text(done,exact=True).first).to_be_visible(timeout=30000);common();assert docker.pulls==1
                page.screenshot(path=str(OUT/'download-1440.png'),full_page=True)
                page.reload();enter();expect(page.get_by_text(done,exact=True).first).to_be_visible();common()
                report['checks'].append('configured test source, empty request body, cancel, double click, pulling/validating/prepared and persistent reload')
                # The fixture administrator changes the existing source; the UI
                # never sends a choice or edits configuration.
                config.write_text(json.dumps({'channel':'latest','mode':'failure'}));refresh();target('0.8.1');prompt().get_by_role('button',name='Confirmar download',exact=True).click()
                failed='Não foi possível concluir o download. A versão em uso não foi alterada.'
                expect(page.get_by_text(failed,exact=True).first).to_be_visible(timeout=30000);common();assert docker.resolved[-1]=='latest'
                assert all(r.post_data_json=={} for r in requests if r.url.endswith('/api/docker-updates/check'))
                assert config.read_text()==json.dumps({'channel':'latest','mode':'failure'})
                last=executor.status()['jobs'][0]['id'];executor.transition(last,'interrupted',error='Docker fixture interrompida; conferir digest.')
                page.reload();enter();expect(page.get_by_text('O download foi interrompido.',exact=False).first).to_be_visible();common()
                report['checks'].append('configured stable source preserved without selector; failed and interrupted downloads remain honest')
                config.write_text(json.dumps({'channel':None,'mode':'normal'}));refresh();expect(page.get_by_text('A busca de versões está indisponível:',exact=False)).to_be_visible();expect(page.get_by_role('button',name='Buscar versão disponível',exact=True)).to_be_disabled();common()
                count=len(docker.resolved);page.get_by_role('button',name='Buscar versão disponível',exact=True).evaluate('(el)=>el.click()');assert len(docker.resolved)==count
                page.locator('.update-diagnostics summary').click();expect(page.get_by_text('O executor precisa identificar o canal',exact=False)).to_be_visible();page.locator('.update-diagnostics summary').click();common()
                config.write_text(json.dumps({'channel':'develop','mode':'unavailable'}));refresh();expect(page.get_by_text('Não foi possível conferir a versão em uso.',exact=False)).to_be_visible();common()
                page.set_viewport_size({'width':390,'height':844});time.sleep(.3);page.screenshot(path=str(OUT/'unavailable-390.png'),full_page=True);assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                report['checks'].append('unknown source refuses lookup without guessing; unavailable installation, collapsed admin diagnosis, mobile width')
                # Actual socket refusal, not a successful fake operation.
                server.shutdown();thread.join(5);server.server_close();server=None;control.unlink()
                refresh();expect(page.get_by_text('Não foi possível conferir o andamento agora.',exact=False)).to_be_visible();common()
                report['checks'].append('socket unavailable shows safe transport error and no technical vocabulary in common flow')
                with closing(sqlite3.connect(root/'web-data'/'escritura.sqlite3')) as db:db.execute("UPDATE users SET role='viewer'");db.commit()
                denied=page.request.get(url+'/api/docker-updates');assert denied.status==403
                page.reload();expect(page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name='Atualização da aplicação',exact=True,include_hidden=True)).to_have_count(0)
                anonymous=browser.new_context();assert anonymous.request.get(url+'/api/docker-updates').status==401;anonymous.close()
                assert not errors,errors
                report.update(ok=True,browser_version=browser.version,pull_receipts='synthetic only',checks=report['checks']+['real web/API/socket admin authorization and CSRF; anonymous/viewer diagnostics denied'])
                browser.close()
        except Exception as exc:
            report['error']=str(exc);raise
        finally:
            if executor:executor.docker.pull_gate.set();executor.docker.validation_gate.set()
            if process:
                process.terminate()
                try:process.wait(10)
                except subprocess.TimeoutExpired:process.kill();process.wait(5)
            if server:server.shutdown();thread.join(5);server.server_close()
            if executor:executor.close()
            (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
