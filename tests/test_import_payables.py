"""Synthetic XML billing integration; test databases are temporary."""
import unittest
import test_fiscal_import as fixtures


class ImportPayablesTests(unittest.TestCase):
    setUp = fixtures.FiscalImportTests.setUp
    tearDown = fixtures.FiscalImportTests.tearDown
    create_company = fixtures.FiscalImportTests.create_company
    activate = fixtures.FiscalImportTests.activate
    scope = fixtures.FiscalImportTests.scope
    document = fixtures.FiscalImportTests.document
    post = fixtures.FiscalImportTests.post
    xml = fixtures.FiscalImportTests.xml
    preview = fixtures.FiscalImportTests.preview
    mapping = fixtures.FiscalImportTests.mapping
    prepared = fixtures.FiscalImportTests.prepared
    confirm = fixtures.FiscalImportTests.confirm
    def test_explicit_billing_creates_linked_titles_only_once(self):
        self.mapping()
        batch = self.preview()
        prepared = self.prepared(batch, create_payables=True)
        plan = prepared['documents'][0]['financial_posting']
        self.assertTrue(plan['eligible'], plan)
        result = self.confirm(batch, prepared)
        self.assertEqual(1, result['titles_created'])
        self.assertEqual(0, result['transactions_created'])
        repeat = self.confirm(batch, prepared)
        self.assertEqual(result['title_ids'], repeat['title_ids'])
        titles = self.core.titles(self.a['id'])
        self.assertEqual(1, len(titles))
        self.assertEqual('001', titles[0]['document'])
        self.assertEqual('2026-12-05', titles[0]['due_date'])
        self.assertEqual(10000, titles[0]['amount_cents'])
        self.assertEqual([], titles[0]['settlements'])
        self.assertEqual(result['document_ids'][0], titles[0]['document_id'])
        second = self.preview(filename='outra-origem.xml')
        next_preview = self.prepared(second, create_payables=True)
        duplicate = self.confirm(second, next_preview)
        self.assertEqual(0, duplicate['titles_created'])
        self.assertEqual(1, duplicate['titles_duplicate'])

    def test_missing_due_date_blocks_atomically_but_opt_out_imports(self):
        self.mapping()
        batch = self.preview(self.xml().replace(b'<dVenc>2026-12-05</dVenc>', b''))
        prepared = self.prepared(batch, create_payables=True)
        self.assertFalse(prepared['documents'][0]['financial_posting']['eligible'])
        self.confirm(batch, prepared, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))
        prepared = self.prepared(batch, create_payables=False)
        self.assertEqual(1, self.confirm(batch, prepared)['documents_created'])
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_no_billing_is_not_an_error_and_old_api_stays_opt_out(self):
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch))
        self.assertEqual(0, result['titles_created'])
        with self.core.db.read() as conn:
            plan = self.core._payables_plan(conn, self.a['id'], {'direction': 'incoming'}, True)
        self.assertEqual('not_applicable', plan['status'])

    def test_reprocess_classification_preserves_titles_and_blocks_cancelled(self):
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch, create_payables=True))
        options = {'create_payables': True, 'document_overrides': {'documents:0': {'cfop': '1556'}}}
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertTrue(plan['can_confirm'], plan)
        result2 = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            **options, 'reason': 'Revisão sintética', 'idempotency_key': 'reclassify-billing', 'reprocess_hash': plan['reprocess_hash']})
        self.assertEqual(result['title_ids'], result2['title_ids'])
        self.assertEqual(0, result2['titles_created'])
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE titles SET cancelled=1 WHERE company_id=? AND id=?', (self.a['id'], result['title_ids'][0]))
        blocked = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertFalse(blocked['can_confirm'])
        self.assertEqual(1, len(self.core.titles(self.a['id'])))

    def test_reprocess_can_create_previously_declined_payables(self):
        self.mapping()
        batch = self.preview()
        self.confirm(batch, self.prepared(batch))
        options = {'create_payables': True}
        plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
        self.assertTrue(plan['can_confirm'], plan)
        result = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
            **options, 'reason': 'Gerar cobrança revisada', 'idempotency_key': 'generate-billing', 'reprocess_hash': plan['reprocess_hash']})
        self.assertEqual(1, result['titles_created'])
        self.assertEqual(0, result['documents_created'])

    def test_multiple_installments_preserve_numbers_dates_and_values(self):
        self.mapping()
        raw = self.xml().replace(b'<vDup>100.00</vDup>', b'<vDup>40.00</vDup>').replace(
            b'</cobr>', b'<dup><nDup>002</nDup><dVenc>2027-01-05</dVenc><vDup>60.00</vDup></dup></cobr>')
        batch = self.preview(raw)
        result = self.confirm(batch, self.prepared(batch, create_payables=True))
        self.assertEqual(2, result['titles_created'])
        titles = sorted(self.core.titles(self.a['id']), key=lambda title: title['installment'])
        self.assertEqual([('001', '2026-12-05', 4000), ('002', '2027-01-05', 6000)],
                         [(t['document'], t['due_date'], t['amount_cents']) for t in titles])
        self.assertTrue(all(t['company_id'] == self.a['id'] and not t['settlements'] for t in titles))

    def test_permission_denial_rolls_back_fiscal_and_is_visible_in_preview(self):
        from unittest.mock import patch
        from app.core import DomainError
        self.mapping()
        batch = self.preview()
        with patch('app.import_payables.effect', side_effect=DomainError('Sem permissão para gerar títulos.', 403, 'forbidden')):
            prepared = self.prepared(batch, create_payables=True)
            self.assertFalse(prepared['documents'][0]['financial_posting']['eligible'])
            self.assertIn('permissão', prepared['documents'][0]['financial_posting']['reason'])
            self.confirm(batch, prepared, status=409)
        self.assertEqual([], self.core.documents(self.a['id']))
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_legacy_batch_recovers_billing_from_exact_original(self):
        import json
        from app.core import pack
        self.mapping()
        batch = self.preview()
        result = self.confirm(batch, self.prepared(batch))
        with self.core.db.transaction() as conn:
            stored = conn.execute('SELECT parsed_json FROM imports WHERE id=?', (batch['id'],)).fetchone()
            parsed = json.loads(stored['parsed_json'])
            for doc in parsed['documents']: doc.pop('billing', None)
            conn.execute('UPDATE imports SET parsed_json=? WHERE id=?', (pack(parsed), batch['id']))
            stored = conn.execute('SELECT extra_json FROM documents WHERE id=?', (result['document_ids'][0],)).fetchone()
            extras = json.loads(stored['extra_json']); extras.pop('billing', None)
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?', (pack(extras), result['document_ids'][0]))
        for attempt in range(2):
            options = {'create_payables': True}
            plan = self.post(f"/imports/{batch['id']}/reprocess-preview", options)
            self.assertTrue(plan['can_confirm'], plan)
            result2 = self.post(f"/imports/{batch['id']}/reprocess-confirm", {
                **options, 'reason': 'Recuperação legada sintética', 'idempotency_key': f'legacy-billing-{attempt}', 'reprocess_hash': plan['reprocess_hash']})
            self.assertEqual(1 if attempt == 0 else 0, result2['titles_created'])
        self.assertEqual(1, len(self.core.titles(self.a['id'])))
        restored = self.core.documents(self.a['id'])[0]
        self.assertEqual('FICT-42', restored['billing']['invoice']['number'])
        self.assertEqual(result['document_ids'][0], restored['id'])

    def test_billing_only_preserves_fiscal_rows_and_generates_183_linked_installments(self):
        import io, json, zipfile
        archive=io.BytesIO()
        decision={'basis':'vNF','source':'XML sintético','responsible':'Teste','reason':'Preservar total clássico revisado'}
        with zipfile.ZipFile(archive,'w') as bundle:
            for index in range(59):
                raw=self.xml().replace(b'35261187654321000198550010000000421000000420',str(10**43+index).encode())
                raw=raw.replace(b'<nNF>42</nNF>',f'<nNF>{index+1}</nNF>'.encode())
                amounts=['25.00']*4 if index<6 else ['30.00','30.00','40.00']
                parts=''.join(f'<dup><nDup>{i+1:03}</nDup><dVenc>2026-12-{i+1:02}</dVenc><vDup>{amount}</vDup></dup>' for i,amount in enumerate(amounts))
                raw=raw.replace(b'<dup><nDup>001</nDup><dVenc>2026-12-05</dVenc><vDup>100.00</vDup></dup>',parts.encode())
                raw=raw.replace(b'</ICMSTot></total>',b'</ICMSTot><vNFTot>105.00</vNFTot></total>')
                bundle.writestr(f'synthetic-{index}.xml',raw)
        batch=self.preview(archive.getvalue(),'59-synthetic.zip')
        overrides={f'documents:{index}':{'cfop':'1102','posting_date':'2026-11-08'} for index in range(59)}
        initial=self.prepared(batch,document_overrides=overrides,total_review=decision)
        self.confirm(batch,initial)
        def snapshot():
            with self.core.db.read() as conn:
                return [dict(r) for r in conn.execute('SELECT * FROM documents WHERE company_id=? ORDER BY id',(self.a['id'],))]
        before=snapshot()
        options={'preserve_fiscal':True,'create_payables':True}
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",options)
        self.assertTrue(plan['can_confirm'],plan)
        self.assertEqual({'documents':59,'installments':183,'amount_cents':590000},plan['billing_summary'])
        self.assertTrue(all(not r['diffs'] and r['document']['cfop']=='1102' and r['document']['total_review']==decision for r in plan['documents']))
        selected=[r['_selection'] for r in plan['documents'] if r['selected']]
        result=self.post(f"/imports/{batch['id']}/reprocess-confirm",options|{'selected':selected,'reprocess_hash':plan['reprocess_hash'],'idempotency_key':'billing-only-183','reason':'Cobranças sintéticas'})
        self.assertEqual(183,result['titles_created'])
        self.assertEqual(0,result['documents_updated'])
        self.assertTrue(result['fiscal_preserved'])
        self.assertEqual(before,snapshot(),'nenhuma coluna fiscal é regravada')
        with self.core.db.read() as conn:
            self.assertEqual(183,conn.execute('SELECT count(*) FROM titles WHERE company_id=?',(self.a['id'],)).fetchone()[0])
            self.assertEqual(59,conn.execute('SELECT count(DISTINCT document_id) FROM titles WHERE company_id=?',(self.a['id'],)).fetchone()[0])
            self.assertEqual(0,conn.execute('SELECT count(*) FROM settlements WHERE company_id=?',(self.a['id'],)).fetchone()[0])
        next_plan=self.post(f"/imports/{batch['id']}/reprocess-preview",options)
        repeat=self.post(f"/imports/{batch['id']}/reprocess-confirm",options|{'reprocess_hash':next_plan['reprocess_hash'],'idempotency_key':'billing-only-new-attempt','reason':'Repetição sintética'})
        self.assertEqual(0,repeat['titles_created'])
        self.assertEqual(183,repeat['titles_duplicate'])
        self.assertEqual(before,snapshot())

    def test_reprocess_restores_existing_cfop_and_total_decision_without_new_mapping(self):
        raw=self.xml().replace(b'</ICMSTot></total>',b'</ICMSTot><vNFTot>105.00</vNFTot></total>')
        decision={'basis':'vNF','source':'XML sintético','responsible':'Teste','reason':'Base revisada'}
        batch=self.preview(raw)
        initial=self.prepared(batch,total_review=decision,document_overrides={'documents:0':{'cfop':'1556','posting_date':'2026-11-08'}})
        self.confirm(batch,initial)
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",{'create_payables':True})
        self.assertTrue(plan['can_confirm'],plan)
        proposed=plan['documents'][0]['document']
        self.assertEqual('1556',proposed['cfop'])
        self.assertEqual('1556',proposed['items'][0]['cfop'])
        self.assertEqual(decision,proposed['total_review'])
        self.assertEqual('2026-11-08',proposed['posting_date'])

    def test_billing_only_rejects_fiscal_edits_and_stale_preview(self):
        self.mapping();batch=self.preview();self.confirm(batch,self.prepared(batch))
        base={'preserve_fiscal':True,'create_payables':True}
        for fields in ({'document_overrides':{'documents:0':{'cfop':'1556'}}},{'cfop_mappings':{'incoming:55:5102':'1556'}},{'preserve_fiscal':'true'}):
            self.post(f"/imports/{batch['id']}/reprocess-preview",base|fields,400)
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",base)
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE documents SET version=version+1 WHERE company_id=?',(self.a['id'],))
        self.post(f"/imports/{batch['id']}/reprocess-confirm",base|{'reprocess_hash':plan['reprocess_hash'],'idempotency_key':'stale-billing-only','reason':'Teste'},409)
        self.assertEqual([],self.core.titles(self.a['id']))

    def test_billing_only_legacy_enrichment_does_not_rewrite_document(self):
        import json
        self.mapping();batch=self.preview();created=self.confirm(batch,self.prepared(batch))
        with self.core.db.transaction() as conn:
            parsed=json.loads(conn.execute('SELECT parsed_json FROM imports WHERE id=?',(batch['id'],)).fetchone()[0])
            parsed['documents'][0].pop('billing',None)
            conn.execute('UPDATE imports SET parsed_json=? WHERE id=?',(json.dumps(parsed),batch['id']))
            doc=dict(conn.execute('SELECT * FROM documents WHERE id=?',(created['document_ids'][0],)).fetchone())
            extra=json.loads(doc['extra_json']);extra.pop('billing',None)
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?',(json.dumps(extra),doc['id']))
            before=dict(conn.execute('SELECT * FROM documents WHERE id=?',(doc['id'],)).fetchone())
        options={'preserve_fiscal':True,'create_payables':True}
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",options)
        self.assertTrue(plan['can_confirm'],plan)
        result=self.post(f"/imports/{batch['id']}/reprocess-confirm",options|{'reprocess_hash':plan['reprocess_hash'],'idempotency_key':'legacy-only','reason':'Teste sintético'})
        self.assertEqual(1,result['titles_created'])
        with self.core.db.read() as conn:
            self.assertEqual(before,dict(conn.execute('SELECT * FROM documents WHERE id=?',(doc['id'],)).fetchone()))
        repeat=self.post(f"/imports/{batch['id']}/reprocess-preview",options)
        self.assertEqual('existing',repeat['documents'][0]['document']['financial_posting']['status'])

    def test_billing_only_duplicate_source_creates_once_and_conflict_stops_all(self):
        import io,zipfile
        self.mapping();archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as bundle:
            bundle.writestr('one.xml',self.xml());bundle.writestr('duplicate.xml',self.xml())
        batch=self.preview(archive.getvalue(),'copies.zip');self.confirm(batch,self.prepared(batch))
        options={'preserve_fiscal':True,'create_payables':True}
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",options)
        self.assertEqual(1,plan['billing_summary']['documents'])
        self.assertEqual(1,plan['billing_summary']['installments'])
        result=self.post(f"/imports/{batch['id']}/reprocess-confirm",options|{'reprocess_hash':plan['reprocess_hash'],'idempotency_key':'duplicate-only','reason':'Teste sintético'})
        self.assertEqual(1,result['titles_created'])
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE titles SET amount_cents=9999 WHERE id=?',(result['title_ids'][0],))
        blocked=self.post(f"/imports/{batch['id']}/reprocess-preview",options|{'selected':['documents:0']})
        self.assertFalse(blocked['can_confirm'])
        self.post(f"/imports/{batch['id']}/reprocess-confirm",options|{'selected':['documents:0'],'reprocess_hash':blocked['reprocess_hash'],'idempotency_key':'conflict-only','reason':'Teste'},409)
        self.assertEqual(1,len(self.core.titles(self.a['id'])))

    def test_billing_only_conflicting_legacy_copies_never_choose_silently(self):
        import io,json,zipfile
        self.mapping();archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as bundle:
            bundle.writestr('one.xml',self.xml())
            bundle.writestr('changed.xml',self.xml().replace(b'2026-12-05',b'2026-12-06'))
        batch=self.preview(archive.getvalue(),'conflicting-billing.zip');created=self.confirm(batch,self.prepared(batch))
        with self.core.db.transaction() as conn:
            doc=dict(conn.execute('SELECT * FROM documents WHERE id=?',(created['document_ids'][0],)).fetchone())
            extra=json.loads(doc['extra_json']);extra.pop('billing',None)
            conn.execute('UPDATE documents SET extra_json=? WHERE id=?',(json.dumps(extra),doc['id']))
        options={'preserve_fiscal':True,'create_payables':True}
        plan=self.post(f"/imports/{batch['id']}/reprocess-preview",options)
        self.assertFalse(plan['can_confirm'])
        self.assertTrue(all('divergentes' in row['reason'] for row in plan['documents']))
        self.post(f"/imports/{batch['id']}/reprocess-confirm",options|{'reprocess_hash':plan['reprocess_hash'],'idempotency_key':'conflicting-legacy','reason':'Teste'},409)
        self.assertEqual([],self.core.titles(self.a['id']))
