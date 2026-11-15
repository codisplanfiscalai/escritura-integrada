"""Real isolated Engine cutover with locally built synthetic registry/image fixtures.

Never contacts a deployment. Registry receipts are fixtures; Engine, containers,
private backup, hold, SQLite, health and recovery are real. No image is published.
"""
from __future__ import annotations
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import urllib.request

from docker_update_executor import Docker,Executor,make_server,REPOSITORY
from docker_update_cutover import CutDocker

ROOT=Path(__file__).resolve().parents[1]
BASE='ghcr.io/codisplanfiscalai/escritura-integrada@sha256:a18f23b430fec8e49ac3345e6c503ac20eeced9cbabefc45c5bd440cadd6bcf5'
OUT=ROOT/'artifacts'/'docker-cutover'


def run(*args):
    env={k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
    result=subprocess.run(['docker','--host','unix:///var/run/docker.sock',*args],env=env,capture_output=True,text=True,timeout=600)
    if result.returncode:raise RuntimeError(result.stderr[-3000:])
    return (result.stdout+result.stderr if args[0]=='logs' else result.stdout).strip()


class FaultDriver(CutDocker):
    backup_failure=False
    release_failure=False
    def exec(self,cid,action,job=None):
        if action=='release' and self.release_failure:
            self.release_failure=False
            raise __import__('docker_update_executor').Refusal('Resposta de liberação perdida antes de unlink na fixture.','engine_uncertain')
        return super().exec(cid,action,job)
    def helper(self,*args,**kwargs):
        if self.backup_failure and args[1]=='backup':
            raise __import__('docker_update_executor').Refusal('Falha sintética de backup injetada.','fixture_backup_failure')
        return super().helper(*args,**kwargs)
    def health(self,cid,version,job,timeout=120):
        return super().health(cid,version,job,timeout=12)


class FixtureRegistry(Docker):
    def __init__(self,project,data,images):
        super().__init__(project,data)
        self.images=images;self.selected='new'

    def image(self,reference):
        value=super().image(reference)
        if value['Id'] in self.images.values():
            value['RepoDigests']=[REPOSITORY+'@'+self.manifest(value['Id'])]
        return value

    @staticmethod
    def manifest(image):return 'sha256:'+hashlib.sha256(('synthetic-manifest:'+image).encode()).hexdigest()

    def resolve(self,channel):
        image=self.image(self.images[self.selected]);labels=image['Config']['Labels']
        return {'digest':self.manifest(image['Id']),'platform_digest':self.manifest(image['Id']),
                'image_id':image['Id'],'version':labels['org.opencontainers.image.version'],
                'revision':labels['org.opencontainers.image.revision']}

    def pull(self,target,channel):
        assert self.image(target['image_id'])['Id']==target['image_id']
        return {k:target[k] for k in ('version','revision')}


def wait_cut(executor,cid,timeout=240):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        cut=next(c for c in executor.cutovers.list() if c['id']==cid)
        if cut['state'] in ('completed','recovery_required','blocked','recovered_previous'):return cut
        time.sleep(.2)
    raise RuntimeError('Cutover fixture timed out')


def prepare(executor):
    plan=executor.check('develop');job=executor.prepare(plan['id'],uuid.uuid4().hex,'1')
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        result=next(j for j in executor.status()['jobs'] if j['id']==job['id'])
        if result['state']=='prepared':return result
        if result['state']=='failed':raise RuntimeError(result['error'])
        time.sleep(.1)
    raise RuntimeError('Preparation fixture timed out')


def build_images(folder):
    context=folder/'build';context.mkdir()
    shutil.copytree(ROOT/'app',context/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (context/'scripts').mkdir();shutil.copy2(ROOT/'scripts'/'run_container.py',context/'scripts'/'run_container.py')
    shutil.copytree(ROOT/'frontend'/'dist',context/'frontend'/'dist')
    # Match a normal CI checkout's program-file permissions. This touches only
    # the copied build context, never data/backup mounts.
    for path in context.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    images={}
    normal_api=(context/'app'/'api.py').read_text()
    # Fixture-only route: a request admitted before maintenance finishes a
    # second transaction after the hold is published. Never ships in app/.
    drain_route='    @application.post(\'/api/storage/fixture-drain\')\n    def fixture_drain():\n        import time\n        with database.transaction() as db:\n            db.execute("INSERT OR REPLACE INTO login_attempts VALUES(\'fixture-drain-started\',1,0)")\n        from .update_guard import hold\n        for _ in range(1200):\n            if hold(database.data_dir):break\n            time.sleep(.05)\n        else:raise RuntimeError(\'Fixture did not enter maintenance\')\n        with database.transaction() as db:\n            db.execute("INSERT OR REPLACE INTO login_attempts VALUES(\'fixture-drain-finished\',1,0)")\n        return {\'drained\':True}\n\n'
    normal_api=normal_api.replace('    @application.get("/api/health")',drain_route+'    @application.get("/api/health")')
    normal_guard=(context/'app'/'update_guard.py').read_text()
    for label,version in [('old','0.9.0-cutover.1'),('new','0.9.0-cutover.2'),('later','0.9.0-cutover.3'),('unhealthy','0.9.0-cutover.4'),('incompatible','0.9.0-cutover.5')]:
        (context/'app'/'api.py').write_text(normal_api if label!='unhealthy' else normal_api.replace('return {"status": "ok", "version": __version__','return {"status": "fixture-unhealthy", "version": __version__'))
        (context/'app'/'update_guard.py').write_text(normal_guard if label!='incompatible' else normal_guard.replace("DATA_ABI = 'sqlite-schema6-no-data-conversion-v1'","DATA_ABI = 'synthetic-incompatible-fixture'"))
        (context/'app'/'__init__.py').write_text(f'__version__ = "{version}"\n')
        (context/'app'/'__init__.py').chmod(0o644)
        (context/'Dockerfile').write_text(f'''FROM {BASE}
COPY --chown=root:root app/ /app/app/
COPY --chown=root:root scripts/ /app/scripts/
COPY --chown=root:root frontend/dist/ /app/frontend/dist/
LABEL org.opencontainers.image.version="{version}" org.opencontainers.image.revision="{'a'*40 if label=='old' else 'b'*40}"
''')
        tag='synthetic-escritura-cutover:'+folder.name+'-'+label
        run('build','--quiet','--tag',tag,str(context))
        images[label]=run('image','inspect','--format','{{.Id}}',tag)
    return images


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'ok':False,'registry':'synthetic-local-image-fixtures','checks':[]}
    executor=server=thread=None
    slow_pool=None
    browser_enabled='--browser' in sys.argv
    created=[]
    with tempfile.TemporaryDirectory(prefix='escritura-cutover-') as temporary:
        folder=Path(temporary);project='synthetic-cut-'+uuid.uuid4().hex[:10]
        data=folder/'data'/'app';data.mkdir(parents=True);data.chmod(0o777)
        state=folder/'.docker-updater';state.mkdir(mode=0o700);control=state/'run';control.mkdir();control.chmod(0o755)
        images={}
        try:
            images=build_images(folder)
            name=project+'-app-1';network=project+'-default'
            run('network','create',network)
            with socket.socket() as available:
                available.bind(('127.0.0.1',0));host_port=available.getsockname()[1]
            original=run('run','-d','--name',name,'--network',network,'--network-alias','app',
                '--label','com.docker.compose.project='+project,'--label','com.docker.compose.service=app',
                '--restart','unless-stopped','--health-interval','1s','--health-start-period','1s','--health-retries','3',
                '-p',f'127.0.0.1:{host_port}:8000','--mount',f'type=bind,source={data},target=/data',
                '--mount',f'type=bind,source={control},target=/run/escritura-update,readonly',
                '-e','ESCRITURA_UPDATE_SOCKET=/run/escritura-update/control.sock',images['old'])
            created.append(original)
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                if (data/'escritura.sqlite3').exists() and run('inspect','--format','{{.State.Health.Status}}',original)=='healthy':break
                time.sleep(.2)
            else:raise RuntimeError('Old fixture unhealthy')
            uid=(data/'escritura.sqlite3').stat().st_uid
            docker=FixtureRegistry(project,data,images)
            executor=Executor(state/'state.sqlite3',docker,cutover_enabled=True)
            executor.cutovers.driver=FaultDriver(docker,state)
            server=make_server(executor,control/'control.sock',uid,host_recovery=True)
            # Fixture only: private host parent + strict peer UID, container bind
            # is read-only. Production uses administrator-provisioned group 0660.
            (control/'control.sock').chmod(0o666)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url='http://'+run('port',original,'8000/tcp')
            import httpx
            with httpx.Client(base_url=url,timeout=120) as client:
                response=client.post('/api/setup',json={'username':'fixture','password':'Synthetic-only-12345!'})
                assert response.status_code==200,response.text
                client.headers['X-CSRF-Token']=response.json()['csrf_token']
                tax=run('exec',original,'python','-c',"from app.core import cnpj_digits;print('TEST00010001'+cnpj_digits('TEST00010001'))")
                company_response=client.post('/api/companies',json={'code':'SYNTHETIC','name':'Empresa sintética de corte','tax_id':tax,'regime':'outros','state':'SP','create_default_accounts':False})
                assert company_response.status_code==201,company_response.text
                company_id=company_response.json()['id']
                context_response=client.post('/api/context',json={'company_id':company_id,'module':'fiscal','period':'2026-11'})
                assert context_response.status_code==200,context_response.text
                run('exec',original,'python','-c',"import sqlite3; db=sqlite3.connect('/data/escritura.sqlite3');db.execute('CREATE INDEX fixture_custom_index ON login_attempts(locked_until)');db.commit();db.close()")
                status=client.get('/api/docker-updates')
                assert status.status_code==200,status.text
                assert status.json()['cutover_supported'] is True,status.text
                # Real record and file live in old app's bind, not in host fixtures.
                run('exec',original,'python','-c',"from pathlib import Path; Path('/data/synthetic.txt').write_text('preserve-current-data')")
                # Incompatible target is refused before maintenance or stop.
                docker.selected='incompatible'
                incompatible=prepare(executor)
                result=executor.cutovers.begin(incompatible['id'],uuid.uuid4().hex,'1')
                result=wait_cut(executor,result['id'])
                assert result['state']=='blocked' and 'incompatível' in result['error'],result
                assert run('inspect','--format','{{.State.Running}}',original)=='true'
                assert not (data/'.escritura-update-hold.json').exists()
                report['checks'].append('incompatible ABI refused before hold/stop')
                # A second writable mount is rejected; no host declaration bypass.
                docker.selected='new'
                writer=run('run','-d','--mount',f'type=bind,source={data},target=/writer',
                           '--entrypoint','python',images['old'],'-c','import time;time.sleep(120)')
                try:
                    try:executor.cutovers.driver.no_other_writers({original})
                    except __import__('docker_update_executor').Refusal:pass
                    else:raise AssertionError('Other writer was not rejected')
                finally:run('rm','-f',writer)
                report['checks'].append('other writable container refused before hold/stop')
                # Backup fault occurs after a real clean stop; host RPC can resume
                # the same image/data while web HTTP is unavailable. No restore.
                executor.cutovers.driver.backup_failure=True
                p=prepare(executor)
                result=executor.cutovers.begin(p['id'],uuid.uuid4().hex,'1')
                result=wait_cut(executor,result['id'])
                assert result['state']=='recovery_required' and 'backup' in result['error'],result
                assert executor.cutovers.load(result['id'])[2].get('new') is None
                command=[sys.executable,'scripts/docker_update_control.py','--project-directory',str(folder),
                         'recover-previous','--cutover-id',result['id']]
                recovery=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
                assert recovery.returncode==0,recovery.stdout+recovery.stderr
                result=wait_cut(executor,result['id']);assert result['state']=='recovered_previous',result
                executor.cutovers.driver.backup_failure=False
                report['checks'].append('backup fault keeps data; real host RPC resumes original image')
                # An actual unhealthy target never opens writes and can return to
                # the retained original only while the entire data tree matches.
                docker.selected='unhealthy';p=prepare(executor)
                result=executor.cutovers.begin(p['id'],uuid.uuid4().hex,'1');result=wait_cut(executor,result['id'])
                assert result['state']=='recovery_required' and ('Healthcheck' in result['error'] or 'saúde' in result['error']),result
                failed_id=executor.cutovers.load(result['id'])[2]['new'];created.append(failed_id)
                assert run('inspect','--format','{{.State.Health.Status}}',failed_id)=='unhealthy'
                held_session=client.get('/api/session')
                assert held_session.status_code==200 and held_session.json()['active_company_id']==company_id,held_session.text
                held_call=client.post('/api/context',json={'company_id':None,'period':'2026-11'})
                assert held_call.status_code==503,held_call.text
                executor.cutovers.recover(result['id'],'previous','1')
                result=wait_cut(executor,result['id']);assert result['state']=='recovered_previous',result
                report['checks'].append('real unhealthy target stays held; original resumes without data restore')
                # Lose the real Engine create response after the container
                # exists, then restart the executor. Only its matching job label,
                # immutable image/config and frozen data permit adoption/resume.
                docker.selected='new';p=prepare(executor)
                engine=executor.cutovers.driver.engine;real_create=engine.create
                def lost_create(name,configuration):
                    real_create(name,configuration)
                    raise __import__('docker_update_executor').Refusal('Resposta de criação perdida na fixture.','engine_uncertain')
                engine.create=lost_create
                uncertain=executor.cutovers.begin(p['id'],uuid.uuid4().hex,'1');uncertain=wait_cut(executor,uncertain['id'])
                assert uncertain['state']=='recovery_required' and not executor.cutovers.load(uncertain['id'])[2].get('new'),uncertain
                server.shutdown();thread.join(5);server.server_close();executor.close();(control/'control.sock').unlink()
                executor=Executor(state/'state.sqlite3',docker,cutover_enabled=True)
                executor.cutovers.driver=FaultDriver(docker,state)
                executor.cutovers.driver.release_failure=True
                server=make_server(executor,control/'control.sock',uid,host_recovery=True);(control/'control.sock').chmod(0o666)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                assert next(c for c in executor.cutovers.list() if c['id']==uncertain['id'])['state']=='recovery_required'
                command=[sys.executable,'scripts/docker_update_control.py','--project-directory',str(folder),
                         'reconcile-target','--cutover-id',uncertain['id']]
                resumed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
                assert resumed.returncode==0,resumed.stdout+resumed.stderr
                uncertain=wait_cut(executor,uncertain['id']);assert uncertain['state']=='recovery_required',uncertain
                assert executor.cutovers.load(uncertain['id'])[2]['released'] is True
                resumed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
                assert resumed.returncode==0,resumed.stdout+resumed.stderr
                uncertain=wait_cut(executor,uncertain['id']);assert uncertain['state']=='completed',uncertain
                report['checks'].append('lost Engine create reply + executor restart: nonce/config adoption and explicit host resume')
                report['checks'].append('durable release intent with intact hold: explicit verified target release retry')
                docker.selected='later'
                p=prepare(executor)
                body={'prepared_id':p['id'],'idempotency_key':uuid.uuid4().hex}
                current_source=docker.installed()['container_id']
                slow_pool=ThreadPoolExecutor(max_workers=1)
                slow=slow_pool.submit(lambda:client.post('/api/storage/fixture-drain',json={},timeout=120))
                for _ in range(60):
                    started=run('exec',current_source,'python','-c',"import sqlite3;d=sqlite3.connect('/data/escritura.sqlite3');print(d.execute(\"SELECT count(*) FROM login_attempts WHERE attempt_key='fixture-drain-started'\").fetchone()[0]);d.close()")
                    if started=='1':break
                    time.sleep(.1)
                else:raise RuntimeError('In-flight fixture request did not begin')
                if browser_enabled:
                    from playwright.sync_api import sync_playwright,expect
                    with sync_playwright() as playwright:
                        browser=playwright.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                        page=browser.new_page(viewport={'width':1440,'height':1000})
                        page.goto(url);page.get_by_label('Usuário',exact=True).fill('fixture')
                        page.locator('input[type=password]').fill('Synthetic-only-12345!')
                        page.get_by_role('button',name='Entrar',exact=True).click()
                        navigation=page.get_by_role('navigation',name='Navegação principal')
                        button=navigation.get_by_role('button',name='Atualização Docker',exact=True,include_hidden=True)
                        expect(button).to_be_attached(timeout=30000)
                        details=button.locator('xpath=ancestor::details')
                        if details.count() and details.get_attribute('open') is None:details.locator('summary').click()
                        button.click()
                        apply=page.get_by_role('button',name='Atualizar aplicação por digest',exact=True)
                        expect(apply).to_be_enabled(timeout=60000);apply.click()
                        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/docker-updates/cutover'),timeout=30000) as pending:
                            page.get_by_role('dialog').get_by_role('button',name='Confirmar janela e atualizar',exact=True).click()
                        accepted=pending.value;assert accepted.status==200,accepted.text()
                        body=accepted.request.post_data_json;cid=accepted.json()['id']
                        result=wait_cut(executor,cid)
                        assert result['state']=='completed',result
                        expect(page.get_by_text('Atualização confirmada',exact=True).first).to_be_visible(timeout=30000)
                        page.screenshot(path=str(OUT/'completed-1440.png'),full_page=True)
                        page.set_viewport_size({'width':390,'height':844})
                        for _ in range(60):
                            box=page.locator('.sidebar').bounding_box()
                            if box and box['x']+box['width']<=1:break
                            time.sleep(.05)
                        page.screenshot(path=str(OUT/'completed-390.png'),full_page=True)
                        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                        report['browser_version']=browser.version
                        browser.close()
                    report['checks'].append('real in-container UI confirmation, reconnect/polling, desktop/mobile result')
                else:
                    accepted=client.post('/api/docker-updates/cutover',json=body)
                    assert accepted.status_code==200,accepted.text
                    cid=accepted.json()['id']
                same=executor.cutovers.begin(p['id'],body['idempotency_key'],'1');assert same['id']==cid
                result=wait_cut(executor,cid)
                (OUT/'cut-result.json').write_text(json.dumps(result,indent=2))
                assert result['state']=='completed',result
                new=executor.cutovers.load(cid)[2]['new'];created.append(new)
                assert new!=current_source
                drained=slow.result(timeout=15);assert drained.status_code==200 and drained.json()['drained'],drained.text
                slow_pool.shutdown(wait=True);slow_pool=None
                report['checks'].append('pre-admitted multi-transaction request completed after hold and before stop')
                assert run('inspect','--format','{{.Image}}',new)==images['later']
                assert run('exec',new,'cat','/data/synthetic.txt')=='preserve-current-data'
                new_url='http://'+run('port',new,'8000/tcp')
                with httpx.Client(base_url=new_url,timeout=30,cookies=client.cookies,headers=client.headers) as after:
                    health=after.get('/api/health').json();assert health['version']=='0.9.0-cutover.3' and health['update_hold'] is None
                    assert after.get('/api/session').json()['authenticated']
                    assert after.get('/api/session').json()['active_company_id']==company_id
                    rows=run('exec',new,'python','-c',"import sqlite3;d=sqlite3.connect('/data/escritura.sqlite3');print(d.execute(\"SELECT count(*) FROM login_attempts WHERE attempt_key='fixture-drain-finished'\").fetchone()[0]);print(d.execute(\"SELECT count(*) FROM sqlite_master WHERE name='fixture_custom_index'\").fetchone()[0]);d.close()")
                    assert rows.splitlines()==['1','1'],rows
                    assert after.post('/api/context',json={'company_id':None,'period':'2026-11'}).status_code==200
                # Once writes are released, even an explicit previous-image
                # request cannot switch back or replace current data.
                row,public,private=executor.cutovers.load(cid)
                executor.cutovers.save(cid,'recovery_required',public,private)
                executor.cutovers.recover(cid,'previous','1')
                blocked=wait_cut(executor,cid)
                assert blocked['state']=='recovery_required' and 'proibido' in blocked['error'],blocked
                assert run('inspect','--format','{{.Image}}',new)==images['later']
                executor.cutovers.recover(cid,'target','1')
                assert wait_cut(executor,cid)['state']=='completed'
                docker.selected='unhealthy';p=prepare(executor)
                drift=executor.cutovers.begin(p['id'],uuid.uuid4().hex,'1');drift=wait_cut(executor,drift['id'])
                assert drift['state']=='recovery_required',drift
                drift_new=executor.cutovers.load(drift['id'])[2]['new'];created.append(drift_new)
                run('exec',drift_new,'python','-c',"from pathlib import Path;Path('/data/synthetic.txt').write_text('external-new-write-preserve')")
                executor.cutovers.recover(drift['id'],'previous','1')
                drift=wait_cut(executor,drift['id'])
                assert drift['state']=='recovery_required' and 'dados' in drift['error'],drift
                assert run('run','--rm','--network','none','--mount',f'type=bind,source={data},target=/source,readonly','--entrypoint','cat',images['old'],'/source/synthetic.txt')=='external-new-write-preserve'
                assert run('inspect','--format','{{.State.Running}}',new)=='false'
                report['checks'].append('data drift blocks image recovery; external new write preserved')
            report.update(ok=True,source_version='0.9.0-cutover.1',target_version='0.9.0-cutover.3',
                          checks=report['checks']+['real Engine recreate with config/mount/network comparison','real private physical and SQLite backup',
                                  'held target with no automatic migrations','healthcheck + HTTP target version',
                                  'real app socket mount + UID authorization + admin API/CSRF','preserved session and synthetic file',
                                  'new writes admitted only after release','previous-image recovery refused after release; target reconciled'])
        except Exception as exc:
            report['error']=str(exc)
            if executor:
                for cut in executor.cutovers.list():
                    _,_,private=executor.cutovers.load(cut['id'])
                    if private.get('new'):
                        actual=executor.cutovers.driver.engine.inspect(private['new'])['HostConfig']
                        expected=private['expected']['HostConfig']
                        (OUT/'fixture-config-diff.json').write_text(json.dumps({k:{'expected':expected.get(k),'actual':actual.get(k)} for k in set(expected)|set(actual) if expected.get(k)!=actual.get(k)},indent=2))
            for container in created:
                try:(OUT/(container[:12]+'.log')).write_text(run('logs',container))
                except Exception:pass
            raise
        finally:
            if slow_pool:slow_pool.shutdown(wait=False,cancel_futures=True)
            if server:server.shutdown();thread.join(5);server.server_close()
            if executor:executor.close()
            # Include containers retained by the cutover, and only this random project.
            ids=run('ps','-aq','--filter','label=com.docker.compose.project='+project).splitlines()
            if ids:run('rm','-f',*ids)
            try:run('network','rm',project+'-default')
            except Exception:pass
            if images:
                owned=[data]
                if (state/'backups').exists():owned+=list((state/'backups').iterdir())
                for path in owned:
                    if path.is_dir():
                        run('run','--rm','--network','none','--user','10001:10001','--mount',f'type=bind,source={path},target=/fixture',
                            '--entrypoint','python',images['old'],'-c',"from pathlib import Path; import shutil; [(shutil.rmtree(p) if p.is_dir() else p.unlink()) for p in Path('/fixture').iterdir()]")
            (OUT/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
