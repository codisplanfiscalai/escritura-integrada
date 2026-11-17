"""Rebuilt local reception workspace; synthetic XML and injected transports only."""
import base64,json,unittest
from unittest.mock import patch
import test_reception_remote as remote
import test_reception_adn as adn
import test_fiscal_import as fiscal
from app.core import DomainError,pack,now,digest
from app.reception_metadata import classify
from app.reception_service import RUN_SCOPE
from app.reception_transport import RemoteReply

def nfse(issuer=remote.MATRIX,taker=remote.BRANCH,intermediary='',name='PRESTADOR SINTETICO'):
    middle='<interm><CNPJ>'+intermediary+'</CNPJ></interm>' if intermediary else ''
    return ('<NFSe xmlns="'+adn.NFSE_NS+'"><infNFSe><nNFSe>9</nNFSe><DPS><infDPS><dhEmi>2026-10-31T23:00:00-03:00</dhEmi><dCompet>2026-09-01</dCompet><prest><CNPJ>'+issuer+'</CNPJ><xNome>'+name+'</xNome></prest><toma><CNPJ>'+taker+'</CNPJ></toma>'+middle+'</infDPS></DPS></infNFSe></NFSe>').encode()

class MetadataTests(unittest.TestCase):
    def test_full_registration_not_root_and_both_roles_and_dates_remain_separate(self):
        for issuer,taker,intermediary,target,direction in [
            (remote.MATRIX,remote.BRANCH,'',remote.MATRIX,'issued'),
            (remote.MATRIX,remote.BRANCH,'',remote.BRANCH,'received'),
            (remote.MATRIX,remote.MATRIX,'',remote.MATRIX,'both'),
            (remote.MATRIX,remote.BRANCH,remote.THIRD,remote.THIRD,'received'),
            (remote.MATRIX,remote.MATRIX,'',remote.BRANCH,'unknown')]:
            raw=nfse(issuer,taker,intermediary);result=classify(raw,'nfse_adn',target)
            self.assertEqual(direction,result['direction'])
            self.assertEqual('2026-09-01',result['declared_competence'])
            self.assertTrue(result['issue_date'].startswith('2026-10'))
            self.assertNotIn('posting_date',result)
        self.assertEqual('unknown',classify(adn.XML,'nfse_adn',remote.MATRIX)['direction'])
        ambiguous=nfse().replace(b'<CNPJ>'+remote.MATRIX.encode()+b'</CNPJ>',b'<CNPJ>'+remote.MATRIX.encode()+b'</CNPJ><CPF>12345678909</CPF>')
        self.assertEqual('unknown',classify(ambiguous,'nfse_adn',remote.MATRIX)['direction'])

