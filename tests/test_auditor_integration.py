"""Aceitação do Auditor migrado: artefatos abertos, escopo, estados, catálogos e recuperação."""
import base64
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
import test_evolution as base


class AuditorIntegrationTests(unittest.TestCase):
    setUp=base.EvolutionTests.setUp
    tearDown=base.EvolutionTests.tearDown
    scope=base.EvolutionTests.scope
    activate=base.EvolutionTests.activate
    create_company=base.EvolutionTests.create_company
    document=base.EvolutionTests.document
    xml=base.EvolutionTests.xml

    def submit(self,raw=None,mode='standalone',key='audit',**extra):
        payload={'mode':mode,'start':'2026-01-01','end':'2026-12-31','idempotency_key':key,**extra}
        if mode=='standalone':payload['files']=extra.get('files') or [{'filename':'document.xml','content_base64':base64.b64encode(raw or self.xml()).decode()}]
        with patch.object(self.app.state.auditor,'submit'):
            response=self.client.post(self.scope('/auditor/jobs'),json=payload)
        self.assertEqual(201,response.status_code,response.text)
        jid=response.json()['id'];self.app.state.auditor.run(self.a['id'],jid)
        return self.core.auditor_job(self.a['id'],jid)

    def test_rejected_company_is_failed_and_has_diagnostic_reports(self):
        raw=self.xml().replace(self.a['tax_id'].encode(),self.b['tax_id'].encode())
        job=self.submit(raw)
        self.assertEqual('failed',job['status']);self.assertEqual(1,job['result']['outcome']['rejected'])
        self.assertEqual([],job['result']['documents']);self.assertEqual(2,len(job['reports']))
        self.assertIn('Nenhum documento',job['error'])
        self.assertEqual([],self.core.documents(self.a['id']))
        content=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf")).content
        self.assertIn('recusados',' '.join(p.extract_text() for p in PdfReader(BytesIO(content)).pages))

    def test_mixed_batch_reports_every_refusal_and_duplicate_without_double_totals(self):
        data=BytesIO()
        with ZipFile(data,'w') as z:
            z.writestr('a.xml',self.xml());z.writestr('repetido.xml',self.xml());z.writestr('invalido.xml','<erro>')
        job=self.submit(files=[{'filename':'amostra.zip','content_base64':base64.b64encode(data.getvalue()).decode()}])
        self.assertEqual('completed',job['status']);self.assertEqual(1,len(job['result']['documents']))
        self.assertEqual(10000,job['result']['totals']['total_cents'])
        self.assertEqual(1,job['result']['outcome']['duplicates']);self.assertEqual(1,job['result']['outcome']['rejected'])
        self.assertEqual(3,len(job['result']['file_outcomes']));self.assertEqual(100,job['progress'])
        self.assertEqual(3,job['processed_files']);self.assertEqual(2,len(job['reports']))

    def test_internal_xml_selection_closed_month_and_three_values(self):
        raw=self.xml()
        preview=self.client.post(self.scope('/imports/preview'),json={'filename':'origem.xml','content_base64':base64.b64encode(raw).decode(),'period':'2026-11','options':{'posting_date':'2026-11-06'}}).json()
        r=self.client.post(self.scope(f"/imports/{preview['id']}/confirm"),json={'preview_hash':preview['preview_hash']});self.assertEqual(200,r.status_code,r.text)
        doc=self.core.documents(self.a['id'])[0]
        changed=[dict(i,taxes={**i['taxes'],'ICMS/ICMS00/vICMS':'19.00'}) for i in doc['items']]
        r=self.client.put(self.scope(f"/documents/{doc['id']}"),json={'version':doc['version'],'reason':'Diferença sintética','items':changed});self.assertEqual(200,r.status_code,r.text)
        # Fechamento fiscal requer conferência; o fixture de bloqueio isola o teste de consulta.
        with self.core.db.transaction() as c:
            c.execute("INSERT INTO period_locks(company_id,module,period,closed,reason,actor,changed_at,version) VALUES(?,'fiscal','2026-11',1,'teste','teste','2026-11-07',1)",(self.a['id'],))
        before=self.core.documents(self.a['id'])
        r=self.client.get(self.scope('/auditor/sources?start=2026-01-01&end=2026-12-31'));self.assertEqual(200,r.status_code,r.text)
        self.assertTrue(r.json()[0]['closed'])
        job=self.submit(mode='internal',document_ids=[doc['id']])
        self.assertEqual('completed',job['status'],job['error'])
        self.assertEqual(doc['id'],job['result']['documents'][0]['bookkeeping_id'])
        self.assertTrue(any(f['rule_code']=='BOOKED-FIELDS-001' for f in job['findings']))
        self.assertEqual('18.00',job['result']['documents'][0]['items'][0]['details']['tax_path_values']['ICMS/ICMS00/vICMS'])
        self.assertEqual(before,self.core.documents(self.a['id']))
        pdf=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf&purpose=print"))
        self.assertEqual(200,pdf.status_code);self.assertGreater(len(PdfReader(BytesIO(pdf.content)).pages),4)

    def test_manual_internal_documents_remain_consultable_without_fabricated_xml(self):
        doc=self.client.post(self.scope('/documents'),json=self.document()).json()
        job=self.submit(mode='internal',document_ids=[doc['id']])
        d=job['result']['documents'][0]
        self.assertEqual('bookkeeping',d['origin']);self.assertIsNone(d['original_file_id']);self.assertEqual('100',d['total_value'])
        self.assertTrue(any(f['rule_code']=='ORIGINAL-MISSING-001' for f in job['findings']))
        r=self.client.post(self.scope(f"/auditor/jobs/{job['id']}/auxiliary"),json={'document_ref':d['document_ref']});self.assertEqual(422,r.status_code)

    def test_full_reports_open_with_numeric_cells_and_evidence(self):
        raw=(Path(__file__).parent/'fixtures/auditor_demo.xml').read_bytes().replace(b'99999999000191',self.a['tax_id'].encode())
        job=self.submit(raw)
        self.assertEqual('completed',job['status'],job['error'])
        content=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=xlsx")).content
        book=load_workbook(BytesIO(content),data_only=True)
        expected={'Resumo Executivo','Notas - Sintético','Itens - Analítico','Tributos','IBS e CBS','Memória de Cálculo','Entradas x Saídas','Inconsistências','Auditoria NCM-ClassTrib','Qualidade Parametrização','Parametrização Utilizada','Fontes e Método','Duplicidades e Eventos','Arquivos processados'}
        self.assertTrue(expected<=set(book.sheetnames))
        self.assertEqual(65000,book['Notas - Sintético']['I2'].value)
        self.assertEqual('87032100',book['Itens - Analítico']['F2'].value)
        self.assertEqual('n',book['Notas - Sintético']['I2'].data_type)
        self.assertEqual(64.96,book['IBS e CBS']['H2'].value)
        memory=list(book['Memória PIS Cofins'].values)
        self.assertTrue(any('PIS' in row and 6.5 in row for row in memory))
        pdf=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf")).content
        reader=PdfReader(BytesIO(pdf));text=' '.join(p.extract_text() for p in reader.pages)
        for label in ('Resumo executivo','65.000,00','Memória de cálculo','87032100','Conciliação','Fontes'):
            self.assertIn(label,text)
        self.assertGreaterEqual(len(reader.pages),6)

    def test_catalog_discovery_explains_drafts_without_publishing_or_leaking_rules(self):
        payload={'name':'Histórico original','valid_from':'2026-01-01','valid_to':'2026-12-31'}
        catalog=self.client.post(self.scope('/auditor/catalogs/reference'),json=payload).json()
        self.assertEqual([],self.client.get(self.scope('/auditor/available-catalogs')).json())
        response=self.client.get(self.scope('/auditor/available-catalogs?include_drafts=true'))
        self.assertEqual(200,response.status_code,response.text)
        options=response.json();self.assertEqual(1,len(options))
        self.assertEqual(catalog['id'],options[0]['id'])
        self.assertEqual('draft',options[0]['state'])
        self.assertEqual(15638,options[0]['entry_count'])
        self.assertEqual(4,options[0]['error_count'])
        for hidden in ('content_json','reference_json','entries','reference','issues'):
            self.assertNotIn(hidden,options[0])
        for mode in ('internal','standalone'):
            with patch.object(self.app.state.auditor,'submit'):
                r=self.client.post(self.scope('/auditor/jobs'),json={'mode':mode,'start':'2026-01-01','end':'2026-12-31','catalog_id':catalog['id'],'idempotency_key':'draft-'+mode})
            self.assertNotEqual(201,r.status_code)
        self.activate(self.b['id'])
        self.assertEqual([],self.client.get(self.scope('/auditor/available-catalogs?include_drafts=true',self.b['id'])).json())

    def test_verified_reference_revision_preserves_original_and_requires_conditions(self):
        from app.auditor_engine.catalog import CatalogSnapshot
        from datetime import date
        payload={'name':'Original','valid_from':'2026-01-01','valid_to':'2026-12-31'}
        original=self.client.post(self.scope('/auditor/catalogs/reference'),json=payload).json()
        iid=original['id']
        response=self.client.post(self.scope(f'/auditor/catalogs/{iid}/revision'),json=payload|{'name':'Erratas verificadas','apply_verified_errata':True})
        self.assertEqual(201,response.status_code,response.text)
        revision=response.json();rid=revision['id']
        self.assertEqual(0,revision['error_count'])
        self.assertEqual(15638,revision['entry_count'])
        self.assertEqual(3,len(revision['reference']['verified_errata']['changes']))
        self.assertEqual('draft',revision['state'])
        preserved=self.client.get(self.scope(f'/auditor/catalogs/{iid}')).json()
        self.assertEqual(original['sha256'],preserved['sha256'])
        self.assertEqual(4,preserved['error_count'])
        self.assertEqual(3,self.client.get(self.scope(f'/auditor/catalogs/{iid}/compare/{rid}')).json()['total'])
        rows=self.client.get(self.scope(f'/auditor/catalogs/{rid}/entries?search=15132120')).json()['rows']
        self.assertEqual('Redução de 100%',rows[0]['reduction_type'])
        snapshot=CatalogSnapshot({'sha256':revision['sha256'],'valid_from':'2026-01-01','valid_to':'2026-12-31','entries':rows})
        self.assertEqual('CONDITION_REVIEW_REQUIRED',snapshot.match('15132120',None,date(2026,9,1))['status'])
        r=self.client.post(self.scope(f'/auditor/catalogs/{rid}/publish'),json={'version':revision['version'],'reason':'Teste: revisão verificada, condições explícitas'})
        self.assertEqual(200,r.status_code,r.text)
        # Applying the errata again must not duplicate conditions or rewrite customized rows.
        again=self.client.post(self.scope(f'/auditor/catalogs/{rid}/revision'),json=payload|{'apply_verified_errata':True}).json()
        self.assertEqual([],again['reference']['verified_errata']['changes'])

    def test_catalog_original_counts_errors_edit_compare_and_immutable_publication(self):
        payload={'name':'Histórico original','valid_from':'2026-01-01','valid_to':'2026-12-31'}
        r=self.client.post(self.scope('/auditor/catalogs/reference'),json=payload);self.assertEqual(201,r.status_code,r.text)
        catalog=r.json();iid=catalog['id'];self.assertEqual(15638,catalog['entry_count'])
        self.assertEqual(19,len(catalog['reference']['cst']));self.assertEqual(142,len(catalog['reference']['cclass']))
        errors=self.client.get(self.scope(f'/auditor/catalogs/{iid}/entries?status=error')).json();self.assertEqual(3,errors['total'])
        r=self.client.post(self.scope(f'/auditor/catalogs/{iid}/publish'),json={'version':catalog['version'],'reason':'Teste'});self.assertEqual(422,r.status_code)
        revision=self.client.post(self.scope(f'/auditor/catalogs/{iid}/revision'),json=payload|{'name':'Revisão de teste'}).json();rid=revision['id']
        for row in errors['rows']:
            cclass=row.get('cclass_trib') or '000001';cst=cclass[:3]
            entry=row|{'cst':cst,'cclass_trib':cclass,'reduction_type':''}
            r=self.client.put(self.scope(f"/auditor/catalogs/{rid}/entries/{row['_index']}"),json={'version':revision['version'],'entry':entry})
            self.assertEqual(200,r.status_code,r.text);revision=r.json()
        self.assertEqual(0,revision['error_count'])
        comparison=self.client.get(self.scope(f'/auditor/catalogs/{iid}/compare/{rid}')).json();self.assertEqual(3,comparison['total'])
        r=self.client.post(self.scope(f'/auditor/catalogs/{rid}/publish'),json={'version':revision['version'],'reason':'Cenário sintético de teste; não constitui validação normativa'});self.assertEqual(200,r.status_code,r.text)
        options=self.client.get(self.scope('/auditor/available-catalogs?include_drafts=true')).json()
        self.assertEqual('published',next(c for c in options if c['id']==rid)['state'])
        self.assertEqual([rid],[c['id'] for c in self.client.get(self.scope('/auditor/available-catalogs')).json()])
        r=self.client.put(self.scope(f"/auditor/catalogs/{rid}/entries/{errors['rows'][0]['_index']}"),json={'version':revision['version']+1,'entry':entry});self.assertEqual(409,r.status_code)
        self.assertEqual(3,self.client.get(self.scope(f'/auditor/catalogs/{iid}/entries?status=error')).json()['total'])

    def test_prepared_reports_are_reused_on_first_download_and_preview(self):
        job=self.submit()
        self.assertEqual(2,len(job['reports']))
        self.assertIn('Concluído',job['logs'][-1]['message'])
        with patch('app.auditor_reports.export_audit',side_effect=AssertionError('Relatório pronto não deve ser recalculado')):
            for fmt in ('pdf','xlsx'):
                response=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format={fmt}"))
                self.assertEqual(200,response.status_code)
                self.assertTrue(response.content.startswith(b'%PDF' if fmt=='pdf' else b'PK'))
            self.assertEqual(200,self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf&purpose=print")).status_code)
        self.assertEqual(2,len(self.core.auditor_job(self.a['id'],job['id'])['reports']))

    def test_report_revisions_persist_and_treatments_do_not_replace_original_artifact(self):
        job=self.submit();rid=job['reports'][0]['id']
        original=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/reports/{rid}")).content
        f=job['findings'][0]
        r=self.client.put(self.scope(f"/auditor/findings/{f['id']}/treatment"),json={'version':f['version'],'status':'resolved','responsible':'Revisor','treatment':'Conferência registrada'});self.assertEqual(200,r.status_code)
        self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf"))
        self.assertEqual(original,self.client.get(self.scope(f"/auditor/jobs/{job['id']}/reports/{rid}")).content)
        self.assertGreater(len(self.core.auditor_job(self.a['id'],job['id'])['reports']),2)
        from app.db import Database
        from app.business import BusinessCore
        reopened=BusinessCore(Database(self.tmp.name))
        reread=reopened.auditor_job(self.a['id'],job['id']);self.assertEqual('resolved',reread['findings'][0]['status'])
        self.assertEqual(job['result'],reread['result']);self.assertEqual([],reopened.documents(self.a['id']))

    def test_auxiliary_models_pdf_opening_and_preserved_originals(self):
        target=self.create_company('RENDER-TEST','999999990001');self.a=target;self.activate(target['id'])
        for n,filename in enumerate(('auditor_demo.xml','auditor_nfce.xml','auditor_cte.xml','auditor_mdfe.xml')):
            with self.subTest(filename=filename):
                raw=(Path(__file__).parent/'fixtures'/filename).read_bytes();job=self.submit(raw,key='renderer-'+str(n))
                self.assertEqual('completed',job['status'],job['error']);d=job['result']['documents'][0]
                r=self.client.post(self.scope(f"/auditor/jobs/{job['id']}/auxiliary"),json={'document_ref':d['document_ref']});self.assertEqual(200,r.status_code,r.text)
                pdf=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/files?file_id={r.json()['file_id']}&inline=1"))
                self.assertEqual('application/pdf',pdf.headers['content-type']);self.assertGreater(len(PdfReader(BytesIO(pdf.content)).pages),0)
                self.assertEqual(raw,self.client.get(self.scope(f"/auditor/jobs/{job['id']}/files?file_id={d['original_file_id']}")).content)

    def test_report_generation_failure_and_reprocess_keep_evidence(self):
        with patch('app.auditor_reports.export_audit',side_effect=RuntimeError('synthetic renderer failure')):job=self.submit()
        self.assertEqual('failed',job['status']);self.assertTrue(job['snapshot']['files']);self.assertEqual([],job['reports'])
        with patch.object(self.app.state.auditor,'submit'):
            r=self.client.post(self.scope(f"/auditor/jobs/{job['id']}/reprocess"),json={'idempotency_key':'retry'})
        self.assertEqual(201,r.status_code,r.text);self.app.state.auditor.run(self.a['id'],r.json()['id'])
        retry=self.core.auditor_job(self.a['id'],r.json()['id']);self.assertEqual('completed',retry['status']);self.assertEqual(job['id'],retry['parent_id'])
        self.assertEqual('failed',self.core.auditor_job(self.a['id'],job['id'])['status'])

    def test_pdf_manual_association_preserves_snapshot_and_checks_scope(self):
        from reportlab.pdfgen.canvas import Canvas
        out=BytesIO();canvas=Canvas(out);canvas.drawString(30,800,'PDF SINTETICO');canvas.save()
        files=[{'filename':name,'content_base64':base64.b64encode(raw).decode()} for name,raw in [('document.xml',self.xml()),('sem-chave.pdf',out.getvalue())]]
        job=self.submit(files=files);d=job['result']['documents'][0]
        self.assertEqual([],d['auxiliary_file_ids'])
        fid=next(f['id'] for f in job['snapshot']['files'] if f['name']=='sem-chave.pdf')
        path=f"/auditor/jobs/{job['id']}/attachments"
        data={'document_ref':d['document_ref'],'file_id':fid,'reason':'Conteúdo conferido manualmente'}
        r=self.client.post(self.scope(path),json=data);self.assertEqual(201,r.status_code,r.text)
        after=self.core.auditor_job(self.a['id'],job['id'])
        self.assertEqual(job['snapshot'],after['snapshot']);self.assertEqual(job['result'],after['result'])
        self.assertEqual(1,len(after['attachments']))
        self.client.post(self.scope(path),json=data)
        self.assertEqual(1,len(self.core.auditor_job(self.a['id'],job['id'])['attachments']))
        self.assertEqual(404,self.client.post(self.scope(path),json=data|{'document_ref':'fora'}).status_code)
        self.assertEqual(404,self.client.post(self.scope(path),json=data|{'file_id':d['original_file_id']}).status_code)
        self.assertEqual([],self.core.documents(self.a['id']))

    def test_rule_validity_intersects_catalog_validity(self):
        from app.auditor_engine.catalog import CatalogSnapshot
        from datetime import date
        catalog=CatalogSnapshot({'sha256':'test','valid_from':'2026-01-01','valid_to':'2026-12-31','entries':[{'ncm':'87032100','cst':'000','cclass_trib':'000001','valid_from':'2025-01-01','valid_to':'2027-12-31'}]})
        self.assertEqual('PARAMETER_OUT_OF_VALIDITY',catalog.match('87032100',None,date(2025,12,31))['status'])
        self.assertEqual('MATCH',catalog.match('87032100',None,date(2026,1,1))['status'])

    def test_new_routes_enforce_company_and_permissions(self):
        job=self.submit();cid=self.a['id']
        self.client.post('/api/users',json={'username':'auditor-leitura','password':'SenhaAuditor12345','role':'custom','company_ids':[cid],'permissions':[{'company_id':cid,'routine':'auditor.analyses','action':'read','effect':'allow'}]})
        client=TestClient(self.app);login=client.post('/api/login',json={'username':'auditor-leitura','password':'SenhaAuditor12345'}).json();client.headers['X-CSRF-Token']=login['csrf_token'];client.post('/api/context',json={'company_id':cid,'module':'auditor','period':'2026-01'})
        self.assertEqual(200,client.get(self.scope(f"/auditor/jobs/{job['id']}/progress")).status_code)
        self.assertEqual(403,client.get(self.scope(f"/auditor/jobs/{job['id']}/reports/{job['reports'][0]['id']}")).status_code)
        self.assertEqual(403,client.get(self.scope(f"/auditor/jobs/{job['id']}/logs/export")).status_code)
        self.assertEqual(403,client.get(self.scope('/auditor/sources?start=2026-01-01&end=2026-12-31',self.b['id'])).status_code)
        self.assertEqual(200,client.get(self.scope('/auditor/available-catalogs')).status_code)
        client.close()
