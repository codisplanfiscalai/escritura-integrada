"""Retained originals for old booked notes; synthetic imports and disposable DB only."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET
import test_fiscal_payment_allocations as prior
from test_document_preview import synthetic_xml

ROOT = '/fiscal-sales-accounting'
NS = '{http://www.portalfiscal.inf.br/nfe}'


class LegacyPaymentSourcesTests(unittest.TestCase):
    for _name in ('setUp','tearDown','scope','activate','create_company','document','journal','post','mode','sale','purchase','model','snapshot','reverse','operator','direct','payload'):
        locals()[_name] = getattr(prior.FiscalPaymentAllocationTests,_name)
    del _name

    def xml(self, number=101, payments=(('01','100.00'),('03','165.75')), change=None, cid=None, status='100'):
        company = self.b if cid==self.b['id'] else self.a
        root=ET.fromstring(synthetic_xml('auditor_nfce',company['tax_id']))
        info=root.find('.//'+NS+'infNFe');key='352601'+'0'*14+'65001'+str(number).zfill(19)
        info.set('Id','NFe'+key);info.find(NS+'ide/'+NS+'nNF').text=str(number)
        for node in info.findall('.//'+NS+'CFOP'):node.text='5102'
        pag=info.find(NS+'pag')
        if pag is None:pag=ET.SubElement(info,NS+'pag')
        for node in list(pag):pag.remove(node)
        for method,value in payments:
            detail=ET.SubElement(pag,NS+'detPag');ET.SubElement(detail,NS+'tPag').text=method;ET.SubElement(detail,NS+'vPag').text=value
        if change is not None:ET.SubElement(pag,NS+'vTroco').text=change
        root.find('.//'+NS+'chNFe').text=key;root.find('.//'+NS+'infProt/'+NS+'cStat').text=status
        return ET.tostring(root,encoding='utf-8')

    def legacy(self, raws=None, *, archive=True, cid=None):
        cid=cid or self.a['id'];raws=raws or [self.xml()]
        if archive:
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
                for i,raw in enumerate(raws):z.writestr(f'folder-{i}/nota.xml',raw)
            content,filename=out.getvalue(),'legacy-synthetic.zip'
        else:content,filename=raws[0],'legacy-synthetic.xml'
        batch=self.post('/imports/preview',dict(filename=filename,period='2026-11',options={'posting_date':'2026-11-06'},content_base64=base64.b64encode(content).decode()),cid=cid)
        self.assertTrue(batch['can_confirm'],batch['issues'])
        self.post(f"/imports/{batch['id']}/confirm",{'preview_hash':batch['preview_hash'],'posting_mode':'pending'},cid=cid)
        hashes={hashlib.sha256(raw).hexdigest() for raw in raws};docs=[]
        for doc in self.core.documents(cid):
            if doc['source_hash'] not in hashes:continue
            doc=self.post(f"/documents/{doc['id']}/review",{'version':doc['version'],'reason':'Revisão sintética anterior preservada'},cid=cid)
            doc=self.post(f"/documents/{doc['id']}/book",{'version':doc['version'],'reason':'Escrituração sintética anterior'},cid=cid)['document']
            with self.core.db.transaction() as conn:
                row=conn.execute('SELECT extra_json FROM documents WHERE company_id=? AND id=?',(cid,doc['id'])).fetchone();extra=json.loads(row['extra_json'])
                extra.pop('declared_document_fields',None);extra.pop('declared_xml',None)
                conn.execute('UPDATE documents SET extra_json=? WHERE company_id=? AND id=?',(json.dumps(extra),cid,doc['id']))
            docs.append(next(d for d in self.core.documents(cid) if d['id']==doc['id']))
        return sorted(docs,key=lambda d:d['number']),batch,content

    def details(self,docs,cid=None):
        return self.post(ROOT+'/payments',{'entries':[{'document_id':d['id'],'version':d['version']} for d in docs]},cid=cid)

    def test_old_xml_mixed_and_cash_consolidate_readonly_without_backfill(self):
        self.mode();docs,batch,raw=self.legacy([self.xml(),self.xml(102,(('01','265.75'),))]);before=self.snapshot()
        from app.auditor_sources import original_xmls
        with patch('app.auditor_sources.original_xmls',wraps=original_xmls) as reader:
            details=self.details(docs);self.assertEqual(1,sum(call.args[0].endswith('.zip') for call in reader.call_args_list));self.assertEqual(3,reader.call_count)
        self.assertEqual(before,self.snapshot());self.assertTrue(all(d['evidence_origin']=='retained_xml' and not d['issue'] for d in details['documents']))
        payload=self.payload(docs);preview=self.post(ROOT+'/preview',payload);self.assertEqual(before,self.snapshot());self.assertEqual(1,preview['created_count'])
        result=self.post(ROOT+'/generate',payload);self.assertEqual((1,2),(result['created_count'],result['accounted_count']));self.assertEqual(53150,result['journals'][0]['total_cents'])
        for doc in docs:
            saved=next(d for d in self.core.documents(self.a['id']) if d['id']==doc['id']);self.assertEqual(doc|{'journal_id':result['journals'][0]['id']},saved)
            self.assertNotIn('declared_document_fields',saved);self.assertNotIn('declared_xml',saved)
        self.assertTrue(all(s['payment_snapshot']['evidence_origin']=='retained_xml' for s in result['sources']))
        before=self.snapshot();self.assertTrue(self.post(ROOT+'/generate',payload)['duplicate']);self.assertEqual(before,self.snapshot())
        skipped=self.post(ROOT+'/generate',self.payload(docs,'new-key'));self.assertEqual((0,2),(skipped['created_count'],len(skipped['skipped'])))

    def test_plain_xml_change_and_individual_mode(self):
        docs,_,_=self.legacy([self.xml(payments=(('01','103.00'),('03','165.75')),change='3.00')],archive=False)
        payload=self.payload(docs);payload['entries'][0]['change_allocations']=[dict(payment_index=0,amount_cents=300)]
        result=self.post(ROOT+'/generate',payload);self.assertEqual('individual',result['mode']);self.assertEqual([10000,16575],[p['net_cents'] for p in result['sources'][0]['payment_snapshot']['payments']])

    def test_missing_tampered_or_malformed_original_is_diagnostic_and_atomic(self):
        docs,batch,original=self.legacy();valid=self.payload(docs)
        self.assertEqual(1,self.post(ROOT+'/preview',valid)['created_count'])
        for raw in [b'',b'<broken',original+b'tampered','invalid-text-in-blob']:
            with self.core.db.transaction() as conn:conn.execute('UPDATE imports SET original=? WHERE company_id=? AND id=?',(raw,self.a['id'],batch['id']))
            before=self.snapshot();self.assertTrue(self.details(docs)['documents'][0]['issue']);self.post(ROOT+'/generate',valid,422);self.assertEqual(before,self.snapshot())
        # Correct digest but invalid XML cannot become payment evidence.
        malformed=b'<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><broken';h=hashlib.sha256(malformed).hexdigest()
        with self.core.db.transaction() as conn:
            row=conn.execute('SELECT parsed_json FROM imports WHERE id=?',(batch['id'],)).fetchone();parsed=json.loads(row['parsed_json']);parsed['documents'][0]['source_hash']=h
            conn.execute('UPDATE imports SET filename=?,original=?,sha256=?,parsed_json=? WHERE id=?',('broken.xml',malformed,h,json.dumps(parsed),batch['id']))
            conn.execute('UPDATE documents SET source_hash=? WHERE id=?',(h,docs[0]['id']))
        before=self.snapshot();self.assertTrue(self.details(docs)['documents'][0]['issue']);self.post(ROOT+'/generate',valid,422);self.assertEqual(before,self.snapshot())

    def test_valid_and_missing_source_in_one_request_are_atomic(self):
        first,_,_=self.legacy(archive=False);second,batch,_=self.legacy([self.xml(102)],archive=False)
        with self.core.db.transaction() as conn:conn.execute('UPDATE imports SET original=? WHERE id=?',(b'',batch['id']))
        payload=self.payload(first+second);before=self.snapshot()
        self.post(ROOT+'/preview',payload,422);self.post(ROOT+'/generate',payload,422);self.assertEqual(before,self.snapshot());self.assertEqual([],self.core.journals(self.a['id']))

    def test_other_company_key_model_or_direction_cannot_supply_evidence(self):
        docs,batch,original=self.legacy();valid=self.payload(docs)
        for field,value in [('key','8'*44),('model','55'),('direction','incoming')]:
            with self.core.db.transaction() as conn:conn.execute('UPDATE documents SET '+field+'=? WHERE id=?',(value,docs[0]['id']))
            current=next(d for d in self.core.documents(self.a['id']) if d['id']==docs[0]['id']);before=self.snapshot();self.assertTrue(self.details([current])['documents'][0]['issue']);self.assertEqual(before,self.snapshot())
            with self.core.db.transaction() as conn:conn.execute('UPDATE documents SET '+field+'=? WHERE id=?',(docs[0][field],docs[0]['id']))
        with self.core.db.transaction() as conn:conn.execute('UPDATE imports SET company_id=? WHERE id=?',(self.b['id'],batch['id']))
        before=self.snapshot();self.assertTrue(self.details(docs)['documents'][0]['issue']);self.post(ROOT+'/generate',valid,422);self.assertEqual(before,self.snapshot())

    def test_forged_metadata_cannot_override_actual_xml_key_or_model(self):
        docs,batch,_=self.legacy()
        with self.core.db.read() as conn:original=json.loads(conn.execute('SELECT parsed_json FROM imports WHERE id=?',(batch['id'],)).fetchone()['parsed_json'])
        for field,value in [('key','8'*44),('model','55')]:
            parsed=json.loads(json.dumps(original));parsed['documents'][0][field]=value
            with self.core.db.transaction() as conn:
                conn.execute('UPDATE imports SET parsed_json=? WHERE id=?',(json.dumps(parsed),batch['id']))
                conn.execute('UPDATE documents SET '+field+'=? WHERE id=?',(value,docs[0]['id']))
            before=self.snapshot();self.assertTrue(self.details(docs)['documents'][0]['issue']);self.post(ROOT+'/generate',self.payload(docs),422);self.assertEqual(before,self.snapshot())
            with self.core.db.transaction() as conn:conn.execute('UPDATE documents SET '+field+'=? WHERE id=?',(docs[0][field],docs[0]['id']))

    def test_xml_issuer_mismatch_and_cancelled_protocol_are_not_fallbacks(self):
        docs,batch,_=self.legacy();key=docs[0]['key']
        for raw in [self.xml(cid=self.b['id']),self.xml(status='101')]:
            h=hashlib.sha256(raw).hexdigest()
            with self.core.db.transaction() as conn:
                parsed=json.loads(conn.execute('SELECT parsed_json FROM imports WHERE id=?',(batch['id'],)).fetchone()['parsed_json']);parsed['documents'][0]['source_hash']=h
                conn.execute('UPDATE imports SET filename=?,original=?,sha256=?,parsed_json=? WHERE id=?',('changed.xml',raw,h,json.dumps(parsed),batch['id']))
                conn.execute('UPDATE documents SET source_hash=? WHERE id=?',(h,docs[0]['id']))
            before=self.snapshot();self.assertTrue(self.details(docs)['documents'][0]['issue']);self.post(ROOT+'/generate',self.payload(docs),422);self.assertEqual(before,self.snapshot())

    def test_stored_snapshot_remains_authoritative_and_avoids_original_lookup(self):
        docs,batch,_=self.legacy();stored=prior.declared([('01','265.75')])
        with self.core.db.transaction() as conn:
            extra=json.loads(conn.execute('SELECT extra_json FROM documents WHERE id=?',(docs[0]['id'],)).fetchone()['extra_json']);extra['declared_document_fields']=stored
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?',(json.dumps(extra),docs[0]['id']))
        with patch('app.fiscal_payment_sources.RetainedPaymentSources._index',side_effect=AssertionError('No fallback for stored evidence')):
            details=self.details(docs);self.assertEqual(['01'],[p['method'] for p in details['documents'][0]['payments']])
        with self.core.db.transaction() as conn:
            extra['declared_document_fields']={};conn.execute('UPDATE documents SET extra_json=? WHERE id=?',(json.dumps(extra),docs[0]['id']))
        self.assertTrue(self.details(docs)['documents'][0]['issue'])

    def test_replay_and_source_reversal_do_not_depend_on_original_retention(self):
        self.mode();docs,batch,_=self.legacy([self.xml(),self.xml(102)]);payload=self.payload(docs);result=self.post(ROOT+'/generate',payload);original=result['journals'][0]
        with self.core.db.transaction() as conn:conn.execute('UPDATE imports SET original=? WHERE id=?',(b'',batch['id']))
        before=self.snapshot();self.assertTrue(self.post(ROOT+'/generate',payload)['duplicate']);self.assertEqual(before,self.snapshot())
        current=next(d for d in self.core.documents(self.a['id']) if d['id']==docs[0]['id']);self.reverse(current)
        self.assertEqual(original,self.client.get(self.scope('/journals/'+str(original['id']))).json())
        self.assertEqual(26575,next(j for j in self.core.journals(self.a['id']) if j['id']!=original['id'])['total_cents'])
        self.assertEqual(original['id'],next(d for d in self.core.documents(self.a['id']) if d['id']==docs[1]['id'])['journal_id'])

    def test_readonly_permissions_and_closed_reopened_competence(self):
        docs,_,_=self.legacy();payload=self.payload(docs)
        client,uid=self.operator({'fiscal.documents':['read'],'accounting.accounts':['read'],'accounting.journals':['read']})
        try:
            before=self.snapshot();r=client.post(self.scope(ROOT+'/payments'),json={'entries':[{'document_id':docs[0]['id'],'version':docs[0]['version']}]});self.assertEqual(200,r.status_code,r.text);self.assertFalse(r.json()['documents'][0]['issue'])
            self.assertEqual(200,client.post(self.scope(ROOT+'/preview'),json=payload).status_code);self.assertEqual(403,client.post(self.scope(ROOT+'/generate'),json=payload).status_code);self.assertEqual(before,self.snapshot())
        finally:client.close()
        self.post('/periods/close',{'module':'accounting','period':'2026-11','reason':'Fixture'})
        before=self.snapshot();self.post(ROOT+'/generate',payload,409);self.assertEqual(before,self.snapshot())
        self.post('/periods/reopen',{'module':'accounting','period':'2026-11','reason':'Fixture'});self.assertEqual(1,self.post(ROOT+'/generate',payload)['created_count'])

    def test_external_entities_are_rejected_without_network_or_mutation(self):
        docs,batch,_=self.legacy();raw=b'<!DOCTYPE NFe [<!ENTITY xxe SYSTEM "https://example.invalid/not-contacted">]><NFe>&xxe;</NFe>';h=hashlib.sha256(raw).hexdigest()
        with self.core.db.transaction() as conn:
            parsed=json.loads(conn.execute('SELECT parsed_json FROM imports WHERE id=?',(batch['id'],)).fetchone()['parsed_json']);parsed['documents'][0]['source_hash']=h
            conn.execute('UPDATE imports SET filename=?,original=?,sha256=?,parsed_json=? WHERE id=?',('unsafe.xml',raw,h,json.dumps(parsed),batch['id']));conn.execute('UPDATE documents SET source_hash=? WHERE id=?',(h,docs[0]['id']))
        before=self.snapshot()
        with patch('socket.create_connection',side_effect=AssertionError('No external connections')):
            self.assertTrue(self.details(docs)['documents'][0]['issue']);self.post(ROOT+'/generate',self.payload(docs),422)
        self.assertEqual(before,self.snapshot())

    def test_cancelled_document_is_skipped_and_concurrent_requests_have_one_effect(self):
        self.mode();docs,_,_=self.legacy([self.xml(),self.xml(102)])
        with self.core.db.transaction() as conn:
            extra=json.loads(conn.execute('SELECT extra_json FROM documents WHERE id=?',(docs[0]['id'],)).fetchone()['extra_json']);extra['document_state']='cancelled'
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?',(json.dumps(extra),docs[0]['id']))
        payload=self.payload(docs)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.core.generate_sales_accounting(self.a['id'],payload,'synthetic'),range(2)))
        self.assertEqual(1,sum(bool(r.get('duplicate')) for r in results));self.assertEqual(1,len(self.core.journals(self.a['id'])))
        created=next(r for r in results if not r.get('duplicate'));self.assertEqual(1,created['accounted_count']);self.assertEqual('not_eligible',created['skipped'][0]['reason'])


if __name__=='__main__':unittest.main()
