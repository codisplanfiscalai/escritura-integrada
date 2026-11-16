"""Synthetic fixtures derived from captured ADN JSON schema; no real service."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core as base
from test_reception_remote import FakeCredentials, FakeTransport, MATRIX, BRANCH, THIRD
from app.core import DomainError, pack
from app.importers import ImportProblem
from app.reception import adn_nsu, adn_request, nfe_request
from app.reception_adn import NFSE_NS, load_adn_json, read_adn_distribution
from app.reception_service import ReceptionService, RUN_SCOPE
from app.reception_transport import RemoteReply

# Not signed, authorized or XSD-valid fiscal evidence. Dates intentionally differ.
XML = f'''<?xml version="1.0" encoding="UTF-8"?><NFSe xmlns="{NFSE_NS}"><infNFSe>
<nNFSe>1</nNFSe><dhProc>2026-11-04T12:00:00-03:00</dhProc>
<DPS><infDPS><dhEmi>2026-10-31T23:00:00-03:00</dhEmi><dCompet>2026-10-01</dCompet></infDPS></DPS>
</infNFSe></NFSe>'''.encode()
EVENT = f'<evento xmlns="{NFSE_NS}"><descricao>SINTETICO SEM EFEITO FISCAL</descricao></evento>'.encode()


def packet(number=1,kind='NFSE',xml=XML):
    return {'NSU':number,'ChaveAcesso':'CHAVE-SINTETICA-SEM-VALIDADE-FISCAL','TipoDocumento':kind,
            'TipoEvento':'CANCELAMENTO' if kind=='EVENTO' else None,
            'ArquivoXml':base64.b64encode(gzip.compress(xml,mtime=0)).decode(),
            'DataHoraGeracao':'2026-11-04T12:00:00-03:00'}


def page(packets=None,mode='InscricaoCertificado',environment='HOMOLOGACAO'):
    return {'TipoConsulta':mode,'TipoAmbiente':environment,'StatusProcessamento':'DOCUMENTOS_LOCALIZADOS',
            'LoteDFe':[packet()] if packets is None else packets,'Erros':[],'Alertas':[],
            'VersaoAplicativo':'SYNTHETIC','DataHoraProcessamento':'2026-11-04T12:00:01-03:00'}


def decode(payload,cursor='0',mode='InscricaoCertificado',environment='restricted_production'):
    return read_adn_distribution(load_adn_json(json.dumps(payload).encode()),cursor,environment,mode)


class AdnProfileTests(unittest.TestCase):
    def test_int64_nsu_is_exact_and_independent_of_nfe(self):
        maximum=9223372036854775807
        self.assertEqual(str(maximum),adn_nsu(maximum))
        request=adn_request(MATRIX,'restricted_production',str(maximum),certificate_tax_id=MATRIX)
        self.assertTrue(request['url'].endswith(str(maximum)+'?lote=true'))
        self.assertNotIn('cnpjConsulta',request['url'])
        result=decode(page([packet(9007199254740993),packet(maximum)]))
        self.assertEqual(str(maximum),result['reported_last_nsu'])
        self.assertEqual('9007199254740993',result['entries'][0]['nsu'])
        with self.assertRaises(ImportProblem):nfe_request(MATRIX,'35','homologation',str(maximum))
        for bad in [True,-1,1.5,str(maximum+1),'1e3','１２','1/2',None]:
            with self.subTest(bad=bad),self.assertRaises(ImportProblem):adn_nsu(bad)

    def test_success_preserves_exact_xml_and_does_not_interpret_events_or_dates(self):
        result=decode(page([packet(9),packet(12,'EVENTO',EVENT)]))
        self.assertEqual('000000000000012',result['reported_last_nsu'])
        self.assertTrue(result['authorization_verified'])
        entry=result['entries'][0]
        self.assertEqual(XML,entry['xml'])
        self.assertEqual(hashlib.sha256(XML).hexdigest(),entry['sha256'])
        self.assertEqual('nfse_bookkeeping_reader_pending',entry['reason'])
        self.assertNotIn('posting_date',entry)
        self.assertNotIn('issued_date',entry)
        self.assertNotIn('amount',entry)
        self.assertTrue(result['entries'][1]['review_pending'])
        self.assertEqual('received_xml_without_fiscal_effect',result['entries'][1]['reason'])

    def test_modes_and_environment_must_match_the_validated_request(self):
        for mode in ['InscricaoCertificado','CnpjBase','Procuracao']:
            self.assertEqual(mode,decode(page(mode=mode),mode=mode)['authorization_mode'])
            for actual in ['InscricaoCertificado','CnpjBase','Procuracao',None]:
                if actual!=mode:
                    with self.assertRaises(ImportProblem):decode(page(mode=actual),mode=mode)
        self.assertTrue(decode(page(environment='PRODUCAO'),environment='production')['authorization_verified'])
        with self.assertRaises(ImportProblem):decode(page(environment='PRODUCAO'))

    def test_entire_page_is_held_on_incomplete_unsupported_or_conflicting_packet(self):
        cases=[page([]),page([packet(),packet()]),page([packet(0)]),page([packet(1.0)]),page([packet(True)]),
               page([packet(9223372036854775808)]),page([packet(kind='NENHUM')]),page([packet(kind='FUTURE')]),
               page([packet(),packet(2)|{'ArquivoXml':None}]),page([packet(),packet(2)|{'ArquivoXml':'bad gzip'}]),
               page([packet()|{'NSU':'1'}]),page([packet()|{'Unexpected':True}]),
               page()|{'Unexpected':1},page()|{'Alertas':[{'Codigo':'A1','Descricao':'private'}]},
               page()|{'Erros':[{'Codigo':'E2245'}]},page()|{'DataHoraProcessamento':'2026-11-01'}]
        for payload in cases:
            with self.subTest(payload=list(payload)),self.assertRaises(ImportProblem):decode(payload)
        with self.assertRaises(ImportProblem):decode(page([packet(20)]),cursor='20')
        # Contract is exclusive and NSUs need not be contiguous or ordered.
        self.assertEqual('000000000000030',decode(page([packet(30),packet(21)]),cursor='20')['reported_last_nsu'])

    def test_json_xml_and_expansion_boundaries(self):
        for raw in [b'{"TipoConsulta":1,"TipoConsulta":2}',b'{"x":NaN}',b'not json',b'\xff']:
            with self.assertRaises(ImportProblem):load_adn_json(raw)
        for raw in [b'<NFSe/>',b'<NFSe xmlns="urn:wrong"><infNFSe/></NFSe>',b'<!DOCTYPE x [<!ENTITY y "x">]><x/>',
                    b'<x>',b'<?xml version="1.0" encoding="ISO-8859-1"?><x/>',b'\xff<x/>']:
            with self.subTest(raw=raw),self.assertRaises(ImportProblem):decode(page([packet(xml=raw)]))
        packed=packet();packed['ArquivoXml']=base64.b64encode(gzip.compress(XML)+gzip.compress(EVENT)).decode()
        with self.assertRaises(ImportProblem):decode(page([packed]))
        with patch('app.reception.MAX_EXPANDED_BYTES',len(XML)+1),self.assertRaises(ImportProblem):
            decode(page([packet(),packet(2)]))
        with patch('app.reception_adn.MAX_ARCHIVE_MEMBERS',1),self.assertRaises(ImportProblem):
            decode(page([packet(),packet(2)]))


class AdnCaptureTests(unittest.TestCase):
    setUpBase=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope

    def setUp(self):
        self.setUpBase()
        self.a=self.create_company('ADN SINTETICO','112223330001')
        self.b=self.create_company('FILIAL SINTETICA','112223330002')
        self.activate(self.a['id']);self.clock=[1000.]
        self.transport=FakeTransport(RemoteReply(200,json.dumps(page([packet(),packet(2,'EVENTO',EVENT)])).encode()))
        self.service=ReceptionService(self.core,FakeCredentials(),self.transport,lambda:self.clock[0])
        self.app.state.reception=self.service
        self.uid=self.client.get('/api/session').json()['user']['id']

    def query(self,key='synthetic-adn-001',status=200,cid=None):
        r=self.client.post(self.scope('/imports/reception/query',cid or self.a['id']),json={
            'provider':'nfse_adn','environment':'restricted_production','period':'2026-11','idempotency_key':key})
        self.assertEqual(status,r.status_code,r.text)
        return r.json()

    def state(self,cid=None,target=MATRIX):
        with self.core.db.read() as conn:
            return self.service._state(conn,cid or self.a['id'],'nfse_adn:restricted_production:'+target)

    def document(self,key='synthetic-adn-001',number='1',cid=None):
        return self.client.get(self.scope(f'/imports/reception/receipts/{key}/documents/{number}/download',cid or self.a['id']))

    def test_success_stores_envelope_and_all_xml_before_cursor_without_bookkeeping(self):
        raw=self.transport.reply.body
        result=self.query()
        self.assertEqual('received',result['state']);self.assertTrue(result['authorization_verified'])
        self.assertEqual('000000000000002',self.state()['cursor'])
        self.assertTrue(result['cursor_advanced'])
        self.assertEqual('2026-11',result['period'])
        self.assertNotIn('xml',result['entries'][0])
        self.assertEqual(XML,self.document().content)
        self.assertEqual(EVENT,self.document(number='2').content)
        self.assertEqual(404,self.document(number='3').status_code)
        self.assertEqual(400,self.document(number='invalid').status_code)
        self.assertEqual(raw,self.client.get(self.scope('/imports/reception/receipts/synthetic-adn-001/download')).content)
        with self.core.db.read() as conn:
            self.assertEqual(3,conn.execute('SELECT COUNT(*) FROM stored_files WHERE company_id=?',(self.a['id'],)).fetchone()[0])
        self.assertEqual([],self.core.documents(self.a['id']));self.assertEqual([],self.core.journals(self.a['id']))
        preview=self.client.post(self.scope('/imports/reception/receipts/synthetic-adn-001/preview'),json={'period':'2026-11'})
        self.assertEqual('nfse_bookkeeping_reader_pending',preview.json()['code'])
        self.assertTrue(self.query()['duplicate']);self.assertEqual(1,len(self.transport.plans))
        self.clock[0]+=3601;self.transport.reply=RemoteReply(200,json.dumps(page([packet(3)])).encode())
        self.assertTrue(self.query(key='synthetic-adn-002')['cursor_advanced'])
        self.assertIn('/DFe/000000000000002',self.transport.plans[-1]['url'])

    def test_matrix_branch_and_separate_cursors_then_explicit_third_party_success(self):
        self.query()
        self.activate(self.b['id'])
        self.transport.reply=RemoteReply(200,json.dumps(page(mode='CnpjBase')).encode())
        result=self.query(key='synthetic-branch',cid=self.b['id'])
        self.assertTrue(result['authorization_verified'])
        self.assertIn('cnpjConsulta='+BRANCH,self.transport.plans[-1]['url'])
        self.assertEqual('000000000000001',self.state(self.b['id'],BRANCH)['cursor'])
        self.assertEqual('000000000000002',self.state()['cursor'])
        self.assertEqual(404,self.document(cid=self.b['id']).status_code)
        self.activate(self.a['id']);self.clock[0]+=3601
        self.service.credentials=FakeCredentials(BRANCH)
        self.transport.reply=RemoteReply(200,json.dumps(page([packet(3)],mode='CnpjBase')).encode())
        self.assertTrue(self.query(key='synthetic-reverse')['authorization_verified'])
        self.assertIn('cnpjConsulta='+MATRIX,self.transport.plans[-1]['url'])
        self.clock[0]+=3601;self.service.credentials=FakeCredentials(THIRD,True)
        self.transport.reply=RemoteReply(200,json.dumps(page([packet(4)],mode='Procuracao')).encode())
        self.assertTrue(self.query(key='synthetic-proc')['authorization_verified'])

    def test_later_corrupt_or_missing_xml_holds_entire_page_and_retains_raw(self):
        for index,changes in enumerate([{'ArquivoXml':None},{'ArquivoXml':'invalid gzip'},{'TipoDocumento':'FUTURE'}]):
            self.clock[0]+=3601
            raw=json.dumps(page([packet(),packet(2)|changes])).encode()
            self.transport.reply=RemoteReply(200,raw);key=f'synthetic-bad-{index}'
            result=self.query(key)
            self.assertEqual('received_unparsed',result['state']);self.assertFalse(result['authorization_verified'])
            self.assertFalse(result['cursor_advanced']);self.assertEqual('000000000000000',self.state()['cursor'])
            self.assertNotIn('entries',result)
            self.assertEqual(raw,self.client.get(self.scope(f'/imports/reception/receipts/{key}/download')).content)
            self.assertEqual(404,self.document(key).status_code)

    def test_error_defaults_mismatches_and_unknown_json_cannot_advance(self):
        for index,payload in enumerate([page(mode='CnpjBase'),page(environment='PRODUCAO'),page()|{'unverified':True},
                page()|{'Erros':[{'Codigo':'E2245','Descricao':'private diagnostic'}]},page()|{'Erros':[{'Codigo':'E2244'}]}]):
            self.clock[0]+=3601;self.transport.reply=RemoteReply(200,json.dumps(payload).encode())
            result=self.query(f'synthetic-mismatch-{index}')
            self.assertFalse(result['authorization_verified']);self.assertFalse(result['cursor_advanced'])
            self.assertNotIn('private diagnostic',json.dumps(result))
        self.assertEqual('000000000000000',self.state()['cursor'])

    def test_packet_storage_failure_rolls_back_envelope_xml_and_cursor(self):
        from app.reception_service import store_file as actual
        calls=[]
        def fail(*args,**kwargs):
            result=actual(*args,**kwargs);calls.append(result)
            if len(calls)==3:raise DomainError('Falha sintética no segundo XML',503,'synthetic_failure')
            return result
        with patch('app.reception_service.store_file',side_effect=fail):self.query(status=503)
        self.assertEqual(3,len(calls));self.assertEqual('000000000000000',self.state()['cursor'])
        with self.core.db.read() as conn:
            self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM stored_files WHERE company_id=?',(self.a['id'],)).fetchone()[0])
        self.query(status=409);self.assertEqual(1,len(self.transport.plans))

    def test_backup_restores_adn_packet_hashes_and_cursor(self):
        self.query()
        from app.snapshots import create_snapshot,restore_snapshot
        from app.db import Database
        from app.file_store import read_file
        root=Path(self.tmp.name)
        create_snapshot(self.core.db.path,root/'adn-synthetic.zip')
        restore_snapshot(root/'adn-synthetic.zip',root/'restored-adn')
        restored=Database(root/'restored-adn')
        with restored.read() as conn:
            row=conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=?',(self.a['id'],RUN_SCOPE)).fetchone()
            result=json.loads(row['result_json'])
            self.assertEqual('000000000000002',result['cursor_after'])
            self.assertEqual(XML,read_file(conn,self.a['id'],result['entries'][0]['file_id'])['content'])
            self.assertEqual(EVENT,read_file(conn,self.a['id'],result['entries'][1]['file_id'])['content'])

    def test_export_permission_and_metadata_integrity_are_required(self):
        self.query()
        with self.core.db.transaction() as conn:
            row=conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=?',(self.a['id'],RUN_SCOPE)).fetchone()
            changed=json.loads(row['result_json']);changed['entries'][0]['sha256']='0'*64
            conn.execute('UPDATE operations SET result_json=? WHERE company_id=? AND scope=?',(pack(changed),self.a['id'],RUN_SCOPE))
        self.assertEqual(409,self.document().status_code)
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','read','allow')",(self.uid,self.a['id']))
        self.assertEqual(403,self.document(number='2').status_code)


if __name__=='__main__':unittest.main()
