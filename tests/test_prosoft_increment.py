"""Fixtures entirely synthetic; tests do not need vendor files or destination access."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from zipfile import ZipFile
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.core import DomainError, digest
from app.prosoft import encode_journals
from app.prosoft_fiscal import archive, encode_fiscal, decimal_field, date_field
import test_core as base


def treatment():
    return {'code': 'SYNTHETIC', 'book_mode': 'other_excluding_ipi',
            'source': 'Decisão exclusivamente sintética', 'responsible': 'Teste',
            'valid_from': '2026-01-01'}


def document(direction='incoming', **extra):
    return {'id': 1, 'status': 'booked', 'model': '55', 'direction': direction,
            'number': '123456789', 'series': '001', 'issue_date': '2026-10-30',
            'posting_date': '2026-11-06', 'total_cents': 10001,
            'cfop': '1102' if direction == 'incoming' else '5102',
            'items': [], 'taxes': {}, 'source': {'file': 'synthetic.xml'},
            'source_hash': 'synthetic-source', 'key': '',
            'partner_tax_id': '11222333000181',
            'issuer': {'state': 'SP', 'ie': '123'}, 'recipient': {'state': 'RJ', 'ie': '456'},
            'fiscal_treatment': treatment(), **extra}


def configuration():
    return {'species': {'55': {'code': 'NFE', 'confirmed': True}, '65': {'code': 'NFCE', 'confirmed': True}},
            'cfop_accounts': {'1102': {'code': '123', 'confirmed': True}, '5102': {'code': '456', 'confirmed': True}}}


class FiscalCodecTests(unittest.TestCase):
    def test_fields_offsets_modern_number_dates_and_blank_legacy(self):
        files, manifest = encode_fiscal([document(), document('outgoing', id=2)], configuration())
        a, b = files['ENTRADAS.TXT'][:-2], files['SAIDAS.TXT'][:-2]
        self.assertEqual((2340, 2611), (len(a), len(b)))
        self.assertEqual(b'061126301026', a[18:30])
        self.assertEqual(b'061126', b[19:25]); self.assertEqual(b'301026', b[727:733])
        self.assertEqual(b'0123456789', a[868:878]); self.assertEqual(b'01234567890123456789', b[988:1008])
        self.assertEqual(b'NFE   001', a[857:866]); self.assertEqual(b'NFE   001', b[977:986])
        self.assertEqual(b' ' * 9, b[0:9]); self.assertEqual(b' ' * 6, a[30:36])
        self.assertEqual(b'00123', a[43:48]); self.assertEqual(b'00456', b[25:30])
        self.assertEqual(b'1102', a[623:627]); self.assertEqual(b'5102', b[733:737])
        self.assertEqual(b'00000000100.01', a[210:224]); self.assertEqual(a[210:224], b[33:47])
        self.assertEqual(b'00000000100.01', a[107:121]); self.assertEqual(b'00000000000.00', a[65:79])
        self.assertEqual(b'11222333000181', a[4:18]); self.assertEqual(b'RJ', b[272:274])
        self.assertEqual(b' ' * (2611-2251), b[2251:])  # no invented IBS/CBS
        self.assertEqual(10001, manifest['totals']['incoming']['total_cents'])
        self.assertFalse(manifest['homologated_in_destination']); self.assertFalse(manifest['official_efd'])
        self.assertTrue(all(raw.endswith(b'\r\n') for raw in files.values()))

    def test_split_lines_reconcile_exactly_and_preserve_origin_and_classification(self):
        items = [{'number': str(i), 'cfop': cfop, 'total': value, 'taxes': {}, 'description': 'Synthetic', 'quantity': '1'}
                 for i, cfop, value in [(1, '1102', '33.33'), (2, '1101', '66.68')]]
        files, m = encode_fiscal([document(items=items)], configuration())
        lines = files['ENTRADAS.TXT'].splitlines()
        self.assertEqual(2, len(lines)); self.assertEqual([b'1', b'2'], [v[42:43] for v in lines])
        self.assertEqual([b'1102', b'1101'], [v[623:627] for v in lines])
        self.assertEqual(10001, sum(t['total_cents'] for t in m['trace']))
        self.assertEqual([['1'], ['2']], [r['item_numbers'] for r in m['trace']])
        self.assertEqual('synthetic.xml', m['trace'][0]['source']['file'])
        self.assertEqual('2026-10-30', m['trace'][0]['issue_date'])
        self.assertEqual(2, m['totals']['incoming']['records'])
        self.assertEqual(1, m['totals']['incoming']['documents'])

    def test_missing_treatment_fields_remain_blank_with_warning(self):
        files, m = encode_fiscal([document(fiscal_treatment={}, taxes={'ICMSTot.vBC': '80.00', 'ICMSTot.vICMS': '14.40'})], configuration())
        line = files['ENTRADAS.TXT'].splitlines()[0]
        self.assertEqual(b' ' * 56, line[65:121])
        self.assertIn('FISCAL_TREATMENT_REQUIRED', m['warnings'][0]['codes'])
        self.assertIn('BOOK_ICMS_NOT_INFORMED', m['warnings'][0]['codes'])

    def test_declared_icms_requires_existing_book_decision(self):
        d = document(analytics=[{'cfop':'1102','operation_total':'100.01','rate':'18.00','cst_icms':'000',
                                 'taxes':{'VL_BC_ICMS':'100.01','VL_ICMS':'18.00'}}],
                     fiscal_treatment=treatment() | {'book_mode':'declared_icms'})
        files, m = encode_fiscal([d], configuration())
        line = files['ENTRADAS.TXT'].splitlines()[0]
        self.assertEqual(b'00000000100.01', line[65:79]); self.assertEqual(b'00000000018.00', line[79:93])
        self.assertEqual(b'18.00', line[135:140]); self.assertEqual(b' ' * 14, line[107:121])
        self.assertEqual('000', m['trace'][0]['classification']['cst_icms'])

    def test_unknown_species_unsupported_pending_and_cancelled_are_explicit(self):
        docs = [document(id=1, model='57'), document(id=2, status='pending'),
                document(id=3, book_cancellation={'source':'Synthetic book'}), document(id=4)]
        files, m = encode_fiscal(docs, {})
        self.assertFalse(files); self.assertEqual(4, len(m['skipped']))
        self.assertEqual({'model_not_supported','not_booked','cancellation_not_supported','species_mapping_required'}, {v['reason'] for v in m['skipped']})
        self.assertEqual(40004, sum(v['total_cents'] for v in m['skipped']))

    def test_no_rounding_truncation_or_control_characters(self):
        for extra in [{'number':'1'*11}, {'series':'1234'}, {'key':'1'*43}, {'number':'१२'},
                      {'issuer':{'ie':'abc\nxyz','state':'SP'}}, {'issue_date':'1999-01-01'}]:
            with self.subTest(extra=extra), self.assertRaises(DomainError): encode_fiscal([document(**extra)], configuration())
        with self.assertRaises(DomainError): decimal_field('100000000000.00')
        with self.assertRaises(DomainError): decimal_field('-0.01')
        with self.assertRaises(DomainError): decimal_field('0.001')
        self.assertEqual('010100', date_field('2000-01-01'))
        self.assertEqual('311299', date_field('2099-12-31'))

    def test_unsupported_rate_cpf_alpha_id_warn_without_fabrication(self):
        d = document(partner_tax_id='12345678901', analytics=[{'cfop':'1102','operation_total':'100.01','rate':'2.4375','taxes':{}}])
        files, m = encode_fiscal([d], configuration())
        row = files['ENTRADAS.TXT'].splitlines()[0]
        self.assertEqual(b' '*14, row[4:18]); self.assertEqual(b' '*5, row[135:140])
        self.assertIn('RATE_NOT_REPRESENTABLE', m['warnings'][0]['codes'])
        self.assertIn('PARTNER_CNPJ_NOT_REPRESENTABLE', m['warnings'][0]['codes'])
        files, m = encode_fiscal([document(partner_tax_id='12ABC34501DE35')], configuration())
        self.assertEqual(b' '*14, files['ENTRADAS.TXT'][4:18])

    def test_ascii_change_review_and_deterministic_archive_without_mutation(self):
        d = document(issuer={'state':'SP','ie':'ISENTÁ'}); before = deepcopy(d)
        files, m = encode_fiscal([d], configuration())
        self.assertEqual(before, d); self.assertTrue(m['needs_ascii_review'])
        accepted_files, accepted_m = encode_fiscal([d], configuration() | {'allow_ascii':True})
        self.assertEqual(archive(files, m), archive(accepted_files, accepted_m))
        with ZipFile(BytesIO(archive(files, m))) as z:
            self.assertEqual(['ENTRADAS.TXT','manifest.json'], z.namelist())
            self.assertEqual(m, json.loads(z.read('manifest.json')))

    def test_total_mismatch_and_too_many_splits_are_technical_errors(self):
        d = document(analytics=[{'cfop':'1102','operation_total':'99.99','taxes':{}}])
        with self.assertRaises(DomainError) as raised: encode_fiscal([d], configuration())
        self.assertEqual('fiscal_total_mismatch', raised.exception.code)
        d['total_cents'] = 3600
        d['analytics'] = [{'cfop':'1102','operation_total':'1.00','taxes':{}} for _ in range(36)]
        with self.assertRaises(DomainError): encode_fiscal([d], configuration())

    def test_configuration_shapes_are_rejected_cleanly(self):
        for p in [{'species':[]}, {'species':{'55':[]}}, {'cfop_accounts':[]}, {'cfop_accounts':{'1102':[]}}]:
            with self.assertRaises(DomainError): encode_fiscal([document()], p)


class AccountingCtaTests(unittest.TestCase):
    def setUp(self):
        self.journal = {'id':1,'number':1,'date':'2026-11-06','document':'TEST1','history':'Synthetic',
                        'total_cents':10001,'lines':[{'account_id':1,'access_code':'1','debit_cents':10001,'credit_cents':0},
                                                   {'account_id':2,'access_code':'2','debit_cents':0,'credit_cents':10001}]}
        self.mappings = {'1':{'code':'123','confirmed':True,'third_mode':'none','create_account':{
            'destination_missing':True,'classifier':'1.01.001','name':'Conta sintetica','cost_center_mode':'0','reconciliation':'0'}},
                         '2':{'code':'456','confirmed':True}}

    def test_cta_precedes_lc1_and_validates_positions_filler_and_totals(self):
        raw, m = encode_journals([self.journal], self.mappings, {}, '1')
        cta, lc = raw.splitlines()
        self.assertEqual((208,448),(len(cta),len(lc)))
        self.assertEqual(b'CTA00001   00123',cta[:16])
        self.assertEqual(b'101001000000000',cta[16:31])
        self.assertEqual(b'10',cta[61:63]);self.assertEqual(b'0',cta[163:164])
        self.assertEqual(b' '*44,cta[164:]);self.assertEqual(b'LC100001',lc[:8])
        self.assertEqual({'CTA':1,'LC1':1,'LC2':0},m['record_counts'])
        self.assertEqual(10001,m['debit_cents']);self.assertEqual(m['debit_cents'],m['credit_cents'])
        self.assertFalse(m['homologated_in_destination'])

    def test_unused_accounts_never_emit_cta_and_omission_preserves_lc(self):
        self.mappings['999'] = deepcopy(self.mappings['1'])
        raw, m = encode_journals([self.journal], self.mappings, {}, '1')
        self.assertEqual(1,m['record_counts']['CTA'])
        self.mappings['1'].pop('create_account')
        raw, m = encode_journals([self.journal], self.mappings, {}, '1')
        self.assertEqual(450,len(raw));self.assertEqual(0,m['record_counts']['CTA'])

    def test_cta_explicit_missing_flag_and_policies_and_no_truncation(self):
        for key, value in [('destination_missing',False),('name','x'*31),('classifier','1'*16),
                           ('cost_center_mode','9'),('reconciliation','9'),('unknown','x')]:
            mapping=deepcopy(self.mappings);mapping['1']['create_account'][key]=value
            with self.subTest(key=key),self.assertRaises(DomainError):encode_journals([self.journal],mapping,{},'1')
        mapping=deepcopy(self.mappings);mapping['1'].pop('third_mode')
        with self.assertRaises(DomainError):encode_journals([self.journal],mapping,{},'1')

    def test_cta_conflicting_destination_and_required_center(self):
        mapping=deepcopy(self.mappings);mapping['2']=deepcopy(mapping['1'])
        mapping['2']['create_account']['name']='Outra conta sintetica'
        with self.assertRaises(DomainError):encode_journals([self.journal],mapping,{},'1')
        self.mappings['1']['create_account']['cost_center_mode']='3'
        with self.assertRaises(DomainError):encode_journals([self.journal],self.mappings,{},'1')

    def test_duplicate_cta_definition_deduplicates_before_detailed_journal(self):
        j=deepcopy(self.journal)
        j['lines']=[dict(j['lines'][0],debit_cents=5000),dict(j['lines'][0],account_id=3,debit_cents=5001),j['lines'][1]]
        mappings=deepcopy(self.mappings);mappings['3']=deepcopy(mappings['1'])
        raw,m=encode_journals([j],mappings,{},'1')
        self.assertEqual([208,448,342,342,342],list(map(len,raw.splitlines())))
        self.assertEqual([1,1],[v['order'] for v in m['account_registrations']])
        self.assertEqual({'CTA':1,'LC1':1,'LC2':3},m['record_counts'])

    def test_cta_required_center_with_confirmed_mapping_and_zero_rejected(self):
        self.journal['lines'][0]['cost_center_id']=7
        self.mappings['1']['create_account']['cost_center_mode']='3'
        raw,m=encode_journals([self.journal],self.mappings,{'7':{'code':'12','confirmed':True}},'1')
        self.assertEqual(b'13',raw[61:63]);self.assertEqual(1,m['record_counts']['CTA'])
        self.mappings['1']['code']='00000'
        with self.assertRaises(DomainError):encode_journals([self.journal],self.mappings,{},'1')

    def test_cta_ascii_review_and_special_plan_fields(self):
        c=self.mappings['1']['create_account'];c.update(name='Conta sintética',special_classifier='2.01',special_name='Especial')
        raw,m=encode_journals([self.journal],self.mappings,{},'1')
        self.assertTrue(m['needs_ascii_review']);self.assertEqual(b'20100000000000000000',raw[63:83])
        self.assertEqual(b'Especial',raw[83:91])


class ProsoftApiTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company
    document=base.CoreApiTests.document
    journal=base.CoreApiTests.journal

    def post(self,path,payload,status=200):
        r=self.client.post(self.scope(path),json=payload)
        self.assertEqual(status,r.status_code,r.text)
        return r.json()

    def booked(self,number='123456789',**extra):
        payload=self.document(number)|{'fiscal_treatment':treatment(),'partner_tax_id':'11222333000181',
                                       'issuer':{'state':'SP','ie':'123'}}|extra
        if not payload.get('fiscal_treatment'):payload.pop('fiscal_treatment',None)
        d=self.post('/documents',payload,201)
        d=self.post(f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Teste sintetico'})
        return self.post(f"/documents/{d['id']}/book",{'version':d['version'],'reason':'Teste sintetico','lines':[]})['document']

    def payload(self,**extra):return configuration()|{'period':'2026-11','company_code':'99'}|extra

    def confirm(self,p):
        pre=self.post('/prosoft-fiscal/preview',p)
        r=self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        return pre,r

    def economic_snapshot(self):
        with self.core.db.read() as c:
            return {t:digest([dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')])
                    for t in ['documents','document_sources','journals','journal_lines','titles','imports']}

    def test_preview_is_read_only_confirmation_download_replay_and_scoped(self):
        d=self.booked();before=self.economic_snapshot();p=self.payload()
        pre=self.post('/prosoft-fiscal/preview',p)
        with self.core.db.read() as c:self.assertEqual(0,c.execute('SELECT count(*) FROM export_batches').fetchone()[0])
        self.assertEqual('0050',pre['manifest']['plan_code'])
        r=self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        again=self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        self.assertEqual(r['id'],again['id']);self.assertTrue(again['duplicate'])
        download=self.client.get(self.scope(f"/prosoft-fiscal/exports/{r['id']}/download"))
        self.assertEqual(200,download.status_code);self.assertEqual(pre['sha256'],digest(download.content))
        with ZipFile(BytesIO(download.content)) as z:
            m=json.loads(z.read('manifest.json'));self.assertEqual(d['id'],m['trace'][0]['document_id'])
            self.assertEqual('2026-10-30',m['trace'][0]['issue_date'])
        self.assertEqual(before,self.economic_snapshot())
        self.activate(self.b['id'])
        self.assertEqual(404,self.client.get(self.scope(f"/prosoft-fiscal/exports/{r['id']}/download",self.b['id'])).status_code)

    def test_source_or_mapping_plan_and_selection_changes_invalidate_preview(self):
        d=self.booked();p=self.payload();pre=self.post('/prosoft-fiscal/preview',p)
        for change in [{'plan_code':'51'},{'company_code':'98'},
                       {'species':{'55':{'code':'NF','confirmed':True}}}, {'cfop_accounts':{}}]:
            self.post('/prosoft-fiscal/confirm',p|change|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},409)
        with self.core.db.transaction() as c:c.execute('UPDATE documents SET total_cents=10001 WHERE id=?',(d['id'],))
        self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},409)

    def test_selection_uses_posting_month_and_rejects_other_company_or_invalid_ids(self):
        current=self.booked();self.activate(self.a['id'],'2026-10')
        old=self.booked('222',posting_date='2026-10-30');self.activate(self.a['id'])
        pre=self.post('/prosoft-fiscal/preview',self.payload())
        self.assertEqual([current['id']],[r['document_id'] for r in pre['manifest']['trace']])
        for ids in [[],[old['id']],[current['id'],current['id']],[True],[{}],['1']]:
            self.post('/prosoft-fiscal/preview',self.payload(document_ids=ids),400)
        foreign=self.core.create_document(self.b['id'],self.document('333'),'teste')
        self.post('/prosoft-fiscal/preview',self.payload(document_ids=[foreign['id']]),400)
        self.post('/prosoft-fiscal/preview',self.payload(period='2025-11'),409)

    def test_export_allowed_closed_period_without_changing_economic_records(self):
        self.booked();before=self.economic_snapshot()
        for module in ['fiscal','accounting']:
            self.post('/periods/close',{'period':'2026-11','module':module,'reason':'Teste de fechamento'})
        self.confirm(self.payload())
        self.assertEqual(before,self.economic_snapshot())
        self.post('/periods/reopen',{'period':'2026-11','module':'fiscal','reason':'Teste de reabertura'})
        self.confirm(self.payload())

    def test_concurrent_confirm_creates_single_batch(self):
        self.booked();p=self.payload();pre=self.post('/prosoft-fiscal/preview',p)
        payload=p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True}
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda _:self.core.export_prosoft_fiscal(self.a['id'],payload,'teste',True),range(2)))
        self.assertEqual(1,len({v['id'] for v in values}));self.assertEqual(1,sum(v.get('duplicate',False) for v in values))

    def test_missing_decisions_are_warnings_and_do_not_prevent_export(self):
        self.booked(fiscal_treatment={});pre,r=self.confirm(self.payload(cfop_accounts={}))
        self.assertTrue(pre['manifest']['warnings']);self.assertIsInstance(r['id'],int)
        self.assertFalse(pre['manifest']['homologated_in_destination'])

    def test_empty_selection_has_explanation_and_no_confirm_or_batch(self):
        pre=self.post('/prosoft-fiscal/preview',self.payload())
        self.assertEqual(0,pre['manifest']['selection_count'])
        self.post('/prosoft-fiscal/confirm',self.payload()|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},400)
        self.booked();pre=self.post('/prosoft-fiscal/preview',self.payload(species={}))
        self.assertEqual('species_mapping_required',pre['manifest']['skipped'][0]['reason'])

    def test_confirm_requires_current_hash_destination_and_ascii_review(self):
        self.booked(issuer={'state':'SP','ie':'ISENTÁ'});p=self.payload();pre=self.post('/prosoft-fiscal/preview',p)
        self.post('/prosoft-fiscal/confirm',p|{'destination_reviewed':True},409)
        self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash']},400)
        self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},400)
        r=self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True,'allow_ascii':True})
        self.assertEqual(pre['sha256'],r['sha256'])

    def test_fiscal_permission_cannot_download_accounting_and_reverse(self):
        self.booked();_,fiscal=self.confirm(self.payload())
        self.core.create_journal(self.a['id'],self.journal()|{'document':'SYNTHETIC'},'teste')
        p={'period':'2026-11','company_code':'99','accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts},'allow_ascii':True}
        pre=self.post('/prosoft/preview',p)
        accounting=self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        for routine,allowed_id,other_id in [('fiscal.prosoft',fiscal['id'],accounting['id']),('accounting.prosoft',accounting['id'],fiscal['id'])]:
            response=self.client.post('/api/users',json={'username':routine,'password':'Senha-ficticia-123!','role':'operator',
                'company_ids':[self.a['id']],'permissions':[{'company_id':self.a['id'],'routine':routine,'action':action,'effect':'allow'} for action in ['read','export']]})
            self.assertEqual(201,response.status_code,response.text)
            with TestClient(self.app) as other:
                login=other.post('/api/login',json={'username':routine,'password':'Senha-ficticia-123!'}).json()
                other.headers['X-CSRF-Token']=login['csrf_token'];self.activate(self.a['id'],client=other)
                if routine=='fiscal.prosoft':
                    self.assertEqual(200,other.get(self.scope(f'/prosoft-fiscal/exports/{allowed_id}/download')).status_code)
                    self.assertEqual(404,other.get(self.scope(f'/prosoft-fiscal/exports/{other_id}/download')).status_code)
                    self.assertEqual(403,other.get(self.scope(f'/exports/{other_id}/download')).status_code)
                    self.assertEqual(200,other.post(self.scope('/prosoft-fiscal/preview'),json=self.payload()).status_code)
                else:
                    self.assertEqual(200,other.get(self.scope(f'/exports/{allowed_id}/download')).status_code)
                    self.assertEqual(403,other.get(self.scope(f'/exports/{other_id}/download')).status_code)
                    self.assertEqual(403,other.post(self.scope('/prosoft-fiscal/preview'),json=self.payload()).status_code)
        self.assertEqual(403,self.client.post(self.scope('/prosoft-fiscal/preview'),headers={'X-CSRF-Token':''},json=self.payload()).status_code)

    def test_confirmation_failure_rolls_back_batch_and_audit(self):
        self.booked();p=self.payload();pre=self.post('/prosoft-fiscal/preview',p)
        with self.core.db.read() as conn:
            before=conn.execute('SELECT count(*) FROM audit').fetchone()[0]
        with patch('app.prosoft_fiscal.audit',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.core.export_prosoft_fiscal(self.a['id'],p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},'teste',True)
        with self.core.db.read() as conn:
            self.assertEqual(0,conn.execute('SELECT count(*) FROM export_batches').fetchone()[0])
            self.assertEqual(before,conn.execute('SELECT count(*) FROM audit').fetchone()[0])

    def test_all_source_references_retained_and_source_change_invalidates_preview(self):
        d=self.booked();p=self.payload();pre=self.post('/prosoft-fiscal/preview',p)
        with self.core.db.transaction() as c:
            c.execute('INSERT INTO document_sources(company_id,document_id,source_hash,source_json,created_at) VALUES(?,?,?,?,?)',
                      (self.a['id'],d['id'],'synthetic-second-source','{"file":"synthetic-second.xml"}','2026-11-06'))
        self.post('/prosoft-fiscal/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},409)
        new=self.post('/prosoft-fiscal/preview',p)
        self.assertIn('synthetic-second-source',[s['source_hash'] for s in new['manifest']['trace'][0]['sources']])

    def test_historical_default_plan_batch_identity_is_preserved(self):
        from app.core import pack,now
        j=self.core.create_journal(self.a['id'],self.journal()|{'document':'SYNTHETIC','history':'Synthetic'},'teste')
        mappings={str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts if a['id'] in {v['account_id'] for v in j['lines']}}
        p={'period':'2026-11','company_code':'99','accounts':mappings,'centers':{}}
        raw,m=encode_journals([j],mappings,{},'1')
        old_fingerprint=digest({'content_sha256':digest(raw),'configuration':mappings,'participants':{},'centers':{},'company_code':'0099','period':'2026-11','journals':[j]})
        with self.core.db.transaction() as c:
            existing=c.execute('INSERT INTO export_batches(company_id,period,layout,fingerprint,filename,content,manifest_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
              (self.a['id'],'2026-11','CTBLCTOS-LC1-LC2-448-342',old_fingerprint,'CTBLCTOS0099_202611.TXT',raw,pack(m),now(),'teste')).lastrowid
        pre=self.post('/prosoft/preview',p)
        self.assertEqual(old_fingerprint,pre['preview_hash'])
        r=self.post('/prosoft/confirm',p|{'plan_code':'050','preview_hash':pre['preview_hash'],'destination_reviewed':True})
        self.assertEqual(existing,r['id']);self.assertTrue(r['duplicate'])

    def test_cta_api_hash_accounts_and_alternate_plan_and_legacy_download(self):
        self.core.create_journal(self.a['id'],self.journal()|{'document':'SYNTHETIC'},'teste')
        mappings={str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts}
        mappings[str(self.aid['3'])].update(third_mode='none',create_account={'destination_missing':True,'classifier':'1.01',
                 'name':'Conta sintetica','cost_center_mode':'0','reconciliation':'0'})
        p={'period':'2026-11','company_code':'99','plan_code':'52','accounts':mappings,'allow_ascii':True}
        pre=self.post('/prosoft/preview',p);self.assertEqual('0052',pre['manifest']['plan_code'])
        self.assertEqual(1,pre['manifest']['record_counts']['CTA'])
        self.post('/prosoft/confirm',p|{'plan_code':'50','preview_hash':pre['preview_hash'],'destination_reviewed':True},409)
        r=self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        raw=self.client.get(self.scope(f"/exports/{r['id']}/download")).content
        self.assertEqual([208,448],list(map(len,raw.splitlines())))
        self.assertTrue(self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})['duplicate'])


if __name__=='__main__':unittest.main()
