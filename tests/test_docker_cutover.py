"""Synthetic holds/backups and narrow cutover state transitions. No server data."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

_IMPORT=tempfile.TemporaryDirectory(prefix='cutover-import-')
os.environ.setdefault('ESCRITURA_DATA_DIR',_IMPORT.name)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from app.db import Database
from app.update_guard import create_hold,hold,release,inventory,backup,UpdateHeld,MARKER,schema
from app.api import create_app
from fastapi.testclient import TestClient
from docker_update_executor import Executor,Refusal
from docker_update_cutover import Cutovers
from test_docker_updates import FakeDocker


@unittest.skipUnless(sys.platform=='linux','Docker hold/backup contract requires Linux')
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.data=self.root/'data';self.db=Database(self.data)
        with self.db.transaction() as db:db.execute("INSERT INTO login_attempts VALUES('fixture',1,0)")

    def test_held_startup_never_initializes_migrates_or_writes(self):
        before=schema(self.db.path);value=create_hold(self.data,'a'*32)
        with patch('app.maintenance.backup_before_schema',side_effect=AssertionError('migration called')):
            guarded=Database(self.data)
        self.assertEqual(before,value['schema'])
        with self.assertRaises(UpdateHeld):
            with guarded.transaction():pass
        with guarded.read() as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute("DELETE FROM login_attempts")
        release(self.data,'a'*32)
        with guarded.transaction() as db:db.execute("INSERT INTO login_attempts VALUES('after-release',1,0)")

    def test_foreign_hold_and_schema_change_cannot_release(self):
        create_hold(self.data,'a'*32)
        with self.assertRaises(FileExistsError):create_hold(self.data,'b'*32)
        with self.assertRaises(UpdateHeld):release(self.data,'b'*32)
        with closing(sqlite3.connect(self.db.path)) as db:
            db.execute('CREATE TABLE incompatible(value TEXT)');db.commit()
        with self.assertRaises(UpdateHeld):Database(self.data)
        with self.assertRaises(UpdateHeld):release(self.data,'a'*32)
        self.assertTrue((self.data/MARKER).exists())

    def test_http_blocks_setup_login_business_but_keeps_health_and_status_readable(self):
        app=create_app(self.data);client=TestClient(app);self.addCleanup(client.close)
        r=client.post('/api/setup',json={'username':'fixture','password':'Synthetic-only-12345!'})
        client.headers['X-CSRF-Token']=r.json()['csrf_token']
        create_hold(self.data,'a'*32)
        for path in ('/api/login','/api/setup','/api/context','/api/companies'):
            self.assertEqual(503,client.post(path,json={}).status_code)
        self.assertEqual(503,client.get('/api/companies').status_code)
        self.assertEqual('a'*32,client.get('/api/health').json()['update_hold'])
        self.assertEqual(200,client.get('/api/docker-updates').status_code)
        self.assertEqual(200,client.get('/api/session').status_code)

    def test_consistent_backup_preserves_files_modes_and_original_and_has_no_restore(self):
        file=self.data/'synthetic.txt';file.write_bytes(b'synthetic-data');file.chmod(0o600)
        folder=self.data/'folder';folder.mkdir();(folder/'second.txt').write_bytes(b'preserve')
        create_hold(self.data,'a'*32)
        before=inventory(self.data)
        destination=self.root/'backup';destination.mkdir()
        receipt=backup(self.data,destination)
        self.assertEqual(before,inventory(self.data))
        self.assertEqual(before['fingerprint'],receipt['fingerprint'])
        self.assertEqual(schema(self.db.path),schema(destination/'consistent.sqlite3'))
        self.assertEqual(b'synthetic-data',(destination/'source'/'synthetic.txt').read_bytes())
        with self.assertRaises(FileExistsError):backup(self.data,destination)
        file.write_bytes(b'new-write')
        self.assertNotEqual(receipt['fingerprint'],inventory(self.data)['fingerprint'])
        self.assertEqual(b'new-write',file.read_bytes())

    @unittest.skipIf(sys.platform=='win32','POSIX link/mode contract')
    def test_links_and_foreign_ownership_fail_closed(self):
        (self.data/'link').symlink_to('/outside')
        with self.assertRaises(UpdateHeld):inventory(self.data)


class CutoverAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.executor=Executor(Path(self.tmp.name)/'ledger.db',FakeDocker())
        self.addCleanup(self.executor.close)

    def test_host_opt_in_required_and_rpc_cannot_pass_commands_paths_or_images(self):
        for body in ({'action':'cutover','prepared_id':'a'*32,'idempotency_key':'b'*32,'actor':'1'},
                     {'action':'recover-previous','cutover_id':'a'*32,'actor':'1'}):
            with self.assertRaises(Refusal) as caught:self.executor.dispatch(body)
            self.assertEqual(403,caught.exception.status)
        for extra in ('image','path','service','command','skip_backup','schema_compatible'):
            with self.subTest(extra=extra),self.assertRaises(Refusal):
                self.executor.dispatch({'action':'cutover','prepared_id':'a'*32,'idempotency_key':'b'*32,'actor':'1',extra:True})
        self.assertFalse(self.executor.status()['cutover_supported'])

    def test_restart_recovery_and_private_snapshot_never_leaks(self):
        cuts=self.executor.cutovers
        with self.executor.db() as db:
            db.execute('INSERT INTO cutovers VALUES(?,?,?,?,?,?,?,?)',('a'*32,'b'*32,'c'*32,'backup',
                json.dumps({'actor_id':'1','error':None}),json.dumps({'Env':['SYNTHETIC_SECRET=not-public']}),1,1))
        recovered=Cutovers(self.executor,enabled=True)
        self.assertTrue(recovered.busy())
        result=recovered.list()[0]
        self.assertEqual('recovery_required',result['state'])
        self.assertNotIn('not-public',json.dumps(result))
        self.assertNotIn('Env',json.dumps(result))
        self.assertFalse(result['application_updated'])

    def test_concurrent_cutovers_and_transport_retries_preserve_one_intention(self):
        e=self.executor;e.cutovers.enabled=True
        first=e.check('develop');prepared=e.prepare(first['id'],'d'*32,'1')
        e.pool.shutdown(wait=True)
        second=e.check('latest')
        with patch.object(e.pool,'submit') as submit:
            with ThreadPoolExecutor(max_workers=6) as callers:
                results=list(callers.map(lambda _:e.cutovers.begin(prepared['id'],'e'*32,'1'),range(6)))
            self.assertEqual(1,len({c['id'] for c in results}));submit.assert_called_once()
            self.assertEqual(results[0]['id'],e.cutovers.begin(prepared['id'],'f'*32,'1')['id'])
            with self.assertRaises(Refusal):e.cutovers.begin('a'*32,'e'*32,'1')
            with self.assertRaises(Refusal):e.cutovers.begin(prepared['id'],'e'*32,'2')
            with self.assertRaises(Refusal):e.prepare(second['id'],'a'*32,'1')
            self.assertEqual('validating',e.cutovers.list()[0]['state'])


class CutoverAuthTests(unittest.TestCase):
    from test_docker_updates import UpdateApiTests
    setUp=UpdateApiTests.setUp

    def test_admin_csrf_origin_and_negative_role_cover_cut_and_recovery(self):
        endpoints=[('/api/docker-updates/cutover',{'prepared_id':'a'*32,'idempotency_key':'b'*32}),
                   ('/api/docker-updates/recover-previous',{'cutover_id':'a'*32}),
                   ('/api/docker-updates/reconcile-target',{'cutover_id':'a'*32})]
        with TestClient(self.app) as anonymous:
            for path,body in endpoints:
                self.assertEqual(401,anonymous.post(path,json=body).status_code)
                self.assertEqual(403,self.client.post(path,json=body,headers={'X-CSRF-Token':''}).status_code)
                self.assertEqual(403,self.client.post(path,json=body,headers={'Origin':'https://evil.invalid'}).status_code)
                self.assertEqual(200,self.client.post(path,json=body).status_code)
        self.stub.reset_mock()
        with self.app.state.db.transaction() as db:db.execute("UPDATE users SET role='viewer'")
        for path,body in endpoints:self.assertEqual(403,self.client.post(path,json=body).status_code)
        self.stub.call.assert_not_called()

    def test_client_cannot_supply_paths_images_services_or_compatibility_override(self):
        for field in ('image','path','service','command','schema_compatible','skip_backup'):
            body={'prepared_id':'a'*32,'idempotency_key':'b'*32,field:True}
            self.assertEqual(422,self.client.post('/api/docker-updates/cutover',json=body).status_code)
        for path in ('recover-previous','reconcile-target'):
            self.assertEqual(422,self.client.post('/api/docker-updates/'+path,json={'cutover_id':'../outside'}).status_code)
        self.stub.call.assert_not_called()


class ConfigurationScopeTests(unittest.TestCase):
    def test_uncertain_release_retries_only_own_unchanged_hold_and_preserves_new_writes(self):
        cut=Cutovers.__new__(Cutovers);driver=Mock();cut.driver=driver
        private={'plan':{'installed':{'image_id':'sha256:'+'a'*64}},'baseline':{'fingerprint':'frozen'}}
        driver.exec.return_value={'held_job':None}
        cut.finish_uncertain_release('b'*32,private,'c'*64,'version')
        driver.helper.assert_not_called();driver.frozen_contract.assert_not_called()
        driver.exec.return_value={'held_job':'b'*32};driver.helper.return_value=private['baseline']
        cut.finish_uncertain_release('b'*32,private,'c'*64,'version')
        self.assertEqual(('c'*64,'release','b'*32),driver.exec.call_args.args)
        driver.helper.return_value={'fingerprint':'new-write'}
        with self.assertRaises(Refusal):cut.finish_uncertain_release('b'*32,private,'c'*64,'version')
        driver.exec.return_value={'held_job':'d'*32}
        with self.assertRaises(Refusal):cut.finish_uncertain_release('b'*32,private,'c'*64,'version')

    def test_restart_mount_signal_and_dynamic_port_changes_fail_closed(self):
        from docker_update_cutover import CutDocker
        from docker_update_executor import REPOSITORY
        cfg={'Cmd':['python','scripts/run_container.py'],'User':'10001:10001','Env':['ESCRITURA_DATA_DIR=/data'],'Labels':{}}
        container={'Config':cfg,'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},
                   'Mounts':[{'RW':True,'Destination':'/data'}],'NetworkSettings':{'Networks':{}}}
        target={'image_id':'sha256:'+'a'*64,'digest':'sha256:'+'b'*64}
        docker=Mock();docker.image.return_value={'Id':target['image_id'],'Config':cfg,'RepoDigests':[REPOSITORY+'@'+target['digest']]}
        driver=CutDocker(docker,'.');driver.validate_config(container,target)
        variants=[]
        for policy in ('always','on-failure'):
            value=copy.deepcopy(container);value['HostConfig']['RestartPolicy']['Name']=policy;variants.append(value)
        value=copy.deepcopy(container);value['Mounts'].append({'RW':True,'Destination':'/other'});variants.append(value)
        value=copy.deepcopy(container);value['Config']['StopSignal']='SIGKILL';variants.append(value)
        value=copy.deepcopy(container);value['HostConfig']['PortBindings']={'8000/tcp':[{'HostPort':'0'}]};variants.append(value)
        value=copy.deepcopy(container);value['Config']['Env']=['ESCRITURA_DATA_DIR=/other'];variants.append(value)
        for value in variants:
            with self.subTest(value=value),self.assertRaises(Refusal):driver.validate_config(value,target)

    def test_oom_default_normalization_preserves_explicit_security_values(self):
        from docker_update_cutover import CutDocker
        self.assertTrue(CutDocker.same_host({'OomKillDisable':None},{'OomKillDisable':False}))
        self.assertFalse(CutDocker.same_host({'OomKillDisable':None},{'OomKillDisable':True}))
        self.assertFalse(CutDocker.same_host({'Binds':['original'],'OomKillDisable':None},{'Binds':['changed'],'OomKillDisable':False}))

    def test_released_target_cannot_request_previous_even_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            executor=Executor(Path(folder)/'ledger.db',FakeDocker(),cutover_enabled=True)
            try:
                with executor.db() as db:
                    db.execute('INSERT INTO cutovers VALUES(?,?,?,?,?,?,?,?)',('a'*32,'b'*32,'c'*32,'completed',
                        json.dumps({'actor_id':'1','error':None}),json.dumps({'released':True,'release_destination':'target'}),1,1))
                with self.assertRaises(Refusal) as caught:executor.cutovers.recover('a'*32,'previous','1')
                self.assertEqual('writes_released',caught.exception.code)
                self.assertEqual('completed',executor.cutovers.list()[0]['state'])
            finally:executor.close()


@unittest.skipUnless(sys.platform=='linux','Docker hold requires Linux')
class DrainAdmissionTests(unittest.TestCase):
    def test_previously_admitted_flow_can_finish_new_flows_cannot_start(self):
        from app.update_guard import admitted
        with tempfile.TemporaryDirectory() as folder:
            db=Database(folder);create_hold(folder,'a'*32)
            token=admitted.set(True)
            try:
                with db.transaction() as connection:connection.execute("INSERT INTO login_attempts VALUES('drained',1,0)")
            finally:admitted.reset(token)
            with self.assertRaises(UpdateHeld):
                with db.transaction():pass
            with db.read() as connection:self.assertEqual(1,connection.execute("SELECT count(*) FROM login_attempts WHERE attempt_key='drained'").fetchone()[0])
