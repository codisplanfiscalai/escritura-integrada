"""Only synthetic booked sales, charts, requests and temporary SQLite databases."""
from app.sql_support import insert_id
import json
from app.sql_support import check_foreign_keys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_core as base
from app.core import DomainError
from app.db import ContextConflict

ROOT = '/fiscal-sales-accounting'


class FiscalSalesAccountingTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    scope = base.CoreApiTests.scope
    activate = base.CoreApiTests.activate
    create_company = base.CoreApiTests.create_company
    document = base.CoreApiTests.document
    journal = base.CoreApiTests.journal

    def post(self, path, payload, status=200, cid=None):
        r = self.client.post(self.scope(path, cid), json=payload)
        self.assertEqual(status, r.status_code, r.text)
        return r.json()

    def mode(self, mode='daily', cid=None):
        path = self.scope(ROOT + '/settings', cid)
        old = self.client.get(path).json()
        r = self.client.put(path, json={'version': old['version'], 'mode': mode})
        self.assertEqual(200, r.status_code, r.text)
        return r.json()['version']

    def model(self, code='SALE', debit='3', credit='5', center=None, cid=None):
        accounts = {a['access_code']: a['id'] for a in self.core.accounts(cid or self.a['id'])}
        return self.post('/masters/accounting_model', {'code': code, 'name': 'Modelo sintético', 'data': {
            'debit_account_id': accounts[debit], 'credit_account_id': accounts[credit], 'cost_center_id': center,
            'valid_from': '2026-01-01', 'status': 'validated', 'direction': 'outgoing', 'history': 'Venda sintética',
            'source': 'Configuração explícita de teste', 'responsible': 'Operador sintético'}}, 201, cid)['id']

    def sale(self, number='S1', amount='100.00', day='2026-11-06', cfop='5102', cid=None, **extra):
        doc = self.post('/documents', self.document(number) | {'direction': 'outgoing', 'total': amount,
            'posting_date': day, 'cfop': cfop, **extra}, 201, cid)
        doc = self.post(f"/documents/{doc['id']}/review", {'version': doc['version'], 'reason': 'Teste'}, cid=cid)
        return self.post(f"/documents/{doc['id']}/book", {'version': doc['version'], 'reason': 'Escrituração sintética'}, cid=cid)['document']

    def payload(self, docs, model, key='sales', version=None):
        if version is None:
            version = self.client.get(self.scope(ROOT + '/settings')).json()['version']
        return {'idempotency_key': key, 'settings_version': version,
                'entries': [{'document_id': d['id'], 'version': d['version'], 'model_id': model} for d in docs]}

    def generate(self, docs, model, key='sales', **kw):
        return self.post(ROOT + '/generate', self.payload(docs, model, key), **kw)

    def snapshot(self):
        with self.core.db.read(snapshot=True) as conn:
            return {r[0]: [tuple(x) for x in conn.execute('SELECT * FROM "' + r[0] + '" ORDER BY rowid')]
                    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}

    def balances(self, cid=None):
        return self.core.business_report(cid or self.a['id'], 'trial-balance', '2026-11-01', '2026-11-30')

    def reverse(self, doc, key='undo', status=200):
        return self.post(f"/documents/{doc['id']}/reverse", {'version': doc['version'], 'date': '2026-11-09',
            'reason': 'Correção sintética', 'idempotency_key': key}, status)

    def test_baseline_single_booking_and_report_are_independent(self):
        model = self.model()
        doc = self.post('/documents', self.document() | {'direction': 'outgoing', 'cfop': '5102'}, 201)
        doc = self.post(f"/documents/{doc['id']}/review", {'version': doc['version'], 'reason': 'Teste'})
        r = self.post(f"/documents/{doc['id']}/book", {'version': doc['version'], 'reason': 'Teste', 'model_id': model})
        self.assertEqual(1, len(self.core.journals(self.a['id'])))
        self.assertEqual(10000, r['journal']['total_cents'])
        before = self.snapshot()
        report = self.core.business_report(self.a['id'], 'consolidated-diary', '2026-11-01', '2026-11-30')
        self.assertIn('somente leitura', report['scope_note'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(2, len(report['rows']))

    def test_individual_generates_distinct_journals_and_preserves_fiscal(self):
        model = self.model(); docs = [self.sale('I1', '0.01'), self.sale('I2', '10.02')]
        result = self.generate(docs, model)
        self.assertEqual('individual', result['mode']); self.assertEqual(2, result['created_count'])
        self.assertEqual([1, 1002], sorted(j['total_cents'] for j in result['journals']))
        current = {d['id']: d for d in self.core.documents(self.a['id'])}
        for source, old in zip(result['sources'], docs):
            self.assertEqual(old | {'journal_id': source['journal_id']}, current[old['id']])
        self.assertEqual([], self.core.titles(self.a['id']))

    def test_daily_real_journal_cents_all_notes_and_inverse_trace(self):
        self.mode(); model = self.model(); docs = [self.sale('D1', '0.01'), self.sale('D2', '10.02'), self.sale('D3', '20.03')]
        result = self.generate(docs, model)
        self.assertEqual((1, 3), (result['created_count'], result['accounted_count']))
        journal = result['journals'][0]
        self.assertEqual(3006, journal['total_cents']); self.assertEqual(2, len(journal['lines']))
        self.assertEqual(3006, sum(x['debit_cents'] for x in journal['lines']))
        self.assertEqual(3006, sum(x['credit_cents'] for x in journal['lines']))
        trace = self.client.get(self.scope(ROOT + f"/journals/{journal['id']}/sources")).json()
        self.assertEqual({d['id'] for d in docs}, {s['document_id'] for s in trace['sources']})
        for doc in docs:
            origin = self.client.get(self.scope(f"/documents/{doc['id']}/trace")).json()
            self.assertEqual(journal['id'], origin['accounting_sources'][0]['journal_id'])
            self.assertEqual(doc['source_hash'], origin['accounting_sources'][0]['source_hash'])
        self.assertEqual([], trace['reversals'])

    def test_dates_accounts_classifications_centers_and_participants_separate(self):
        self.mode(); model = self.model(); other = self.model('OTHER', credit='4')
        center = self.core.save_cost_center(self.a['id'], {'code': 'C1', 'name': 'Centro sintético'}, 'test')
        centered = self.model('CENTER', center=center['id'])
        docs = [self.sale('G1'), self.sale('G2'), self.sale('G3', day='2026-11-07'),
                self.sale('G4', cfop='6102'), self.sale('G5'), self.sale('G6')]
        payload = self.payload(docs, model)
        payload['entries'][4]['model_id'] = other; payload['entries'][5]['model_id'] = centered
        result = self.post(ROOT + '/generate', payload)
        self.assertEqual(5, result['created_count'])
        self.assertEqual(60000, sum(j['total_cents'] for j in result['journals']))
        self.assertEqual(20000, max(j['total_cents'] for j in result['journals']))

    def test_item_classification_signature_is_not_invented_allocation(self):
        self.mode(); model = self.model()
        docs = [self.sale('C1', items=[{'cfop': '5102', 'cst_icms': '00'}, {'cfop': '6102', 'cst_icms': '20'}]),
                self.sale('C2', items=[{'cfop': '6102', 'cst_icms': '20'}, {'cfop': '5102', 'cst_icms': '00'}]),
                self.sale('C3', items=[{'cfop': '5102', 'cst_icms': '00'}])]
        result = self.generate(docs, model)
        self.assertEqual(2, result['created_count'])
        self.assertEqual([10000, 20000], sorted(j['total_cents'] for j in result['journals']))
        self.assertEqual(2, len(result['sources'][0]['classification']['item_classifications']))

    def test_mode_persisted_by_company_without_movement_changes(self):
        docs = [self.sale('M1'), self.sale('M2')]; model = self.model()
        first = self.generate(docs[:1], model)
        before = self.core.journals(self.a['id'])
        self.mode()
        self.assertEqual(before, self.core.journals(self.a['id']))
        second = self.generate(docs, model, 'daily-after-individual')
        self.assertEqual(1, second['created_count']); self.assertEqual(1, len(second['skipped']))
        self.assertEqual(first['journals'][0]['id'], second['skipped'][0]['journal_id'])
        self.assertEqual('individual', self.client.get(self.scope(ROOT + '/settings', self.b['id'])).json()['mode'])
        self.mode('individual')
        replay = self.generate(docs, model, 'individual-after-daily')
        self.assertEqual(0, replay['created_count']); self.assertEqual(2, len(replay['skipped']))
        self.assertEqual(2, len(self.core.journals(self.a['id'])))
        # Re-open configuration through a fresh core instance on the same test DB.
        from app.business import BusinessCore
        fresh = BusinessCore(self.app.state.db)
        self.assertEqual('individual', fresh.fiscal_sales_accounting_settings(self.a['id'])['mode'])

    def test_same_day_later_selection_adds_without_rewriting(self):
        self.mode(); model = self.model(); d1 = self.sale('L1'); d2 = self.sale('L2')
        first = self.generate([d1], model); original = first['journals'][0]
        second = self.generate([d1, d2], model, 'additional')
        self.assertEqual(1, second['created_count']); self.assertEqual(1, len(second['skipped']))
        current = self.client.get(self.scope('/journals/' + str(original['id']))).json()
        self.assertEqual(original, current)
        self.assertIn('complementares', second['notice'])

    def test_idempotent_same_and_different_keys_and_conflicting_content(self):
        self.mode(); model = self.model(); docs = [self.sale('R1'), self.sale('R2')]
        payload = self.payload(docs, model)
        result = self.post(ROOT + '/generate', payload)
        snapshot = self.snapshot()
        replay = self.post(ROOT + '/generate', payload)
        self.assertTrue(replay['duplicate']); self.assertEqual(result['journals'], replay['journals'])
        self.assertEqual(snapshot, self.snapshot())
        self.post(ROOT + '/generate', payload | {'reason': 'changed'}, 409)
        self.mode('individual')
        historical = self.post(ROOT + '/generate', payload)
        self.assertTrue(historical['duplicate']); self.assertEqual('daily', historical['mode'])
        again = self.generate(docs, model, 'new-key')
        self.assertEqual(0, again['created_count']); self.assertEqual(2, len(again['skipped']))
        self.assertEqual(1, len(self.core.journals(self.a['id'])))

    def test_concurrent_requests_cannot_double_account(self):
        self.mode(); model = self.model(); docs = [self.sale('RACE1'), self.sale('RACE2')]
        def run(index):
            return self.core.generate_sales_accounting(self.a['id'], self.payload(docs, model, 'race-' + str(index)), 'test')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, (1, 2)))
        self.assertEqual([0, 1], sorted(r['created_count'] for r in results))
        self.assertEqual(1, len(self.core.journals(self.a['id'])))

    def test_stale_settings_or_document_and_bad_model_are_atomic(self):
        model = self.model(); docs = [self.sale('A1'), self.sale('A2')]
        payload = self.payload(docs, model); self.mode()
        before = self.snapshot()
        self.post(ROOT + '/generate', payload, 409); self.assertEqual(before, self.snapshot())
        payload['settings_version'] = 1; payload['entries'][1]['version'] -= 1
        self.post(ROOT + '/generate', payload, 409); self.assertEqual(before, self.snapshot())
        payload['entries'][1]['version'] += 1; payload['entries'][1]['model_id'] = 999999
        self.post(ROOT + '/generate', payload, 404); self.assertEqual(before, self.snapshot())
        payload['entries'][1]['model_id'] = model
        self.assertEqual(2, self.post(ROOT + '/generate', payload)['accounted_count'])

    def test_missing_or_invalid_configuration_does_not_assume_accounts(self):
        doc = self.sale(); model = self.model(); payload = self.payload([doc], model)
        before = self.snapshot()
        del payload['entries'][0]['model_id']
        self.post(ROOT + '/generate', payload, 400)
        self.assertEqual(before, self.snapshot())
        payload['entries'][0]['model_id'] = model
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE masters SET active=0 WHERE id=?', (model,))
        self.post(ROOT + '/generate', payload, 400)
        self.assertEqual([], self.core.journals(self.a['id']))

    def test_interrupt_after_first_journal_rolls_back_sources_and_retry(self):
        model = self.model(); docs = [self.sale('INT1'), self.sale('INT2')]
        payload = self.payload(docs, model); before = self.snapshot()
        original = self.core._create_journal; calls = []
        def interrupted(*args, **kwargs):
            journal = original(*args, **kwargs); calls.append(journal)
            if len(calls) == 2:
                raise RuntimeError('Synthetic interruption')
            return journal
        with patch.object(self.core, '_create_journal', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'Synthetic interruption'):
                self.core.generate_sales_accounting(self.a['id'], payload, 'test')
        self.assertEqual(before, self.snapshot())
        self.assertEqual(2, self.post(ROOT + '/generate', payload)['created_count'])

    def test_fiscal_and_accounting_closed_reopened(self):
        self.mode(); model = self.model(); docs = [self.sale('OPEN1'), self.sale('OPEN2')]
        for module in ('fiscal', 'accounting'):
            self.post('/periods/close', {'module': module, 'period': '2026-11', 'reason': 'Teste'})
            before = self.snapshot()
            self.generate(docs, model, status=409); self.assertEqual(before, self.snapshot())
            self.post('/periods/reopen', {'module': module, 'period': '2026-11', 'reason': 'Reabertura sintética'})
        result = self.generate(docs, model)
        self.assertEqual(1, result['created_count'])
        doc = next(d for d in self.core.documents(self.a['id']) if d['id'] == docs[0]['id'])
        self.post('/periods/close', {'module': 'accounting', 'period': '2026-11', 'reason': 'Teste'})
        self.reverse(doc, status=409)
        # A read-only synthetic diary remains available in a closed period.
        before = self.snapshot()
        self.core.business_report(self.a['id'], 'consolidated-diary', '2026-11-01', '2026-11-30')
        self.assertEqual(before, self.snapshot())
        self.post('/periods/reopen', {'module': 'accounting', 'period': '2026-11', 'reason': 'Teste'})
        self.assertEqual(10000, self.reverse(doc)['journal']['total_cents'])

    def test_partial_reversal_leaves_other_note_and_original_unchanged(self):
        self.mode(); model = self.model(); docs = [self.sale('U1', '10.01'), self.sale('U2', '20.02')]
        result = self.generate(docs, model); original = result['journals'][0]
        current = {d['id']: d for d in self.core.documents(self.a['id'])}
        undone = self.reverse(current[docs[0]['id']])
        self.assertEqual(1001, undone['journal']['total_cents'])
        self.assertIsNone(undone['journal']['reversal_of'])
        self.assertEqual(original, self.client.get(self.scope('/journals/' + str(original['id']))).json())
        remaining = next(d for d in self.core.documents(self.a['id']) if d['id'] == docs[1]['id'])
        self.assertEqual(original['id'], remaining['journal_id']); self.assertEqual('booked', remaining['status'])
        self.assertEqual(2002, next(r for r in self.balances()['rows'] if r['access_code'] == '3')['closing_cents'])
        trace = self.client.get(self.scope(ROOT + f"/journals/{original['id']}/sources")).json()
        self.assertEqual(2, len(trace['sources'])); self.assertEqual(1, len(trace['reversals']))
        self.assertTrue(self.reverse(current[docs[0]['id']])['duplicate'])
        self.reverse(remaining, 'undo-other')
        self.assertTrue(all(r['closing_cents'] == 0 for r in self.balances()['rows']))
        # Direct reversal also cannot reverse compensation or a fully detached aggregate.
        for jid in (original['id'], undone['journal']['id']):
            self.post(f'/journals/{jid}/reverse', {'date': '2026-11-10', 'reason': 'Teste'}, 409)

    def test_rebook_after_explicit_reversal_uses_new_contribution(self):
        self.mode(); model = self.model(); doc = self.sale()
        self.generate([doc], model)
        current = self.core.documents(self.a['id'])[0]
        reversed_doc = self.reverse(current)['document']
        reviewed = self.post(f"/documents/{doc['id']}/review", {'version': reversed_doc['version'], 'reason': 'Teste'})
        booked = self.post(f"/documents/{doc['id']}/book", {'version': reviewed['version'], 'reason': 'Teste'})['document']
        result = self.generate([booked], model, 'new-intent')
        self.assertEqual(1, result['created_count'])
        trace = self.client.get(self.scope(f"/documents/{doc['id']}/trace")).json()
        self.assertEqual(2, len(trace['accounting_sources']))
        self.assertEqual(10000, next(r for r in self.balances()['rows'] if r['access_code'] == '3')['closing_cents'])

    def test_cancelled_and_unbooked_skipped_without_accounting_effects(self):
        model = self.model()
        pending = self.post('/documents', self.document('PENDING') | {'direction': 'outgoing'}, 201)
        cancelled = self.sale('CANCELLED', '0.00', source_hash='', taxes={}, book_cancellation={
            'source': 'Livro fictício', 'responsible': 'Teste', 'reason': 'Teste'})
        result = self.generate([pending, cancelled], model)
        self.assertEqual(0, result['created_count']); self.assertEqual(2, len(result['skipped']))
        self.assertEqual([], self.core.journals(self.a['id']))

    def test_settings_validate_version_mode_and_csrf(self):
        path = self.scope(ROOT + '/settings')
        for invalid in ([], {}, None, 'unknown'):
            r = self.client.put(path, json={'version': 0, 'mode': invalid})
            self.assertEqual(400, r.status_code, r.text)
        self.assertEqual(403, self.client.put(path, json={'version': 0, 'mode': 'daily'}, headers={'X-CSRF-Token': ''}).status_code)
        self.mode()
        self.assertEqual(409, self.client.put(path, json={'version': 0, 'mode': 'individual'}).status_code)

    def test_company_isolation_settings_documents_models_trace_and_context(self):
        self.mode(); model = self.model(); doc = self.sale()
        result = self.generate([doc], model); jid = result['journals'][0]['id']
        self.activate(self.b['id'])
        self.assertEqual('individual', self.client.get(self.scope(ROOT + '/settings', self.b['id'])).json()['mode'])
        model_b = self.model(cid=self.b['id']); doc_b = self.sale('B1', cid=self.b['id'])
        self.post(ROOT + '/generate', self.payload([doc_b], model_b, 'inactive', 0), 409)
        self.post(ROOT + '/generate', self.payload([doc], model_b, 'foreign-document', 0), 404, self.b['id'])
        self.post(ROOT + '/generate', self.payload([doc_b], model, 'foreign-model', 0), 404, self.b['id'])
        self.assertEqual(404, self.client.get(self.scope(ROOT + f'/journals/{jid}/sources', self.b['id'])).status_code)
        response = self.post(ROOT + '/generate', self.payload([doc_b], model_b, 'company-B', 0), cid=self.b['id'])
        self.assertEqual(1, response['created_count']); self.assertEqual(self.b['id'], response['journals'][0]['company_id'])
        self.assertEqual(1, len(self.core.journals(self.a['id'])))
        self.assertEqual(1, len(self.core.journals(self.b['id'])))

    def test_bookkeeping_date_independent_from_issue_and_stale_year(self):
        model = self.model(); doc = self.sale(day='2026-12-02', issue_date='2026-10-30')
        result = self.generate([doc], model)
        self.assertEqual('2026-12-02', result['journals'][0]['date'])
        self.assertEqual('2026-12', result['journals'][0]['period'])
        self.assertEqual('2026-10-30', result['sources'][0]['issue_date'])
        other = self.sale('YEAR')
        self.post('/exercises', {'module': 'fiscal', 'year': 2027}, 201)
        self.activate(self.a['id'], '2027-01')
        self.generate([other], model, 'wrong-year', status=409)

    def test_report_is_readonly_with_filters_and_mode_changes(self):
        model = self.model(); docs = [self.sale('F1'), self.sale('F2'), self.sale('F3', day='2026-11-07')]
        result = self.generate(docs, model)
        self.assertEqual(3, result['created_count'])
        before = self.snapshot()
        path = '/business-reports/consolidated-diary?start=2026-11-06&end=2026-11-06'
        for _ in range(2):
            response = self.client.get(self.scope(path)); self.assertEqual(200, response.status_code, response.text)
            report = response.json(); self.assertEqual(2, len(report['rows']))
            self.assertEqual(20000, report['totals']['debit_cents'])
            self.assertEqual(2, len(report['rows'][0]['journal_ids']))
        self.assertEqual(before, self.snapshot())
        self.mode()
        self.assertEqual(3, len(self.core.journals(self.a['id'])))
        filtered = self.client.get(self.scope(path + '&account_id=' + str(self.aid['3']))).json()
        self.assertEqual(1, len(filtered['rows']))
        self.assertEqual(20000, filtered['rows'][0]['debit_cents'])
        empty = self.client.get(self.scope(path.replace('2026-11-06', '2026-11-20'))).json()
        self.assertEqual([], empty['rows'])

    def test_malformed_selection_and_incoming_rejected_without_writes(self):
        model = self.model(); doc = self.sale(); payload = self.payload([doc], model)
        before = self.snapshot()
        variants = [payload | {'entries': []}, payload | {'entries': [None]},
                    payload | {'entries': payload['entries'] * 2}, payload | {'unexpected': True},
                    payload | {'entries': [payload['entries'][0] | {'lines': []}]}]
        for bad in variants:
            self.post(ROOT + '/generate', bad, 400)
            self.assertEqual(before, self.snapshot())
        incoming = self.post('/documents', self.document('INCOMING'), 201)
        self.generate([incoming], model, status=400)

    def operator(self, permissions):
        with self.core.db.transaction() as conn:
            uid = insert_id(conn,"INSERT INTO users(username,password_hash,created_at,role,active) VALUES(?,?,?,'operator',1)",('sales-operator', self.core._password_hash('Synthetic-password-456!'), '2026-11-01'))
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)', (uid, self.a['id']))
            for routine, actions in permissions.items():
                for action in actions:
                    conn.execute('INSERT INTO user_permissions VALUES(?,?,?,?,?)', (uid, self.a['id'], routine, action, 'allow'))
        client = TestClient(self.app)
        r = client.post('/api/login', json={'username': 'sales-operator', 'password': 'Synthetic-password-456!'})
        self.assertEqual(200, r.status_code, r.text); client.headers['X-CSRF-Token'] = r.json()['csrf_token']
        self.activate(self.a['id'], client=client)
        return client, uid

    def test_permissions_revalidated_for_configuration_generation_and_trace(self):
        model = self.model(); doc = self.sale(); payload = self.payload([doc], model)
        client, uid = self.operator({'accounting.journals': ['read', 'create'], 'fiscal.documents': ['read']})
        try:
            self.assertEqual(403, client.get(self.scope(ROOT + '/settings')).status_code)
            self.assertEqual(403, client.post(self.scope(ROOT + '/generate'), json=payload).status_code)
            with self.core.db.transaction() as conn:
                conn.execute('INSERT INTO user_permissions VALUES(?,?,?,?,?)', (uid, self.a['id'], 'accounting.histories', 'read', 'allow'))
            response = client.post(self.scope(ROOT + '/generate'), json=payload)
            self.assertEqual(200, response.status_code, response.text)
            jid = response.json()['journals'][0]['id']
            self.assertEqual(200, client.get(self.scope(ROOT + f'/journals/{jid}/sources')).status_code)
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND routine='accounting.histories'", (uid,))
            limited = client.get(self.scope(ROOT + f'/journals/{jid}/sources')).json()
            self.assertNotIn('model_snapshot', limited['sources'][0])
            limited_doc = client.get(self.scope(f"/documents/{doc['id']}/trace")).json()
            self.assertNotIn('model_snapshot', limited_doc['accounting_sources'][0])
            self.assertEqual(403, client.post(self.scope(ROOT + '/generate'), json=payload).status_code)
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE user_permissions SET effect='deny' WHERE user_id=? AND routine='fiscal.documents'", (uid,))
            self.assertEqual(403, client.post(self.scope(ROOT + '/generate'), json=payload).status_code)
            self.assertEqual(403, client.get(self.scope(ROOT + f'/journals/{jid}/sources')).status_code)
            trace = client.get(self.scope(f"/documents/{doc['id']}/trace"))
            self.assertEqual(403, trace.status_code)
        finally:
            client.close()

    def test_partial_reversal_needs_reverse_permission_only_and_allows_inactive_accounts(self):
        self.mode(); model = self.model(); doc = self.sale()
        self.generate([doc], model)
        doc = self.core.documents(self.a['id'])[0]
        client, _ = self.operator({'accounting.journals': ['read', 'reverse'], 'fiscal.documents': ['read', 'reverse']})
        try:
            with self.core.db.transaction() as conn:
                conn.execute('UPDATE accounts SET active=0 WHERE company_id=? AND id IN (?,?)', (self.a['id'], self.aid['3'], self.aid['5']))
            response = client.post(self.scope(f"/documents/{doc['id']}/reverse"), json={
                'version': doc['version'], 'date': '2026-11-09', 'reason': 'Teste', 'idempotency_key': 'reverse-only'})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(10000, response.json()['journal']['total_cents'])
        finally:
            client.close()
    def test_participants_are_independent_accounting_dimensions(self):
        self.mode(); model = self.model()
        parties = [self.post('/masters/participant', {'code': 'P' + str(i), 'name': 'Cliente sintético', 'tax_id': '', 'data': {}}, 201)['id'] for i in (1, 2)]
        docs = [self.sale('PARTY' + str(i), participant_id=p) for i, p in enumerate((parties[0], parties[0], parties[1]))]
        result = self.generate(docs, model)
        self.assertEqual(2, result['created_count'])
        self.assertEqual(set(parties), {line['participant_id'] for j in result['journals'] for line in j['lines']})
        self.assertEqual([10000, 20000], sorted(j['total_cents'] for j in result['journals']))

    def test_configured_global_plan_and_own_fork_preserve_account_ids(self):
        import test_global_account_plans as plans
        plan, _, _ = plans.GlobalAccountPlanTests.publish(self)
        cid = self.b['id']; self.activate(cid)
        preview = self.post(f"/global-account-plans/{plan['id']}/preview", {'mode': 'shared'}, cid=cid)
        self.post(f"/global-account-plans/previews/{preview['id']}/confirm", {
            'preview_hash': preview['preview_hash'], 'properties_reviewed': True, 'reason': 'Teste'}, cid=cid)
        model = self.model('GLOBAL', debit='00101', credit='00102', cid=cid)
        self.mode(cid=cid)
        docs = [self.sale('GLOBAL1', cid=cid), self.sale('GLOBAL2', cid=cid)]
        result = self.post(ROOT + '/generate', self.payload(docs, model, version=1), cid=cid)
        self.assertEqual(1, result['created_count'])
        accounts = {x['account_id'] for x in result['journals'][0]['lines']}
        self.assertTrue(all(x > 0 for x in accounts))
        binding = self.client.get(self.scope('/global-account-plans', cid)).json()['binding']
        self.post('/global-account-plans/binding/detach', {'version': binding['version'], 'reason': 'Teste', 'copy_scope': 'used'}, cid=cid)
        self.assertEqual(accounts, {x['account_id'] for x in self.core.journals(cid)[0]['lines']})
        self.assertEqual(1, len(self.core.journals(cid)))

    def test_new_integration_honors_closure_with_permissive_legacy_setting(self):
        model = self.model(); doc = self.sale()
        from app.operational_settings import save_settings
        with self.core.db.transaction() as conn:
            old = conn.execute('SELECT version FROM company_operational_settings WHERE company_id=?', (self.a['id'],)).fetchone()
            save_settings(conn, self.a['id'], {'version': old['version'], 'settings': {'enforce_period_locks': False}}, 'test')
        self.post('/periods/close', {'module': 'accounting', 'period': '2026-11', 'reason': 'Teste'})
        self.generate([doc], model, status=409)
        self.post('/periods/reopen', {'module': 'accounting', 'period': '2026-11', 'reason': 'Teste'})
        self.generate([doc], model)
        self.post('/periods/close', {'module': 'fiscal', 'period': '2026-11', 'reason': 'Teste'})
        self.reverse(self.core.documents(self.a['id'])[0], status=409)

    def test_stale_context_headers_and_session_change_cannot_write(self):
        model = self.model(); doc = self.sale(); payload = self.payload([doc], model)
        for header, value in [('X-Company-Id', str(self.b['id'])), ('X-Year', '2025'), ('X-Module', 'accounting')]:
            response = self.client.post(self.scope(ROOT + '/generate'), json=payload, headers={header: value})
            self.assertEqual(409, response.status_code, response.text)
        self.assertEqual([], self.core.journals(self.a['id']))
        # The same transaction guard protects a queued request after a context switch.
        from app.db import request_context
        from app.core import digest
        cookie = self.client.cookies.get('escritura_session')
        token = request_context.set({'token_hash': digest(cookie.encode()), 'company_id': self.b['id'],
            'period': '2026-11', 'module': 'fiscal'})
        try:
            with self.assertRaises(ContextConflict):
                self.core.generate_sales_accounting(self.a['id'], payload, 'test')
        finally:
            request_context.reset(token)
        self.assertEqual([], self.core.journals(self.a['id']))

    def test_generated_journal_link_prevents_partial_bulk_deletion(self):
        self.mode(); model = self.model(); docs = [self.sale('DEL1'), self.sale('DEL2')]
        result = self.generate(docs, model)
        from app.bulk_operations import BulkOperations
        bulk = BulkOperations(self.core)
        with self.core.db.read() as conn:
            uid = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        preview = bulk.preview(self.a['id'], {'kind': 'documents', 'action': 'delete', 'period': '2026-11',
            'ids': [docs[0]['id']], 'include_linked_journals': True}, uid, 'test')
        self.assertFalse(preview['can_confirm'])
        self.assertTrue(any(b['code'] == 'dependent_records' for b in preview['blockers']))
        self.assertEqual(1, len(self.core.journals(self.a['id'])))

    def test_import_replay_reprocess_and_package_cleanup_preserve_accounting(self):
        import base64
        from pathlib import Path
        self.mode(); model = self.model()
        # The committed fixture is entirely fictional; make this test company its issuer.
        raw = (Path(__file__).parent / 'fixtures/nfe_ficticia.xml').read_bytes()
        raw = raw.replace(b'87654321000198', self.a['tax_id'].encode()).replace(b'<tpAmb>2</tpAmb>', b'<tpAmb>1</tpAmb>')
        batch = self.post('/imports/preview', {'filename': 'synthetic-sales.xml', 'period': '2026-11', 'content_base64': base64.b64encode(raw).decode()})
        options = {'document_overrides': {'documents:0': {'posting_date': '2026-11-06', 'cfop': '5102'}}}
        prepared = self.post(f"/imports/{batch['id']}/posting-preview", options)
        confirmation = {'posting_mode': 'book', 'posting_hash': prepared['posting_hash'], 'preview_hash': batch['preview_hash'], 'selected': ['documents:0'], **options}
        self.post(f"/imports/{batch['id']}/confirm", confirmation)
        doc = self.core.documents(self.a['id'])[0]
        self.assertEqual('outgoing', doc['direction']); self.assertEqual('booked', doc['status'])
        self.generate([doc], model)
        before = self.core.journals(self.a['id'])
        self.assertTrue(self.post(f"/imports/{batch['id']}/confirm", confirmation)['duplicate'])
        reprocess = self.post(f"/imports/{batch['id']}/reprocess-preview", {})
        self.assertFalse(reprocess['can_confirm'])
        self.post(f"/imports/{batch['id']}/reprocess-confirm", {'reprocess_hash': reprocess['reprocess_hash'],
            'idempotency_key': 'blocked-reprocess', 'reason': 'Teste'}, 409)
        self.assertEqual(before, self.core.journals(self.a['id']))
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE imports SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (batch['id'],))
        cleanup = self.post('/import-packages/cleanup-preview', {'ids': [batch['id']], 'mode': 'originals_and_hide_history'})
        result = self.post('/import-packages/cleanup-confirm', {'ids': cleanup['ids'], 'mode': cleanup['mode'],
            'preview_hash': cleanup['preview_hash'], 'acknowledge_irreversible': True})
        self.assertTrue(result['movements_preserved'])
        self.assertEqual(before, self.core.journals(self.a['id']))
        trace = self.client.get(self.scope(f"/documents/{doc['id']}/trace")).json()
        self.assertEqual(1, len(trace['accounting_sources']))
        self.assertEqual(0, self.generate([doc], model, 'after-cleanup')['created_count'])
        with self.core.db.read() as conn:
            self.assertFalse(check_foreign_keys(conn))
    def test_existing_titles_unchanged_and_reversal_cancels_only_own_titles(self):
        self.mode(); model = self.model()
        doc = self.post('/documents', self.document('TITLE') | {'direction': 'outgoing', 'cfop': '5102'}, 201)
        doc = self.post(f"/documents/{doc['id']}/review", {'version': doc['version'], 'reason': 'Teste'})
        doc = self.post(f"/documents/{doc['id']}/book", {'version': doc['version'], 'reason': 'Teste',
            'generate_titles': True, 'installments': [{'due_date': '2026-12-06', 'amount': '100.00'}]})['document']
        other = self.sale('WITHOUT-TITLE')
        titles = self.core.titles(self.a['id'])
        result = self.generate([doc, other], model)
        self.assertEqual(titles, self.core.titles(self.a['id']))
        self.assertEqual(1, result['created_count'])
        self.reverse(next(d for d in self.core.documents(self.a['id']) if d['id'] == doc['id']))
        self.assertTrue(self.core.titles(self.a['id'])[0]['cancelled'])
        remaining = next(d for d in self.core.documents(self.a['id']) if d['id'] == other['id'])
        self.assertEqual(result['journals'][0]['id'], remaining['journal_id'])

    def test_deleted_generated_movements_cannot_replay_as_success(self):
        self.mode(); model = self.model(); docs = [self.sale('DELETE1'), self.sale('DELETE2')]
        payload = self.payload(docs, model); result = self.post(ROOT + '/generate', payload)
        from app.bulk_operations import BulkOperations
        bulk = BulkOperations(self.core)
        with self.core.db.read() as conn:
            uid = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
        preview = bulk.preview(self.a['id'], {'kind': 'documents', 'action': 'delete', 'period': '2026-11',
            'ids': [d['id'] for d in docs], 'include_linked_journals': True}, uid, 'test')
        self.assertTrue(preview['can_confirm'], preview)
        bulk.confirm(self.a['id'], {'preview_id': preview['id'], 'preview_hash': preview['preview_hash'],
            'irreversible_acknowledged': True, 'reason': 'Exclusão sintética explícita'}, uid, 'test')
        self.assertEqual([], self.core.journals(self.a['id']))
        response = self.post(ROOT + '/generate', payload, 409)
        self.assertEqual('movement_deleted', response['code'])
        with self.core.db.read() as conn:
            self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM audit WHERE action='sales-accounting-source'").fetchone()[0])

    def test_missing_source_contribution_cannot_reverse_whole_shared_journal(self):
        self.mode(); model = self.model(); docs = [self.sale('EVIDENCE1'), self.sale('EVIDENCE2')]
        self.generate(docs, model)
        # Deliberately corrupt only this synthetic database to test fail-closed behavior.
        with self.core.db.transaction() as conn:
            conn.execute("DELETE FROM audit WHERE action='sales-accounting-source' AND entity_id=?", (str(docs[0]['id']),))
        doc = next(d for d in self.core.documents(self.a['id']) if d['id'] == docs[0]['id'])
        before = self.snapshot()
        response = self.reverse(doc, status=409)
        self.assertEqual('source_evidence_missing', response['code'])
        self.assertEqual(before, self.snapshot())

    def test_unexpected_existing_journal_key_cannot_attach_new_sources(self):
        from app.core import digest
        model = self.model(); doc = self.sale()
        payload = self.payload([doc], model)
        key = 'sales:' + digest([payload['idempotency_key'], str(doc['id'])])
        self.core.create_journal(self.a['id'], self.journal(key=key) | {
            'document': 'SAIDAS-FISCAIS', 'history': 'Integração contábil de saídas fiscais.'}, 'test')
        before = self.snapshot()
        self.post(ROOT + '/generate', payload, 409)
        self.assertEqual(before, self.snapshot())
        self.assertIsNone(self.core.documents(self.a['id'])[0]['journal_id'])
    def test_real_xml_tax_paths_and_sped_cst_rate_classifications_stay_separate(self):
        self.mode(); model = self.model()
        common = {'cfop': '5102', 'ncm': '99999999'}
        docs = [self.sale('XML-CST00', items=[common | {'taxes': {'ICMS/ICMS00/CST': '00', 'ICMS/ICMS00/pICMS': '18.00'}}]),
                self.sale('XML-CST20', items=[common | {'taxes': {'ICMS/ICMS20/CST': '20', 'ICMS/ICMS20/pICMS': '18.00'}}]),
                self.sale('XML-RATE12', items=[common | {'taxes': {'ICMS/ICMS00/CST': '00', 'ICMS/ICMS00/pICMS': '12.00'}}]),
                self.sale('SPED-CST000', analytics=[{'cfop': '5102', 'cst_icms': '000', 'rate': '18.00', 'operation_total': '100.00'}]),
                self.sale('SPED-CST020', analytics=[{'cfop': '5102', 'cst_icms': '020', 'rate': '18.00', 'operation_total': '100.00'}])]
        result = self.generate(docs, model)
        self.assertEqual(5, result['created_count'])
        classes = [s['classification']['item_classifications'][0] for s in result['sources']]
        self.assertEqual({'00', '20', '000', '020'}, {c['cst_icms'] for c in classes})
        self.assertEqual({'12.00', '18.00'}, {c['rate'] for c in classes})

    def test_declared_pis_and_ibs_classifications_are_not_lost_in_grouping(self):
        self.mode(); model = self.model()
        docs = [self.sale('TAXCLASS' + str(i), items=[{'cfop': '5102', 'ncm': '99999999', 'taxes': taxes}])
                for i, taxes in enumerate(({'PIS/PISAliq/CST': '01'}, {'PIS/PISNT/CST': '04'},
                    {'IBSCBS/cClassTrib': '000001'}, {'IBSCBS/cClassTrib': '000002'}))]
        result = self.generate(docs, model)
        self.assertEqual(4, result['created_count'])
        self.assertTrue(all(s['classification']['item_classifications'][0]['declared_tax_classifications'] for s in result['sources']))


if __name__ == '__main__':
    unittest.main()
