"""Testes de invariantes do domínio e da fronteira HTTP; dados sintéticos."""
import base64
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import DomainError, cnpj_digits, digest, money, normalize_cnpj
from app.db import ContextConflict, request_context


class CoreApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.core = self.app.state.core
        self.client = TestClient(self.app)
        response = self.client.post('/api/setup', json={'username': 'teste', 'password': 'Senha-ficticia-123!'} )
        self.assertEqual(200, response.status_code, response.text)
        self.client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        self.a = self.create_company('TESTE001', 'TEST00010001')
        self.b = self.create_company('TESTE002', 'TEST00020001')
        self.activate(self.a['id'])
        self.accounts = self.client.get(self.scope('/accounts')).json()
        self.aid = {x['access_code']: x['id'] for x in self.accounts}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def scope(self, path, cid=None):
        return f"/api/companies/{cid or self.a['id']}{path}"

    def activate(self, cid, period='2026-11', client=None):
        response = (client or self.client).post('/api/context', json={'company_id': cid, 'period': period})
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def create_company(self, code, base):
        response = self.client.post('/api/companies', json={'code': code, 'name': f'{code} (dados fictícios)', 'tax_id': base + cnpj_digits(base), 'regime': 'outros', 'state': 'SP', 'create_default_accounts': True})
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def journal(self, key='test-journal', amount='123.45', day='2026-11-06', center=None):
        return {'date': day, 'document': 'FICTÍCIO-001', 'history': 'Partida sintética de teste', 'idempotency_key': key, 'lines': [{'account_id': self.aid['3'], 'debit': amount, 'credit': '0.00', 'cost_center_id': center}, {'account_id': self.aid['5'], 'debit': '0.00', 'credit': amount}]}

    def document(self, number='TEST-DOC'):
        return {'direction': 'incoming', 'number': number, 'series': '1', 'model': '55', 'issue_date': '2026-10-30', 'posting_date': '2026-11-06', 'partner_name': 'Fornecedor fictício', 'partner_tax_id': '', 'key': '', 'cfop': '1102', 'total': '100.00', 'taxes': {'declared_example': '0.00'}, 'items': [], 'source': {'file': 'origem-ficticia.xml'}, 'source_hash': 'abc123'}

    def title(self, amount='100.00', kind='payable'):
        payload = {'kind': kind, 'description': 'Título fictício', 'partner_name': 'Parceiro fictício', 'document': 'T-TESTE', 'issue_date': '2026-11-06', 'due_date': '2026-12-10', 'amount': amount}
        r = self.client.post(self.scope('/titles'), json=payload)
        self.assertEqual(201, r.status_code, r.text)
        return r.json()

    def test_cnpj_alpha_numeric_and_money_exactness(self):
        self.assertEqual('11222333000181', normalize_cnpj('11.222.333/0001-81'))
        self.assertEqual('12ABC34501DE35', normalize_cnpj('12.abc.345/01de-35'))
        for invalid in ['00000000000000', '11222333000180', '12@BC34501DE35', '१२ABC34501DE35']:
            with self.assertRaises(DomainError):
                normalize_cnpj(invalid)
        self.assertEqual(12345, money('123.4500'))
        self.assertEqual(-123, money('-1.23', signed=True))
        for invalid in [0.1, '1,23', 'NaN', '1e3', '1.001', True]:
            with self.assertRaises(DomainError):
                money(invalid)

    def test_authentication_csrf_setup_and_origin(self):
        other = TestClient(self.app)
        self.assertEqual(401, other.get('/api/companies').status_code)
        self.assertFalse(other.get('/api/session').json()['authenticated'])
        self.assertEqual(404, other.post('/api/demo-login').status_code)
        self.assertEqual(409, other.post('/api/setup', json={'username': 'novo', 'password': 'Senha-nova-12345!'}).status_code)
        self.assertEqual(403, self.client.post('/api/context', headers={'X-CSRF-Token': ''}, json={'company_id': self.b['id'], 'period': '2026-11'}).status_code)
        self.assertEqual(403, other.post('/api/login', headers={'Origin': 'https://foreign.invalid'}, json={'username': 'teste', 'password': 'Senha-ficticia-123!'}).status_code)
        self.assertEqual(200, self.client.post('/api/logout').status_code)
        self.assertEqual(401, self.client.get('/api/companies').status_code)
        other.close()

    def test_edit_a_while_b_active_keeps_context_and_optimistic_version(self):
        self.activate(self.b['id'])
        payload = self.a | {'name': 'Empresa A editada (fictícia)', 'city': 'Cidade de teste'}
        result = self.client.put(f"/api/companies/{self.a['id']}", json=payload)
        self.assertEqual(200, result.status_code, result.text)
        self.assertEqual(2, result.json()['version'])
        self.assertEqual(self.b['id'], self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual(409, self.client.put(f"/api/companies/{self.a['id']}", json=payload).status_code)
        self.assertEqual(self.a['id'], result.json()['id'])
        duplicate = self.client.post('/api/companies', json=self.a | {'code': 'NEW'})
        self.assertEqual(409, duplicate.status_code)

    def test_session_context_is_independent_and_stale_modal_blocked(self):
        other = TestClient(self.app)
        response = other.post('/api/login', json={'username': 'teste', 'password': 'Senha-ficticia-123!'})
        other.headers['X-CSRF-Token'] = response.json()['csrf_token']
        self.activate(self.b['id'], client=other)
        self.assertEqual(self.a['id'], self.client.get('/api/session').json()['active_company_id'])
        self.assertEqual(409, other.post(self.scope('/journals'), json=self.journal()).status_code)
        self.assertEqual(201, self.client.post(self.scope('/journals'), json=self.journal()).status_code)
        self.activate(self.b['id'])
        self.assertEqual(409, self.client.post(self.scope('/journals'), json=self.journal('stale')).status_code)
        self.assertEqual(0, len(self.client.get(self.scope('/journals', self.b['id'])).json()))
        other.close()

    def test_transaction_rechecks_session_after_context_change(self):
        token = self.client.cookies['escritura_session']
        guard = request_context.set({'token_hash': digest(token.encode()), 'company_id': self.a['id'], 'period': '2026-11'})
        try:
            # Simulate a request authenticated before another browser tab changed context.
            with self.app.state.db.read() as conn:
                conn.execute('UPDATE sessions SET active_company_id=? WHERE token_hash=?', (self.b['id'], digest(token.encode())))
            with self.assertRaises(ContextConflict):
                self.core.create_journal(self.a['id'], self.journal(), 'teste')
        finally:
            request_context.reset(guard)
        self.assertEqual([], self.core.journals(self.a['id'], '2026-11'))

    def test_company_and_period_isolation_for_journals(self):
        other_accounts = self.client.get(self.scope('/accounts', self.b['id'])).json()
        data = self.journal()
        data['lines'][0]['account_id'] = other_accounts[0]['id']
        self.assertEqual(404, self.client.post(self.scope('/journals'), json=data).status_code)
        self.assertEqual(409, self.client.post(self.scope('/journals'), json=self.journal(day='2025-10-31')).status_code)
        center = self.core.save_cost_center(self.b['id'], {'code': 'B', 'name': 'CC outra empresa'}, 'teste')
        self.assertEqual(404, self.client.post(self.scope('/journals'), json=self.journal(center=center['id'])).status_code)
        self.assertEqual([], self.core.journals(self.a['id'], '2026-11'))

    def test_journal_balance_idempotency_conflict_and_concurrency(self):
        unbalanced = self.journal()
        unbalanced['lines'][1]['credit'] = '123.44'
        self.assertEqual(400, self.client.post(self.scope('/journals'), json=unbalanced).status_code)
        payload = self.journal()
        r = self.client.post(self.scope('/journals'), json=payload)
        self.assertEqual(201, r.status_code, r.text)
        again = self.client.post(self.scope('/journals'), json=payload)
        self.assertEqual(r.json()['id'], again.json()['id'])
        self.assertTrue(again.json()['duplicate'])
        self.assertEqual(409, self.client.post(self.scope('/journals'), json=self.journal(amount='125.00')).status_code)
        # Two concurrent callers cannot produce duplicate journals with the same key.
        concurrent = self.journal('concurrent')
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: self.core.create_journal(self.a['id'], concurrent, 'teste'), range(2)))
        self.assertEqual(values[0]['id'], values[1]['id'])
        self.assertEqual(2, len(self.core.journals(self.a['id'], '2026-11')))

    def test_independent_period_locks_and_reopen(self):
        created = self.client.post(self.scope('/journals'), json=self.journal()).json()
        lock = {'period': '2026-11', 'module': 'accounting', 'reason': 'Conferência de teste'}
        r = self.client.post(self.scope('/periods/close'), json=lock)
        self.assertEqual(200, r.status_code, r.text)
        self.assertTrue(r.json()['accounting']['closed'])
        self.assertFalse(r.json()['fiscal']['closed'])
        self.assertEqual(409, self.client.post(self.scope('/journals'), json=self.journal('closed')).status_code)
        # The original duplicate operation remains idempotent after close.
        self.assertEqual(created['id'], self.client.post(self.scope('/journals'), json=self.journal()).json()['id'])
        doc = self.client.post(self.scope('/documents'), json=self.document())
        self.assertEqual(201, doc.status_code, doc.text)
        fiscal = lock | {'module': 'fiscal'}
        self.assertEqual(409, self.client.post(self.scope('/periods/close'), json=fiscal).status_code)
        self.assertEqual(200, self.client.post(self.scope('/periods/reopen'), json=lock).status_code)
        self.assertEqual(201, self.client.post(self.scope('/journals'), json=self.journal('reopened')).status_code)

    def test_fiscal_edit_invalidates_review_preserves_origin_and_books_explicitly(self):
        response = self.client.post(self.scope('/documents'), json=self.document())
        self.assertEqual(201, response.status_code, response.text)
        doc = response.json()
        self.assertEqual('2026-10-30', doc['issue_date'])
        review = self.client.post(self.scope(f"/documents/{doc['id']}/review"), json={'version': 1, 'reason': 'Conferência humana fictícia'})
        self.assertEqual(200, review.status_code, review.text)
        edited = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': 2, 'reason': 'Correção conferida', 'cfop': '1101', 'source_hash': 'tamper', 'source': {}})
        self.assertEqual(200, edited.status_code, edited.text)
        self.assertEqual('pending', edited.json()['status'])
        self.assertEqual('abc123', edited.json()['source_hash'])
        self.assertEqual('origem-ficticia.xml', edited.json()['source']['file'])
        self.assertEqual(409, self.client.post(self.scope(f"/documents/{doc['id']}/book"), json={'version': 3, 'reason': 'Ainda não revisado'}).status_code)
        reviewed = self.client.post(self.scope(f"/documents/{doc['id']}/review"), json={'version': 3, 'reason': 'Nova conferência'}).json()
        booked = self.client.post(self.scope(f"/documents/{doc['id']}/book"), json={'version': reviewed['version'], 'reason': 'Escrituração explicitamente fiscal'})
        self.assertEqual(200, booked.status_code, booked.text)
        self.assertIsNone(booked.json()['journal'])
        self.assertEqual([], self.core.journals(self.a['id'], '2026-11'))
        correction = self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': 5, 'reason': 'Correção posterior rastreável', 'cfop': '1102'})
        self.assertEqual(200, correction.status_code, correction.text)
        self.assertEqual('booked', correction.json()['status'])
        self.assertEqual('abc123', correction.json()['source_hash'])
        closed = self.client.post(self.scope('/periods/close'), json={'period': '2026-11', 'module': 'fiscal', 'reason': 'Fim da conferência'})
        self.assertEqual(200, closed.status_code, closed.text)
        self.assertEqual(409, self.client.put(self.scope(f"/documents/{doc['id']}"), json={'version': correction.json()['version'], 'reason': 'Competência fechada', 'cfop': '1101'}).status_code)
        self.assertEqual(409, self.client.post(self.scope('/documents'), json=self.document('OUTRO')).status_code)
        self.assertEqual(201, self.client.post(self.scope('/journals'), json=self.journal()).status_code)

    def test_fiscal_accounting_integration_rolls_back_on_closed_accounting(self):
        doc = self.client.post(self.scope('/documents'), json=self.document()).json()
        reviewed = self.client.post(self.scope(f"/documents/{doc['id']}/review"), json={'version': 1, 'reason': 'Revisado'}).json()
        self.client.post(self.scope('/periods/close'), json={'period': '2026-11', 'module': 'accounting', 'reason': 'Fechado'})
        book = self.client.post(self.scope(f"/documents/{doc['id']}/book"), json={'version': reviewed['version'], 'reason': 'Com contabilização', 'lines': self.journal(amount='100.00')['lines']})
        self.assertEqual(409, book.status_code)
        self.assertEqual('reviewed', self.core.documents(self.a['id'], '2026-11')[0]['status'])
        self.assertEqual([], self.core.journals(self.a['id'], '2026-11'))

    def test_reports_opening_center_filter_and_reversal_preserve_history(self):
        center = self.client.post(self.scope('/cost-centers'), json={'code': 'ADM', 'name': 'Administrativo fictício'}).json()
        self.core.create_journal(self.a['id'], self.journal('opening', '100.00', '2026-10-30'), 'teste')
        doc = self.client.post(self.scope('/journals'), json=self.journal('november', '25.50', center=center['id'])).json()
        report = self.client.get(self.scope('/reports/trial-balance?period=2026-11')).json()
        clients = next(x for x in report['rows'] if x['account_id'] == self.aid['3'])
        self.assertEqual((10000, 2550, 12550), (clients['opening_cents'], clients['debit_cents'], clients['closing_cents']))
        filtered = self.client.get(self.scope(f"/reports/diary?period=2026-11&cost_center_id={center['id']}")).json()
        self.assertEqual(1, len(filtered['rows']))
        self.assertEqual({'debit_cents': 2550, 'credit_cents': 0}, filtered['totals'])
        reverse = self.client.post(self.scope(f"/journals/{doc['id']}/reverse"), json={'date': '2026-11-07', 'reason': 'Estorno de teste', 'idempotency_key': 'reverse-test'})
        self.assertEqual(200, reverse.status_code, reverse.text)
        diary = self.client.get(self.scope('/reports/diary?period=2026-11')).json()
        self.assertEqual(4, len(diary['rows']))
        self.assertEqual(5100, diary['totals']['debit_cents'])
        ledger = self.client.get(self.scope(f"/reports/ledger?period=2026-11&account_id={self.aid['3']}")).json()
        self.assertEqual(10000, ledger['totals']['closing_cents'])
        self.assertEqual(10000, ledger['rows'][-1]['balance_cents'])
        self.assertEqual([], self.client.get(self.scope('/reports/diary?period=2026-11', self.b['id'])).json()['rows'])

    def test_title_partial_settlement_overpayment_and_accounting_atomicity(self):
        title = self.title()
        payload = {'date': '2026-11-06', 'amount': '40.00', 'reason': 'Baixa fictícia', 'idempotency_key': 'settle-1'}
        response = self.client.post(self.scope(f"/titles/{title['id']}/settle"), json=payload)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(6000, response.json()['title']['balance_cents'])
        self.assertEqual('partial', response.json()['title']['status'])
        repeated = self.client.post(self.scope(f"/titles/{title['id']}/settle"), json=payload)
        self.assertTrue(repeated.json()['duplicate'])
        self.assertEqual(409, self.client.post(self.scope(f"/titles/{title['id']}/settle"), json=payload | {'amount': '60.01', 'idempotency_key': 'too-much'}).status_code)
        self.client.post(self.scope('/periods/close'), json={'period': '2026-11', 'module': 'accounting', 'reason': 'Teste'})
        integrated = payload | {'amount': '60.00', 'idempotency_key': 'closed-settle', 'lines': self.journal(amount='60.00')['lines']}
        self.assertEqual(409, self.client.post(self.scope(f"/titles/{title['id']}/settle"), json=integrated).status_code)
        self.assertEqual(6000, self.core.titles(self.a['id'])[0]['balance_cents'])

    def test_rule_versions_memories_and_template_clone_are_drafts(self):
        rule = {'name': 'Parâmetro matemático fictício', 'tax': 'EXEMPLO', 'rate': '2.125', 'direction': 'both', 'cfop': '', 'ncm': '', 'valid_from': '2026-01-01', 'valid_to': '', 'source': 'Fonte declarada fictícia', 'responsible': 'Responsável de teste', 'status': 'validated'}
        response = self.client.post(self.scope('/rules'), json=rule)
        self.assertEqual(201, response.status_code, response.text)
        old = response.json()
        updated = self.client.put(self.scope(f"/rules/{old['id']}"), json={'version': 1, 'rate': '3.00'}).json()
        self.assertNotEqual(old['id'], updated['id'])
        self.assertEqual(2, updated['version'])
        self.assertEqual(2, len(self.client.get(self.scope(f"/rules/{old['id']}/versions")).json()))
        calc = self.client.post(self.scope(f"/rules/{old['id']}/simulate"), json={'date': '2026-11-06', 'base': '10.00'}).json()
        self.assertEqual(21, calc['result_cents'])
        self.assertTrue(calc['simulation'])
        self.assertFalse(calc['legal_validation'])
        template = self.client.post('/api/templates', json={'name': 'Modelo fictício', 'description': 'Teste', 'source_company_id': self.a['id'], 'rule_ids': [updated['id']]}).json()
        self.activate(self.b['id'])
        copied = self.client.post(self.scope(f"/templates/{template['id']}/apply", self.b['id']), json={'reason': 'Avaliação individual da empresa destino'})
        self.assertEqual(200, copied.status_code, copied.text)
        self.assertEqual('draft', copied.json()['rules'][0]['status'])
        self.assertEqual('', copied.json()['rules'][0]['responsible'])

    def test_whole_percent_rules_remain_editable_and_simulate_exactly(self):
        for raw, expected, base, cents in [('10.00', '10', '0.05', 1), ('100.000000', '100', '123.45', 12345)]:
            rule = self.client.post(self.scope('/rules'), json={'name': 'Percentual fictício ' + raw, 'tax': 'TESTE', 'rate': raw, 'valid_from': '2026-01-01', 'valid_to': '2026-12-31', 'status': 'draft'})
            self.assertEqual(201, rule.status_code, rule.text)
            item = rule.json()
            self.assertEqual(expected, item['rate'])
            edited = self.client.put(self.scope(f"/rules/{item['id']}"), json={'version': 1, 'name': 'Nome ajustado ' + raw})
            self.assertEqual(200, edited.status_code, edited.text)
            current = edited.json()
            simulation = self.client.post(self.scope(f"/rules/{current['id']}/simulate"), json={'date': '2026-11-06', 'base': base})
            self.assertEqual(200, simulation.status_code, simulation.text)
            self.assertEqual(cents, simulation.json()['result_cents'])
            self.assertTrue(simulation.json()['simulation'])
            self.assertFalse(simulation.json()['legal_validation'])
            invalid_date = self.client.post(self.scope(f"/rules/{current['id']}/simulate"), json={'date': '2027-01-01', 'base': base})
            self.assertEqual(400, invalid_date.status_code)
            deactivated = self.client.delete(self.scope(f"/rules/{current['id']}?version=2"))
            self.assertEqual(200, deactivated.status_code, deactivated.text)
            self.assertFalse(deactivated.json()['active'])
        self.assertEqual([], self.core.documents(self.a['id'], '2026-11'))
        self.assertEqual([], self.core.journals(self.a['id'], '2026-11'))
        # Preserve usability of an early development row without rewriting history.
        old = self.core.save_rule(self.a['id'], {'name': 'Representação anterior', 'tax': 'TESTE', 'rate': '10', 'valid_from': '2026-01-01'}, 'teste')
        with self.app.state.db.transaction() as conn:
            conn.execute('UPDATE rules SET rate=? WHERE id=?', ('1E+1', old['id']))
        self.assertEqual('10', next(r for r in self.core.rules(self.a['id']) if r['id'] == old['id'])['rate'])
        self.assertEqual('10', self.core.save_rule(self.a['id'], {'version': 1, 'name': 'Nome corrigido'}, 'teste', old['id'])['rate'])

    def test_import_preview_isolation_bank_confirmation_idempotency_and_reconciliation(self):
        title = self.title('100.00', 'payable')
        raw = b'Date,Amount,Description,Reference\n2026-11-06,-100.00,Pagamento ficticio,TEST-1\n'
        options = {'date_format': 'YMD', 'decimal_separator': '.', 'delimiter': ',', 'bank_columns': {'date': 'Date', 'amount': 'Amount', 'description': 'Description', 'reference': 'Reference'}}
        payload = {'filename': 'bank-test.csv', 'content_base64': base64.b64encode(raw).decode(), 'period': '2026-11', 'options': options}
        preview = self.client.post(self.scope('/imports/preview'), json=payload)
        self.assertEqual(200, preview.status_code, preview.text)
        data = preview.json()
        self.assertNotEqual('blocked', data['status'], data.get('issues'))
        self.assertEqual([], self.core.banks(self.a['id'], '2026-11'))
        self.assertEqual(400, self.client.post(self.scope(f"/imports/{data['id']}/confirm"), json={'preview_hash': data['preview_hash']}).status_code)
        request = {'preview_hash': data['preview_hash'], 'bank_account': 'Conta fictícia 001'}
        confirmed = self.client.post(self.scope(f"/imports/{data['id']}/confirm"), json=request)
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        self.assertEqual(1, confirmed.json()['transactions_created'])
        self.assertTrue(self.client.post(self.scope(f"/imports/{data['id']}/confirm"), json=request).json()['duplicate'])
        self.assertEqual(409, self.client.post(self.scope(f"/imports/{data['id']}/confirm"), json=request | {'bank_account': 'Outra conta'}).status_code)
        bank = self.core.banks(self.a['id'], '2026-11')[0]
        response = self.client.post(self.scope(f"/banks/{bank['id']}/reconcile"), json={'title_id': title['id'], 'reason': 'Conferência manual de teste'})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(409, self.client.post(self.scope(f"/banks/{bank['id']}/reconcile"), json={'title_id': title['id'], 'reason': 'Duplicado'}).status_code)
        self.assertEqual(10000, self.core.titles(self.a['id'])[0]['balance_cents'])
        self.activate(self.b['id'])
        self.assertEqual(404, self.client.post(self.scope(f"/imports/{data['id']}/confirm", self.b['id']), json=request).status_code)
        self.assertEqual([], self.core.banks(self.b['id'], '2026-11'))

    def test_import_errors_never_write_business_records(self):
        response = self.client.post(self.scope('/imports/preview'), json={'filename': 'broken.xml', 'content_base64': base64.b64encode(b'<bad>').decode(), 'period': '2026-11'})
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        self.assertEqual('blocked', data['status'])
        self.assertEqual(409, self.client.post(self.scope(f"/imports/{data['id']}/confirm"), json={'preview_hash': data['preview_hash']}).status_code)
        self.assertEqual([], self.core.documents(self.a['id'], '2026-11'))
        self.assertEqual([], self.core.banks(self.a['id'], '2026-11'))

    def test_xml_import_edit_review_and_integrated_post_preserve_original(self):
        target = self.create_company('XML-FICTICIO', '123456780001')
        cid = target['id']
        self.activate(cid)
        raw = (Path(__file__).parent / 'fixtures' / 'nfe_ficticia.xml').read_bytes()
        payload = {'filename': 'nfe-ficticia.xml', 'content_base64': base64.b64encode(raw).decode(), 'period': '2026-11', 'options': {'posting_date': '2026-11-06'}}
        preview = self.client.post(self.scope('/imports/preview', cid), json=payload)
        self.assertEqual(200, preview.status_code, preview.text)
        data = preview.json()
        self.assertEqual('preview', data['status'], data['issues'])
        result = self.client.post(self.scope(f"/imports/{data['id']}/confirm", cid), json={'preview_hash': data['preview_hash']})
        self.assertEqual(200, result.status_code, result.text)
        renamed = self.client.post(self.scope('/imports/preview', cid), json=payload | {'filename': 'mesmo-conteudo-renomeado.xml'}).json()
        repeated = self.client.post(self.scope(f"/imports/{renamed['id']}/confirm", cid), json={'preview_hash': renamed['preview_hash']})
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertEqual(1, repeated.json()['documents_duplicate'])
        self.assertEqual(0, repeated.json()['documents_created'])
        doc = self.core.documents(cid, '2026-11')[0]
        self.assertEqual('', doc['cfop'])
        self.assertEqual(['5102'], doc['source_cfops'])
        self.assertEqual('5102', doc['items'][0]['source_cfop'])
        self.assertEqual('18.00', doc['taxes']['ICMSTot/vICMS'])
        self.assertEqual('2026-11-05', doc['issue_date'])
        self.assertEqual('2026-11-06', doc['posting_date'])
        self.client.post(self.scope(f"/documents/{doc['id']}/review", cid), json={'version': 1, 'reason': 'Conferência inicial de teste'})
        blocked = self.client.post(self.scope(f"/documents/{doc['id']}/book", cid), json={'version': 2, 'reason': 'Falta classificar itens'})
        self.assertEqual(409, blocked.status_code)
        self.assertEqual('cfop_required', blocked.json()['code'])
        items = doc['items']
        items[0]['cfop'] = '1102'
        edited = self.client.put(self.scope(f"/documents/{doc['id']}", cid), json={'version': 2, 'reason': 'Classificação explicitamente conferida no teste', 'items': items})
        self.assertEqual(200, edited.status_code, edited.text)
        reviewed = self.client.post(self.scope(f"/documents/{doc['id']}/review", cid), json={'version': 3, 'reason': 'Nova conferência dos itens'})
        self.assertEqual(200, reviewed.status_code, reviewed.text)
        accounts = {r['access_code']: r['id'] for r in self.core.accounts(cid)}
        lines = [{'account_id': accounts['6'], 'debit': '100.00', 'credit': '0.00'}, {'account_id': accounts['4'], 'debit': '0.00', 'credit': '100.00'}]
        booked = self.client.post(self.scope(f"/documents/{doc['id']}/book", cid), json={'version': 4, 'reason': 'Integração explícita de teste', 'lines': lines, 'idempotency_key': 'xml-integrated'})
        self.assertEqual(200, booked.status_code, booked.text)
        self.assertEqual('booked', booked.json()['document']['status'])
        self.assertEqual(10000, booked.json()['journal']['total_cents'])
        self.assertEqual([], self.core.titles(cid))
        with self.app.state.db.read() as conn:
            stored = conn.execute('SELECT original,sha256 FROM imports WHERE id=?', (data['id'],)).fetchone()
            self.assertEqual(raw, stored['original'])
            self.assertEqual(digest(raw), stored['sha256'])

    def test_closed_fiscal_blocks_import_confirmation_atomically(self):
        target = self.create_company('XML-BLOQUEADO', '123456780001')
        cid = target['id']
        self.activate(cid)
        close_payload = {'period': '2026-11', 'module': 'fiscal', 'reason': 'Competência encerrada antes de importar'}
        raw = (Path(__file__).parent / 'fixtures' / 'nfe_ficticia.xml').read_bytes()
        preview = self.client.post(self.scope('/imports/preview', cid), json={'filename': 'nfe.xml', 'content_base64': base64.b64encode(raw).decode(), 'period': '2026-11'}).json()
        self.assertEqual(200, self.client.post(self.scope('/periods/close', cid), json=close_payload).status_code)
        confirm = self.client.post(self.scope(f"/imports/{preview['id']}/confirm", cid), json={'preview_hash': preview['preview_hash']})
        self.assertEqual(409, confirm.status_code, confirm.text)
        self.assertEqual('period_closed', confirm.json()['code'])
        self.assertEqual([], self.core.documents(cid, '2026-11'))
        self.assertEqual('preview', self.core.import_detail(cid, preview['id'])['status'])
        self.assertFalse(any(r['action'] == 'confirm' for r in self.core.audit(cid)))

    def test_default_is_empty_and_explicit_demo_is_fictional(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            client = TestClient(app)
            self.assertTrue(client.get('/api/session').json()['setup_required'])
            self.assertEqual([], app.state.core.companies())
            self.assertFalse(client.get('/api/health').json()['demo'])
            client.close()
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder, demo=True)
            client = TestClient(app)
            self.assertEqual(200, client.post('/api/demo-login').status_code)
            companies = client.get('/api/companies').json()
            self.assertEqual(2, len(companies))
            self.assertTrue(all('(demonstração)' in x['name'] and x['tax_id'].startswith('DEMO') for x in companies))
            self.assertEqual([], app.state.core.rules(companies[0]['id']))
            self.assertEqual([], app.state.core.catalogs(companies[0]['id']))
            client.close()


if __name__ == '__main__':
    unittest.main()
