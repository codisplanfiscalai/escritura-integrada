"""Aceitação do modelo editorial, planilhas e agregações sem efeitos na origem."""
from io import BytesIO
from decimal import Decimal
from copy import deepcopy
import unittest
from openpyxl import load_workbook
from pypdf import PdfReader
import test_auditor_integration as integration
from auditor_samples import sample_archive
from app.auditor_reports import export_audit
from app.auditor_results import analytics
import base64


class AuditorPresentationTests(unittest.TestCase):
    setUp=integration.AuditorIntegrationTests.setUp
    tearDown=integration.AuditorIntegrationTests.tearDown
    scope=integration.AuditorIntegrationTests.scope
    activate=integration.AuditorIntegrationTests.activate
    create_company=integration.AuditorIntegrationTests.create_company
    document=integration.AuditorIntegrationTests.document
    xml=integration.AuditorIntegrationTests.xml
    submit=integration.AuditorIntegrationTests.submit

    def test_original_editorial_sections_columns_and_totals(self):
        job=self.submit(files=[{'filename':'amostra.zip','content_base64':base64.b64encode(sample_archive(self.a['tax_id'])).decode()}])
        self.assertEqual('completed',job['status'],job['error'])
        stats=job['analytics'];self.assertEqual(8,stats['overview']['documents']);self.assertEqual(24,stats['overview']['items'])
        self.assertEqual(4,stats['overview']['input_count']);self.assertEqual(4,stats['overview']['output_count'])
        self.assertEqual(Decimal('3528'),Decimal(stats['overview']['total_value']))
        self.assertEqual(24,stats['comparable_items'])
        self.assertTrue(all(Decimal(r['difference'])==0 for r in stats['tax_comparison']))
        pdf,_=export_audit(job,'pdf');reader=PdfReader(BytesIO(pdf));texts=[p.extract_text() for p in reader.pages]
        for label in ['Resumo executivo','AÇÕES PRIORITÁRIAS','Como a base de IBS/CBS foi formada','Relatório analítico das saídas','Relatório analítico das entradas','Auditoria NCM','Conciliação econômica','Memória de cálculo','Fontes, método']:
            self.assertTrue(any(label in text for text in texts),label)
        output_page=next(t for t in texts if 'Relatório analítico das saídas' in t)
        input_page=next(t for t in texts if 'Relatório analítico das entradas' in t)
        self.assertIn('CLIENTE SINTÉTICO',output_page);self.assertNotIn('FORNECEDOR SINTÉTICO',output_page)
        self.assertIn('FORNECEDOR SINTÉTICO',input_page);self.assertIn('3.528,00',texts[0])
        data,_=export_audit(job,'xlsx');wb=load_workbook(BytesIO(data),data_only=True)
        self.assertEqual('Resumo Executivo',wb.active.title);self.assertIn('A1:H1',[str(r) for r in wb.active.merged_cells])
        self.assertEqual(3528,wb.active['C5'].value);self.assertEqual(8,wb.active['A5'].value)
        self.assertEqual(3528,sum(row[8] for row in list(wb['Notas - Sintético'].values)[1:]))
        headers=list(next(wb['Itens - Analítico'].values))
        self.assertTrue({'vProd','vPIS','vCOFINS','vICMS','Diferença base','Base recalculada','IBS XML','CBS recálculo'}<=set(headers))
        self.assertTrue({'CST PIS','CST COFINS'}<=set(next(wb['Tributos'].values)))
        self.assertEqual('s',wb['Itens - Analítico']['F2'].data_type)
        self.assertTrue(wb['Notas - Sintético'].tables)
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_noncomparable_items_and_excluded_documents_do_not_pollute_totals(self):
        job=self.submit();doc=job['result']['documents'][0];special=deepcopy(doc);special['status']='outside_period';special['document_ref']='excluded'
        special['total_value']='999999';special['items'][0]['calculation_scope']='regular'
        original=doc['items'][0];original['calculation_scope']='unsupported_special';original['ibs_recalculated']='999'
        a=analytics([doc,special],job['findings'])
        self.assertEqual(1,a['excluded_documents']);self.assertEqual(0,a['comparable_items']);self.assertEqual(1,a['not_recalculated_items'])
        self.assertEqual(Decimal('100'),Decimal(a['overview']['total_value']))
        data,_=export_audit(job,'xlsx');ws=load_workbook(BytesIO(data))['IBS e CBS']
        self.assertIsNone(ws['I2'].value);self.assertIsNone(ws['N2'].value)

    def test_resolved_findings_leave_priority_queue_without_changing_history(self):
        job=self.submit();count=job['analytics']['open_findings'];f=job['findings'][0]
        self.assertGreater(count,0)
        self.client.put(self.scope(f"/auditor/findings/{f['id']}/treatment"),json={'version':f['version'],'status':'resolved','responsible':'Revisor','treatment':'Revisão documentada'})
        fresh=self.core.auditor_job(self.a['id'],job['id'])
        self.assertEqual(count-1,fresh['analytics']['open_findings']);self.assertEqual(len(job['findings']),len(fresh['findings']))
        self.assertNotIn(f['id'],[f['id'] for f in fresh['analytics']['priorities']])

    def test_pdf_preview_is_same_origin_only_and_requires_permission(self):
        job=self.submit()
        prefix=self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf")
        preview=self.client.get(prefix+'&purpose=print')
        self.assertEqual(200,preview.status_code)
        self.assertEqual('SAMEORIGIN',preview.headers['x-frame-options'])
        self.assertIn("frame-ancestors 'self'",preview.headers['content-security-policy'])
        self.assertEqual('DENY',self.client.get(prefix).headers['x-frame-options'])
        self.assertEqual('DENY',self.client.get('/').headers['x-frame-options'])

    def test_export_keeps_document_event_and_catalog_evidence(self):
        job=self.submit();d=job['result']['documents'][0]
        f=deepcopy(job['findings'][0]);f.update(category='duplicate',rule_code='DUP-001',evidence={'matching_document':'987','reason':'Mesma chave'})
        job['findings'].append(f)
        job['result']['events']=[{'access_key':d['access_key'],'event_type':'110111','status_code':'135','description':'Cancelamento registrado','registered_at':'2026-01-20T15:00:00-03:00'}]
        job['snapshot']['catalog']={'name':'Revisão sintética','entries':[{'ncm':'87032100','cst':'999','cclass_trib':'000001','source_sheet':'NCM_ORIGEM','source_row':87}],'reference':{}}
        wb=load_workbook(BytesIO(export_audit(job,'xlsx')[0]),data_only=True)
        def rows(name):
            values=list(wb[name].values)
            return [dict(zip(values[0],r)) for r in values[1:]]
        finding=next(r for r in rows('Inconsistências') if r['Regra']=='DUP-001')
        self.assertEqual(d['number'],finding['NF']);self.assertEqual(d['access_key'],finding['Chave'])
        self.assertIn('matching_document',finding['Evidência'])
        occurrences=rows('Duplicidades e Eventos');self.assertEqual(2,len(occurrences))
        self.assertEqual(d['number'],occurrences[1]['NF']);self.assertEqual(d['access_key'],occurrences[1]['Chave'])
        self.assertEqual('2026-01-20T15:00:00-03:00',occurrences[1]['Data/Evidência'])
        quality=rows('Qualidade Parametrização')[0]
        self.assertEqual('NCM_ORIGEM',quality['Aba']);self.assertEqual(87,quality['Linha'])
        self.assertIn('87032100',quality['Contexto'])
