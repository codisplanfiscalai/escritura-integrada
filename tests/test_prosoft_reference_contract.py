"""Independent PDF reader versus API preview, persisted manifest and actual download.

Only synthetic values. Vendor documents are not runtime dependencies or fixtures.
"""
from hashlib import sha256
from io import BytesIO
import json
import unittest
from zipfile import ZipFile

from app.prosoft import encode_journals
from app.prosoft_fiscal import encode_fiscal
import prosoft_reference_reader as reader
import test_core as base
import test_prosoft_increment as prior
import test_prosoft_cancel_references as approved
import test_fiscal_sales_accounting as daily


class ReferenceReaderControls(unittest.TestCase):
    def test_decimal_vectors_are_decoded_without_exporter_format_helpers(self):
        for cents in (0,1,9,10,99,100,10001,9999999999999):
            with self.subTest(cents=cents):
                files,manifest=encode_fiscal([prior.document(total_cents=cents)],prior.configuration())
                row=reader.fiscal(files['ENTRADAS.TXT'],'incoming')[0]
                self.assertEqual(cents,row['total_cents'])
                self.assertEqual(cents,manifest['trace'][0]['total_cents'])
                self.assertEqual(cents,row['book_other_cents'])
                self.assertEqual(0,row['book_base_cents'])

    def test_unknown_tax_fields_remain_unknown_in_readback(self):
        files,manifest=encode_fiscal([prior.document(fiscal_treatment={})],prior.configuration())
        row=reader.fiscal(files['ENTRADAS.TXT'],'incoming')[0]
        for field in ('book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents'):
            self.assertIsNone(row[field])
            self.assertIsNone(manifest['totals']['incoming'][field])
        self.assertEqual(10001,row['total_cents'])

    def test_reader_rejects_corrupt_downloads_instead_of_normalizing_them(self):
        j={'id':1,'number':1,'date':'2026-11-06','document':'SYN1','history':'Synthetic',
           'total_cents':10001,'lines':[
               {'account_id':1,'access_code':'1','debit_cents':3333,'credit_cents':0},
               {'account_id':2,'access_code':'2','debit_cents':6668,'credit_cents':0},
               {'account_id':3,'access_code':'3','debit_cents':0,'credit_cents':10001}]}
        raw,_=encode_journals([j],{str(i):{'code':str(i),'confirmed':True} for i in (1,2,3)},{},'1')
        rows=raw[:-2].split(b'\r\n')
        _,read=reader.accounting(raw)
        self.assertEqual(10001,read[0]['total_cents'])
        def changed(index,start,value):
            damaged=list(rows);r=damaged[index];damaged[index]=r[:start-1]+value+r[start-1+len(value):]
            return b'\r\n'.join(damaged)+b'\r\n'
        bad=[raw[:-1],raw.replace(b'\r\n',b'\n'),raw+b'\r\n',
             b'\r\n'.join(rows[:-1])+b'\r\n',changed(1,4,b'00002'),changed(2,9,b'001'),
             changed(0,69,b'0'),changed(1,50,b','),changed(1,37,b'1'),changed(1,294,b'X'),
             changed(0,21,b'\x80'),b'\r\n'.join([rows[1],*rows])+b'\r\n']
        for index,damaged in enumerate(bad):
            with self.subTest(index=index),self.assertRaises(ValueError):reader.accounting(damaged)
        files,_=encode_fiscal([prior.document()],prior.configuration())
        fiscal=files['ENTRADAS.TXT']
        for damaged in (fiscal[1:],fiscal[:808]+b'9'+fiscal[809:],fiscal[:221]+b','+fiscal[222:]):
            with self.assertRaises(ValueError):reader.fiscal(damaged,'incoming')


