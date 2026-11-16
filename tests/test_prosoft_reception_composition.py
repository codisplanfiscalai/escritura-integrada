"""Synthetic reception-to-Prosoft composition; no certificate or remote fiscal call."""
from io import BytesIO
from zipfile import ZipFile
import unittest
import test_core as base
import test_reception as reception
import test_prosoft_increment as prosoft


class ProsoftReceptionCompositionTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope
    raw = reception.ReceptionApiTests.raw
    preview = reception.ReceptionApiTests.preview
    post = prosoft.ProsoftApiTests.post

    def economic(self):
        with self.core.db.read(snapshot=True) as conn:
            return {table: [tuple(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY id')]
                    for table in ('documents','document_sources','journals','journal_lines','titles','imports')}

    def test_received_booked_xml_exports_with_original_receipt_and_book_decisions_preserved(self):
        mapping = self.client.post(self.scope('/fiscal-import-mappings'),json={
            'direction':'incoming','model':'55','source_cfop':'5102','target_cfop':'1102',
            'valid_from':'2026-01-01','valid_to':'','reason':'Synthetic composition','responsible':'Synthetic'})
        self.assertEqual(200,mapping.status_code,mapping.text)
        raw = self.raw()
        envelope = reception.response([('1','procNFe_v4.00.xsd',raw)],environment='1')
        batch = self.preview(envelope)
        overrides = {'document_overrides':{'documents:0':{'posting_date_confirmed':True}}}
        prepared = self.post(f"/imports/{batch['id']}/posting-preview",overrides)
        result = self.post(f"/imports/{batch['id']}/confirm",{'posting_mode':'book',
            'posting_hash':prepared['posting_hash'],'preview_hash':batch['preview_hash'],**overrides})
        self.assertEqual(1,result['documents_booked'])
        doc = self.core.documents(self.a['id'])[0]
        self.assertEqual(('booked','2026-10-30','2026-11-06'),tuple(doc[k] for k in ('status','issue_date','posting_date')))
        before = self.economic()
        payload = prosoft.configuration() | {'period':'2026-11','company_code':'99'}
        preview = self.post('/prosoft-fiscal/preview',payload)
        saved = self.post('/prosoft-fiscal/confirm',payload | {
            'preview_hash':preview['preview_hash'],'destination_reviewed':True})
        response = self.client.get(self.scope(f"/prosoft-fiscal/exports/{saved['id']}/download"))
        self.assertEqual(200,response.status_code,response.text)
        with ZipFile(BytesIO(response.content)) as archive:
            lines = archive.read('ENTRADAS.TXT').splitlines()
            self.assertEqual([2340],list(map(len,lines)))
            self.assertEqual(b'0',lines[0][808:809])
            self.assertEqual(b'1102',lines[0][623:627])
        trace = saved['manifest']['trace'][0]
        self.assertEqual(doc['id'],trace['document_id'])
        self.assertEqual(doc['source_hash'],trace['source_hash'])
        self.assertFalse(trace['cancelled'])
        self.assertTrue(trace['sources'])
        self.assertEqual(10000,saved['manifest']['totals']['incoming']['total_cents'])
        self.assertEqual(envelope,self.client.get(self.scope(f"/imports/{batch['id']}/original")).content)
        self.assertEqual(raw,self.client.get(self.scope(f"/imports/{batch['id']}/documents/0/download")).content)
        self.assertEqual(before,self.economic())
        self.assertEqual([],self.core.journals(self.a['id']))
        self.assertEqual([],self.core.titles(self.a['id']))


if __name__ == '__main__': unittest.main()
