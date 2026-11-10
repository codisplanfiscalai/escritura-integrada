"""Synthetic book assertions, distinct from electronic cancellation events."""
import io
import unittest
from openpyxl import load_workbook
from pypdf import PdfReader
import test_business as base

class BookCancellationTests(unittest.TestCase):
    setUp = base.BusinessTests.setUp
    tearDown = base.BusinessTests.tearDown
    scope = base.BusinessTests.scope
    activate = base.BusinessTests.activate
    create_company = base.BusinessTests.create_company
    document = base.BusinessTests.document
    post = base.BusinessTests.post

    def payload(self, **extra):
        return self.document('90201') | {'direction':'outgoing','total':'0.00','taxes':{},'items':[], 'source_hash':'',
            'book_cancellation':{'source':'Livro sintético, página 2, linha 3','responsible':'Revisor sintético','reason':'Período conferido'}, **extra}

    def test_review_book_exports_and_idempotence(self):
        payload=self.payload(idempotency_key='cancel-synthetic')
        d=self.post('/documents',payload,201)
        self.assertEqual('cancelled',d['document_state']);self.assertEqual('pending',d['status'])
        self.assertEqual('validated_fiscal_book',d['source']['type'])
        self.assertNotIn('authorization',d)
        self.assertEqual(d['id'],self.post('/documents',payload,201)['id'])
        d=self.post(f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Conferido conforme livro sintético'})
        book={'version':d['version'],'reason':'Registro da linha cancelada','idempotency_key':'cancel-book'}
        result=self.post(f"/documents/{d['id']}/book",book)
        self.assertEqual([],result['titles']);self.assertIsNone(result['journal'])
        self.assertEqual('booked',result['document']['status'])
        self.assertTrue(self.post(f"/documents/{d['id']}/book",book)['duplicate'])
        url='/business-reports/fiscal-outputs?start=2026-11-01&end=2026-11-30&status=cancelled'
        report=self.client.get(self.scope(url)).json()
        self.assertEqual('cancelled',report['filters']['status'])
        self.assertEqual('booked',report['rows'][0]['status'])
        self.assertEqual(1,len(report['rows']));row=report['rows'][0]
        for field in ('total_cents','book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents'):
            self.assertEqual(0,row[field],field)
        self.assertEqual(0,report['totals']['total_cents'])
        for key in ('declared_icms_cents','declared_ipi_cents','declared_icms_base_cents','declared_ipi_base_cents'):
            self.assertIsNone(row[key])
        self.assertEqual(payload['book_cancellation']['source'],row['cancellation_source'])
        pdf=self.client.get(self.scope(url+'&format=pdf'))
        self.assertEqual(200,pdf.status_code)
        text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        self.assertIn('Canceladas conforme livro validado',text);self.assertIn('Livro sintético',text)
        xlsx=self.client.get(self.scope(url+'&format=xlsx'))
        wb=load_workbook(io.BytesIO(xlsx.content))
        self.assertIn('Estado documental',[c.value for c in wb['Dados'][1]])
        self.assertEqual([],self.core.titles(self.a['id']));self.assertEqual([],self.core.journals(self.a['id']))

    def test_identity_immutable_and_effect_guards(self):
        d=self.post('/documents',self.payload(),201)
        for change in ({'total':'1.00'}, {'book_cancellation':None}):
            r=self.client.put(self.scope(f"/documents/{d['id']}"),json={'version':d['version'],'reason':'Tentativa sintética',**change})
            self.assertEqual(409,r.status_code,r.text)
        self.post('/documents',self.payload(total='1.00'),400)
        normal=self.document('00090201')|{'direction':'outgoing','series':'001'}
        self.post('/documents',normal,409)
        other=self.post('/documents',self.payload(model='65'),201)
        self.assertNotEqual(d['id'],other['id'])
        for effect in ({'generate_titles':True},{'model_id':1},{'lines':[{}]}):
            self.post(f"/documents/{d['id']}/book",{'version':d['version'],'reason':'Teste',**effect},400)
        r=self.client.post(self.scope('/titles'),json={'kind':'receivable','description':'Teste','amount':'1.00','issue_date':'2026-11-06','due_date':'2026-11-10','document_id':d['id']})
        self.assertEqual(400,r.status_code,r.text)

    def test_evidence_period_and_existing_document_guards(self):
        self.post('/documents',self.payload(book_cancellation={'source':'x'}),400)
        self.post('/documents',self.payload(authorization={'protocol':'fake'}),400)
        self.post('/documents',self.payload(direction='incoming'),400)
        normal=self.post('/documents',self.document('90201')|{'direction':'outgoing'},201)
        self.post('/documents',self.payload(),409)
        self.assertEqual(10000,self.core.documents(self.a['id'])[0]['total_cents'])
        normal=self.post(f"/documents/{normal['id']}/review",{'version':normal['version'],'reason':'Conferido'})
        self.post(f"/documents/{normal['id']}/book",{'version':normal['version'],'reason':'Escrituração sem efeitos'})
        self.post('/periods/close',{'period':'2026-11','module':'fiscal','reason':'Teste'})
        self.post('/documents',self.payload(number='90202'),409)
        self.activate(self.b['id'])
        # Same identity in another company is independent.
        response=self.client.post(self.scope('/documents',self.b['id']),json=self.payload())
        self.assertEqual(201,response.status_code,response.text)
        self.assertEqual(self.b['id'],response.json()['company_id'])

    def test_untrusted_markers_and_incoming_issuer_identity(self):
        fake=self.post('/documents',self.document('FAKE')|{'source':{'book_cancellation':{'source':'x'},'document_state':'cancelled'}, 'extra_json':'{"document_state":"cancelled"}'},201)
        self.assertNotIn('document_state',fake)
        self.assertNotIn('book_cancellation',fake)
        self.post('/documents',self.document('FAKE2')|{'document_state':'cancelled'},400)
        r=self.client.put(self.scope(f"/documents/{fake['id']}"),json={'version':fake['version'],'reason':'Teste','book_cancellation':self.payload()['book_cancellation']})
        self.assertEqual(409,r.status_code)
        d=self.post('/documents',self.payload(direction='incoming',partner_tax_id='11111111111'),201)
        authorized=self.document('90201')|{'partner_tax_id':'111.111.111-11','key':'synthetic-key','authorization':{'protocol':'synthetic'}}
        self.post('/documents',authorized,409)
        other=self.post('/documents',authorized|{'partner_tax_id':'22222222222','key':'synthetic-key-other'},201)
        self.assertNotEqual(d['id'],other['id'])
        from app.auditor_results import bookkeeping_document
        audited=bookkeeping_document(d)
        self.assertEqual('cancelled',audited['status'])
        self.assertEqual(d['book_cancellation'],audited['book_cancellation'])

    def test_concurrent_identical_creates(self):
        from concurrent.futures import ThreadPoolExecutor
        def create(_):
            return self.core.create_document(self.a['id'],self.payload(idempotency_key='race-cancel'),'synthetic-reviewer')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(create,range(2)))
        self.assertEqual(results[0]['id'],results[1]['id'])
        self.assertEqual(1,len(self.core.documents(self.a['id'])))

    def test_later_effects_reverse_and_closed_context(self):
        from app.core import DomainError
        d=self.post('/documents',self.payload(),201)
        d=self.post(f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Conferido'})
        # Optional XML/rule generators reject persisted cancellation even with a
        # caller-supplied source that omits its marker. No real XML is fabricated.
        for method in ('_create_import_payables','_create_generated_payables'):
            with self.core.db.transaction() as conn:
                args=[conn,self.a['id'],{'id':d['id']},{'direction':'incoming'}]
                if method=='_create_generated_payables':args.append({'enabled':True})
                with self.assertRaises(DomainError) as failure:
                    getattr(self.core,method)(*args,'synthetic')
                self.assertEqual('cancelled_document',failure.exception.code)
        d=self.post(f"/documents/{d['id']}/book",{'version':d['version'],'reason':'Registro sintético'})['document']
        reverse={'version':d['version'],'date':d['posting_date'],'reason':'Tentativa sintética','idempotency_key':'reverse-cancel'}
        reversed=self.post(f"/documents/{d['id']}/reverse",reverse)
        self.assertEqual('pending',reversed['document']['status'])
        self.assertEqual('cancelled',reversed['document']['document_state'])
        self.assertEqual(d['source'],reversed['document']['source'])
        self.assertIsNone(reversed['journal']);self.assertEqual(0,reversed['cancelled_titles'])
        d=reversed['document']
        d=self.post(f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Reconferido'})
        d=self.post(f"/documents/{d['id']}/book",{'version':d['version'],'reason':'Reescriturado sem efeitos'})['document']
        self.post('/periods/close',{'period':'2026-11','module':'fiscal','reason':'Fechamento sintético'})
        for action in ('book','review'):
            self.post(f"/documents/{d['id']}/{action}",{'version':d['version'],'reason':'Tentativa fechada'},409)
        self.assertEqual([],self.core.journals(self.a['id']))
        self.assertEqual([],self.core.titles(self.a['id']))

    def test_reprocess_and_import_cannot_replace_book_assertion(self):
        import test_fiscal_import as imports
        batch=imports.FiscalImportTests.preview(self,raw=imports.FiscalImportTests.xml(self))
        raw=batch['documents'][0]
        d=self.post('/documents',self.payload(**{k:raw[k] for k in ('direction','model','series','number','key','issue_date','partner_name','partner_tax_id')}),201)
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",{})
        self.assertFalse(plan['can_confirm'])
        self.assertIn('Cancelada conforme livro',plan['documents'][0]['reason'])
        self.post(f"/imports/{batch['id']}/reprocess-confirm",{'reprocess_hash':plan['reprocess_hash'],'idempotency_key':'blocked-reprocess','reason':'Teste'},409)
        self.post(f"/imports/{batch['id']}/confirm",{'preview_hash':batch['preview_hash'],'posting_mode':'pending'},409)
        current=self.core.documents(self.a['id'])
        self.assertEqual(1,len(current));self.assertEqual(d['version'],current[0]['version'])
        self.assertEqual(d['source'],current[0]['source'])

    def test_readonly_permission_cannot_register_review_or_book(self):
        from fastapi.testclient import TestClient
        d=self.post('/documents',self.payload(),201)
        permissions=[{'company_id':self.a['id'],'routine':'fiscal.documents','action':'read','effect':'allow'}]
        r=self.client.post('/api/users',json={'username':'reader-cancel','password':'Synthetic-Reader-123!','role':'custom','company_ids':[self.a['id']],'permissions':permissions})
        self.assertEqual(201,r.status_code,r.text)
        with TestClient(self.app) as reader:
            r=reader.post('/api/login',json={'username':'reader-cancel','password':'Synthetic-Reader-123!'})
            self.assertEqual(200,r.status_code,r.text)
            reader.headers['X-CSRF-Token']=r.json()['csrf_token']
            self.activate(self.a['id'],client=reader)
            for route,payload in [('/documents',self.payload()),*( (f"/documents/{d['id']}/{action}",{'version':d['version'],'reason':'Teste'}) for action in ('review','book','reverse'))]:
                r=reader.post(self.scope(route),json=payload)
                self.assertEqual(403,r.status_code,r.text)

    def test_alphanumeric_issuers_with_same_digits_are_distinct(self):
        # Both identifiers share every numeric character, but letters differ.
        first=self.post('/documents',self.payload(direction='incoming',partner_tax_id='AB.CDE.FGH/0001-23'),201)
        second=self.post('/documents',self.document('90201')|{'partner_tax_id':'XY.ZUV.WST/0001-23'},201)
        self.assertNotEqual(first['id'],second['id'])
        self.post('/documents',self.document('90201')|{'partner_tax_id':'abcdefgh000123'},409)

    def test_book_cancellation_has_no_declared_tax_coverage(self):
        self.post('/documents',self.payload(),201)
        url='/business-reports/fiscal-taxes?start=2026-11-01&end=2026-11-30&status=cancelled'
        response=self.client.get(self.scope(url))
        self.assertEqual(200,response.status_code,response.text)
        report=response.json()
        self.assertEqual(1,len(report['rows']))
        for tax in ('icms','ipi','iss','pis','cofins','ibs','cbs'):
            self.assertIsNone(report['rows'][0][tax+'_cents'])
            self.assertIsNone(report['rows'][0][tax+'_base_cents'])
            self.assertEqual(0,report['totals'][tax+'_informed_documents'])
        response=self.client.get(self.scope(url+'&format=pdf'))
        self.assertEqual(200,response.status_code)
        text=' '.join(' '.join(p.extract_text().split()) for p in PdfReader(io.BytesIO(response.content)).pages)
        self.assertIn('campos ausentes permanecem em branco',text)
        for tax in ('ICMS','IPI','ISS','PIS','COFINS','IBS','CBS'):
            self.assertIn('Documentos com '+tax+' 0',text)
        self.assertIn('Livro sintético',text)
        self.assertNotIn('1/1',text)

    def test_specialized_cancelled_book_pdfs_have_no_empty_final_page(self):
        from app.fiscal_report_models import fiscal_pdf
        d=self.post('/documents',self.payload(),201)
        d=self.post(f"/documents/{d['id']}/review",{'version':d['version'],'reason':'Revisão visual sintética'})
        self.post(f"/documents/{d['id']}/book",{'version':d['version'],'reason':'Linha cancelada sem efeitos'})
        for kind in ('fiscal-outputs','fiscal-taxes'):
            result=self.client.get(self.scope(f'/business-reports/{kind}?start=2026-11-01&end=2026-11-30&status=cancelled')).json()
            data,_=fiscal_pdf(result)
            for index,page in enumerate(PdfReader(io.BytesIO(data)).pages,1):
                body=[line.strip() for line in page.extract_text().splitlines()
                      if line.strip() and line.strip()!=result['title']
                      and not line.strip().startswith(('Período:','Folha:','Empresa:','Escritura Integrada |','internal-fiscal-'))]
                self.assertTrue(body,f'{kind}, página {index}: apenas cabeçalho/rodapé')

    def test_bulk_update_cancelled_preview_confirm_and_forged_snapshot(self):
        from app.bulk_operations import BulkOperations, initialize_bulk_schema
        from app.core import DomainError
        from unittest.mock import patch
        service=BulkOperations(self.core)
        with self.core.db.transaction() as conn:
            initialize_bulk_schema(conn)
            uid=conn.execute("SELECT id FROM users WHERE username='teste'").fetchone()[0]
        d=self.post('/documents',self.payload(cfop='5102'),201)
        req={'kind':'documents','action':'update','period':'2026-11','ids':[d['id']],'changes':{'cfop':'5405'}}
        preview=service.preview(self.a['id'],req,uid,'teste')
        self.assertFalse(preview['can_confirm'])
        self.assertIn('document_immutable',[b['code'] for b in preview['blockers']])
        def confirm(p,**extra):
            return service.confirm(self.a['id'],{'preview_id':p['id'],'preview_hash':p['preview_hash'],'reason':'Teste sintético','confirmation_phrase':p['confirmation_phrase'],**extra},uid,'teste')
        with self.assertRaises(DomainError) as failure:confirm(preview)
        self.assertEqual('document_immutable',failure.exception.code)
        with self.assertRaises(DomainError):confirm(preview,changes={'cfop':'5405'})
        # Simulate a previously issued preview under the old, permissive code.
        inspect=service._inspect
        def legacy(*args):
            result,rows=inspect(*args)
            return result|{'blockers':[],'can_confirm':True},rows
        with patch.object(service,'_inspect',side_effect=legacy):
            stale=service.preview(self.a['id'],req,uid,'teste')
        self.assertTrue(stale['can_confirm'])
        with self.assertRaises(DomainError) as failure:confirm(stale)
        self.assertEqual('document_immutable',failure.exception.code)
        with self.core.db.transaction() as conn:
            row=dict(conn.execute('SELECT * FROM documents WHERE id=?',(d['id'],)).fetchone())
            row['extra_json']='{}'
            with self.assertRaises(DomainError) as failure:
                service._apply(conn,self.a['id'],req,[row],'teste','Tentativa com snapshot forjado')
            self.assertEqual('document_immutable',failure.exception.code)
        current=self.core.documents(self.a['id'])[0]
        self.assertEqual('5102',current['cfop']);self.assertEqual(d['version'],current['version'])
        self.assertEqual(d['source'],current['source'])
        # The guard must not remove safe lifecycle transitions, even without CFOP.
        no_cfop=self.post('/documents',self.payload(number='90288',cfop=''),201)
        req=req|{'ids':[d['id'],no_cfop['id']]}
        for action in ('review','book'):
            ready=service.preview(self.a['id'],req|{'action':action,'changes':{}},uid,'teste')
            self.assertTrue(ready['can_confirm'],ready)
            confirm(ready)
        self.assertEqual('booked',self.core.documents(self.a['id'])[0]['status'])
        self.assertEqual([],self.core.titles(self.a['id']));self.assertEqual([],self.core.journals(self.a['id']))
