"""Only synthetic documents/journals; original vendor data and Prosoft are not needed."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import DomainError
from app.prosoft import encode_journals
from app.prosoft_fiscal import encode_fiscal
import test_prosoft_increment as prior


class CancellationCodecTests(unittest.TestCase):
    def cancelled(self, direction='incoming', **extra):
        return prior.document(direction, total_cents=0, document_state='cancelled',
                              book_cancellation={'source':'Synthetic book', 'responsible':'Synthetic', 'reason':'Reviewed'}, **extra)

    def test_exact_cancelled_and_regular_positions_zero_totals_identity_and_origin(self):
        for direction, name, position, width in [('incoming','ENTRADAS.TXT',809,2340), ('outgoing','SAIDAS.TXT',930,2611)]:
            with self.subTest(direction=direction):
                docs=[prior.document(direction),self.cancelled(direction,id=2)]
                before=deepcopy(docs)
                files, manifest=encode_fiscal(docs,prior.configuration())
                rows=files[name].splitlines()
                self.assertEqual([width,width],list(map(len,rows)))
                self.assertEqual([b'0',b'1'],[r[position-1:position] for r in rows])
                total_position=211 if direction=='incoming' else 34
                self.assertEqual(b'00000000000.00',rows[1][total_position-1:total_position+13])
                self.assertEqual([False,True],[r['cancelled'] for r in manifest['trace']])
                self.assertEqual('validated_fiscal_book',manifest['trace'][1]['cancellation_evidence'])
                self.assertEqual(('123456789','2026-10-30','2026-11-06'),tuple(manifest['trace'][1][k] for k in ('number','issue_date','posting_date')))
                self.assertEqual((2,1,10001),tuple(manifest['totals'][direction][k] for k in ('documents','cancelled_documents','total_cents')))
                self.assertFalse(manifest['skipped']);self.assertEqual(before,docs)
                self.assertEqual(files,encode_fiscal(docs,prior.configuration())[0])

    def test_unbooked_forged_or_nonzero_cancellation_cannot_become_a_valid_zero(self):
        files,manifest=encode_fiscal([self.cancelled(status='pending')],prior.configuration())
        self.assertFalse(files);self.assertEqual('not_booked',manifest['skipped'][0]['reason'])
        with self.assertRaises(DomainError):encode_fiscal([prior.document(document_state='cancelled')],prior.configuration())
        bad=self.cancelled();bad['total_cents']=1
        with self.assertRaises(DomainError):encode_fiscal([bad],prior.configuration())


class DocumentReferenceTests(unittest.TestCase):
    setUp=prior.AccountingCtaTests.setUp

    def encode(self, originals):
        journals=[dict(deepcopy(self.journal),id=i+1,number=i+1,document=value) for i,value in enumerate(originals)]
        before=deepcopy(journals)
        raw,manifest=encode_journals(journals,self.mappings,{},'1')
        self.assertEqual(before,journals)
        return raw,manifest

    def test_only_long_references_change_and_preserve_full_original_without_ascii_review(self):
        raw,manifest=self.encode(['1234567890','REFERÊNCIA CONTÁBIL EXTENSA'])
        lc=[r for r in raw.splitlines() if r.startswith(b'LC1')]
        self.assertEqual(b'1234567890',lc[0][20:30])
        ref=manifest['trace'][1]['document_reference']
        self.assertEqual('REFERÊNCIA CONTÁBIL EXTENSA',ref['original'])
        self.assertEqual(10,len(ref['exported']));self.assertTrue(ref['exported'].isascii())
        self.assertEqual(ref['exported'].encode(),lc[1][20:30])
        self.assertNotIn('document_reference',manifest['trace'][0])
        self.assertFalse(manifest['needs_ascii_review'])
        self.assertEqual('sha256-base32-10',ref['scheme']);self.assertEqual(64,len(ref['original_sha256']))

    def test_deterministic_independent_of_order_selection_and_repeated_original(self):
        originals=['SAIDAS-FISCAIS','OUTRA REFERENCIA LONGA','SAIDAS-FISCAIS']
        raw,manifest=self.encode(originals)
        self.assertEqual(raw,self.encode(originals)[0])
        mapping={r['document_reference']['original']:r['document_reference']['exported'] for r in manifest['trace']}
        self.assertEqual(2,len(set(mapping.values())))
        for original in reversed(originals):
            _,single=self.encode([original])
            self.assertEqual(mapping[original],single['trace'][0]['document_reference']['exported'])
        self.assertEqual(mapping['SAIDAS-FISCAIS'],manifest['trace'][2]['document_reference']['exported'])

    def test_hash_collisions_and_collision_with_unchanged_short_reference_are_explicit(self):
        for originals in [['LONG REFERENCE ONE','LONG REFERENCE TWO'],['COLLIDE123','LONG REFERENCE ONE']]:
            with self.subTest(originals=originals),patch('app.prosoft._short_document_reference',return_value='COLLIDE123'):
                with self.assertRaises(DomainError) as raised:self.encode(originals)
                self.assertEqual('document_reference_collision',raised.exception.code)

    def test_control_characters_are_rejected_instead_of_hidden_in_alias(self):
        for value in ['LONG\nREFERENCE','LONG\tREFERENCE','SHORT\x00']:
            with self.subTest(value=value),self.assertRaises(DomainError):self.encode([value])


class ProsoftCancellationReferenceApiTests(unittest.TestCase):
    setUp=prior.ProsoftApiTests.setUp
    tearDown=prior.ProsoftApiTests.tearDown
    scope=prior.ProsoftApiTests.scope
    activate=prior.ProsoftApiTests.activate
    create_company=prior.ProsoftApiTests.create_company
    document=prior.ProsoftApiTests.document
    journal=prior.ProsoftApiTests.journal
    post=prior.ProsoftApiTests.post
    economic_snapshot=prior.ProsoftApiTests.economic_snapshot

    def cancellation(self,direction,number):
        payload=self.document(number)|{'direction':direction,'cfop':'1102' if direction=='incoming' else '5102',
            'total':'0.00','taxes':{},'items':[],'source_hash':'','partner_tax_id':'11222333000181',
            'book_cancellation':{'source':'Synthetic reviewed book','responsible':'Synthetic','reason':'Reviewed'}}
        doc=self.post('/documents',payload,201)
        doc=self.post(f"/documents/{doc['id']}/review",{'version':doc['version'],'reason':'Synthetic review'})
        return self.post(f"/documents/{doc['id']}/book",{'version':doc['version'],'reason':'Synthetic booking'})['document']

    def accounting_payload(self):
        return {'period':'2026-11','company_code':'99','accounts':{
            str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts},'allow_ascii':True}

    def cancelled_download_case(self):
        docs=[self.cancellation('incoming','901'),self.cancellation('outgoing','902')]
        before=self.economic_snapshot()
        for module in ('fiscal','accounting'):
            self.post('/periods/close',{'module':module,'period':'2026-11','reason':'Synthetic close'})
        payload=prior.configuration()|{'period':'2026-11','company_code':'99'}
        preview=self.post('/prosoft-fiscal/preview',payload)
        confirm=payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True}
        result=self.post('/prosoft-fiscal/confirm',confirm)
        self.assertEqual(result['id'],self.post('/prosoft-fiscal/confirm',confirm)['id'])
        response=self.client.get(self.scope(f"/prosoft-fiscal/exports/{result['id']}/download"))
        self.assertEqual(200,response.status_code)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(b'1',archive.read('ENTRADAS.TXT')[808:809])
            self.assertEqual(b'1',archive.read('SAIDAS.TXT')[929:930])
            trace=json.loads(archive.read('manifest.json'))['trace']
            self.assertEqual({d['id'] for d in docs},{r['document_id'] for r in trace})
            self.assertTrue(all(r['cancelled'] for r in trace))
        self.assertEqual(before,self.economic_snapshot())
        return result['id']

    def test_cancelled_download_repeat_closed_period_and_economic_state(self):
        self.cancelled_download_case()

    def test_long_reference_saved_manifest_download_replay_and_original_preserved(self):
        journal=self.core.create_journal(self.a['id'],self.journal()|{'document':'SAIDAS-FISCAIS','history':'Synthetic'},'synthetic')
        before=self.economic_snapshot();payload=self.accounting_payload()
        preview=self.post('/prosoft/preview',payload)
        confirm=payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True}
        saved=self.post('/prosoft/confirm',confirm)
        self.assertEqual(saved['id'],self.post('/prosoft/confirm',confirm)['id'])
        response=self.client.get(self.scope(f"/prosoft/exports/{saved['id']}/manifest"))
        self.assertEqual(200,response.status_code);self.assertEqual(saved['manifest'],response.json())
        ref=response.json()['trace'][0]['document_reference']
        self.assertEqual('SAIDAS-FISCAIS',ref['original'])
        download=self.client.get(self.scope(f"/exports/{saved['id']}/download"))
        self.assertEqual(ref['exported'].encode(),download.content[20:30])
        self.assertEqual('SAIDAS-FISCAIS',self.core.journals(self.a['id'])[0]['document'])
        self.assertEqual(before,self.economic_snapshot())
        self.activate(self.b['id'])
        self.assertEqual(404,self.client.get(self.scope(f"/prosoft/exports/{saved['id']}/manifest",self.b['id'])).status_code)

    def test_manifest_cannot_cross_layout_or_bypass_export_permission(self):
        fiscal=self.cancelled_download_case()
        self.assertEqual(404,self.client.get(self.scope(f'/prosoft/exports/{fiscal}/manifest')).status_code)
        self.post('/periods/reopen',{'module':'accounting','period':'2026-11','reason':'Synthetic reopen'})
        self.core.create_journal(self.a['id'],self.journal()|{'document':'SAIDAS-FISCAIS','history':'Synthetic'},'synthetic')
        payload=self.accounting_payload();pre=self.post('/prosoft/preview',payload)
        saved=self.post('/prosoft/confirm',payload|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        created=self.client.post('/api/users',json={'username':'manifest-read','password':'Senha-ficticia-123!','role':'operator',
            'company_ids':[self.a['id']],'permissions':[{'company_id':self.a['id'],'routine':'accounting.prosoft','action':'read','effect':'allow'}]})
        self.assertEqual(201,created.status_code,created.text)
        with TestClient(self.app) as other:
            login=other.post('/api/login',json={'username':'manifest-read','password':'Senha-ficticia-123!'}).json()
            other.headers['X-CSRF-Token']=login['csrf_token'];self.activate(self.a['id'],client=other)
            self.assertEqual(403,other.get(self.scope(f"/prosoft/exports/{saved['id']}/manifest")).status_code)

    def test_collision_rolls_back_without_new_batch_or_audit(self):
        for i in (1,2):
            self.core.create_journal(self.a['id'],self.journal(key=f'synthetic-{i}')|{'document':f'LONG REFERENCE {i}','history':'Synthetic'},'synthetic')
        payload=self.accounting_payload();preview=self.post('/prosoft/preview',payload)
        with self.core.db.read() as conn:
            before={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('audit','export_batches')}
        with patch('app.prosoft._short_document_reference',return_value='COLLIDE123'):
            result=self.post('/prosoft/confirm',payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True},409)
            self.assertEqual('document_reference_collision',result['code'])
        with self.core.db.read() as conn:
            self.assertEqual(before,{t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before})


if __name__=='__main__':unittest.main()
