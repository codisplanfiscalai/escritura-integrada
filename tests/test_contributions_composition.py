"""dev.26 composition: preparation discovery does not confer export or mutate data."""
import unittest
from fastapi.testclient import TestClient
import test_contributions_snapshot as fixture
from app.sped_generator.obligations import CATALOG_PATH,obligation_catalog

PATH='/api/companies/{cid}/sped-generator/contributions-snapshot'

class ContributionsDiscoveryTests(unittest.TestCase):
    def test_exact_readonly_route_is_not_an_official_generator_or_export(self):
        for registered,expected in [([],False),([('POST',PATH)],False),([('GET',PATH+'-other')],False),([('GET',PATH)],True)]:
            with self.subTest(registered=registered):
                obligations={o['id']:o for o in obligation_catalog(registered)['obligations']}
                contribution=obligations['efd_contribuicoes']
                self.assertEqual('not_implemented',contribution['implementation'])
                self.assertEqual([],contribution['exports'])
                self.assertFalse(contribution['complete_file_generator'])
                evidence=contribution['preparations'][0]
                self.assertEqual(expected,evidence['registered']);self.assertEqual('json',evidence['format'])
                self.assertTrue(evidence['requires_authorized_company_context'])
                self.assertFalse(evidence['generates_obligation_file']);self.assertFalse(evidence['mutates_domain'])
                self.assertFalse(evidence['validated_in_official_program'])
    def test_preparation_metadata_is_fresh_and_does_not_invent_ecf_serializer(self):
        first=obligation_catalog([('GET',PATH)])
        contribution=next(o for o in first['obligations'] if o['id']=='efd_contribuicoes')
        contribution['preparations'][0]['mutates_domain']=True
        fresh=obligation_catalog([('GET',PATH)])
        by_id={o['id']:o for o in fresh['obligations']}
        self.assertFalse(by_id['efd_contribuicoes']['preparations'][0]['mutates_domain'])
        self.assertEqual([],by_id['ecf']['preparations'])
        self.assertFalse(fresh['interoperability']['transmission_implemented'])

class ContributionsCompositionApiTests(unittest.TestCase):
    setUp=fixture.ContributionsSnapshotApiTests.setUp
    tearDown=fixture.ContributionsSnapshotApiTests.tearDown
    scope=fixture.ContributionsSnapshotApiTests.scope
    activate=fixture.ContributionsSnapshotApiTests.activate
    create_company=fixture.ContributionsSnapshotApiTests.create_company
    database_hash=fixture.ContributionsSnapshotApiTests.database_hash
    import_xmls=fixture.ContributionsSnapshotApiTests.import_xmls
    own_xml=fixture.ContributionsSnapshotApiTests.own_xml
    endpoint=fixture.ContributionsSnapshotApiTests.endpoint
    get=fixture.ContributionsSnapshotApiTests.get
    def test_running_catalog_and_evidence_preserve_current_index_and_database(self):
        self.import_xmls(11)
        with self.app.state.db.read() as c:
            before_index=c.execute("SELECT sql FROM sqlite_master WHERE name='idx_documents_cancellation_identity'").fetchone()[0]
        before=self.database_hash()
        result=self.client.get(CATALOG_PATH);self.assertEqual(200,result.status_code,result.text)
        obligations={o['id']:o for o in result.json()['obligations']}
        self.assertTrue(obligations['efd_contribuicoes']['preparations'][0]['registered'])
        self.assertTrue(obligations['ecd']['preparations'][0]['registered'])
        self.assertNotIn(self.a['tax_id'],result.text);self.assertNotIn(self.b['tax_id'],result.text)
        evidence=self.get();self.assertEqual(200,evidence.status_code,evidence.text)
        self.assertFalse(evidence.json()['snapshot']['generates_efd'])
        self.assertEqual(before,self.database_hash())
        with self.app.state.db.read() as c:self.assertEqual(before_index,c.execute("SELECT sql FROM sqlite_master WHERE name='idx_documents_cancellation_identity'").fetchone()[0])
    def test_global_metadata_does_not_grant_document_or_master_access(self):
        created=self.client.post('/api/users',json={'username':'catalog-only-composition','password':'Catalogo-sintetico-123!','role':'custom','company_ids':[self.a['id']],'permissions':[{'company_id':self.a['id'],'routine':'accounting.journals','action':'read','effect':'allow'}]})
        self.assertEqual(201,created.status_code,created.text)
        with TestClient(self.app) as reader:
            login=reader.post('/api/login',json={'username':'catalog-only-composition','password':'Catalogo-sintetico-123!'})
            self.assertEqual(200,login.status_code,login.text);reader.headers['X-CSRF-Token']=login.json()['csrf_token']
            self.assertEqual(200,reader.get(CATALOG_PATH).status_code)
            self.activate(self.a['id'],client=reader)
            response=self.get(client=reader);self.assertEqual(403,response.status_code,response.text)
        with TestClient(self.app) as anonymous:self.assertEqual(401,anonymous.get(CATALOG_PATH).status_code)
