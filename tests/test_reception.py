"""Synthetic reception evidence. No certificate, remote fiscal call or live NSU."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET

import test_core as base
from app.importers import ImportProblem, parse_file
from app.reception import (ADN_ENDPOINTS, NFE_NS, SOAP_NS, adn_request, adn_rejection,
                           nfe_request, read_nfe_distribution)

FIXTURE = Path(__file__).parent / 'fixtures/nfe_ficticia.xml'
SUMMARY = f'<resNFe xmlns="{NFE_NS}" versao="1.01"><chNFe>35261187654321000198550010000000421000000420</chNFe></resNFe>'.encode()
EVENT = f'<procEventoNFe xmlns="{NFE_NS}" versao="1.00"/>'.encode()


def response(entries=(), status='138', environment='2', last='3', maximum='4', soap=False):
    root = ET.Element(f'{{{NFE_NS}}}retDistDFeInt', versao='1.01')
    for name, value in [('tpAmb', environment), ('cStat', status), ('ultNSU', last), ('maxNSU', maximum)]:
        ET.SubElement(root, f'{{{NFE_NS}}}{name}').text = value
    lot = ET.SubElement(root, f'{{{NFE_NS}}}loteDistDFeInt')
    for current, schema, raw in entries:
        packet = ET.SubElement(lot, f'{{{NFE_NS}}}docZip', NSU=current, schema=schema)
        packet.text = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    if soap:
        envelope = ET.Element(f'{{{SOAP_NS}}}Envelope')
        ET.SubElement(envelope, f'{{{SOAP_NS}}}Body').append(root)
        root = envelope
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def mixed(raw=None, soap=False):
    return response([('1', 'procNFe_v4.00.xsd', raw or FIXTURE.read_bytes()),
                     ('2', 'resNFe_v1.01.xsd', SUMMARY),
                     ('3', 'procEventoNFe_v1.00.xsd', EVENT)], soap=soap)


class ReceptionProtocolTests(unittest.TestCase):
    def test_nfe_plan_contains_only_dist_nsu_and_fixed_environment(self):
        for environment, code in [('production','1'), ('homologation','2')]:
            request = nfe_request('11222333000181', '35', environment, '42')
            root = ET.fromstring(request['body'])
            self.assertEqual('POST', request['method'])
            self.assertEqual('000000000000042', next(root.iter(f'{{{NFE_NS}}}ultNSU')).text)
            self.assertEqual(code, next(root.iter(f'{{{NFE_NS}}}tpAmb')).text)
            self.assertEqual(1, len(list(root.iter(f'{{{NFE_NS}}}distNSU'))))
            self.assertFalse(request['network_executed'])
            for forbidden in [b'envEvento', b'consChNFe', b'enviNFe', b'110110', b'210210']:
                self.assertNotIn(forbidden, request['body'])

    def test_query_plans_reject_unsupported_inputs_and_never_fallback_environment(self):
        for value in ['', '-1', '1'*16, '１２', 1, True]:
            with self.subTest(value=value), self.assertRaises(ImportProblem):
                nfe_request('11222333000181','35','production',value)
        for args in [('12ABC34501DE30','35','production','0'), ('11222333000181','99','production','0'), ('11222333000181','35','restricted_production','0')]:
            with self.assertRaises(ImportProblem): nfe_request(*args)
        with self.assertRaises(ImportProblem): adn_request('11222333000181','homologation','0')

    def test_adn_explicit_target_cpf_or_cnpj_and_separate_environments(self):
        for environment, endpoint in ADN_ENDPOINTS.items():
            request = adn_request('11222333000181', environment, '42')
            self.assertEqual(endpoint+'/DFe/000000000000042?cnpjConsulta=11222333000181&lote=true',request['url'])
            self.assertEqual('GET', request['method'])
            self.assertFalse(request['network_executed'])
            self.assertFalse(request['authorization_verified'])
        self.assertIn('?cpfConsulta=12345678909', adn_request('12345678909','production','0')['url'])
        self.assertNotIn('cnpjConsulta', adn_request('12345678909','production','0')['url'])

    def test_adn_procuration_rejection_never_resets_cursor_or_assumes_authorization(self):
        payload = {'TipoConsulta': 'InscricaoCertificado', 'Erros': [{'Codigo':'E2245','Descricao':'private details must not enter diagnostic'}]}
        result = adn_rejection(payload,'123')
        self.assertEqual('000000000000123',result['last_nsu'])
        self.assertEqual('authorization_pending',result['state'])
        self.assertFalse(result['cursor_advance_allowed'])
        self.assertFalse(result['authorization_verified'])
        self.assertNotIn('private details',json.dumps(result))
        for code in ['E2210','E2244','E2220','E999']:
            self.assertEqual('rejected',adn_rejection({'Erros':[{'Codigo':code}]},'42')['state'])
        for payload in [{}, {'Erros':[]}, {'Erros':[{'Codigo':2245}]}, {'Erros':'E2245'}]:
            with self.assertRaises(ImportProblem): adn_rejection(payload,'42')

    def test_bare_and_soap_preserve_exact_xml_bytes_and_classify_evidence(self):
        for soap in [False,True]:
            result = read_nfe_distribution(mixed(soap=soap))
            self.assertEqual(['full_xml','summary','event'],[e['kind'] for e in result['entries']])
            self.assertEqual(FIXTURE.read_bytes(),result['entries'][0]['xml'])
            self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),result['entries'][0]['sha256'])
            self.assertFalse(result['cursor_advance_allowed'])
            self.assertEqual('000000000000003', result['reported_last_nsu'])

    def test_empty_rejected_and_end_of_page_are_cooldown_hints_without_advancing(self):
        for status in ['137','656','108']:
            result=read_nfe_distribution(response(status=status))
            self.assertEqual([],result['entries'])
            self.assertFalse(result['cursor_advance_allowed'])
            self.assertEqual(3600 if status in {'137','656'} else 0,result['cooldown_seconds'])
        self.assertEqual(3600,read_nfe_distribution(mixed().replace(b'>4<',b'>3<'))['cooldown_seconds'])

    def test_packets_validate_before_any_document_is_imported(self):
        for raw,code in [
            (mixed().replace(b'NSU="2"',b'NSU="1"'),'RECEPTION_NSU'),
            (mixed().replace(b'NSU="1"',b'NSU="9"'),'RECEPTION_NSU'),
            (mixed().replace(b'>4<',b'>2<'),'RECEPTION_NSU'),
            (mixed().replace(b'>2</ns0:tpAmb>',b'>1</ns0:tpAmb>'),'RECEPTION_ENVIRONMENT'),
            (mixed().replace(b'cStat>138',b'cStat>137'),'RECEPTION_RESPONSE_INVALID'),
        ]:
            with self.subTest(code=code):
                parsed=parse_file('retorno.xml',raw,{'tax_id':'12345678000195'})
                self.assertFalse(parsed['can_confirm'])
                self.assertEqual([],parsed['documents'])
                self.assertIn(code,{i['code'] for i in parsed['issues']})

    def test_malformed_compression_trailing_data_and_xml_entities_are_rejected(self):
        root=ET.fromstring(response([('1','resNFe_v1.01.xsd',SUMMARY)]))
        packet=next(root.iter(f'{{{NFE_NS}}}docZip'))
        for invalid in ['!',base64.b64encode(SUMMARY).decode(),base64.b64encode(gzip.compress(SUMMARY)+b'extra').decode(),base64.b64encode(gzip.compress(SUMMARY)[:-4]).decode(),base64.b64encode(gzip.compress(SUMMARY)+gzip.compress(SUMMARY)).decode()]:
            packet.text=invalid
            with self.assertRaises(ImportProblem):read_nfe_distribution(ET.tostring(root))
        for encoding in ['utf-8','utf-16','utf-32']:
            bad='<!DOCTYPE x [<!ENTITY e SYSTEM "file:///do-not-read">]><x>&e;</x>'.encode(encoding)
            with self.assertRaises(ImportProblem):read_nfe_distribution(response([('1','unknown',bad)]))

    def test_bounded_expansion_and_total_member_limit(self):
        from app import reception
        with patch.object(reception,'MAX_FILE_BYTES',1000):
            with self.assertRaises(ImportProblem):read_nfe_distribution(response([('1','x',b'x'*1001)]))
        with patch.object(reception,'MAX_EXPANDED_BYTES',len(SUMMARY)*2-1):
            with self.assertRaises(ImportProblem):read_nfe_distribution(response([('1','x',SUMMARY),('2','x',SUMMARY)]))
        with self.assertRaises(ImportProblem):read_nfe_distribution(mixed(),{'members':999,'expanded':0})
        for expanded in [reception.MAX_EXPANDED_BYTES, reception.MAX_EXPANDED_BYTES+1]:
            with self.assertRaises(ImportProblem):read_nfe_distribution(mixed(),{'members':0,'expanded':expanded})
        with self.assertRaises(ImportProblem):read_nfe_distribution(response([(str(i),'x',SUMMARY) for i in range(1,52)],last='51',maximum='51'))

    def test_unknown_models_and_schema_do_not_become_notes(self):
        for schema, raw in [('procNFe_v9.99.xsd',FIXTURE.read_bytes()),('procNFe_v4.00.xsd',FIXTURE.read_bytes().replace(b'<mod>55',b'<mod>65')),('procCTe_v4.00.xsd',b'<cteProc xmlns="http://www.portalfiscal.inf.br/cte"/>')]:
            decoded=read_nfe_distribution(response([('1',schema,raw)]))
            self.assertEqual('unsupported',decoded['entries'][0]['kind'])
            parsed=parse_file('retorno.xml',response([('1',schema,raw)]),{'tax_id':'12345678000195'})
            self.assertEqual([],parsed['documents'])
            self.assertFalse(parsed['can_confirm'])

    def test_importer_preserves_dates_company_direction_and_pending(self):
        raw=FIXTURE.read_bytes().replace(b'2026-11-05T',b'2026-10-30T')
        for company,direction in [('12345678000195','incoming'),('87654321000198','outgoing')]:
            result=parse_file('retorno.xml',mixed(raw),{'tax_id':company,'import_options':{'posting_date':'2026-11-06'}})
            self.assertTrue(result['can_confirm'])
            doc=result['documents'][0]
            self.assertEqual(('2026-10-30','2026-11-06',direction),(doc['issue_date'],doc['posting_date'],doc['direction']))
            self.assertEqual(3,len(result['reception'][0]['entries']))
            self.assertTrue(result['partial'])
        wrong=parse_file('retorno.xml',mixed(),{'tax_id':'11222333000181'})
        self.assertFalse(wrong['can_confirm'])
        self.assertIn('COMPANY_MISMATCH',{i['code'] for i in wrong['issues']})


class ReceptionApiTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope

    def raw(self):
        return FIXTURE.read_bytes().replace(b'12345678000195',self.a['tax_id'].encode()).replace(b'<tpAmb>2',b'<tpAmb>1').replace(b'2026-11-05T',b'2026-10-30T')

    def preview(self, raw=None, options=None):
        r=self.client.post(self.scope('/imports/preview'),json={'filename':'retorno.xml','content_base64':base64.b64encode(raw or response([('1','procNFe_v4.00.xsd',self.raw()),('2','resNFe_v1.01.xsd',SUMMARY)],environment='1')).decode(),'period':'2026-11','options':options or {'posting_date':'2026-11-06'}})
        self.assertEqual(200,r.status_code,r.text)
        return r.json()

    def test_preview_confirmation_idempotency_original_and_download(self):
        envelope=response([('1','procNFe_v4.00.xsd',self.raw()),('2','resNFe_v1.01.xsd',SUMMARY)],environment='1')
        batch=self.preview(envelope)
        self.assertTrue(batch['can_confirm'])
        self.assertEqual(batch['id'],self.preview(envelope)['id'])
        self.assertEqual(envelope,self.client.get(self.scope(f"/imports/{batch['id']}/original")).content)
        download=self.client.get(self.scope(f"/imports/{batch['id']}/documents/0/download"))
        self.assertEqual(200,download.status_code,download.text)
        self.assertEqual(self.raw(),download.content)
        payload={'preview_hash':batch['preview_hash'],'posting_mode':'pending'}
        for _ in range(2):
            confirmed=self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json=payload)
            self.assertEqual(200,confirmed.status_code,confirmed.text)
        docs=self.core.documents(self.a['id'])
        self.assertEqual(1,len(docs))
        self.assertEqual('pending',docs[0]['status'])
        self.assertEqual(('2026-10-30','2026-11-06'),(docs[0]['issue_date'],docs[0]['posting_date']))
        self.assertEqual([],self.core.journals(self.a['id']))
        self.assertEqual([],self.core.titles(self.a['id']))
        detail=self.client.get(self.scope(f"/imports/{batch['id']}")).json()
        self.assertEqual('summary',detail['reception'][0]['entries'][1]['kind'])
        self.assertEqual(404,self.client.get(self.scope(f"/imports/{batch['id']}/documents/0/download",self.b['id'])).status_code)
        self.assertEqual(404,self.client.get(self.scope(f"/imports/{batch['id']}/documents/1/download")).status_code)

    def test_reception_uses_existing_company_cfop_and_posting_review(self):
        mapping=self.client.post(self.scope('/fiscal-import-mappings'),json={
            'direction':'incoming','model':'55','source_cfop':'5102','target_cfop':'1102',
            'valid_from':'2026-01-01','valid_to':'','reason':'Teste sintético','responsible':'Teste'})
        self.assertEqual(200,mapping.status_code,mapping.text)
        batch=self.preview()
        overrides={'document_overrides':{'documents:0':{'posting_date_confirmed':True}}}
        prepared=self.client.post(self.scope(f"/imports/{batch['id']}/posting-preview"),json=overrides)
        self.assertEqual(200,prepared.status_code,prepared.text)
        plan=prepared.json()
        self.assertTrue(plan['documents'][0]['import_posting']['eligible'])
        result=self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json={
            'posting_mode':'book','posting_hash':plan['posting_hash'],'preview_hash':batch['preview_hash'],**overrides})
        self.assertEqual(200,result.status_code,result.text)
        self.assertEqual(1,result.json()['documents_booked'])
        doc=self.core.documents(self.a['id'])[0]
        self.assertEqual('1102',doc['items'][0]['cfop'])
        self.assertEqual('5102',doc['items'][0]['source_cfop'])
        self.assertEqual('booked',doc['status'])
        self.assertTrue(doc['import_posting']['review_pending'])
        self.assertEqual([],self.core.journals(self.a['id']))
        self.assertEqual([],self.core.titles(self.a['id']))

    def test_homologation_xml_cannot_be_booked_as_production(self):
        raw=self.raw().replace(b'<tpAmb>1',b'<tpAmb>2')
        batch=self.preview(response([('1','procNFe_v4.00.xsd',raw)],environment='2'))
        overrides={'document_overrides':{'documents:0':{'posting_date_confirmed':True}}}
        prepared=self.client.post(self.scope(f"/imports/{batch['id']}/posting-preview"),json=overrides)
        self.assertEqual(200,prepared.status_code,prepared.text)
        plan=prepared.json()
        self.assertFalse(plan['documents'][0]['import_posting']['eligible'])
        result=self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json={
            'posting_mode':'book','posting_hash':plan['posting_hash'],'preview_hash':batch['preview_hash'],**overrides})
        self.assertEqual(409,result.status_code,result.text)
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_summary_only_remains_explainable_and_original_is_available(self):
        envelope=response([('1','resNFe_v1.01.xsd',SUMMARY)])
        batch=self.preview(envelope)
        self.assertFalse(batch['can_confirm'])
        self.assertIn('Resumo sem XML',batch['reception'][0]['entries'][0]['reason'])
        self.assertEqual(envelope,self.client.get(self.scope(f"/imports/{batch['id']}/original")).content)
        r=self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json={'preview_hash':batch['preview_hash']})
        self.assertEqual(409,r.status_code)
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_closed_competence_must_reopen_before_import_confirmation(self):
        batch=self.preview()
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'fiscal','reason':'Teste sintético'},'teste',True)
        payload={'preview_hash':batch['preview_hash'],'posting_mode':'pending'}
        r=self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json=payload)
        self.assertEqual(409,r.status_code,r.text)
        self.assertEqual([],self.core.documents(self.a['id']))
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'fiscal','reason':'Reabrir teste'},'teste',False)
        self.assertEqual(200,self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json=payload).status_code)

    def test_reception_closed_month_requires_reopening_even_with_legacy_locks_disabled(self):
        from app.operational_settings import save_settings
        with self.core.db.transaction() as conn:
            cfg = conn.execute('SELECT version FROM company_operational_settings WHERE company_id=?',(self.a['id'],)).fetchone()
            save_settings(conn,self.a['id'],{'version':cfg['version'],'settings':{'enforce_period_locks':False}},'teste')
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'fiscal','reason':'Teste'},'teste',True)
        batch=self.preview()
        self.assertEqual('period_closed',batch['documents'][0]['_eligibility']['code'])
        result=self.client.post(self.scope(f"/imports/{batch['id']}/confirm"),json={'preview_hash':batch['preview_hash'],'posting_mode':'pending'})
        self.assertEqual(409,result.status_code,result.text)
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_csrf_context_and_export_permission(self):
        batch=self.preview()
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE username='teste'")
            uid=conn.execute("SELECT id FROM users WHERE username='teste'").fetchone()[0]
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(uid,self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','read','allow')",(uid,self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','import','allow')",(uid,self.a['id']))
        path=self.scope(f"/imports/{batch['id']}/documents/0/download")
        self.assertEqual(403,self.client.get(path).status_code)
        self.assertEqual(403,self.client.post(self.scope('/imports/preview'),headers={'X-CSRF-Token':''},json={}).status_code)
        self.assertEqual(403,self.client.post(self.scope('/imports/preview',self.b['id']),json={}).status_code)
        with self.core.db.transaction() as conn:
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','export','allow')",(uid,self.a['id']))
        self.assertEqual(self.raw(),self.client.get(path).content)

    def test_nested_zip_and_source_extraction_share_expansion_budget(self):
        envelope=response([('1','procNFe_v4.00.xsd',self.raw())],environment='1')
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('recepcao.xml',envelope)
        from app.auditor_sources import original_xmls
        self.assertEqual(self.raw(),original_xmls('origem.zip',buffer.getvalue())[0][1])
        parsed=parse_file('origem.zip',buffer.getvalue(),{'tax_id':self.a['tax_id']})
        self.assertTrue(parsed['can_confirm'])
        self.assertEqual(hashlib.sha256(self.raw()).hexdigest(),parsed['documents'][0]['source_hash'])
