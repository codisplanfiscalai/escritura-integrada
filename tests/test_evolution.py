"""Fluxos 0.7: exercício, importação independente, auditor isolado e originais."""
import base64
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from fastapi.testclient import TestClient
import test_core as base
from app.core import DomainError
from app.module_imports import LAYOUTS
from app.auditor import members


class EvolutionTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    scope=base.CoreApiTests.scope
    activate=base.CoreApiTests.activate
    create_company=base.CoreApiTests.create_company
    journal=base.CoreApiTests.journal
    document=base.CoreApiTests.document
    title=base.CoreApiTests.title

    def tearDown(self):
        self.app.state.auditor.close();base.CoreApiTests.tearDown(self)

    def csv_preview(self,layout,lines,client=None):
        c=client or self.client;module=LAYOUTS[layout]['module']
        raw=(';'.join(LAYOUTS[layout]['fields'])+'\n'+lines).encode()
        r=c.post(self.scope('/module-imports/preview'),json={'module':module,'layout':layout,'year':2026,'filename':'lote.csv','content_base64':base64.b64encode(raw).decode()})
        self.assertEqual(200,r.status_code,r.text);return r.json()

    def confirm(self,p,client=None,selected=None):
        return (client or self.client).post(self.scope(f"/module-imports/{p['id']}/confirm"),json={'module':p['module'],'fingerprint':p['fingerprint'],'selected':selected if selected is not None else [r['_selection'] for r in p['records'] if r['_eligibility']['status']=='eligible']})

    def xml(self):
        raw=(Path(__file__).parent/'fixtures/nfe_ficticia.xml').read_bytes()
        # Fixture utiliza CNPJ numérico; empresa do teste é alfanumérica.
        return raw.replace(b'12345678000195',self.a['tax_id'].encode())

    def job(self,mode='standalone',**extra):
        payload={'mode':mode,'start':'2026-01-01','end':'2026-12-31','idempotency_key':'audit-'+str(extra.pop('key',1)),**extra}
        if mode=='standalone' and 'files' not in payload:payload['files']=[{'filename':'documento.xml','content_base64':base64.b64encode(self.xml()).decode()}]
        with patch.object(self.app.state.auditor,'submit'):
            r=self.client.post(self.scope('/auditor/jobs'),json=payload)
        self.assertEqual(201,r.status_code,r.text);jid=r.json()['id'];self.app.state.auditor.run(self.a['id'],jid)
        result=self.client.get(self.scope(f'/auditor/jobs/{jid}')).json()
        self.assertEqual('completed',result['status'],result.get('error'));return result

    def test_months_are_flexible_but_year_and_month_closure_are_not(self):
        self.assertEqual(201,self.client.post(self.scope('/journals'),json=self.journal(day='2026-02-03')).status_code)
        self.core.set_period(self.a['id'],{'period':'2026-03','module':'accounting','reason':'Conferido','version':0},True,'teste')
        r=self.client.post(self.scope('/journals'),json=self.journal(key='closed',day='2026-03-03'));self.assertEqual(409,r.status_code);self.assertEqual('period_closed',r.json()['code'])
        self.assertEqual(409,self.client.post(self.scope('/journals'),json=self.journal(key='wrong-year',day='2027-01-01')).status_code)
        doc=self.document();doc.update(issue_date='2025-12-31',posting_date='2026-04-01')
        self.assertEqual(201,self.client.post(self.scope('/documents'),json=doc).status_code)
        self.assertEqual('2026-11',self.client.get('/api/session').json()['period'])
        self.assertEqual(409,self.client.post(self.scope('/journals'),headers={'X-Year':'2025'},json=self.journal(key='stale')).status_code)

    def test_catalog_xlsx_preview_preserves_exclusions_and_original(self):
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active;ws.title='Tabela Completa'
        ws.append(['NCM','EX','DESCRIÇÃO','CST IBS/CBS','cClassTrib','Tipo_Redução'])
        ws.append(['87','','Hierarquia','','',''])
        ws.append(['8703.21.00','','Produto',0,1,''])
        ws.append(['','01','Exceção',0,1,''])
        ws.append(['12345678','','Erro','999','000001',''])
        buf=io.BytesIO();wb.save(buf);raw=buf.getvalue()
        r=self.client.post(self.scope('/auditor/catalogs/import-preview'),json={'filename':'tabela.xlsx','content_base64':base64.b64encode(raw).decode()})
        self.assertEqual(200,r.status_code,r.text);preview=r.json()
        self.assertEqual((4,2,2),(preview['rows'],preview['eligible'],preview['excluded']))
        self.assertTrue(preview['entries'][1]['inherited_ncm']);self.assertEqual(4,preview['entries'][1]['source_row'])
        payload={'name':'Versão revisada','source':'Tabela sintética de teste','valid_from':'2026-01-01','valid_to':'2026-12-31','entries':preview['entries'],'source_id':preview['source_id']}
        for field,value in [('ncm',87032100),('cst',0),('cclass_trib',1),('ex_code',1)]:
            invalid=payload|{'entries':[preview['entries'][0]|{field:value}],'acknowledge_issues':True}
            self.assertEqual(400,self.client.post(self.scope('/auditor/catalogs'),json=invalid).status_code)
        self.assertEqual(400,self.client.post(self.scope('/auditor/catalogs'),json=payload).status_code)
        r=self.client.post(self.scope('/auditor/catalogs'),json=payload|{'acknowledge_issues':True});self.assertEqual(201,r.status_code,r.text)
        self.assertEqual(raw,self.client.get(self.scope(f"/auditor/catalogs/{r.json()['id']}/original")).content)
        self.activate(self.b['id'])
        self.assertEqual(404,self.client.post(self.scope('/auditor/catalogs',self.b['id']),json=payload|{'acknowledge_issues':True}).status_code)

    def test_accounting_only_user_imports_without_fiscal_and_denied_company(self):
        cid=self.a['id'];perms=[{'company_id':cid,'routine':r,'action':'*','effect':'allow'} for r in ['accounting.imports','accounting.journals','accounting.accounts']]
        u=self.client.post('/api/users',json={'username':'contador','password':'Senha-do-contador-123','role':'custom','company_ids':[cid],'permissions':perms});self.assertEqual(201,u.status_code,u.text)
        c=TestClient(self.app);r=c.post('/api/login',json={'username':'contador','password':'Senha-do-contador-123'});c.headers['X-CSRF-Token']=r.json()['csrf_token']
        self.assertEqual(200,c.post('/api/context',json={'company_id':cid,'module':'accounting','period':'2026-11'}).status_code)
        self.assertEqual(403,c.get(self.scope('/documents')).status_code)
        p=self.csv_preview('journals-v1','EXT-1;2026-02-03;D-1;Importação contábil;3;10.00;0;\nEXT-1;2026-02-03;D-1;Importação contábil;5;0;10.00;\n',c)
        r=self.confirm(p,c);self.assertEqual(200,r.status_code,r.text);self.assertEqual(1,len(r.json()['written']))
        self.assertEqual(403,c.get(self.scope('/module-imports?module=accounting',self.b['id'])).status_code)
        r=self.confirm(p,c);self.assertTrue(r.json()['duplicate']);self.assertEqual(1,len(self.core.journals(cid)))
        c.close()

    def test_accounting_batch_mixed_months_requires_explicit_selection(self):
        self.core.set_period(self.a['id'],{'period':'2026-03','module':'accounting','reason':'Fechado','version':0},True,'teste')
        lines=''
        for key,day in [('A','2026-02-01'),('B','2026-03-01'),('C','2025-11-01')]:
            for account,debit,credit in [('3','1.00','0'),('5','0','1.00')]:lines+=f'{key};{day};DOC;Histórico;{account};{debit};{credit};\n'
        p=self.csv_preview('journals-v1',lines);self.assertEqual(['eligible','blocked','outside_year'],[r['_eligibility']['status'] for r in p['records']])
        r=self.confirm(p,selected=['0','1']);self.assertEqual(409,r.status_code);self.assertEqual([],self.core.journals(self.a['id']))
        r=self.confirm(p,selected=['0']);self.assertEqual(200,r.status_code,r.text);self.assertEqual(2,len(r.json()['refused']))

    def test_audit_avulsa_does_not_create_bookkeeping_and_exports(self):
        job=self.job();self.assertEqual([],self.core.documents(self.a['id']));self.assertEqual([],self.core.titles(self.a['id']));self.assertEqual([],self.core.journals(self.a['id']))
        self.assertEqual(1,len(job['result']['documents']),job['findings'])
        for fmt in ['pdf','xlsx']:
            r=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format={fmt}"));self.assertEqual(200,r.status_code,r.text[:200] if fmt!='pdf' else r.content[:40]);self.assertGreater(len(r.content),1000)
        self.assertEqual(404,self.client.get(self.scope(f"/auditor/jobs/{job['id']}/files?file_id=99999")).status_code)
        self.assertEqual(404,self.client.get(self.scope(f"/auditor/jobs/{job['id']}",self.b['id'])).status_code)
        r=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=pdf&purpose=print"));self.assertTrue(r.headers['content-disposition'].startswith('inline'))

    def test_cross_year_settlement_and_journal_links_survive_restore(self):
        cid=self.a['id'];title=self.title();self.core.create_journal(cid,self.journal(key='prior-balance'),'teste')
        for module in ('financial','accounting'):
            self.core.create_exercise(cid,{'module':module,'year':2027},'teste')
        self.client.post('/api/context',json={'company_id':cid,'module':'financial','period':'2027-01'})
        r=self.client.post(self.scope(f"/titles/{title['id']}/settle"),json={'date':'2027-02-01','amount':'100.00','reason':'Liquidação no exercício seguinte','idempotency_key':'cross-year','lines':[{'account_id':self.aid['3'],'debit':'100.00','credit':'0'},{'account_id':self.aid['5'],'debit':'0','credit':'100.00'}]})
        self.assertEqual(200,r.status_code,r.text);result=r.json();self.assertEqual(title['id'],result['settlement']['title_id']);self.assertEqual(0,result['title']['balance_cents'])
        report=self.core.business_report(cid,'ledger','2027-01-01','2027-12-31',account_id=self.aid['3'])
        self.assertEqual(12345,report['ledger_groups'][0]['opening_cents']);self.assertEqual(22345,report['rows'][-1]['balance_cents'])
        from app.snapshots import create_snapshot,restore_snapshot
        from app.db import Database
        from app.business import BusinessCore
        archive=Path(self.tmp.name)/'years.zip';target=Path(self.tmp.name)/'years-restored'
        create_snapshot(self.core.db.path,archive);restore_snapshot(archive,target)
        restored=BusinessCore(Database(target));saved=restored.titles(cid)[0]
        self.assertEqual(0,saved['balance_cents']);self.assertEqual(result['journal']['id'],saved['settlements'][0]['journal_id'])
        self.assertEqual(report,restored.business_report(cid,'ledger','2027-01-01','2027-12-31',account_id=self.aid['3']))

    def test_special_tax_scope_is_not_presented_as_recalculated_in_reports(self):
        from openpyxl import load_workbook
        raw=(Path(__file__).parent/'fixtures/auditor_demo.xml').read_bytes().replace(b'99999999000191',self.a['tax_id'].encode())
        raw=raw.replace(b'</gCBS>',b'<gRed><pRedAliq>60.00</pRedAliq><pAliqEfet>0.36</pAliqEfet></gRed></gCBS>')
        job=self.job(files=[{'filename':'especial.xml','content_base64':base64.b64encode(raw).decode()}])
        self.assertEqual('unsupported_special',job['result']['documents'][0]['items'][0]['calculation_scope'])
        data=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/report?format=xlsx")).content
        sheet=load_workbook(io.BytesIO(data))['Comparativo tributos']
        row=dict(zip([c.value for c in sheet[1]],[c.value for c in sheet[2]]))
        self.assertEqual('Não recalculado: cenário especial',row['Cobertura'])
        self.assertIsNone(row['IBS recalculado']);self.assertIsNone(row['CBS recalculada']);self.assertIsNotNone(row['CBS XML'])

    def test_internal_closed_audit_snapshot_stale_and_treatment_has_no_side_effect(self):
        d=self.client.post(self.scope('/documents'),json=self.document()).json()
        # Documento pendente impede fechamento fiscal; contábil pode ser fechado separadamente.
        self.core.set_period(self.a['id'],{'period':'2026-11','module':'accounting','reason':'Fechado','version':0},True,'teste')
        job=self.job('internal');self.assertEqual(1,len(job['snapshot']['bookkeeping']))
        f=job['findings'][0];r=self.client.put(self.scope(f"/auditor/findings/{f['id']}/treatment"),json={'version':f['version'],'status':'resolved','responsible':'Teste','treatment':'Original solicitado'})
        self.assertEqual(200,r.status_code,r.text);self.assertFalse(r.json()['source_corrected'])
        self.assertEqual(d['version'],self.core.documents(self.a['id'])[0]['version'])
        self.core.update_document(self.a['id'],d['id'],{**self.document(),'version':d['version'],'reason':'Correção autorizada','total':'101.00'},'teste')
        self.assertEqual([d['id']],self.core.auditor_job(self.a['id'],job['id'])['stale_document_ids'])
        self.assertEqual(10000,self.core.auditor_job(self.a['id'],job['id'])['snapshot']['bookkeeping'][0]['total_cents'])

    def test_catalog_publication_is_immutable_and_snapshot_independent(self):
        payload={'name':'Sintético 1','source':'Fixture sintética, não normativa','valid_from':'2026-01-01','valid_to':'2026-12-31','entries':[{'ncm':'12345678','cst':'000','cclass_trib':'000001'}]}
        c=self.client.post(self.scope('/auditor/catalogs'),json=payload).json()
        r=self.client.post(self.scope(f"/auditor/catalogs/{c['id']}/publish"),json={'version':c['version'],'reason':'Revisão sintética de teste'});self.assertEqual(200,r.status_code,r.text)
        r=self.client.put(self.scope(f"/auditor/catalogs/{c['id']}"),json={**payload,'version':2});self.assertEqual(409,r.status_code)
        job=self.job(catalog_id=c['id']);self.assertEqual(c['sha256'],job['result']['catalog_sha256'])
        self.assertEqual(201,self.client.post(self.scope('/auditor/catalogs'),json={**payload,'name':'Versão 2'}).status_code)
        self.assertEqual(c['sha256'],self.core.auditor_job(self.a['id'],job['id'])['result']['catalog_sha256'])

    def test_cancel_delete_restore_and_restart(self):
        p={'mode':'standalone','start':'2026-01-01','end':'2026-12-31','idempotency_key':'cancel','files':[{'filename':'x.xml','content_base64':base64.b64encode(self.xml()).decode()}]}
        with patch.object(self.app.state.auditor,'submit'):r=self.client.post(self.scope('/auditor/jobs'),json=p)
        jid=r.json()['id'];r=self.client.post(self.scope(f'/auditor/jobs/{jid}/cancel'),json={'version':1,'reason':'Teste cancelamento'});self.assertEqual(200,r.status_code,r.text)
        self.app.state.auditor.run(self.a['id'],jid);j=self.core.auditor_job(self.a['id'],jid);self.assertEqual('cancelled',j['status']);self.assertIsNone(j['result'])
        j=self.core.auditor_action(self.a['id'],jid,'delete',{'version':j['version'],'reason':'Teste'},'teste');self.assertTrue(j['deleted_at'])
        j=self.core.auditor_action(self.a['id'],jid,'restore',{'version':j['version'],'reason':'Teste'},'teste');self.assertIsNone(j['deleted_at'])
        with self.core.db.transaction() as conn:conn.execute("UPDATE auditor_jobs SET status='running',cancelled=0 WHERE id=?",(jid,))
        with patch.object(self.app.state.auditor,'submit') as submit:self.app.state.auditor.recover();submit.assert_called_once_with(self.a['id'],jid)
        self.assertEqual('queued',self.core.auditor_job(self.a['id'],jid)['status'])

    def test_archive_traversal_and_invalid_decimal_are_not_silent(self):
        buf=io.BytesIO()
        with ZipFile(buf,'w') as z:z.writestr('../escape.xml',b'x')
        with self.assertRaises(DomainError):members('a.zip',buf.getvalue())
        from app.auditor_engine.xml_parser import _dec
        from lxml import etree
        with self.assertRaises(ValueError):_dec(etree.fromstring(b'<x>NaN</x>'),'.')

    def test_manual_document_idempotency_survives_changed_identity(self):
        p=self.document();p['idempotency_key']='manual-sequence'
        first=self.client.post(self.scope('/documents'),json=p);self.assertEqual(201,first.status_code,first.text)
        self.assertEqual(first.json()['id'],self.client.post(self.scope('/documents'),json=p).json()['id'])
        p['number']='ALTERADO';self.assertEqual(409,self.client.post(self.scope('/documents'),json=p).status_code);self.assertEqual(1,len(self.core.documents(self.a['id'])))

    def test_files_rebuild_from_database_and_ledger_reads_closed_year_carry(self):
        job=self.job();fid=job['snapshot']['files'][0]['id']
        from app.file_store import read_file,file_path,inventory
        with self.core.db.read() as conn:r=read_file(conn,self.a['id'],fid)
        path=file_path(self.core.db,r);self.assertTrue(path.is_file());path.unlink();self.assertTrue(inventory(self.core.db,self.a['id'],2026)['files'][0]['verified'])
        self.core.create_exercise(self.a['id'],{'module':'accounting','year':2025},'teste')
        self.core.create_journal(self.a['id'],self.journal(key='prior',day='2025-12-31'), 'teste')
        result=self.core.business_report(self.a['id'],'ledger','2026-01-01','2026-12-31',account_id=self.aid['3'])
        self.assertEqual(12345,result['ledger_groups'][0]['opening_cents'])
        from app.report_models import ledger_pdf
        data,mime=ledger_pdf(result);self.assertTrue(data.startswith(b'%PDF'));self.assertEqual('application/pdf',mime)

    def test_backup_restore_preserves_originals_totals_and_permissions(self):
        self.job()
        self.core.create_journal(self.a['id'],self.journal(),'teste')
        from app.snapshots import create_snapshot,restore_snapshot,manifest
        archive=Path(self.tmp.name)/'backup.zip';restored=Path(self.tmp.name)/'restored'
        before=create_snapshot(self.core.db.path,archive);after=restore_snapshot(archive,restored)
        self.assertEqual(before['records'],after['records']);self.assertEqual(before['money'],after['money']);self.assertEqual(before['originals'],after['originals'])
        self.assertTrue(list((restored/'companies'/str(self.a['id'])/'2026'/'audit').glob('*')))
        with self.assertRaises(RuntimeError):restore_snapshot(archive,restored)
        self.assertEqual(before['records'],manifest(self.core.db.path)['records'])

    def test_danfe_python_renderer_is_distinct_from_audit_and_keeps_original(self):
        from app.auxiliary import render_danfe
        from lxml import etree
        raw=(Path(__file__).parent/'fixtures/auditor_demo.xml').read_bytes()
        root=etree.fromstring(raw);ns={'n':'http://www.portalfiscal.inf.br/nfe'}
        root.find('.//n:emit/n:CNPJ',ns).text=self.a['tax_id'];raw=etree.tostring(root)
        pdf,renderer=render_danfe(raw);self.assertTrue(pdf.startswith(b'%PDF'));self.assertIn('1.3.1',renderer)
        job=self.job(files=[{'filename':'demo.xml','content_base64':base64.b64encode(raw).decode()}])
        self.assertEqual([],job['auxiliary'])
        ref=job['result']['documents'][0]['document_ref']
        r=self.client.post(self.scope(f"/auditor/jobs/{job['id']}/auxiliary"),json={'document_ref':ref});self.assertEqual(200,r.status_code,r.text)
        self.assertEqual([],self.core.documents(self.a['id']))
        current=self.core.auditor_job(self.a['id'],job['id']);self.assertEqual(job['result']['snapshot_sha256'],current['result']['snapshot_sha256'])
        self.assertEqual(1,len(current['auxiliary']))
        fid=r.json()['file_id'];download=self.client.get(self.scope(f"/auditor/jobs/{job['id']}/files?file_id={fid}"));self.assertTrue(download.content.startswith(b'%PDF'))
        with self.assertRaises(DomainError):render_danfe(self.xml())  # modelo incompleto para impressão

    def test_new_auditor_module_session_and_company_year_context(self):
        r=self.client.post('/api/context',json={'company_id':self.a['id'],'module':'auditor','period':'2024-01'});self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(2024,r.json()['year']);self.assertIn('auditor',r.json()['available_modules'])
        r=self.client.post('/api/context',json={'company_id':self.a['id'],'module':'accounting'});self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(2026,r.json()['year'])
        r=self.client.post('/api/context',json={'company_id':self.a['id'],'module':'auditor'});self.assertEqual(2024,r.json()['year'])

    def test_account_and_title_csv_preview_and_idempotency(self):
        p=self.csv_preview('accounts-v1','900;9.0.001;Conta sintética;debit;1;0;asset;900\n')
        self.assertEqual('eligible',p['records'][0]['_eligibility']['status'],p)
        r=self.confirm(p);self.assertEqual(200,r.status_code,r.text)
        p=self.csv_preview('titles-v1','T1;payable;Parcela teste;Fornecedor;D1;2026-02-01;2027-03-01;125.60;1\n')
        self.assertEqual('eligible',p['records'][0]['_eligibility']['status'],p)
        r=self.confirm(p);self.assertEqual(200,r.status_code,r.text);self.assertEqual(12560,self.core.titles(self.a['id'])[0]['amount_cents'])
        self.assertTrue(self.confirm(p).json()['duplicate'])

    def test_fiscal_month_batch_keeps_blocked_and_previous_issue_date(self):
        from unittest.mock import patch
        self.core.set_period(self.a['id'],{'period':'2026-03','module':'fiscal','reason':'Fechado','version':0},True,'teste')
        docs=[]
        for index,day in enumerate(['2026-02-01','2026-03-01','2025-12-31']):
            doc=self.document(str(index));doc.update(posting_date=day,issue_date='2025-11-01');docs.append(doc)
        payload={'filename':'mixed.xml','period':'2026-11','content_base64':base64.b64encode(b'<synthetic/>').decode()}
        with patch('app.importers.parse_file',return_value={'documents':docs,'transactions':[],'issues':[],'sources':[]}):
            r=self.client.post(self.scope('/imports/preview'),json=payload)
        self.assertEqual(200,r.status_code,r.text);p=r.json()
        self.assertEqual(['eligible','blocked','outside_year'],[d['_eligibility']['status'] for d in p['documents']])
        r=self.client.post(self.scope(f"/imports/{p['id']}/confirm"),json={'preview_hash':p['preview_hash']});self.assertEqual(409,r.status_code)
        r=self.client.post(self.scope(f"/imports/{p['id']}/confirm"),json={'preview_hash':p['preview_hash'],'selected':['documents:0']});self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(2,len(r.json()['refused']));self.assertEqual('2025-11-01',self.core.documents(self.a['id'])[0]['issue_date'])