class WorkspaceTests(unittest.TestCase):
    setUpBase=remote.base.CoreApiTests.setUp
    setUp=remote.CaptureApiTests.setUp
    tearDown=remote.base.CoreApiTests.tearDown
    create_company=remote.base.CoreApiTests.create_company
    activate=remote.base.CoreApiTests.activate
    scope=remote.base.CoreApiTests.scope
    query=remote.CaptureApiTests.query
    post=fiscal.FiscalImportTests.post
    prepared=fiscal.FiscalImportTests.prepared
    confirm=fiscal.FiscalImportTests.confirm
    def overview(self,provider='nfe_distribution',environment='homologation',cid=None,**params):
        return self.client.get(self.scope('/reception/'+provider,cid),params={'environment':environment,'year':2026,**params})
    def test_open_local_views_never_load_a1_or_use_transport_or_write(self):
        with self.core.db.read() as conn:before=[tuple(r) for r in conn.execute('SELECT * FROM operations')]
        for provider,env in [('nfe_distribution','homologation'),('nfse_adn','restricted_production')]:
            response=self.overview(provider,env)
            self.assertEqual(200,response.status_code,response.text)
            self.assertEqual([],response.json()['documents'])
            self.assertEqual(provider=='nfe_distribution',response.json()['capabilities']['remote_available'])
        with self.core.db.read() as conn:self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT * FROM operations')])
        self.assertEqual(0,self.service.credentials.calls);self.assertEqual([],self.transport.plans)
    def test_external_adn_is_explicitly_pending_without_touching_credentials_or_cursor(self):
        r=self.client.post(self.scope('/reception/nfse_adn/query'),json={'environment':'restricted_production','period':'2026-11','idempotency_key':'pending-contract-001'})
        self.assertEqual(409,r.status_code,r.text)
        self.assertEqual('reception_contract_pending',r.json()['code'])
        self.assertEqual(0,self.service.credentials.calls);self.assertEqual([],self.transport.plans)
    def test_local_nfe_documents_report_packet_download_and_company_isolation(self):
        self.query()
        count=self.service.credentials.calls
        result=self.overview().json()
        self.assertEqual(2,len(result['documents']))
        self.assertEqual(1,len(result['receipts']))
        self.assertNotIn('xml',json.dumps(result).replace('full_xml','').replace('xml_access_key',''))
        row=next(d for d in result['documents'] if d['kind']=='full_xml')
        self.assertEqual(self.raw,self.client.get(self.scope('/imports/reception/receipts/'+row['receipt_key']+'/documents/'+row['nsu']+'/download')).content)
        report=self.client.get(self.scope('/reception/nfe_distribution/report'),params={'environment':'homologation','year':2026})
        self.assertEqual(200,report.status_code,report.text);self.assertIn('reference_period',report.text)
        self.assertEqual(count,self.service.credentials.calls);self.assertEqual(1,len(self.transport.plans))
        self.activate(self.b['id'])
        self.assertEqual([],self.overview(cid=self.b['id']).json()['documents'])
        self.assertEqual(404,self.client.get(self.scope('/imports/reception/receipts/'+row['receipt_key']+'/documents/'+row['nsu']+'/download',self.b['id'])).status_code)
    def test_adn_success_has_no_invented_wait_and_direction_competence_filters_are_local(self):
        xml=nfse(remote.MATRIX,remote.MATRIX,name='  =SYNTHETIC_FORMULA')
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([adn.packet(1,xml=xml)])).encode())
        result=self.query(provider='nfse_adn',environment='restricted_production')
        self.assertEqual('received',result['state'])
        self.assertEqual(self.clock[0],self.state('nfse_adn','restricted_production')['next_allowed_at'])
        for direction in ['issued','received','both']:
            r=self.overview('nfse_adn','restricted_production',direction=direction,competence='2026-09')
            self.assertEqual(1,len(r.json()['documents']),r.text)
            d=r.json()['documents'][0];self.assertEqual('both',d['direction']);self.assertEqual('2026-11',d['reference_period'])
        self.assertEqual([],self.overview('nfse_adn','restricted_production',competence='2026-10').json()['documents'])
        self.assertEqual([],self.overview('nfse_adn','production').json()['documents'])
        report=self.client.get(self.scope('/reception/nfse_adn/report'),params={'environment':'restricted_production','year':2026})
        self.assertIn("'=SYNTHETIC_FORMULA",report.text)
        self.assertEqual(1,len(self.transport.plans));self.assertEqual([],self.core.documents(self.a['id']))
        # A second positive page may be requested immediately under the contributor contract.
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([adn.packet(2,xml=xml)])).encode())
        self.assertEqual('received',self.query('synthetic-adn-next','nfse_adn','restricted_production')['state'])
    state=remote.CaptureApiTests.state
    def test_history_filters_pagination_and_read_only_permissions(self):
        with self.core.db.transaction() as conn:
            for i in range(23):
                result={'period':'2026-11','provider':'nfse_adn','environment':'restricted_production','state':'received','entries':[{'nsu':str(i),'access_key':'SYNTHETIC-'+str(i),'document_type':'NFSE'}]}
                conn.execute('INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)',(self.a['id'],RUN_SCOPE,'local-history-'+str(i).zfill(8),digest(result),pack(result),now()))
        first=self.overview('nfse_adn','restricted_production').json();second=self.overview('nfse_adn','restricted_production',offset=20).json()
        self.assertEqual((20,3),(len(first['documents']),len(second['documents'])));self.assertTrue(first['has_more']);self.assertFalse(second['has_more'])
        self.assertEqual(1,len(self.overview('nfse_adn','restricted_production',query='SYNTHETIC-22').json()['documents']))
        self.assertEqual(400,self.overview(offset=-1).status_code)
        from app.reception_workspace import ReceptionWorkspace
        workspace=ReceptionWorkspace(self.core,self.service)
        with patch.object(workspace,'overview',side_effect=AssertionError('Report must not rescan pages')),patch.object(self.core.db,'read',wraps=self.core.db.read) as reads:
            raw=workspace.report(self.a['id'],self.uid,'nfse_adn','restricted_production',2026)
        self.assertEqual(1,reads.call_count)
        self.assertEqual({'snapshot':True},reads.call_args.kwargs)
        import csv,io
        records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(23,len(records));self.assertEqual(23,len({r['receipt_key'] for r in records}))

        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT OR IGNORE INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
            conn.execute('INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,?,?,?)',(self.uid,self.a['id'],'fiscal.imports','read','allow'))
        self.assertEqual(200,self.overview().status_code)
        self.assertEqual(403,self.client.post(self.scope('/reception/nfe_distribution/check'),json={'environment':'homologation'}).status_code)
        self.assertEqual(403,self.client.get(self.scope('/reception/nfe_distribution/report'),params={'environment':'homologation','year':2026}).status_code)
        self.assertEqual(403,self.client.get(self.scope('/reception-settings')).status_code)
        self.assertEqual(403,self.client.get(self.scope('/reception/nfe_distribution',self.b['id']),params={'environment':'homologation','year':2026}).status_code)
    def test_xml_import_then_reception_review_does_not_duplicate_or_rewrite_original(self):
        upload=self.post('/imports/preview',{'filename':'synthetic.xml','period':'2026-11','content_base64':base64.b64encode(self.raw).decode(),'options':{'posting_date':'2026-11-06'}})
        first=self.post('/imports/'+str(upload['id'])+'/confirm',{'preview_hash':upload['preview_hash'],'posting_mode':'pending'})
        self.assertEqual(1,first['documents_created'])
        self.query()
        review=self.post('/imports/reception/receipts/synthetic-0001/preview',{'period':'2026-11','options':{'posting_date':'2026-11-06'}})
        second=self.post('/imports/'+str(review['id'])+'/confirm',{'preview_hash':review['preview_hash'],'posting_mode':'pending'})
        self.assertEqual(0,second['documents_created']);self.assertEqual(1,second['documents_duplicate'])
        self.assertEqual(1,len(self.core.documents(self.a['id'])))
        self.assertEqual(self.envelope,self.client.get(self.scope('/imports/reception/receipts/synthetic-0001/download')).content)

    def adn_capture(self,packets,key,environment='restricted_production',period='2026-11'):
        body=adn.page(packets,environment='PRODUCAO' if environment=='production' else 'HOMOLOGACAO')
        self.transport.reply=RemoteReply(200,json.dumps(body).encode())
        return self.service.query(self.a['id'],{'provider':'nfse_adn','environment':environment,'period':period,'idempotency_key':key},'synthetic',self.uid)
    def details(self,row,environment='restricted_production',year=2026,offset=0,cid=None):
        return self.client.get(self.scope('/reception/nfse_adn/documents/'+row['record_id'],cid),params={'environment':environment,'year':year,'offset':offset})
    def test_requery_groups_duplicates_preserves_versions_events_and_first_original(self):
        raw=nfse(remote.MATRIX,remote.BRANCH)
        first=self.adn_capture([adn.packet(1,xml=raw)],'grouped-source-001')
        self.assertEqual(remote.MATRIX,first['target_tax_id'])
        self.adn_capture([adn.packet(2,xml=raw)],'grouped-source-002')
        grouped=self.overview('nfse_adn','restricted_production').json()['documents']
        self.assertEqual(1,len(grouped));self.assertEqual((1,2),(grouped[0]['version_count'],grouped[0]['occurrence_count']))
        plans=len(self.transport.plans)
        replay=self.adn_capture([adn.packet(3,xml=raw+b'\n')],'grouped-source-002')
        self.assertTrue(replay['duplicate']);self.assertEqual(plans,len(self.transport.plans))
        changed=raw.replace(b'PRESTADOR SINTETICO',b'OUTRO TEXTO SINTETICO')
        self.adn_capture([adn.packet(3,xml=changed)],'grouped-source-003')
        self.adn_capture([adn.packet(4,kind='EVENTO',xml=adn.EVENT)],'grouped-source-004')
        documents=self.overview('nfse_adn','restricted_production').json()['documents'];self.assertEqual(2,len(documents))
        row=next(d for d in documents if d['document_type']=='NFSE')
        self.assertEqual((2,3),(row['version_count'],row['occurrence_count']));self.assertTrue(row['versions_pending_review'])
        detail=self.details(row);self.assertEqual(200,detail.status_code,detail.text);detail=detail.json()
        self.assertEqual(digest(raw),detail['first_sha256']);self.assertEqual([2,1],[v['occurrence_count'] for v in detail['versions']])
        for version,expected in zip(detail['versions'],[raw,changed]):
            received=self.client.get(self.scope('/imports/reception/receipts/'+version['receipt_key']+'/documents/'+version['nsu']+'/download'))
            self.assertEqual(expected,received.content)
        self.assertNotIn('<NFSe',json.dumps(detail));self.assertEqual([],self.core.documents(self.a['id']))
        self.assertEqual('000000000000004',self.state('nfse_adn','restricted_production')['cursor'])
        from app.reception_workspace import ReceptionWorkspace
        import app.reception_workspace as workspace_module
        with patch('app.reception_workspace.read_file',wraps=workspace_module.read_file) as reads:
            self.overview('nfse_adn','restricted_production')
        self.assertEqual(3,reads.call_count)  # Two unique note XMLs + event, not four occurrences.
        params={'environment':'restricted_production','year':2026,'query':'CHAVE-SINTETICA'}
        docs=self.client.get(self.scope('/reception/nfse_adn/report'),params=params)
        sources=self.client.get(self.scope('/reception/nfse_adn/report'),params=params|{'view':'occurrences'})
        import csv,io
        self.assertEqual(2,len(list(csv.DictReader(io.StringIO(docs.content.decode('utf-8-sig')),delimiter=';'))))
        exported=list(csv.DictReader(io.StringIO(sources.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(4,len(exported));self.assertEqual(4,len({r['receipt_key'] for r in exported}))
        self.assertEqual(400,self.client.get(self.scope('/reception/nfse_adn/report'),params=params|{'view':'arbitrary'}).status_code)

        self.assertEqual(404,self.details(row,environment='production').status_code)
        self.activate(self.b['id']);self.assertEqual(404,self.details(row,cid=self.b['id']).status_code)
    def test_versions_cross_receipt_years_filters_select_matching_original_without_replacing_first(self):
        first=nfse(remote.MATRIX,remote.BRANCH)
        second=first.replace(b'2026-09-01',b'2026-10-01')
        self.adn_capture([adn.packet(1,xml=first)],'cross-year-001')
        self.adn_capture([adn.packet(2,xml=second)],'cross-year-002',period='2027-01')
        response=self.overview('nfse_adn','restricted_production',competence='2026-09').json();row=response['documents'][0]
        self.assertEqual(digest(first),row['sha256']);self.assertEqual(2,row['version_count']);self.assertEqual(1,row['matching_occurrences'])
        other=self.client.get(self.scope('/reception/nfse_adn'),params={'environment':'restricted_production','year':2027,'competence':'2026-10'}).json()['documents'][0]
        self.assertEqual(row['record_id'],other['record_id']);self.assertEqual(digest(second),other['sha256']);self.assertEqual(digest(first),other['first_sha256']);self.assertEqual('2027-01',other['reference_period'])
        report=self.client.get(self.scope('/reception/nfse_adn/report'),params={'environment':'restricted_production','year':2027,'competence':'2026-10'})
        import csv,io
        exported=list(csv.DictReader(io.StringIO(report.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(1,len(exported));self.assertEqual('2026-10-01',exported[0]['declared_competence']);self.assertEqual('2',exported[0]['version_count'])
        self.assertEqual(404,self.details(row,year=2025).status_code)
    def test_unknown_key_uses_verified_bytes_not_number_or_cnpj_root_and_detail_is_paged(self):
        raw=nfse(remote.MATRIX,remote.BRANCH)
        items=[adn.packet(i,xml=raw)|{'ChaveAcesso':None} for i in [1,2]]
        items.append(adn.packet(3,xml=raw+b'\n')|{'ChaveAcesso':None})
        self.adn_capture(items,'unknown-key-001')
        rows=self.overview('nfse_adn','restricted_production').json()['documents'];self.assertEqual(2,len(rows));self.assertTrue(all(r['identity_evidence']=='content_hash' for r in rows))
        duplicate=next(r for r in rows if r['occurrence_count']==2);self.assertEqual(1,duplicate['version_count'])
        variants=[adn.packet(i,xml=raw+('\n'*i).encode())|{'ChaveAcesso':'SYNTHETIC-VERSIONED-KEY'} for i in range(4,26)]
        self.adn_capture(variants,'many-versions-001')
        row=next(r for r in self.overview('nfse_adn','restricted_production').json()['documents'] if r.get('access_key')=='SYNTHETIC-VERSIONED-KEY')
        first=self.details(row).json();second=self.details(row,offset=20).json()
        self.assertEqual((20,2),(len(first['versions']),len(second['versions'])));self.assertTrue(first['has_more']);self.assertFalse(second['has_more'])
        self.assertEqual(22,len({v['sha256'] for v in first['versions']+second['versions']}))
        self.assertEqual(400,self.details(row,offset=-1).status_code)
    def test_failed_page_keeps_archive_and_cursor_then_resumes_without_duplicate_document(self):
        raw=nfse(remote.MATRIX,remote.BRANCH)
        self.adn_capture([adn.packet(1,xml=raw)],'resume-page-001')
        original=self.overview('nfse_adn','restricted_production').json()['documents'][0]
        bad=self.adn_capture([adn.packet(2,xml=b'not an XML')],'resume-page-002')
        self.assertEqual('received_unparsed',bad['state']);self.assertEqual('000000000000001',self.state('nfse_adn','restricted_production')['cursor'])
        current=self.overview('nfse_adn','restricted_production').json()['documents'];self.assertEqual(1,len(current));self.assertEqual(original['record_id'],current[0]['record_id']);self.assertEqual(1,current[0]['occurrence_count'])
        self.adn_capture([adn.packet(2,xml=raw)],'resume-page-003')
        resumed=self.overview('nfse_adn','restricted_production').json()['documents'];self.assertEqual(1,len(resumed));self.assertEqual((1,2),(resumed[0]['version_count'],resumed[0]['occurrence_count']))
        self.assertEqual('000000000000001',self.transport.plans[-1]['url'].split('/DFe/')[1].split('?')[0])
        self.assertEqual([],self.core.documents(self.a['id']))

if __name__=='__main__':unittest.main()
