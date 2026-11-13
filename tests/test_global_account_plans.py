"""Shared account definitions retain repeated classifiers and company identity."""
import base64
import json
import sqlite3
import re
import unittest
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient
import test_core as base
from app.account_plans import default_plan
from app.db import Database
from app.snapshots import create_snapshot, restore_snapshot, manifest


def synthetic_plan():
    plan = json.loads(json.dumps(default_plan()))
    plan['accounts'] = [dict(plan['accounts'][0], access_code='00100', prosoft_code='00100', classifier='1', analytical=False),
        dict(plan['accounts'][3], access_code='00101', prosoft_code='00101', classifier='1.1.01.001', name='Subconta ficticia A'),
        dict(plan['accounts'][3], access_code='00102', prosoft_code='00102', classifier='1.1.01.001', name='Subconta ficticia B')]
    plan['accounts'][1]['synthetic_metadata'] = {'preserved': True}
    plan['accounts'][2]['prosoft']['currency_conversion'] = 'N'
    plan['warnings'] = ['Flag de origem sintética preservada para revisão.']
    return plan


class GlobalAccountPlanTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope

    def post(self, path, payload, status=200, cid=None):
        active = cid or self.client.get('/api/session').json()['active_company_id']
        r = self.client.post(self.scope(path, active), json=payload)
        self.assertEqual(status, r.status_code, r.text)
        return r.json()

    def publish(self, plan=None):
        raw = json.dumps(plan or synthetic_plan()).encode()
        batch = self.post('/account-plans/preview', {'format': 'native', 'filename': 'synthetic-private.json', 'content_base64': base64.b64encode(raw).decode()})
        payload = {'name': 'Plano sintético compartilhado', 'reason': 'Publicação sintética revisada', 'preview_hash': batch['preview_hash'], 'properties_reviewed': True, 'global_visibility_reviewed': True}
        return self.post(f"/global-account-plans/batches/{batch['id']}/publish", payload), batch, payload

    def prepare(self, plan_id, mode='shared'):
        return self.post(f'/global-account-plans/{plan_id}/preview', {'mode': mode})

    def confirm(self, preview, status=200):
        return self.post(f"/global-account-plans/previews/{preview['id']}/confirm", {'preview_hash': preview['preview_hash'], 'properties_reviewed': True, 'reason': 'Adoção sintética revisada'}, status)

    def test_operational_repeated_classifier_isolation_and_detach_preserves_ids(self):
        global_plan, batch, publish_payload = self.publish()
        self.assertEqual((3, 2, 1), (global_plan['record_count'], global_plan['classifier_count'], global_plan['repeated_classifier_records']))
        self.assertTrue(self.post(f"/global-account-plans/batches/{batch['id']}/publish", publish_payload)['duplicate'])
        self.activate(self.b['id'])
        before = self.core.accounts(self.b['id'])
        p = self.prepare(global_plan['id']); self.assertTrue(p['can_confirm'])
        r = self.confirm(p); self.assertEqual((0,6,3), (r['created'],r['local_accounts_preserved'],r['available']))
        with self.core.db.read() as conn:
            self.assertEqual(6,conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=?',(self.b['id'],)).fetchone()[0])
            self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM account_plan_batches WHERE company_id=?',(self.b['id'],)).fetchone()[0])
        self.assertTrue(self.confirm(p)['duplicate'])
        accounts = self.core.accounts(self.b['id']); self.assertEqual(9, len(accounts))
        for a in before: self.assertEqual(a, next(x for x in accounts if x['id']==a['id']))
        shared = {a['access_code']: a for a in accounts if a['access_code'].startswith('001')}
        a, b = shared['00101'], shared['00102']
        self.assertNotEqual(a['id'], b['id']); self.assertEqual(a['classifier'], b['classifier'])
        journal = self.post('/journals', {'idempotency_key':'synthetic-shared-journal', 'date': '2026-11-06', 'document': 'SYNTHETIC', 'history': 'Contas distintas sob mesmo classificador', 'lines': [
            {'account_id': a['id'], 'debit': '17.00', 'credit': '0.00'}, {'account_id': b['id'], 'debit': '0.00', 'credit': '17.00'}]}, 201)
        report = self.core.business_report(self.b['id'], 'trial-balance', '2026-11-01', '2026-11-30')
        movements = {x['access_code']: x for x in report['rows']}
        self.assertEqual(1700,movements[a['access_code']]['closing_cents']); self.assertEqual(-1700,movements[b['access_code']]['closing_cents'])
        used_ids={x['account_id'] for x in journal['lines']}
        self.assertTrue(all(aid>0 for aid in used_ids))
        filtered=self.core.business_report(self.b['id'],'ledger','2026-11-01','2026-11-30',account_id=a['id'])
        self.assertEqual(1,len(filtered['rows']))
        with self.core.db.read() as conn:
            refs=[dict(r) for r in conn.execute('SELECT * FROM accounts WHERE company_id=? AND shared_entry_id IS NOT NULL',(self.b['id'],))]
            self.assertEqual(2,len(refs));self.assertTrue(all(r['classifier'] is None and r['name'] is None and r['nature'] is None for r in refs))
        edit = self.client.put(self.scope('/accounts/'+str(a['id']), self.b['id']), json=a | {'name':'Alteração proibida'})
        self.assertEqual(409, edit.status_code, edit.text)
        self.post('/accounts', {'access_code':'X','classifier':'1','name':'Local','nature':'debit'},409)
        binding = self.client.get(self.scope('/global-account-plans',self.b['id'])).json()['binding']
        self.post('/global-account-plans/binding/detach', {'version':binding['version'],'reason':'Adaptação própria sintética'})
        own=next(x for x in self.core.accounts(self.b['id']) if x['access_code']==a['access_code'])
        edited = self.client.put(self.scope('/accounts/'+str(a['id']),self.b['id']), json=own | {'name':'Adaptação fictícia B'})
        self.assertEqual(200, edited.status_code, edited.text)
        detail = self.client.get(self.scope('/global-account-plans/'+str(global_plan['id']),self.b['id'])).json()
        self.assertEqual('Subconta ficticia A',next(x for x in detail['accounts'] if x['access_code']=='00101')['name'])
        self.assertEqual(6,len(self.core.accounts(self.a['id'])))
        self.assertEqual(used_ids,{x['id'] for x in self.core.accounts(self.b['id']) if x['access_code'] in {'00101','00102'}})
        with self.core.db.read() as conn: self.assertEqual([], list(conn.execute('PRAGMA foreign_key_check')))

    def test_preview_conflict_and_stale_are_atomic(self):
        g, _, _ = self.publish(); p = self.prepare(g['id'], 'own')
        account = self.core.accounts(self.a['id'])[0]
        self.client.put(self.scope('/accounts/'+str(account['id'])),json=account|{'name':'Concurrent synthetic edit'})
        self.confirm(p,409); self.assertEqual(6,len(self.core.accounts(self.a['id'])))
        collision = synthetic_plan()['accounts'][1] | {'name': 'Diferente'}
        self.post('/accounts',collision,201)
        p = self.prepare(g['id']); self.assertFalse(p['can_confirm']); self.assertEqual(1,p['conflict_count'])
        self.confirm(p,409); self.assertEqual(7,len(self.core.accounts(self.a['id'])))

    def test_publish_requires_global_admin_visibility_and_unique_access(self):
        g,b,p = self.publish()
        self.post(f"/global-account-plans/batches/{b['id']}/publish", p|{'global_visibility_reviewed':False},400)
        self.client.post('/api/users',json={'username':'local-reader','password':'Senha-sintetica-2026','role':'custom','company_ids':[self.a['id']], 'permissions':[
            {'company_id':self.a['id'],'routine':'accounting.accounts','action':'read','effect':'allow'}]})
        with TestClient(self.app) as limited:
            session=limited.post('/api/login',json={'username':'local-reader','password':'Senha-sintetica-2026'}).json()
            limited.headers['X-CSRF-Token']=session['csrf_token'];self.activate(self.a['id'],client=limited)
            self.assertEqual(200,limited.get(self.scope('/global-account-plans')).status_code)
            self.assertEqual(403,limited.post(self.scope(f"/global-account-plans/batches/{b['id']}/publish"),json=p).status_code)
            self.assertEqual(403,limited.get(self.scope('/global-account-plans',self.b['id'])).status_code)
        plan=synthetic_plan();plan['accounts'][2]['access_code']=plan['accounts'][1]['access_code']
        raw=json.dumps(plan).encode()
        batch=self.post('/account-plans/preview',{'format':'native','filename':'synthetic.json','content_base64':base64.b64encode(raw).decode()})
        self.post(f"/global-account-plans/batches/{batch['id']}/publish",p|{'preview_hash':batch['preview_hash']},409)
        self.assertEqual(1,len(self.client.get(self.scope('/global-account-plans')).json()['plans']))

    def test_large_synthetic_plan_projects_every_distinct_access_without_classifier_suffixes(self):
        plan=synthetic_plan();prototype=plan['accounts'][1]
        plan['accounts']=[dict(prototype,access_code=str(10000+i),prosoft_code=str(10000+i),name=f'Conta ficticia {i}') for i in range(22596)]
        g,_,_=self.publish(plan)
        self.assertEqual((22596,1,22595),(g['record_count'],g['classifier_count'],g['repeated_classifier_records']))
        confirmed=self.confirm(self.prepare(g['id'],'shared'));self.assertEqual((0,22596),(confirmed['created'],confirmed['available']))
        with self.core.db.read() as conn:
            self.assertEqual(6,conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=?',(self.a['id'],)).fetchone()[0])
        accounts=self.core.accounts(self.a['id']);imported=[a for a in accounts if len(a['access_code'])==5]
        self.assertEqual(22596,len(imported));self.assertEqual(22596,len({a['access_code'] for a in imported}))
        self.assertEqual({'1.1.01.001'},{a['classifier'] for a in imported})
        page=self.client.get(self.scope(f"/global-account-plans/{g['id']}?page=226")).json()
        self.assertEqual((22596,96),(page['total'],len(page['accounts'])))
        first,last=imported[0],imported[-1]
        posted=self.post('/journals',{'date':'2026-11-06','document':'SCALE','history':'Synthetic scale journal','idempotency_key':'scale-ref-allocation','lines':[
            {'account_id':first['id'],'debit':'1.00','credit':'0.00'}, {'account_id':last['id'],'debit':'0.00','credit':'1.00'}]},201)
        self.assertTrue(all(line['account_id']>0 for line in posted['lines']))
        with self.core.db.read() as conn:
            self.assertEqual(8,conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=?',(self.a['id'],)).fetchone()[0])
            self.assertEqual(2,conn.execute('SELECT COUNT(*) FROM accounts WHERE company_id=? AND shared_entry_id IS NOT NULL AND name IS NULL',(self.a['id'],)).fetchone()[0])

    def test_exact_metadata_native_backup_and_restore(self):
        g, _, _ = self.publish();self.activate(self.b['id']);self.confirm(self.prepare(g['id'],'own'))
        with self.core.db.read() as conn:
            accounts,properties=self.core._plan_state(conn,self.b['id'])
        imported = {a['access_code']:{k:v for k,v in a.items() if k not in {'id','version'}} for a in accounts if a['access_code'].startswith('001')}
        self.assertEqual({a['access_code']:a for a in synthetic_plan()['accounts']},imported)
        archive=Path(self.tmp.name)/'snapshot.zip';destination=Path(self.tmp.name)/'restored'
        snapshot=create_snapshot(self.core.db.path,archive)
        self.assertTrue(any(x['table']=='global_account_plans' for x in snapshot['originals']))
        restore_snapshot(archive,destination)
        restored=Database(destination)
        with restored.read() as conn:
            self.assertEqual(3,conn.execute('SELECT COUNT(*) FROM global_account_plan_links').fetchone()[0])
            self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))
        with ZipFile(archive) as z:
            legacy_manifest=json.loads(z.read('manifest.json'));database=z.read('escritura.sqlite3')
        legacy_manifest.pop('originals_scope')
        legacy_manifest['originals']=[r for r in legacy_manifest['originals'] if r['table'] in {'imports','stored_files'}]
        legacy_archive=Path(self.tmp.name)/'legacy-snapshot.zip'
        with ZipFile(legacy_archive,'w') as z:
            z.writestr('escritura.sqlite3',database);z.writestr('manifest.json',json.dumps(legacy_manifest))
        restore_snapshot(legacy_archive,Path(self.tmp.name)/'legacy-restored')
        with self.core.db.transaction() as conn:conn.execute("UPDATE global_account_plans SET original=X'0000'")
        with self.assertRaisesRegex(RuntimeError,'hash divergente'):manifest(self.core.db.path)

    def test_own_native_interchange_explicit_identity_by_access(self):
        raw=json.dumps(synthetic_plan()).encode()
        p=self.post('/account-plans/preview',{'format':'native','filename':'synthetic.json','content_base64':base64.b64encode(raw).decode(),'options':{'identity_mode':'access'}})
        self.assertTrue(p['can_confirm']);self.assertEqual(3,p['created'])
        self.post(f"/account-plans/{p['id']}/confirm",{'preview_hash':p['preview_hash'],'reason':'Identidade por acesso revisada','properties_reviewed':True})
        repeated=[a for a in self.core.accounts(self.a['id']) if a['access_code'] in {'00101','00102'}]
        self.assertEqual(2,len(repeated));self.assertEqual(repeated[0]['classifier'],repeated[1]['classifier'])

    def test_legacy_migration_keeps_ids_used_fk_triggers_and_pre_upgrade_backup(self):
        journal=self.post('/journals',base.CoreApiTests.journal(self),201)
        before=self.core.accounts(self.a['id'])
        conn=self.core.db.connect();conn.execute('PRAGMA foreign_keys=OFF');conn.execute('BEGIN IMMEDIATE')
        sql=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()[0]
        sql=re.sub(r'CREATE TABLE(?: IF NOT EXISTS)?\s+(?:"accounts"|accounts)','CREATE TABLE legacy_accounts',sql,count=1).replace('UNIQUE(company_id,id)','UNIQUE(company_id,classifier), UNIQUE(company_id,id)')
        conn.execute('DROP VIEW effective_accounts');conn.execute(sql);conn.execute('INSERT INTO legacy_accounts SELECT * FROM accounts');conn.execute('DROP TABLE accounts');conn.execute('ALTER TABLE legacy_accounts RENAME TO accounts')
        conn.execute('CREATE INDEX synthetic_account_index ON accounts(name)')
        conn.execute("CREATE TRIGGER synthetic_account_trigger AFTER UPDATE ON accounts BEGIN INSERT OR REPLACE INTO meta(key,value) VALUES('synthetic-trigger','fired'); END")
        conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'");conn.commit();conn.close()
        migrated=Database(self.tmp.name)
        self.assertIsNotNone(migrated.upgrade_backup);self.assertTrue(Path(migrated.upgrade_backup).is_file())
        self.assertEqual(before,self.core.accounts(self.a['id']))
        with migrated.transaction() as conn:
            self.assertEqual([],list(conn.execute('PRAGMA foreign_key_check')))
            self.assertEqual(2,conn.execute('SELECT COUNT(*) FROM journal_lines WHERE journal_id=?',(journal['id'],)).fetchone()[0])
            conn.execute("UPDATE accounts SET name=name WHERE id=?",(before[0]['id'],))
            self.assertEqual('fired',conn.execute("SELECT value FROM meta WHERE key='synthetic-trigger'").fetchone()[0])
            self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='synthetic_account_index'").fetchone())
            self.assertEqual('6',conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])


if __name__=='__main__':unittest.main()
