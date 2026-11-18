"""Local batch posting and service policies, synthetic XMLs and no fiscal network."""
import json
import unittest
from copy import deepcopy
import test_reception_adn as adn
import test_reception_remote as remote
from test_reception_remote import MATRIX, BRANCH
from app.importers import parse_file
from app.reception_transport import RemoteReply
from app.fiscal_analytics import fiscal_posting_lines


def xml(number=1, incoming=False, retained='2', base=True):
    issuer,recipient=(BRANCH,MATRIX) if incoming else (MATRIX,BRANCH)
    return (f'<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS{number:050d}">'
        f'<nNFSe>{number}</nNFSe><emit><CNPJ>{issuer}</CNPJ><xNome>PRESTADOR SINTETICO</xNome></emit>'
        f'<valores>{"<vBC>100.00</vBC>" if base else ""}<vISSQN>2.00</vISSQN><vLiq>98.00</vLiq></valores>'
        '<DPS><infDPS><tpAmb>1</tpAmb><serie>1</serie><dhEmi>2026-10-01T12:00:00-03:00</dhEmi>'
        f'<dCompet>2026-09-01</dCompet><prest><CNPJ>{issuer}</CNPJ></prest>'
        f'<toma><CNPJ>{recipient}</CNPJ><xNome>TOMADOR SINTETICO</xNome></toma>'
        '<serv><cServ><xDescServ>Serviço sintético</xDescServ></cServ></serv>'
        '<valores><vServPrest><vServ>100.00</vServ></vServPrest><trib><tribMun>'
        f'<tpRetISSQN>{retained}</tpRetISSQN></tribMun></trib></valores></infDPS></DPS></infNFSe></NFSe>').encode()


class ReaderTests(unittest.TestCase):
    def test_both_directions_dates_and_declared_amounts(self):
        for incoming in (False,True):
            result=parse_file('nota.xml',xml(incoming=incoming),{'tax_id':MATRIX,'import_options':{'posting_date':'2026-11-15'}})
            self.assertTrue(result['can_confirm'],result['issues'])
            d=result['documents'][0]
            self.assertEqual(f'{1:050d}',d['key'])
            self.assertEqual('incoming' if incoming else 'outgoing',d['direction'])
            self.assertEqual(('2026-10-01','2026-09-01','2026-11-15'),(d['issue_date'],d['declared_competence'],d['posting_date']))
            self.assertEqual('100.00',d['taxes']['ISS.vBC']);self.assertEqual('2.00',d['taxes']['ISS.vISSRetido'])
            self.assertFalse(d['signature_verified']);self.assertEqual('',d['cfop'])
            self.assertEqual('PRESTADOR SINTETICO',d['issuer']['name'])

    def test_foreign_company_duplicate_fields_and_wrong_namespace_block(self):
        for raw in (xml().replace(MATRIX.encode(),b'99888777000101'),xml().replace(b'<vBC>100.00</vBC>',b'<vBC>100.00</vBC><vBC>100.00</vBC>'),xml().replace(b'http://www.sped.fazenda.gov.br/nfse',b'urn:wrong')):
            r=parse_file('nota.xml',raw,{'tax_id':MATRIX})
            self.assertFalse(r['can_confirm']);self.assertFalse(r['documents'])

    def test_service_pdf_is_bounded_pdf_and_identifies_representation(self):
        from app.auxiliary import render_danfe
        raw,renderer=render_danfe(xml())
        self.assertTrue(raw.startswith(b'%PDF-'));self.assertIn('DANFSe-conferencia',renderer)

    def test_cancelled_service_does_not_reintroduce_historical_values(self):
        document=parse_file('nota.xml',xml(),{'tax_id':MATRIX})['documents'][0]
        document['book_cancellation']={'reason':'Cancelamento confirmado na escrituração'}
        document['service_bookkeeping']={'profile':{'version':1},'values':{'accounting':'100.00','base':'100.00','iss_withheld':'2.00'}}
        lines=fiscal_posting_lines(document)
        self.assertEqual('0.00',lines[0]['document_total'])
        self.assertNotEqual('2.00',lines[0].get('service_withheld'))


