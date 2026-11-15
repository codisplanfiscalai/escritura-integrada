"""Synthetic preparation executor + negative API tests. Never changes an app container."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

_IMPORT_DATA = tempfile.TemporaryDirectory(prefix='docker-updater-test-import-')
os.environ.setdefault('ESCRITURA_DATA_DIR', _IMPORT_DATA.name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from docker_update_executor import Docker, Executor, Refusal, REPOSITORY
from app.docker_updates import ExecutorClient
from fastapi.testclient import TestClient
from app.api import create_app


def digest(char):
    return 'sha256:' + char * 64


class FakeDocker:
    def __init__(self):
        self.current = {'container_id': 'a'*64, 'image_id': digest('b'), 'digest': digest('c'),
                        'version': '0.9.0-dev.1', 'uid_gid': '10001:10001', 'configuration_hash': 'd'*64}
        self.target = {'digest': digest('e'), 'platform_digest': digest('e'), 'image_id': digest('f'),
                       'version': '0.9.0-dev.2', 'revision': 'f'*40}
        self.pulls = 0
        self.release = threading.Event()
        self.release.set()
        self.failure = None

    def installed(self): return copy.deepcopy(self.current)
    def resolve(self, channel): return copy.deepcopy(self.target)
    def space(self):
        if self.failure == 'space': raise Refusal('Espaço insuficiente.', 'disk_space')
    def pull(self, target, channel):
        self.pulls += 1
        self.release.wait(5)
        if self.failure == 'pull': raise Refusal('Download falhou.', 'docker_failed')
        if self.failure == 'timeout': raise Refusal('Prazo excedido; conferir cache.', 'docker_timeout')
        return {'version': self.target['version'], 'revision': self.target['revision']}


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docker = FakeDocker()
        self.executor = Executor(Path(self.tmp.name)/'state.sqlite3', self.docker)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.executor.close)

    def prepare(self, plan=None, key='1'*32):
        return self.executor.prepare((plan or self.executor.check('develop'))['id'], key, '1')

    def finish(self):
        self.executor.pool.shutdown(wait=True)
        return self.executor.status()['jobs'][0]

    def test_real_preparation_result_never_claims_cutover(self):
        before = self.docker.installed()
        job = self.prepare()
        final = self.finish()
        self.assertEqual(final['id'], job['id'])
        self.assertEqual(final['state'], 'prepared')
        self.assertFalse(final['application_updated'])
        self.assertFalse(final['cutover_supported'])
        self.assertEqual(final['installed'], before)
        self.assertEqual(self.docker.installed(), before)
        self.assertEqual(1, self.docker.pulls)

    def test_concurrent_repeat_and_new_keys_on_same_plan_are_deduplicated(self):
        plan = self.executor.check('develop')
        self.docker.release.clear()
        with ThreadPoolExecutor(max_workers=6) as pool:
            jobs = list(pool.map(lambda _: self.prepare(plan), range(6)))
        self.assertEqual(1, len({j['id'] for j in jobs}))
        self.assertEqual(jobs[0]['id'], self.prepare(plan, '2'*32)['id'])
        other = self.executor.check('latest')
        with self.assertRaisesRegex(Refusal, 'andamento'): self.prepare(other, '3'*32)
        self.docker.release.set()
        self.assertEqual('prepared', self.finish()['state'])
        self.assertEqual(1, self.docker.pulls)
        with self.assertRaisesRegex(Refusal, 'outra intenção'): self.prepare(other)

    def test_change_target_and_installed_config_prevents_pull(self):
        plan = self.executor.check('develop')
        self.docker.target['digest'] = digest('9')
        self.prepare(plan)
        self.assertEqual('failed', self.finish()['state'])
        self.assertEqual(0, self.docker.pulls)
        self.assertIn('canal mudou', self.executor.status()['jobs'][0]['error'])

    def test_change_mount_or_uid_snapshot_prevents_pull(self):
        plan = self.executor.check('develop')
        self.docker.current['configuration_hash'] = 'changed-synthetic-mount-or-uid'
        self.prepare(plan)
        self.assertEqual('failed', self.finish()['state'])
        self.assertEqual(0, self.docker.pulls)

    def test_download_failure_and_timeout_are_honest(self):
        for failure in ('pull', 'timeout', 'space'):
            with self.subTest(failure=failure):
                fake = FakeDocker(); fake.failure = failure
                executor = Executor(Path(self.tmp.name)/(failure+'.db'), fake)
                try:
                    plan = executor.check('develop')
                    executor.prepare(plan['id'], '1'*32, '1')
                    executor.pool.shutdown(wait=True)
                    result = executor.status()['jobs'][0]
                    self.assertEqual('failed', result['state'])
                    self.assertFalse(result['application_updated'])
                    self.assertTrue(result['error'])
                finally: executor.close()

    def test_missing_container_does_not_hide_jobs(self):
        self.prepare(); self.finish()
        self.docker.installed = Mock(side_effect=Refusal('Container ausente.'))
        status = self.executor.status()
        self.assertEqual(1, len(status['jobs']))
        self.assertIsNone(status['installed'])
        self.assertEqual('Container ausente.', status['installed_error'])

    def test_interrupted_job_is_persistent_without_automatic_retry(self):
        plan = self.executor.check('develop')
        self.executor.close()
        with closing(sqlite3.connect(self.executor.ledger)) as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)', ('9'*32,'1'*32,plan['id'],'1',1,1,'pulling',json.dumps(plan),None))
            db.commit()
        # Windows forbids this rename while SQLite still owns an open handle.
        probe = self.executor.ledger.with_suffix('.closed-check')
        self.executor.ledger.rename(probe)
        probe.rename(self.executor.ledger)
        recovered = Executor(self.executor.ledger, self.docker)
        try:
            result = recovered.status()['jobs'][0]
            self.assertEqual('interrupted', result['state'])
            self.assertEqual(result['id'], recovered.prepare(plan['id'],'1'*32,'1')['id'])
            self.assertEqual(0, self.docker.pulls)
        finally: recovered.close()

    def test_expired_plan_rate_limit_and_arbitrary_fields(self):
        plan = self.executor.check('develop')
        with patch('docker_update_executor.time.time', return_value=plan['expires_at']+1):
            with self.assertRaisesRegex(Refusal, 'vencida'): self.prepare(plan)
        for _ in range(11): self.executor.check('develop')
        with self.assertRaises(Refusal) as caught: self.executor.check('develop')
        self.assertEqual(429, caught.exception.status)
        for payload in ({'action':'check','channel':'main'}, {'action':'check','channel':'develop','image':'evil'},
                        {'action':'prepare','plan_id':plan['id'],'idempotency_key':'1'*32,'actor':'1','command':'shell'},
                        {'action':[]}, []):
            with self.subTest(payload=payload), self.assertRaises(Refusal): self.executor.dispatch(payload)

    def test_cutover_backup_health_and_rollback_requests_fail_closed(self):
        # Including writes/schema changes cannot grant missing cutover authority.
        for action in ('update','recreate','backup','health','rollback','restore','shell'):
            for extra in ({}, {'schema_compatible':True}, {'writes_after_backup':True}, {'backup_ok':False}, {'health_ok':False}):
                with self.subTest(action=action, extra=extra), self.assertRaises(Refusal):
                    self.executor.dispatch({'action':action, **extra})
        self.assertEqual([], self.executor.status()['jobs'])
        self.assertEqual(0, self.docker.pulls)


class DockerContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch('docker_update_executor.shutil.which', return_value='/usr/bin/docker'):
            self.docker = Docker('synthetic-stack', Path(self.tmp.name))
        self.labels = {'org.opencontainers.image.source':'https://github.com/codisplanfiscalai/escritura-integrada',
                       'org.opencontainers.image.version':'0.9.0-dev.1', 'org.opencontainers.image.revision':'a'*40}
        self.image = {'Id':digest('b'),'Os':'linux','Architecture':'amd64', 'Config':{'User':'10001:10001','Labels':self.labels}, 'RepoDigests':[REPOSITORY+'@'+digest('c')]}
        self.container = {'Image':digest('b'), 'Config':{'User':'10001:10001','Labels':{'com.docker.compose.project':'synthetic-stack','com.docker.compose.service':'app'},'Env':['SYNTHETIC_SECRET=never-report']},
                          'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},
                          'Mounts':[{'Destination':'/data','Type':'bind','Source':self.docker.data_bind,'RW':True}]}

    def inspect(self):
        with patch.object(self.docker,'run',side_effect=['a'*64,json.dumps([self.container]),json.dumps([self.image])]):
            return self.docker.installed()

    def test_installed_bind_uid_and_secret_redaction(self):
        result = self.inspect()
        self.assertEqual('10001:10001', result['uid_gid'])
        self.assertNotIn('never-report', json.dumps(result))
        self.assertNotIn(self.tmp.name, json.dumps(result))
        for field,value in (('Source', '/wrong/data/app'),('Type','volume'),('RW',False)):
            original = copy.deepcopy(self.container)
            self.container['Mounts'][0][field] = value
            with self.assertRaises(Refusal): self.inspect()
            self.container = original
        self.container['Config']['User'] = '0:0'
        with self.assertRaises(Refusal): self.inspect()

    def test_digest_and_uid_verification_after_pull(self):
        target = {'digest':digest('c'),'image_id':digest('b'),'version':'0.9.0-dev.1','revision':'a'*40}
        with patch.object(self.docker,'run',return_value='') as run, patch.object(self.docker,'image',return_value=self.image):
            result = self.docker.pull(target,'develop')
            self.assertEqual(target['version'],result['version'])
            self.assertEqual(['pull','--platform','linux/amd64',REPOSITORY+'@'+digest('c')],run.call_args.args[0])
            with self.assertRaises(Refusal): self.docker.pull(target,'latest')
            self.image['Config']['User']='0'
            with self.assertRaises(Refusal): self.docker.pull(target,'develop')

    def test_manifest_bytes_must_match_descriptor(self):
        raw = '{"schemaVersion":2}'
        value = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
        Docker.verify_manifest(raw,value)
        Docker.verify_manifest(raw+'\n',value)
        with self.assertRaises(Refusal): Docker.verify_manifest(raw+' ',value)


class UpdateApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'ESCRITURA_UPDATE_SOCKET':''}): self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app)
        self.addCleanup(self.client.close)
        response=self.client.post('/api/setup',json={'username':'fixture','password':'Synthetic-only-12345!'})
        self.assertEqual(200,response.status_code,response.text)
        self.client.headers['X-CSRF-Token']=response.json()['csrf_token']
        self.stub = Mock(path='/synthetic/socket')
        self.stub.call.return_value={'configured':True,'jobs':[],'cutover_supported':False}
        self.app.state.docker_executor=self.stub

    def test_auth_csrf_origin_and_admin_are_required_without_company(self):
        endpoints=[('GET','/api/docker-updates',None),('POST','/api/docker-updates/check',{'channel':'develop'}),
                   ('POST','/api/docker-updates/prepare',{'plan_id':'a'*32,'idempotency_key':'b'*32})]
        with TestClient(self.app) as anonymous:
            for method,path,body in endpoints:
                self.assertEqual(401,anonymous.request(method,path,json=body).status_code)
                self.assertEqual(200,self.client.request(method,path,json=body).status_code)
                if method=='POST':
                    self.assertEqual(403,self.client.post(path,json=body,headers={'X-CSRF-Token':''}).status_code)
                    self.assertEqual(403,self.client.post(path,json=body,headers={'Origin':'https://evil.invalid'}).status_code)
        self.stub.reset_mock()
        with self.app.state.db.transaction() as db: db.execute("UPDATE users SET role='viewer'")
        for method,path,body in endpoints:
            self.assertEqual(403,self.client.request(method,path,json=body).status_code)
        self.stub.call.assert_not_called()

    def test_disabled_no_fake_success_unknown_commands_and_extra_inputs(self):
        self.app.state.docker_executor=ExecutorClient('')
        result=self.client.get('/api/docker-updates').json()
        self.assertFalse(result['configured']);self.assertIsNone(result['installed'])
        self.assertEqual(503,self.client.post('/api/docker-updates/check',json={'channel':'develop'}).status_code)
        for body in ({'channel':'main'},{'channel':'develop','image':'evil'},{'channel':'latest','service':'redis'}):
            self.assertEqual(422,self.client.post('/api/docker-updates/check',json=body).status_code)
        self.assertIn(self.client.post('/api/docker-updates/apply',json={}).status_code,(404,405))


@unittest.skipUnless(sys.platform == 'linux', 'SO_PEERCRED requires Linux')
class SocketBoundaryTests(unittest.TestCase):
    def start(self, uid=None):
        from docker_update_executor import make_server
        tmp=tempfile.TemporaryDirectory(prefix='updater-socket-')
        self.addCleanup(tmp.cleanup)
        executor=Executor(Path(tmp.name)/'ledger.db',FakeDocker())
        self.addCleanup(executor.close)
        path=Path(tmp.name)/'control.sock'
        server=make_server(executor,path,os.getuid() if uid is None else uid)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        thread.start()
        def close():
            server.shutdown();thread.join(5);server.server_close()
        self.addCleanup(close)
        return ExecutorClient(str(path)),executor,path

    def test_real_socket_plan_and_job_round_trip(self):
        client,executor,_=self.start()
        plan=client.call('check',channel='latest')
        job=client.call('prepare',plan_id=plan['id'],idempotency_key='1'*32,actor='1')
        executor.pool.shutdown(wait=True)
        result=client.call('status')['jobs'][0]
        self.assertEqual(job['id'],result['id'])
        self.assertNotEqual(plan['id'],result['id'])
        self.assertEqual('prepared',result['state'])
        self.assertFalse(result['application_updated'])

    def test_wrong_peer_uid_and_missing_socket_cannot_execute(self):
        from app.core import DomainError
        client,executor,path=self.start(os.getuid()+1)
        with self.assertRaises(DomainError): client.call('check',channel='develop')
        self.assertEqual([],executor.status()['jobs'])
        with self.assertRaises(DomainError): ExecutorClient(str(path)+'-absent').call('status')

    def test_invalid_and_oversized_socket_payload_fail_closed(self):
        import socket
        _,executor,path=self.start()
        for raw in (b'invalid-json\n',b'x'*4097+b'\n',b'{"action":"shell"}\n'):
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(5);client.connect(str(path));client.sendall(raw)
                with client.makefile('rb') as stream:
                    result=json.loads(stream.readline(65537))
                self.assertNotEqual(200,result['status'])
        self.assertEqual(0,executor.docker.pulls)


@unittest.skipUnless(sys.platform == 'linux', 'Linux mountinfo is host-executor specific')
class SpaceProbeTests(unittest.TestCase):
    def test_rootless_daemon_probes_correct_mountpoint_without_reading_data(self):
        with tempfile.TemporaryDirectory() as temporary, patch('docker_update_executor.shutil.which',return_value='/usr/bin/docker'):
            docker=Docker('fixture',Path(temporary))
        mounts='1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /private rw - ext4 /dev/synthetic rw\n'
        with patch.object(docker,'run',return_value='/private/daemon/docker\n'), \
             patch('docker_update_executor.Path.read_text',return_value=mounts), \
             patch('docker_update_executor.shutil.disk_usage',side_effect=[PermissionError(),Mock(free=3*1024**3)]) as usage:
            docker.space()
            self.assertEqual(Path('/private'),usage.call_args.args[0])

    def test_space_failure_blocks_before_pull(self):
        with tempfile.TemporaryDirectory() as temporary, patch('docker_update_executor.shutil.which',return_value='/usr/bin/docker'):
            docker=Docker('fixture',Path(temporary))
        with patch.object(docker,'run',return_value='/synthetic/docker\n'), \
             patch('docker_update_executor.shutil.disk_usage',return_value=Mock(free=1)):
            with self.assertRaisesRegex(Refusal,'2 GiB'):docker.space()


class PullRaceTests(unittest.TestCase):
    setUp=ExecutorTests.setUp
    prepare=ExecutorTests.prepare
    finish=ExecutorTests.finish
    def test_alias_moves_during_pull_still_prepares_only_approved_digest(self):
        plan=self.executor.check('develop')
        receipt={k:plan['target'][k] for k in ('version','revision')}
        captured=[]
        def pull(target,channel):
            captured.append(copy.deepcopy(target))
            self.docker.target['digest']=digest('8')
            return receipt
        self.docker.pull=pull
        self.prepare(plan)
        result=self.finish()
        self.assertEqual('prepared',result['state'])
        self.assertEqual(plan['target']['digest'],result['target']['digest'])
        self.assertEqual([plan['target']],captured)

    def test_external_recreate_during_pull_fails_preparation_receipt(self):
        plan=self.executor.check('develop')
        def pull(target,channel):
            self.docker.current['container_id']='9'*64
            return {k:target[k] for k in ('version','revision')}
        self.docker.pull=pull
        self.prepare(plan)
        result=self.finish()
        self.assertEqual('failed',result['state'])
        self.assertFalse(result['application_updated'])
        self.assertIn('durante o download',result['error'])