class SpeciesReferenceTests(unittest.TestCase):
    def test_exact_hyphenated_species_roundtrip_in_five_position_windows_fields(self):
        for model,code in [('55','NF-E'),('65','NFC-E')]:
            for direction,filename in [('incoming','ENTRADAS.TXT'),('outgoing','SAIDAS.TXT')]:
                with self.subTest(model=model,direction=direction):
                    cfg=prior.configuration();cfg['species'][model]={'code':code,'confirmed':True}
                    files,manifest=encode_fiscal([prior.document(direction,model=model)],cfg)
                    self.assertEqual([],manifest['skipped'])
                    self.assertEqual(code,reader.fiscal(files[filename],direction)[0]['species'])
                    start=858 if direction=='incoming' else 978
                    self.assertEqual(code.ljust(5),reader.field(files[filename],start,5))

    def test_species_rejects_spaces_overflow_and_unapproved_punctuation(self):
        for code in [' NF-E','NF-E ','NF E','NFC E','NFC-E ','NFC-EE','NF--E','N-FE','-NFE',
                     'NFE-','NF/E','NF.E','NF_E','NF*E','NF–E','NF-E\n','NF-E\r','nf-e',None,1]:
            with self.subTest(code=code):
                cfg=prior.configuration();cfg['species']['55']={'code':code,'confirmed':True}
                files,manifest=encode_fiscal([prior.document()],cfg)
                self.assertFalse(files)
                self.assertEqual('species_mapping_required',manifest['skipped'][0]['reason'])


class DownloadReferenceContractTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    document=base.CoreApiTests.document
    journal=base.CoreApiTests.journal
    post=daily.FiscalSalesAccountingTests.post
    booked=prior.ProsoftApiTests.booked
    economic_snapshot=prior.ProsoftApiTests.economic_snapshot
    cancellation=approved.ProsoftCancellationReferenceApiTests.cancellation
    mode=daily.FiscalSalesAccountingTests.mode
    model=daily.FiscalSalesAccountingTests.model
    sale=daily.FiscalSalesAccountingTests.sale

    def download(self,path):
        response=self.client.get(self.scope(path))
        self.assertEqual(200,response.status_code,response.text[:200] if response.status_code!=200 else '')
        return response.content

    def accounting_payload(self,**extra):
        return {'period':'2026-11','company_code':'91','plan_code':'52','batch':'27','allow_ascii':True,
                'accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts},**extra}

    def accounting_batch(self,payload):
        preview=self.post('/prosoft/preview',payload)
        saved=self.post('/prosoft/confirm',payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True})
        raw=self.download(f"/exports/{saved['id']}/download")
        manifest=json.loads(self.download(f"/prosoft/exports/{saved['id']}/manifest?download=1"))
        self.assertEqual(preview['manifest'],manifest)
        self.assertEqual(saved['manifest'],manifest)
        self.assertEqual(preview['sha256'],sha256(raw).hexdigest())
        self.assertEqual(preview['sample'],raw.decode('ascii').splitlines()[:5])
        cta,journals=reader.accounting(raw)
        self.assertEqual(manifest['journals'],len(journals))
        self.assertEqual(manifest['record_counts'],{'CTA':len(cta),'LC1':len(journals),
            'LC2':sum(j['count'] for j in journals if j['mode']=='2')})
        for trace,journal in zip(manifest['trace'],journals):
            self.assertEqual(trace['order'],journal['order'])
            self.assertEqual(trace['line_count'],len(journal['lines']))
            self.assertEqual(trace['total_cents'],journal['total_cents'])
        total=sum(j['total_cents'] for j in journals)
        self.assertEqual(total,manifest['debit_cents']);self.assertEqual(total,manifest['credit_cents'])
        return saved,cta,journals

    def test_saved_species_configuration_exports_exact_codes_without_claiming_remote_registration(self):
        self.booked('8001',model='55');self.booked('8002',model='65',direction='outgoing',cfop='5102')
        initial=self.client.get(self.scope('/prosoft-fiscal/settings')).json()
        cfg=initial['settings']|{'company_code':'91','species':{
            '55':{'code':'NF-E','confirmed':True},'65':{'code':'NFC-E','confirmed':True}}}
        response=self.client.put(self.scope('/prosoft-fiscal/settings'),json={'version':initial['version'],'settings':cfg})
        self.assertEqual(200,response.status_code,response.text)
        settings=response.json();before=self.economic_snapshot()
        payload=settings['settings']|{'period':'2026-11','settings_version':settings['version']}
        preview=self.post('/prosoft-fiscal/preview',payload)
        self.assertFalse(preview['manifest']['skipped'])
        self.assertFalse(preview['manifest']['homologated_in_destination'])
        saved=self.post('/prosoft-fiscal/confirm',payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True})
        with ZipFile(BytesIO(self.download(f"/prosoft-fiscal/exports/{saved['id']}/download"))) as archive:
            self.assertEqual('NF-E',reader.fiscal(archive.read('ENTRADAS.TXT'),'incoming')[0]['species'])
            self.assertEqual('NFC-E',reader.fiscal(archive.read('SAIDAS.TXT'),'outgoing')[0]['species'])
        stored=self.client.get(self.scope('/prosoft-fiscal/settings')).json()
        self.assertEqual(settings,stored)
        self.assertEqual(before,self.economic_snapshot())
        for bad in [' NF-E','NF-E ','NFC E','NFC-E ','NFC-EE','NF--E','N-FE','NF/E','NF.E','NF–E','NF-E\n']:
            with self.subTest(code=bad):
                changed=cfg|{'species':{'55':{'code':bad,'confirmed':True}}}
                response=self.client.put(self.scope('/prosoft-fiscal/settings'),json={'version':settings['version'],'settings':changed})
                self.assertEqual(400,response.status_code,response.text)
                self.assertEqual(stored,self.client.get(self.scope('/prosoft-fiscal/settings')).json())
        self.assertEqual(before,self.economic_snapshot())

    def test_fiscal_download_reconciles_split_origin_cancelled_selection_and_competence(self):
        incoming=self.booked('1234567890',total='100.01',key='1'*44,analytics=[
            {'cfop':'1102','operation_total':'33.33','rate':'18.00','cst_icms':'000','taxes':{}},
            {'cfop':'1101','operation_total':'66.68','rate':'18.00','cst_icms':'000','taxes':{}}])
        outgoing=self.booked('2345678901',direction='outgoing',model='65',cfop='5102',total='0.01',key='2'*44)
        cancelled=self.cancellation('outgoing','3456789012')
        self.activate(self.a['id'],'2026-12')
        excluded=self.booked('4567890123',posting_date='2026-12-01',total='999.99')
        self.activate(self.b['id']);foreign=self.sale('5678901234','888.88',cid=self.b['id'])
        self.activate(self.a['id']);before=self.economic_snapshot()
        payload=prior.configuration()|{'period':'2026-11','company_code':'91','plan_code':'52',
            'record_types':['incoming_notes','outgoing_notes']}
        preview=self.post('/prosoft-fiscal/preview',payload)
        saved=self.post('/prosoft-fiscal/confirm',payload|{'preview_hash':preview['preview_hash'],'destination_reviewed':True})
        raw=self.download(f"/prosoft-fiscal/exports/{saved['id']}/download")
        self.assertEqual(preview['sha256'],sha256(raw).hexdigest())
        with ZipFile(BytesIO(raw)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(preview['manifest'],manifest);self.assertEqual(saved['manifest'],manifest)
            self.assertEqual((self.a['id'],'2026-11','0091','0052'),tuple(manifest[k] for k in ('company_id','period','company_code','plan_code')))
            self.assertEqual({incoming['id'],outgoing['id'],cancelled['id']},{t['document_id'] for t in manifest['trace']})
            originals={d['id']:d for d in (incoming,outgoing,cancelled)}
            for direction,filename in [('incoming','ENTRADAS.TXT'),('outgoing','SAIDAS.TXT')]:
                data=archive.read(filename);decoded=reader.fiscal(data,direction)
                self.assertEqual(manifest['files'][filename],{'sha256':sha256(data).hexdigest(),'size_bytes':len(data)})
                self.assertEqual(preview['sample'][filename],data.decode('ascii').splitlines()[:2])
                traces=[t for t in manifest['trace'] if t['file']==filename]
                self.assertEqual(len(decoded),manifest['totals'][direction]['records'])
                self.assertEqual(sum(x['total_cents'] for x in decoded),manifest['totals'][direction]['total_cents'])
                for trace in traces:
                    row=decoded[trace['record']-1];source=originals[trace['document_id']]
                    for name in ('posting_date','issue_date','total_cents','key','cancelled'):
                        self.assertEqual(trace[name],row[name])
                    self.assertEqual(str(int(row['number'])),source['number'])
                    self.assertEqual(trace['source_hash'],source['source_hash'])
                    self.assertEqual(trace['source'],source['source'])
                    self.assertEqual(trace['classification']['cfop'],row['cfop'])
                    self.assertEqual('2026-10-30',row['issue_date'])
                for tax in ('book_base','book_icms','book_other','book_ipi'):
                    values=[r[tax+'_cents'] for r in decoded if r[tax+'_cents'] is not None]
                    self.assertEqual(sum(values) if values else None,manifest['totals'][direction][tax+'_cents'])
                    self.assertEqual(len(values),manifest['totals'][direction][tax+'_informed_lines'])
            self.assertEqual(1,manifest['totals']['outgoing']['cancelled_documents'])
            for did,original in originals.items():
                self.assertEqual(original['total_cents'],sum(t['total_cents'] for t in manifest['trace'] if t['document_id']==did))
        for bad in (excluded,foreign):
            self.post('/prosoft-fiscal/preview',payload|{'document_ids':[bad['id']]},400)
        only=self.post('/prosoft-fiscal/preview',payload|{'record_types':['outgoing_notes']})
        self.assertEqual({'SAIDAS.TXT'},set(only['manifest']['files']))
        self.assertEqual([incoming['id']],[t['document_id'] for t in only['manifest']['skipped']])
        self.assertEqual(before,self.economic_snapshot())

    def test_accounting_modes_cta_traceable_reference_and_scoped_selection(self):
        long='SYNTHETIC REFERENCE 2026-11'
        simple=self.core.create_journal(self.a['id'],self.journal(amount='0.01')|{'document':long,'history':'Synthetic'},'test')
        detailed_payload=self.journal('detailed',amount='100.01')|{'document':'SYN2','history':'Synthetic', 'lines':[
            {'account_id':self.aid['3'],'debit':'33.33','credit':'0'},
            {'account_id':self.aid['4'],'debit':'66.68','credit':'0'},
            {'account_id':self.aid['5'],'debit':'0','credit':'100.01'}]}
        detailed=self.core.create_journal(self.a['id'],detailed_payload,'test')
        self.activate(self.a['id'],'2026-12')
        other=self.core.create_journal(self.a['id'],self.journal('other',day='2026-12-02')|{'document':'OTHER'},'test')
        self.activate(self.b['id'])
        foreign_accounts={a['access_code']:a['id'] for a in self.core.accounts(self.b['id'])}
        foreign_payload=self.journal('foreign')|{'document':'FOREIGN'}
        for line in foreign_payload['lines']:
            line['account_id']=foreign_accounts['3' if line['debit']!='0.00' else '5']
        foreign=self.core.create_journal(self.b['id'],foreign_payload,'test')
        self.activate(self.a['id']);before=self.economic_snapshot();payload=self.accounting_payload()
        payload['accounts'][str(self.aid['3'])].update(third_mode='none',create_account={
            'destination_missing':True,'classifier':'1.01.001','name':'Synthetic account','cost_center_mode':'0','reconciliation':'0'})
        without,cta,journals=self.accounting_batch(payload|{'record_types':['LC1','LC2']})
        self.assertEqual([],cta);self.assertEqual(['1','2'],[j['mode'] for j in journals])
        saved,cta,journals=self.accounting_batch(payload|{'record_types':['LC1','LC2','CTA']})
        self.assertEqual(1,len(cta));self.assertEqual(3,cta[0]['account'])
        self.assertEqual('101001000000000',cta[0]['classifier'])
        self.assertEqual(10002,sum(j['total_cents'] for j in journals))
        source={simple['id']:simple,detailed['id']:detailed}
        self.assertEqual(set(source),{t['journal_id'] for t in saved['manifest']['trace']})
        for trace,journal in zip(saved['manifest']['trace'],journals):
            original=source[trace['journal_id']]
            self.assertEqual(original['date'],journal['date']);self.assertEqual(27,journal['batch'])
            expected=sorted((int(payload['accounts'][str(line['account_id'])]['code']),
                'D' if line['debit_cents'] else 'C',line['debit_cents'] or line['credit_cents']) for line in original['lines'])
            actual=sorted((line['account'],line['nature'],line['cents']) for line in journal['lines'])
            self.assertEqual(expected,actual)
            self.assertTrue(all(line['center']==0 and line['third']=='' for line in journal['lines']))
            if 'document_reference' in trace:
                ref=trace['document_reference']
                self.assertEqual(long,ref['original']);self.assertEqual(sha256(long.encode()).hexdigest(),ref['original_sha256'])
                self.assertEqual(ref['exported'],journal['document']);self.assertEqual('YZF5USNWLD',journal['document'])
            else:self.assertEqual(original['document'],journal['document'])
        self.assertEqual(without['manifest']['trace'],saved['manifest']['trace'])
        replay,_,_=self.accounting_batch(payload|{'record_types':['LC1','LC2','CTA']})
        self.assertTrue(replay['duplicate']);self.assertEqual(saved['id'],replay['id'])
        subset,_,only=self.accounting_batch(payload|{'record_types':['LC1','LC2'],'journal_ids':[simple['id']]})
        self.assertEqual(1,len(only));self.assertEqual('YZF5USNWLD',only[0]['document'])
        self.assertEqual([simple['id']],[trace['journal_id'] for trace in subset['manifest']['trace']])
        for bad in (other,foreign):self.post('/prosoft/preview',payload|{'journal_ids':[bad['id']]},400)
        self.assertEqual(long,next(j for j in self.core.journals(self.a['id']) if j['id']==simple['id'])['document'])
        self.assertEqual(before,self.economic_snapshot())

    def test_visual_daily_synthesis_does_not_replace_real_exported_journals(self):
        model=self.model()
        docs=[self.sale('7001','0.01'),self.sale('7002','10.02')]
        # The existing service owns individual/daily generation; this test only consumes it.
        for index,doc in enumerate(docs):
            p=daily.FiscalSalesAccountingTests.payload(self,[doc],model,'individual-'+str(index))
            self.post(daily.ROOT+'/generate',p)
        before=self.economic_snapshot()
        report=self.core.business_report(self.a['id'],'consolidated-diary','2026-11-01','2026-11-30')
        self.assertEqual(2,len(report['rows']));self.assertEqual(2,len(report['rows'][0]['journal_ids']))
        _,_,decoded=self.accounting_batch(self.accounting_payload())
        self.assertEqual([1,1002],sorted(j['total_cents'] for j in decoded))
        self.assertEqual(before,self.economic_snapshot())
        self.mode('daily')
        new=[self.sale('7003','0.09',day='2026-11-07'),self.sale('7004','20.03',day='2026-11-07')]
        generated=self.post(daily.ROOT+'/generate',daily.FiscalSalesAccountingTests.payload(self,new,model,'daily-contract'))
        self.assertEqual(1,generated['created_count'])
        before=self.economic_snapshot()
        saved,_,decoded=self.accounting_batch(self.accounting_payload())
        self.assertEqual([1,1002,2012],sorted(j['total_cents'] for j in decoded))
        consolidated=generated['journals'][0]
        self.assertIn(consolidated['id'],[t['journal_id'] for t in saved['manifest']['trace']])
        origins=self.client.get(self.scope(daily.ROOT+f"/journals/{consolidated['id']}/sources")).json()
        self.assertEqual({d['id'] for d in new},{s['document_id'] for s in origins['sources']})
        self.assertEqual(before,self.economic_snapshot())


if __name__=='__main__':unittest.main()