class BatchTests(unittest.TestCase):
    setUpBase=adn.AdnCaptureTests.setUpBase
    tearDown=adn.AdnCaptureTests.tearDown
    create_company=adn.AdnCaptureTests.create_company
    activate=adn.AdnCaptureTests.activate
    scope=adn.AdnCaptureTests.scope
    def query(self,key):
        r=self.client.post(self.scope('/imports/reception/query'),json={'provider':'nfse_adn','environment':'production','period':'2026-11','idempotency_key':key})
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def setUp(self):
        adn.AdnCaptureTests.setUp(self)
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([adn.packet(1,xml=xml())|{'ChaveAcesso':f'{1:050d}'},adn.packet(2,xml=xml(2,True))|{'ChaveAcesso':f'{2:050d}'}],environment='PRODUCAO')).encode())
        self.query('batch-source-001')

    def profile(self,**changes):
        payload={'version':0,'base':True,'iss':False,'iss_withheld':True,'source':'Decisão sintética','responsible':'TESTE'}|changes
        r=self.client.put(self.scope('/service-bookkeeping-profile'),json=payload)
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def preview(self,**changes):
        body={'period':'2026-11','posting_date':'2026-11-15','environment':'production',
              'documents':[{'receipt_key':'batch-source-001','nsu':'1'},{'receipt_key':'batch-source-001','nsu':'2'}]}|changes
        r=self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview'),json=body)
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def post(self,batch,expected=200):
        r=self.client.post(self.scope(f'/imports/{batch["id"]}/posting-preview'),json={})
        self.assertEqual(200,r.status_code,r.text);p=r.json()
        r=self.client.post(self.scope(f'/imports/{batch["id"]}/confirm'),json={'preview_hash':batch['preview_hash'],'posting_mode':'book','posting_hash':p['posting_hash'],'selected':['documents:0','documents:1']})
        self.assertEqual(expected,r.status_code,r.text);return r.json(),p

    def test_batch_confirmation_preserves_originals_dates_and_profile_snapshot(self):
        self.profile();r=self.preview();batch=r['batch']
        self.assertEqual(2,len(batch['documents']));self.assertEqual([],self.core.documents(self.a['id']))
        posted,p=self.post(batch);self.assertEqual(2,posted['documents_booked'])
        docs=self.core.documents(self.a['id']);self.assertEqual(2,len(docs))
        for d in docs:
            self.assertEqual('booked',d['status']);self.assertEqual('2026-11',d['period'])
            values=d['service_bookkeeping']['values'];self.assertEqual('100.00',values['base']);self.assertEqual('2.00',values['iss_withheld']);self.assertIsNone(values['iss'])
            line=fiscal_posting_lines(d)[0];self.assertIsNone(line['book_icms']);self.assertEqual('100.00',line['service_base'])
        self.profile(version=1,base=False,iss=True,iss_withheld=False)
        self.assertEqual(docs,self.core.documents(self.a['id']))
        replay,_=self.post(batch);self.assertTrue(replay['duplicate']);self.assertEqual(2,len(self.core.documents(self.a['id'])))

    def test_profiles_are_company_scoped_and_missing_policy_blocks_booking(self):
        batch=self.preview()['batch'];_,p=self.post(batch,409)
        self.assertFalse(any(d['import_posting']['eligible'] for d in p['documents']))
        self.profile()
        self.activate(self.b['id'])
        r=self.client.get(self.scope('/service-bookkeeping-profile',self.b['id']))
        self.assertEqual(0,r.json()['version'])
        r=self.client.get(self.scope('/imports/'+str(batch['id']),self.b['id']))
        self.assertEqual(404,r.status_code)

    def test_filters_use_xml_competence_and_not_reception_reference(self):
        r=self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview'),json={'period':'2026-11','posting_date':'2026-11-15','environment':'production','filters':{'competence':'2026-09'}})
        self.assertEqual(200,r.status_code,r.text);self.assertEqual(2,r.json()['documents'])
        r=self.client.get(self.scope('/imports/reception/receipts/batch-source-001/documents/1/auxiliary'))
        self.assertEqual(200,r.status_code,r.text);self.assertTrue(r.content.startswith(b'%PDF-'))

    def test_changed_profile_invalidates_preview_without_partial_writes(self):
        self.profile();batch=self.preview()['batch']
        p=self.client.post(self.scope(f'/imports/{batch["id"]}/posting-preview'),json={}).json()
        self.profile(version=1,base=False)
        r=self.client.post(self.scope(f'/imports/{batch["id"]}/confirm'),json={'preview_hash':batch['preview_hash'],'posting_mode':'book','posting_hash':p['posting_hash'],'selected':['documents:0','documents:1']})
        self.assertEqual(409,r.status_code);self.assertEqual('stale_posting_preview',r.json()['code']);self.assertEqual([],self.core.documents(self.a['id']))

    def test_missing_declared_selected_amount_blocks_instead_of_using_total_or_zero(self):
        self.profile()
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([adn.packet(3,xml=xml(3,base=False))],environment='PRODUCAO')).encode())
        self.query('missing-base-source')
        r=self.preview(documents=[{'receipt_key':'missing-base-source','nsu':'3'}])
        p=self.client.post(self.scope('/imports/'+str(r['import_id'])+'/posting-preview'),json={}).json()
        self.assertFalse(p['documents'][0]['import_posting']['eligible'])
        self.assertIn('sem valor declarado',p['documents'][0]['import_posting']['reason'])

    def test_related_event_arriving_after_preview_prevents_booking(self):
        self.profile();batch=self.preview()['batch']
        p=self.client.post(self.scope(f'/imports/{batch["id"]}/posting-preview'),json={}).json()
        event=adn.packet(3,kind='EVENTO',xml=adn.EVENT)|{'ChaveAcesso':f'{1:050d}'}
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([event],environment='PRODUCAO')).encode())
        self.query('event-after-preview')
        r=self.client.post(self.scope(f'/imports/{batch["id"]}/confirm'),json={'preview_hash':batch['preview_hash'],'posting_mode':'book','posting_hash':p['posting_hash'],'selected':['documents:0','documents:1']})
        self.assertEqual(409,r.status_code);self.assertEqual([],self.core.documents(self.a['id']))

    def test_report_uses_booked_profile_and_does_not_change_after_settings_update(self):
        self.profile();self.post(self.preview()['batch'])
        path=self.scope('/service-bookkeeping-profile/report?period=2026-11')
        original=self.client.get(path);self.assertEqual(200,original.status_code)
        self.assertIn(b'100.00',original.content)
        self.profile(version=1,base=False,iss=True,iss_withheld=False)
        self.assertEqual(original.content,self.client.get(path).content)

    def test_summary_event_and_wrong_period_are_not_bookable_batches(self):
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([adn.packet(3,kind='EVENTO',xml=adn.EVENT)],environment='PRODUCAO')).encode())
        self.query('event-source-only')
        body={'period':'2026-11','posting_date':'2026-11-15','environment':'production','documents':[{'receipt_key':'event-source-only','nsu':'3'}]}
        r=self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview'),json=body)
        self.assertEqual(409,r.status_code);self.assertEqual('reception_not_full_xml',r.json()['code'])
        body['posting_date']='2026-10-15'
        self.assertEqual(400,self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview'),json=body).status_code)

    def test_permissions_are_revalidated_for_preparation_and_confirmation(self):
        self.profile();batch=self.preview()['batch']
        p=self.client.post(self.scope(f'/imports/{batch["id"]}/posting-preview'),json={}).json()
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
            for routine,action in [('fiscal.imports','read'),('fiscal.imports','import'),('fiscal.imports','export'),('fiscal.documents','read'),('fiscal.documents','create')]:
                conn.execute('INSERT INTO user_permissions VALUES(?,?,?,?,?)',(self.uid,self.a['id'],routine,action,'allow'))
        body={'period':'2026-11','posting_date':'2026-11-15','environment':'production','documents':[{'receipt_key':'batch-source-001','nsu':'1'}]}
        self.assertEqual(403,self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview'),json=body).status_code)
        r=self.client.post(self.scope(f'/imports/{batch["id"]}/confirm'),json={'preview_hash':batch['preview_hash'],'posting_mode':'book','posting_hash':p['posting_hash'],'selected':['documents:0','documents:1']})
        self.assertEqual(403,r.status_code);self.assertEqual([],self.core.documents(self.a['id']))

    def test_receipt_environment_cannot_be_changed_by_the_batch(self):
        body={'period':'2026-11','posting_date':'2026-11-15','environment':'restricted_production','documents':[{'receipt_key':'batch-source-001','nsu':'1'}]}
        r=self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview'),json=body)
        self.assertEqual(409,r.status_code);self.assertEqual('reception_source_mismatch',r.json()['code'])
        self.activate(self.b['id'])
        body['environment']='production'
        self.assertEqual(404,self.client.post(self.scope('/reception/nfse_adn/bookkeeping-preview',self.b['id']),json=body).status_code)


class NfeBatchTests(unittest.TestCase):
    setUpBase=remote.CaptureApiTests.setUpBase
    setUp=remote.CaptureApiTests.setUp
    tearDown=remote.CaptureApiTests.tearDown
    create_company=remote.CaptureApiTests.create_company
    activate=remote.CaptureApiTests.activate
    scope=remote.CaptureApiTests.scope
    query=remote.CaptureApiTests.query

    def test_dfe_batch_reuses_full_xml_only_without_booking(self):
        self.query()
        r=self.client.post(self.scope('/reception/nfe_distribution/bookkeeping-preview'),json={'period':'2026-11',
            'posting_date':'2026-11-15','environment':'homologation','filters':{}})
        self.assertEqual(200,r.status_code,r.text);result=r.json()
        self.assertEqual(1,result['documents']);self.assertEqual('55',result['batch']['documents'][0]['model'])
        self.assertEqual('2026-11-15',result['batch']['documents'][0]['posting_date'])
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_summary_cannot_be_selected_as_full_document(self):
        self.query()
        r=self.client.post(self.scope('/reception/nfe_distribution/bookkeeping-preview'),json={'period':'2026-11',
            'posting_date':'2026-11-15','environment':'homologation','documents':[{'receipt_key':'synthetic-0001','nsu':'2'}]})
        self.assertEqual(409,r.status_code);self.assertEqual('reception_not_full_xml',r.json()['code'])
