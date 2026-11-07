"""Regressões de leitura em lote, sessão, impressão e permissões."""
import unittest
from unittest.mock import patch
import test_core as base
from app.periods import decision
from app.desktop_pdf import preview_url_allowed


class ExportPerformanceTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company
    document=base.CoreApiTests.document

    def trace(self, callback):
        sql=[];original=self.app.state.db.connect
        def connect():
            conn=original();conn.set_trace_callback(sql.append);return conn
        with patch.object(self.app.state.db,'connect',connect):result=callback()
        return result,sql

    def test_document_list_preserves_detail_sources_order_company_and_year(self):
        for n in range(12):self.core.create_document(self.a['id'],self.document(str(n)),'teste')
        self.core.create_document(self.b['id'],self.document('outra empresa'),'teste')
        with self.app.state.db.transaction() as c:
            c.execute("UPDATE documents SET period='2025-12',posting_date='2025-12-01' WHERE company_id=? AND number='0'",(self.a['id'],))
        result,sql=self.trace(lambda:self.core.documents(self.a['id'],year=2026))
        self.assertEqual(11,len(result));self.assertLessEqual(len(sql),6)
        with self.app.state.db.read() as c:
            for row in result:self.assertEqual(self.core._document(c,self.a['id'],row['id']),row)
        self.assertEqual(sorted([r['id'] for r in result],reverse=True),[r['id'] for r in result])
        self.assertEqual(result,self.client.get(self.scope('/documents?year=2026')).json())
        report,sql=self.trace(lambda:self.core.fiscal_report(self.a['id'],'fiscal-documents','2026-01-01','2026-12-31'))
        self.assertLessEqual(len(sql),5);self.assertEqual(110000,report['totals']['total_cents'])
        self.assertEqual(11,report['totals']['documents'])

    def test_request_does_not_rebuild_permission_matrix_but_session_still_does(self):
        with patch('app.periods.decision',wraps=decision) as check:
            response=self.client.get(self.scope('/documents?year=2026'))
            self.assertEqual(200,response.status_code,response.text);self.assertEqual(0,check.call_count)
            session=self.client.get('/api/session').json()
            self.assertIn('fiscal.reports',session['permissions']);self.assertGreater(check.call_count,0)
        with self.app.state.db.transaction() as c:c.execute("UPDATE users SET active=0 WHERE username='teste'")
        self.assertEqual(401,self.client.get(self.scope('/documents?year=2026')).status_code)

    def test_pdf_preview_for_fiscal_accounting_financial_and_print_permission(self):
        from fastapi.testclient import TestClient
        user=self.client.post('/api/users',json={'username':'impressao','password':'Senha-sintetica-2026','role':'custom','company_ids':[self.a['id']],
            'permissions':[{'company_id':self.a['id'],'routine':m+'.reports','action':a,'effect':'allow'} for m in ('fiscal','accounting','financial') for a in ('read','print')]}).json()
        with TestClient(self.app) as client:
            session=client.post('/api/login',json={'username':'impressao','password':'Senha-sintetica-2026'}).json()
            client.headers['X-CSRF-Token']=session['csrf_token'];self.activate(self.a['id'],client=client)
            for kind in ('fiscal-documents','diary','financial'):
                path=self.scope(f'/business-reports/{kind}?start=2026-01-01&end=2026-12-31&format=pdf')
                self.assertEqual(403,client.get(path).status_code)
                response=client.get(path+'&purpose=print')
                self.assertEqual(200,response.status_code,response.text[:100] if response.status_code!=200 else '')
                self.assertTrue(response.content.startswith(b'%PDF'));self.assertTrue(response.headers['content-disposition'].startswith('inline;'))
                from pypdf import PdfReader
                from io import BytesIO
                label={'fiscal-documents':'Documentos fiscais','diary':'Diário Geral','financial':'Títulos por vencimento'}[kind]
                self.assertIn(label,PdfReader(BytesIO(response.content)).pages[0].extract_text())
                self.assertTrue(preview_url_allowed('http://127.0.0.1:3456'+path+'&purpose=print','http://127.0.0.1:3456'))
        self.assertTrue(preview_url_allowed('http://127.0.0.1:3456'+self.scope('/tax-ledgers/1/report?format=pdf&purpose=print'),'http://127.0.0.1:3456'))
        self.assertFalse(preview_url_allowed('http://127.0.0.1:3456'+self.scope('/business-reports/diary?format=pdf&purpose=export'),'http://127.0.0.1:3456'))
