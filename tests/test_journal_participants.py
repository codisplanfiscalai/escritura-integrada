"""Third-party dimension regressions; all records synthetic."""
import base64
from unittest.mock import patch
import unittest
import test_core as base
from app.core import DomainError


class JournalParticipantsTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company
    journal=base.CoreApiTests.journal
    document=base.CoreApiTests.document
    def party(self, code='P1'):
        r=self.client.post(self.scope('/masters/participant'),json={'code':code,'name':'Fornecedor fictício','tax_id':'','data':{}})
        self.assertEqual(201,r.status_code,r.text)
        return r.json()['id']

    def test_party_persist_retry_and_reverse(self):
        pid=self.party(); payload=self.journal();payload['lines'][1]['participant_id']=pid
        result=self.core.create_journal(self.a['id'],payload,'test')
        self.assertEqual(pid,result['lines'][1]['participant_id'])
        self.assertTrue(self.core.create_journal(self.a['id'],payload,'test')['duplicate'])
        changed=self.journal();changed['lines'][1]['participant_id']=self.party('P2')
        with self.assertRaises(DomainError):self.core.create_journal(self.a['id'],changed,'test')
        reverse=self.core.reverse_journal(self.a['id'],result['id'],{'date':'2026-11-07','reason':'Teste'},'test')
        self.assertEqual(pid,reverse['lines'][1]['participant_id'])

    def test_company_isolation_and_policy(self):
        pid=self.party();payload=self.journal()
        with patch('app.journal_participants.participant_policy',return_value='required'):
            with self.assertRaises(DomainError):self.core.create_journal(self.a['id'],payload,'test')
        payload['lines'][1]['participant_id']=pid
        with patch('app.journal_participants.participant_policy',return_value='none'):
            with self.assertRaises(DomainError):self.core.create_journal(self.a['id'],payload,'test')
        self.activate(self.b['id'])
        r=self.client.post(self.scope('/masters/participant',self.b['id']),json={'code':'OTHER','name':'Outro fictício','tax_id':'','data':{}})
        self.assertEqual(201,r.status_code,r.text)
        payload['lines'][1]['participant_id']=r.json()['id']
        self.activate(self.a['id'])
        with self.assertRaises(DomainError):self.core.create_journal(self.a['id'],payload,'test')

    def test_csv_v2_resolves_party_and_preserves_identity(self):
        pid=self.party()
        raw='id;date;document;history;account;debit;credit;cost_center;participant_code\nx;2026-11-06;D;Teste;3;100;0;;\nx;2026-11-06;D;Teste;5;0;100;;P1\n'
        result=self.core.preview_module_import(self.a['id'],{'module':'accounting','layout':'journals-v2','year':2026,'content_base64':base64.b64encode(raw.encode()).decode(),'filename':'synthetic.csv'},'test')
        row=result['records'][0]
        self.assertIsNone(row['validation_error'])
        self.assertEqual(pid,row['payload']['lines'][1]['participant_id'])
        self.assertEqual('journals-v1:x',row['payload']['idempotency_key'])
        result=self.core.create_journal(self.a['id'],row['payload'],'test')
        self.assertEqual(pid,result['lines'][1]['participant_id'])

    def booked_document(self):
        pid=self.party()
        r=self.client.post(self.scope('/documents'),json=self.document()|{'participant_id':pid})
        self.assertEqual(201,r.status_code,r.text);doc=r.json()
        r=self.client.post(self.scope(f"/documents/{doc['id']}/review"),json={'version':doc['version'],'reason':'Teste'})
        self.assertEqual(200,r.status_code,r.text);doc=r.json()
        r=self.client.post(self.scope(f"/documents/{doc['id']}/book"),json={'version':doc['version'],'reason':'Teste','idempotency_key':'book-party','generate_titles':True,'installments':[{'due_date':'2026-12-06','amount':'100.00'}]})
        self.assertEqual(200,r.status_code,r.text)
        return r.json()['document'],pid

    def test_postbooking_preserves_fiscal_and_titles(self):
        doc,pid=self.booked_document();titles=self.core.titles(self.a['id'])
        payload={'version':doc['version'],'idempotency_key':'account-party','lines':self.journal(amount='100.00')['lines']}
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(200,r.status_code,r.text);result=r.json()
        self.assertEqual(doc|{'journal_id':result['journal']['id']},result['document'])
        self.assertEqual(titles,self.core.titles(self.a['id']))
        self.assertEqual(pid,result['journal']['lines'][1]['participant_id'])
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(200,r.status_code,r.text);self.assertTrue(r.json()['duplicate'])
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload|{'idempotency_key':'another'})
        self.assertEqual(409,r.status_code,r.text)
        self.assertEqual(1,len(self.core.journals(self.a['id'])))

    def test_postbooking_rejects_titles_and_wrong_party(self):
        doc,pid=self.booked_document()
        payload={'version':doc['version'],'idempotency_key':'post','lines':self.journal(amount='100.00')['lines']}
        with self.assertRaises(DomainError):self.core.account_document(self.a['id'],doc['id'],payload|{'generate_titles':True},'test')
        payload['lines'][1]['participant_id']=self.party('P2')
        with self.assertRaises(DomainError):self.core.account_document(self.a['id'],doc['id'],payload,'test')
        self.assertEqual([],self.core.journals(self.a['id']))

    def test_postbooking_fiscal_closed_accounting_open(self):
        doc,pid=self.booked_document()
        r=self.client.post(self.scope('/periods/close'),json={'period':'2026-11','module':'fiscal','reason':'Teste'})
        self.assertEqual(200,r.status_code,r.text)
        result=self.core.account_document(self.a['id'],doc['id'],{'version':doc['version'],'idempotency_key':'after-close','lines':self.journal(amount='100.00')['lines']},'test')
        self.assertEqual(doc['version'],result['document']['version'])

    def test_legacy_schema6_backup_and_retry_preserves_lines(self):
        from app.db import Database
        from app.maintenance import integrity
        original=self.core.create_journal(self.a['id'],self.journal(),'test')
        with self.core.db.transaction() as conn:
            conn.execute('ALTER TABLE journal_lines DROP COLUMN participant_id')
        folder=self.core.db.data_dir
        with patch('app.migrations.migrate',side_effect=RuntimeError('interrompida')):
            with self.assertRaises(RuntimeError):Database(folder)
        backups=list((folder/'backups').glob('*.sqlite3'))
        self.assertTrue(backups)
        self.assertEqual(6,integrity(backups[-1])['schema_version'])
        migrated=Database(folder)
        self.assertIsNotNone(migrated.upgrade_backup)
        with migrated.read() as conn:
            lines=[dict(r) for r in conn.execute('SELECT * FROM journal_lines WHERE journal_id=?',(original['id'],))]
        self.assertEqual(2,len(lines));self.assertTrue(all(l['participant_id'] is None for l in lines))
        self.assertIsNone(Database(folder).upgrade_backup)

    def test_prosoft_uses_party_mapping_not_fixed_account_supplier(self):
        from app.prosoft import encode_journals
        pid=self.party();payload=self.journal();payload['document']='SYN';payload['lines'][1]['participant_id']=pid
        journal=self.core.create_journal(self.a['id'],payload,'test')
        mapping={str(l['account_id']):{'code':str(i+1),'confirmed':True,'third_mode':'none'} for i,l in enumerate(journal['lines'])}
        mapping[str(journal['lines'][1]['account_id'])].update(third_mode='required',third='WRONG')
        with self.assertRaises(DomainError):encode_journals([journal],mapping,{},'1')
        raw,_=encode_journals([journal],mapping,{},'1',participants={str(pid):{'code':'RIGHT','confirmed':True}})
        self.assertIn(b'RIGHT',raw);self.assertNotIn(b'WRONG',raw)

    def test_postbooking_concurrent_retry_creates_one_journal(self):
        from concurrent.futures import ThreadPoolExecutor
        doc,_=self.booked_document()
        payload={'version':doc['version'],'idempotency_key':'concurrent','lines':self.journal(amount='100.00')['lines']}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.core.account_document(self.a['id'],doc['id'],payload,'test'),range(2)))
        self.assertEqual(results[0]['journal']['id'],results[1]['journal']['id'])
        self.assertEqual(1,len(self.core.journals(self.a['id'])))
        self.assertEqual(1,len(self.core.titles(self.a['id'])))

    def test_postbooking_requires_fiscal_read_and_accounting_create(self):
        doc,_=self.booked_document()
        payload={'version':doc['version'],'idempotency_key':'permissions','lines':self.journal(amount='100.00')['lines']}
        for forbidden in [('fiscal.documents','read'),('accounting.journals','create')]:
            def reject(conn,cid,routine,action):
                if (routine,action)==forbidden:raise DomainError('Sem permissão',403)
            with patch('app.permissions.effect',side_effect=reject):
                with self.assertRaises(DomainError):self.core.account_document(self.a['id'],doc['id'],payload,'test')
        self.assertEqual([],self.core.journals(self.a['id']))

    def accounting_snapshot(self):
        with self.core.db.read() as conn:
            return {table:[dict(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('documents','journals','journal_lines','titles','operations')}

    def test_http_real_permissions_and_catalog_scope(self):
        from fastapi.testclient import TestClient
        doc,pid=self.booked_document()
        payload={'version':doc['version'],'idempotency_key':'real-permissions','lines':self.journal(amount='100.00')['lines']}
        before=self.accounting_snapshot()
        cases=[('fiscal-reader',[('fiscal.documents','read')],403),
               ('account-writer',[('accounting.journals','create'),('accounting.accounts','read')],403),
               ('account-reader',[('accounting.journals','read')],200)]
        for username,grants,catalog_status in cases:
            permissions=[{'company_id':self.a['id'],'routine':routine,'action':action,'effect':'allow'} for routine,action in grants]
            r=self.client.post('/api/users',json={'username':username,'password':'Synthetic-Reader-123!','role':'custom','company_ids':[self.a['id']],'permissions':permissions})
            self.assertEqual(201,r.status_code,r.text)
            with TestClient(self.app) as limited:
                r=limited.post('/api/login',json={'username':username,'password':'Synthetic-Reader-123!'})
                self.assertEqual(200,r.status_code,r.text)
                limited.headers['X-CSRF-Token']=r.json()['csrf_token']
                self.activate(self.a['id'],client=limited)
                for _ in range(2):
                    r=limited.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
                    self.assertEqual(403,r.status_code,r.text)
                r=limited.get(self.scope('/journal-participants'))
                self.assertEqual(catalog_status,r.status_code,r.text)
                if catalog_status==200:
                    self.assertEqual([pid],[p['id'] for p in r.json()])
                    self.assertEqual({'id','code','name','tax_id'},set(r.json()[0]))
                self.assertNotEqual(200,limited.get(self.scope('/journal-participants',self.b['id'])).status_code)
            self.assertEqual(before,self.accounting_snapshot())
        # Refused calls must not consume the idempotency key.
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(200,r.status_code,r.text)
        replay=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(200,replay.status_code,replay.text)
        self.assertTrue(replay.json()['duplicate'])

    def test_http_inactive_and_foreign_party_preserve_state(self):
        doc,pid=self.booked_document()
        payload={'version':doc['version'],'idempotency_key':'party-guard','lines':self.journal(amount='100.00')['lines']}
        self.activate(self.b['id'])
        r=self.client.post(self.scope('/masters/participant',self.b['id']),json={'code':'OTHER','name':'Fornecedor externo fictício','tax_id':'','data':{}})
        self.assertEqual(201,r.status_code,r.text);other=r.json()['id']
        self.activate(self.a['id'])
        payload['lines'][1]['participant_id']=other
        before=self.accounting_snapshot()
        for _ in range(2):
            r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
            self.assertEqual(400,r.status_code,r.text)
        self.assertEqual(before,self.accounting_snapshot())
        payload['lines'][1]['participant_id']=pid
        with self.core.db.transaction() as conn:conn.execute('UPDATE masters SET active=0 WHERE id=?',(pid,))
        before=self.accounting_snapshot()
        for _ in range(2):
            r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
            self.assertEqual(400,r.status_code,r.text)
        self.assertEqual(before,self.accounting_snapshot())
        self.assertEqual([],self.client.get(self.scope('/journal-participants')).json())

    def test_http_stale_version_and_context_are_atomic(self):
        doc,_=self.booked_document()
        payload={'version':doc['version'],'idempotency_key':'context-guard','lines':self.journal(amount='100.00')['lines']}
        before=self.accounting_snapshot()
        for _ in range(2):
            r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload|{'version':doc['version']-1})
            self.assertEqual(409,r.status_code,r.text)
        self.activate(self.b['id'])
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(409,r.status_code,r.text)
        self.activate(self.a['id'])
        r=self.client.post(self.scope('/exercises'),json={'module':'fiscal','year':2025})
        self.assertEqual(201,r.status_code,r.text)
        self.activate(self.a['id'],period='2025-11')
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(409,r.status_code,r.text)
        self.assertEqual(before,self.accounting_snapshot())
        self.activate(self.a['id'])
        r=self.client.post(self.scope(f"/documents/{doc['id']}/account"),json=payload)
        self.assertEqual(200,r.status_code,r.text)
