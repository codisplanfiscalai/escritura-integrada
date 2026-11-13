"""Synthetic arithmetic checks never infer credit or tax treatment."""
import unittest
from app.document_totals import document_total_issue


class DocumentTotalsTests(unittest.TestCase):
    def document(self, total=39504, **components):
        return {'items':[{'number':'1','total':'415.83','declared_product_fields':{'indTot':'1'}}], 'total_cents':total,
                'taxes':{'ICMSTot.vProd':'415.83','ICMSTot.vDesc':'20.79','ICMSTot.vNF':'395.04',**{'ICMSTot.'+k:v for k,v in components.items()}}}

    def test_discount_reconciles_instead_of_false_alert(self):
        self.assertIsNone(document_total_issue(self.document()))
        changed=self.document(total=40000)
        self.assertEqual('ITEM_HEADER_DIFFERENCE',document_total_issue(changed)[0])
        self.assertEqual(40000,changed['total_cents'])

    def test_declared_additions_and_real_difference(self):
        doc=self.document(total=43104,vST='10.00',vFCPST='1.00',vFrete='5.00',vSeg='2.00',vOutro='3.00',vII='4.00',vIPI='6.00',vIPIDevol='5.00',vNF='431.04')
        self.assertIsNone(document_total_issue(doc))
        doc['taxes']['ICMSTot.vFrete']='6.00'
        self.assertEqual('ITEM_HEADER_DIFFERENCE',document_total_issue(doc)[0])

    def test_indtot_excluded_and_header_item_mismatch_remain_visible(self):
        doc=self.document();doc['items'].append({'total':'99.00','declared_product_fields':{'indTot':'0'}})
        self.assertIsNone(document_total_issue(doc))
        doc['items'][0]['total']='414.83'
        self.assertEqual('ITEM_HEADER_DIFFERENCE',document_total_issue(doc)[0])

    def test_desoneration_is_not_inferred(self):
        doc=self.document(vICMSDeson='5.00')
        self.assertEqual('TOTAL_COMPONENTS_REVIEW',document_total_issue(doc)[0])
        doc['items'][0]['taxes']={'ICMS.ICMS20.vICMSDeson':'5.00','ICMS.ICMS20.indDeduzDeson':'0'}
        self.assertIsNone(document_total_issue(doc))
        doc['items'][0]['taxes']['ICMS.ICMS20.indDeduzDeson']='1'
        doc['taxes']['ICMSTot.vNF']='390.04';doc['total_cents']=39004
        self.assertIsNone(document_total_issue(doc))

    def test_incomplete_invalid_and_manual_totals(self):
        doc=self.document(vDesc='inválido')
        self.assertEqual('ITEM_VALUE',document_total_issue(doc)[0])
        doc=self.document();del doc['taxes']['ICMSTot.vNF']
        self.assertEqual('TOTAL_COMPONENTS_REVIEW',document_total_issue(doc)[0])
        doc=self.document();doc['taxes']={}
        self.assertEqual('ITEM_HEADER_DIFFERENCE',document_total_issue(doc)[0])
        doc['total_cents']=41583;self.assertIsNone(document_total_issue(doc))


class DocumentTotalReportIntegrationTests(unittest.TestCase):
    import test_core as fixtures
    setUp = fixtures.CoreApiTests.setUp
    tearDown = fixtures.CoreApiTests.tearDown
    create_company = fixtures.CoreApiTests.create_company
    activate = fixtures.CoreApiTests.activate
    scope = fixtures.CoreApiTests.scope
    document = fixtures.CoreApiTests.document

    def test_discount_is_reconciled_in_actual_pending_report(self):
        values=DocumentTotalsTests().document()
        payload=self.document('SYN-3020')|{'total':'395.04','taxes':values['taxes'],'items':values['items']}
        created=self.client.post(self.scope('/documents'),json=payload)
        self.assertEqual(201,created.status_code,created.text)
        endpoint=self.scope('/business-reports/fiscal-inconsistencies?start=2026-11-01&end=2026-11-30')
        report=self.client.get(endpoint)
        self.assertEqual(200,report.status_code,report.text)
        self.assertNotIn('ITEM_HEADER_DIFFERENCE',[r['code'] for r in report.json()['rows']])
        doc=created.json()
        changed=self.client.put(self.scope(f"/documents/{doc['id']}"),json={'version':doc['version'],'reason':'Diferença sintética','total':'400.00'})
        self.assertEqual(200,changed.status_code,changed.text)
        self.assertIn('ITEM_HEADER_DIFFERENCE',[r['code'] for r in self.client.get(endpoint).json()['rows']])
