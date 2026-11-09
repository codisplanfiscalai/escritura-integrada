"""Bulk safety invariants. All databases are synthetic TemporaryDirectory fixtures."""
import json
from unittest.mock import patch
from tests import test_core as fixtures
from app.bulk_operations import BulkOperations, initialize_bulk_schema
from app.core import DomainError


class BulkOperationsTests(fixtures.CoreApiTests):
    # Reuse fixture helpers, not the inherited unrelated test suite.
    def setUp(self):
        super().setUp()
        self.service = BulkOperations(self.core)
        with self.core.db.transaction() as conn:
            initialize_bulk_schema(conn)
            self.uid = conn.execute("SELECT id FROM users WHERE username='teste'").fetchone()[0]

    def doc(self, number='BULK'):
        return self.core.create_document(self.a['id'], self.document(number), 'teste')

    def preview(self, ids, kind='documents', action='delete', **extra):
        return self.service.preview(self.a['id'], {'kind': kind, 'action': action, 'period': '2026-11', 'ids': ids, **extra}, self.uid, 'teste')

    def confirm(self, preview, **overrides):
        return self.service.confirm(self.a['id'], {'preview_id': preview['id'], 'preview_hash': preview['preview_hash'], 'reason': 'Teste sintético autorizado', 'confirmation_phrase': preview['confirmation_phrase'], 'irreversible_acknowledged': True, **overrides}, self.uid, 'teste')

    def integrity(self):
        with self.core.db.read() as conn:
            self.assertEqual([], list(conn.execute('PRAGMA foreign_key_check')))
            self.assertEqual('ok', conn.execute('PRAGMA integrity_check').fetchone()[0])

    def test_bulk_delete_physical_atomic_idempotent(self):
        docs = [self.doc(str(i)) for i in range(2)]
        p = self.preview([d['id'] for d in docs])
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual(2, p['affected_counts']['document_sources'])
        self.assertTrue(self.confirm(p)['completed'])
        self.assertTrue(self.confirm(p)['duplicate'])
        self.assertEqual([], self.core.documents(self.a['id']))
        with self.core.db.read() as conn:
            self.assertEqual(0, conn.execute('SELECT count(*) FROM document_sources').fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT count(*) FROM audit WHERE action='bulk-delete'").fetchone()[0])
        self.integrity()

    def test_bulk_confirmation_expiry_identity_and_stale(self):
        d = self.doc()
        p = self.preview([d['id']])
        with self.assertRaises(DomainError): self.confirm(p, irreversible_acknowledged=False)
        with self.assertRaises(DomainError): self.confirm(p, preview_hash='wrong')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE documents SET version=version+1 WHERE id=?', (d['id'],))
        with self.assertRaises(DomainError) as raised: self.confirm(p)
        self.assertEqual('stale_preview', raised.exception.code)
        p = self.preview([d['id']])
        with patch('app.bulk_operations.time.time', return_value=p['expires_at'] + 1):
            with self.assertRaises(DomainError) as raised: self.confirm(p)
        self.assertEqual('preview_expired', raised.exception.code)
        with self.assertRaises(DomainError):
            self.service.confirm(self.b['id'], {'preview_id': p['id'], 'reason': 'teste'}, self.uid, 'teste')
        self.integrity()

    def test_bulk_closed_and_foreign_or_missing_selection(self):
        d = self.doc()
        self.core.set_period(self.a['id'], {'period': '2026-11', 'module': 'accounting', 'reason': 'Teste'}, 'teste', True)
        j = self.core.create_journal(self.a['id'], self.journal(day='2026-10-06'), 'teste')
        self.assertFalse(self.preview([j['id']], kind='journals')['can_confirm'])
        self.assertFalse(self.preview([d['id'], 999999])['can_confirm'])
        for ids in ([], [d['id'], d['id']], [True], list(range(1, 5002))):
            with self.assertRaises(DomainError): self.preview(ids)
        self.integrity()

    def test_bulk_financial_dependency_blocks_entire_batch(self):
        d, other = self.doc(), self.doc('OTHER')
        self.core.create_title(self.a['id'], {'kind': 'payable', 'description': 'Teste', 'partner_name': 'Teste', 'document': 'Teste', 'issue_date': '2026-11-01', 'due_date': '2026-11-05', 'amount': '10.00', 'document_id': d['id']}, 'teste')
        p = self.preview([d['id'], other['id']])
        self.assertFalse(p['can_confirm'])
        self.assertIn('titles.document_id', str(p['blockers']))
        with self.assertRaises(DomainError): self.confirm(p)
        self.assertEqual(2, len(self.core.documents(self.a['id'])))
        self.integrity()

    def test_bulk_review_book_no_implicit_effects(self):
        docs = [self.doc(str(i)) for i in range(2)]
        self.confirm(self.preview([d['id'] for d in docs], action='review'))
        self.confirm(self.preview([d['id'] for d in docs], action='book'))
        self.assertTrue(all(d['status'] == 'booked' for d in self.core.documents(self.a['id'])))
        with self.core.db.read() as conn:
            self.assertEqual(0, conn.execute('SELECT count(*) FROM journals').fetchone()[0])
            self.assertEqual(0, conn.execute('SELECT count(*) FROM titles').fetchone()[0])
        self.confirm(self.preview([d['id'] for d in docs]))
        self.integrity()

    def test_bulk_shared_consolidated_journal_explicit_only(self):
        d, other = self.doc(), self.doc('OTHER')
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE documents SET journal_id=?,status='booked' WHERE id IN (?,?)", (j['id'], d['id'], other['id']))
        self.assertFalse(self.preview([d['id'], other['id']])['can_confirm'])
        self.assertFalse(self.preview([d['id']], include_linked_journals=True)['can_confirm'])
        p = self.preview([d['id'], other['id']], include_linked_journals=True)
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual(1, p['affected_counts']['journals'])
        self.confirm(p)
        self.assertEqual([], self.core.journals(self.a['id']))
        self.integrity()

    def test_bulk_reversal_pair_requires_full_selection(self):
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        reversal = self.core.reverse_journal(self.a['id'], j['id'], {'date': '2026-11-07', 'reason': 'Teste', 'idempotency_key': 'reverse-test'}, 'teste')
        p = self.preview([j['id']], kind='journals')
        self.assertFalse(p['can_confirm'])
        p = self.preview([j['id'], reversal['id']], kind='journals')
        self.assertTrue(p['can_confirm'], p)
        self.confirm(p)
        self.integrity()

    def test_bulk_rollback_if_last_write_fails(self):
        docs = [self.doc(str(i)) for i in range(2)]
        self.confirm(self.preview([d['id'] for d in docs], action='review'))
        p = self.preview([d['id'] for d in docs], action='book')
        original = self.core._book_document
        calls = []
        def broken(*args):
            calls.append(1)
            if len(calls) == 2: raise DomainError('Falha sintética')
            return original(*args)
        with patch.object(self.core, '_book_document', side_effect=broken):
            with self.assertRaises(DomainError): self.confirm(p)
        self.assertTrue(all(d['status'] == 'reviewed' for d in self.core.documents(self.a['id'])))
        self.assertTrue(self.confirm(p)['completed'])
        self.integrity()

    def test_bulk_safe_update_and_forbidden_fields(self):
        d = self.doc()
        with self.assertRaises(DomainError): self.preview([d['id']], action='update', changes={'total': '500'})
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        self.confirm(self.preview([j['id']], kind='journals', action='update', changes={'history': 'Novo histórico'}))
        self.assertEqual('Novo histórico', self.core.journals(self.a['id'])[0]['history'])
        self.assertEqual(j['total_cents'], self.core.journals(self.a['id'])[0]['total_cents'])
        with self.core.db.read() as conn:
            event = json.loads(conn.execute("SELECT details_json FROM audit WHERE entity='journal' AND entity_id=? AND action='update'", (str(j['id']),)).fetchone()[0])
            self.assertEqual({'history': j['history']}, event['before'])
            self.assertEqual({'history': 'Novo histórico'}, event['after'])

        self.integrity()

    def test_bulk_replay_markers_and_tombstones_preserve_sources(self):
        payload = self.document() | {'idempotency_key': 'manual-key'}
        d = self.core.create_document(self.a['id'], payload, 'teste')
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE documents SET journal_id=?,status='booked' WHERE id=?", (j['id'], d['id']))
        p = self.preview([d['id']], include_linked_journals=True)
        self.assertTrue(p['can_confirm'], p)
        self.confirm(p)
        with self.core.db.read() as conn:
            tombstones = [dict(r) for r in conn.execute('SELECT * FROM bulk_deleted_movements ORDER BY kind')]
            self.assertEqual(['documents', 'journals'], [r['kind'] for r in tombstones])
            self.assertEqual('test-journal', tombstones[1]['idempotency_key'])
            replay = json.loads(conn.execute("SELECT result_json FROM operations WHERE scope='manual-document'").fetchone()[0])
            self.assertTrue(replay['movement_deleted'])
            self.assertEqual(p['id'], replay['deleted_by_bulk_id'])
            self.assertTrue(conn.execute("SELECT 1 FROM audit WHERE action='create' AND entity='document'").fetchone())
        self.integrity()

    def test_bulk_new_financial_dependency_after_preview_blocks(self):
        d = self.doc()
        p = self.preview([d['id']])
        self.core.create_title(self.a['id'], {'kind': 'payable', 'description': 'Teste', 'partner_name': 'Teste', 'document': 'Teste', 'issue_date': '2026-11-01', 'due_date': '2026-11-05', 'amount': '10.00', 'document_id': d['id']}, 'teste')
        with self.assertRaises(DomainError) as raised: self.confirm(p)
        self.assertEqual('dependent_records', raised.exception.code)
        self.assertEqual(1, len(self.core.documents(self.a['id'])))
        self.integrity()

    def test_bulk_close_after_preview_blocks(self):
        d = self.doc()
        self.confirm(self.preview([d['id']], action='review'))
        self.confirm(self.preview([d['id']], action='book'))
        p = self.preview([d['id']])
        self.core.set_period(self.a['id'], {'period': '2026-11', 'module': 'fiscal', 'reason': 'Teste'}, 'teste', True)
        with self.assertRaises(DomainError) as raised: self.confirm(p)
        self.assertEqual('period_closed', raised.exception.code)
        self.assertIn('Reabra', raised.exception.detail)
        self.integrity()

    def test_bulk_review_import_booked_with_linked_journal(self):
        d = self.doc()
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE documents SET status='booked',journal_id=?,extra_json=? WHERE id=?", (j['id'], json.dumps({'import_posting': {'review_pending': True}}), d['id']))
        p = self.preview([d['id']], action='review')
        self.assertTrue(p['can_confirm'], p)
        self.confirm(p)
        current = self.core.documents(self.a['id'])[0]
        self.assertEqual('booked', current['status'])
        self.assertEqual(j['id'], current['journal_id'])
        self.assertFalse(current['import_posting']['review_pending'])
        events = self.core.trace_document(self.a['id'], d['id'])['events']
        reviewed = [e for e in events if e['action'] == 'review']
        self.assertEqual(1, len(reviewed))
        self.assertTrue(reviewed[0]['details']['before']['import_posting.review_pending'])
        self.assertFalse(reviewed[0]['details']['after']['import_posting.review_pending'])

        self.integrity()

    def test_bulk_accounting_independent_of_finalized_fiscal_assessment(self):
        d = self.doc()
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        with self.core.db.transaction() as conn:
            aid = conn.execute("INSERT INTO tax_assessments(company_id,period,tax,source,responsible,snapshot_json,fingerprint,created_at,created_by) VALUES(?,'2026-11','icms','synthetic','teste','{}','synthetic','2026-11-01','teste')", (self.a['id'],)).lastrowid
            conn.execute("INSERT INTO tax_ledgers(company_id,period,tax,assessment_id,opening_credit_cents,carry_credit_cents,payable_cents,snapshot_json,fingerprint,reason,created_at,created_by) VALUES(?,'2026-11','icms',?,0,0,0,'{}','synthetic','synthetic','2026-11-01','teste')", (self.a['id'], aid))
        self.assertFalse(self.preview([d['id']])['can_confirm'])
        p = self.preview([j['id']], kind='journals', action='update', changes={'history': 'Histórico independente'})
        self.assertTrue(p['can_confirm'], p)
        self.confirm(p)
        p = self.preview([j['id']], kind='journals')
        self.assertTrue(p['can_confirm'], p)
        self.confirm(p)
        self.integrity()

    def reversal_pair(self, original_day, reversal_day, key):
        if reversal_day[:4] == '2027':
            self.core.create_exercise(self.a['id'], {'module': 'accounting', 'year': 2027}, 'teste')
        original = self.core.create_journal(self.a['id'], self.journal(key=key, day=original_day), 'teste')
        reversal = self.core.reverse_journal(self.a['id'], original['id'], {'date': reversal_day, 'reason': 'Estorno sintético', 'idempotency_key': key + '-reversal'}, 'teste')
        return original, reversal

    def test_bulk_explicit_reversals_cross_month_and_year(self):
        for old_day, new_day, key in [('2026-06-05', '2026-07-05', 'jun-jul'), ('2026-12-05', '2027-01-05', 'dec-jan')]:
            with self.subTest(key=key):
                original, reversal = self.reversal_pair(old_day, new_day, key)
                self.assertFalse(self.preview([original['id']], kind='journals', period=old_day[:7])['can_confirm'])
                p = self.preview([original['id']], kind='journals', period=old_day[:7], include_reversal_pairs=True)
                self.assertTrue(p['can_confirm'], p)
                self.assertEqual(1, p['selected_count'])
                self.assertEqual(2, p['affected_counts']['journals'])
                self.assertEqual([old_day[:7], new_day[:7]], p['affected_periods'])
                self.assertIn(new_day[:7], p['confirmation_phrase'])
                self.assertEqual([original['id'], reversal['id']], p['effective_ids'])
                result = self.confirm(p)
                self.assertEqual(1, result['selected_count'])
                with self.core.db.read() as conn:
                    removed = {r[0] for r in conn.execute("SELECT record_id FROM bulk_deleted_movements WHERE kind='journals'")}
                    self.assertTrue({original['id'], reversal['id']} <= removed)
                self.integrity()

    def test_bulk_explicit_reversal_other_period_closed_and_revalidated(self):
        original, reversal = self.reversal_pair('2026-06-05', '2026-07-05', 'closed-pair')
        p = self.preview([original['id']], kind='journals', period='2026-06', include_reversal_pairs=True)
        self.core.set_period(self.a['id'], {'period': '2026-07', 'module': 'accounting', 'reason': 'Fechamento sintético'}, 'teste', True)
        with self.assertRaises(DomainError) as raised: self.confirm(p)
        self.assertEqual('period_closed', raised.exception.code)
        blocked = self.preview([original['id']], kind='journals', period='2026-06', include_reversal_pairs=True)
        self.assertFalse(blocked['can_confirm'])
        self.assertIn('2026-07', str(blocked['blockers']))
        self.assertEqual(2, len(self.core.journals(self.a['id'])))
        self.core.set_period(self.a['id'], {'period': '2026-07', 'module': 'accounting', 'reason': 'Reabertura sintética'}, 'teste', False)
        # Selecting the reversal expands back to the original, too.
        self.confirm(self.preview([reversal['id']], kind='journals', period='2026-07', include_reversal_pairs=True))
        self.integrity()

    def test_bulk_reversal_expansion_external_document_dependency_blocks(self):
        original, reversal = self.reversal_pair('2026-06-05', '2026-07-05', 'dependent-pair')
        doc = self.doc()
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE documents SET journal_id=? WHERE id=?', (reversal['id'], doc['id']))
        p = self.preview([original['id']], kind='journals', period='2026-06', include_reversal_pairs=True)
        self.assertFalse(p['can_confirm'])
        self.assertIn('documents.journal_id', str(p['blockers']))
        with self.assertRaises(DomainError): self.confirm(p)
        self.assertEqual(2, len(self.core.journals(self.a['id'])))
        self.integrity()

    def test_bulk_fiscal_explicit_linked_reversal_cross_year(self):
        original, reversal = self.reversal_pair('2026-12-05', '2027-01-05', 'fiscal-pair')
        doc = self.core.create_document(self.a['id'], self.document('DEC') | {'posting_date': '2026-12-05'}, 'teste')
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE documents SET status='booked',journal_id=? WHERE id=?", (original['id'], doc['id']))
        self.assertFalse(self.preview([doc['id']], period='2026-12', include_linked_journals=True)['can_confirm'])
        p = self.preview([doc['id']], period='2026-12', include_linked_journals=True, include_reversal_pairs=True)
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual([original['id'], reversal['id']], p['linked_journal_ids'])
        self.assertEqual(['2026-12', '2027-01'], p['affected_periods'])
        self.confirm(p)
        self.assertEqual([], self.core.journals(self.a['id']))
        self.assertEqual([], self.core.documents(self.a['id']))
        self.integrity()

    def test_bulk_rejects_isolated_unicode_surrogates(self):
        j = self.core.create_journal(self.a['id'], self.journal(), 'teste')
        self.client.post('/api/context', json={'company_id': self.a['id'], 'module': 'accounting', 'period': '2026-11'})
        payload = {'kind': 'journals', 'action': 'update', 'period': '2026-11', 'ids': [j['id']], 'changes': {'history': chr(0xd800)}}
        response = self.client.post(self.scope('/bulk-operations/preview'), content=json.dumps(payload, ensure_ascii=True), headers={'content-type': 'application/json'})
        self.assertEqual(400, response.status_code, response.text)
        p = self.preview([j['id']], kind='journals')
        with self.assertRaises(DomainError): self.confirm(p, reason=chr(0xd800))
        with self.assertRaises(DomainError): self.confirm(p, confirmation_phrase=chr(0xd800))
        self.assertEqual(1, len(self.core.journals(self.a['id'])))
        self.integrity()

    def test_company_cleanup_preserves_closed_and_dependent_movements(self):
        open_doc = self.doc('eligible')
        dependent = self.doc('dependent')
        old = self.core.create_document(self.a['id'], self.document('closed') | {'posting_date': '2026-10-06'}, 'teste')
        self.core.create_title(self.a['id'], {'kind': 'payable', 'description': 'Teste', 'partner_name': 'Teste', 'document': 'Teste', 'issue_date': '2026-11-01', 'due_date': '2026-11-05', 'amount': '10.00', 'document_id': dependent['id']}, 'teste')
        self.confirm(self.preview([old['id']], action='review', period='2026-10'))
        self.confirm(self.preview([old['id']], action='book', period='2026-10'))
        self.core.set_period(self.a['id'], {'period': '2026-10', 'module': 'fiscal', 'reason': 'Teste'}, 'teste', True)
        p = self.preview([], scope='company')
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual(3, p['total_count'])
        self.assertEqual(1, p['selected_count'])
        self.assertEqual(2, p['preserved_count'])
        self.assertEqual({old['id'], dependent['id']}, {r['id'] for r in p['preserved_rows']})
        confirmation = {'preview_id': p['id'], 'preview_hash': p['preview_hash'], 'irreversible_acknowledged': True}
        result = self.service.confirm(self.a['id'], confirmation, self.uid, 'teste')
        self.assertTrue(self.service.confirm(self.a['id'], confirmation, self.uid, 'teste')['duplicate'])
        self.assertEqual(2, result['preserved_count'])
        with self.core.db.read() as conn:
            self.assertIsNone(conn.execute('SELECT id FROM documents WHERE id=?', (open_doc['id'],)).fetchone())
            self.assertEqual(2, conn.execute('SELECT count(*) FROM documents WHERE company_id=?', (self.a['id'],)).fetchone()[0])
        self.integrity()

    def test_company_cleanup_new_record_invalidates_preview(self):
        self.doc('first')
        p = self.preview([], scope='company')
        self.doc('new-after-preview')
        with self.assertRaises(DomainError) as raised:
            self.confirm(p)
        self.assertEqual('stale_preview', raised.exception.code)
        self.assertEqual(2, len(self.core.documents(self.a['id'])))

    def test_company_cleanup_preserves_complete_closed_reversal_chain(self):
        original, reversal = self.reversal_pair('2026-06-05', '2026-07-05', 'closed-chain')
        independent = self.core.create_journal(self.a['id'], self.journal('independent'), 'teste')
        self.core.set_period(self.a['id'], {'period': '2026-07', 'module': 'accounting', 'reason': 'Teste'}, 'teste', True)
        p = self.preview([], kind='journals', scope='company', include_reversal_pairs=True)
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual([independent['id']], p['effective_ids'])
        self.assertEqual(2, p['preserved_count'])
        self.confirm(p)
        with self.core.db.read() as conn:
            self.assertEqual({original['id'], reversal['id']}, {r[0] for r in conn.execute('SELECT id FROM journals WHERE company_id=?', (self.a['id'],))})
        self.integrity()

    def test_company_cleanup_linked_components_preserve_only_blocked_chain(self):
        eligible, protected = self.doc('linked-eligible'), self.doc('linked-protected')
        good = self.core.create_journal(self.a['id'], self.journal('linked-good'), 'teste')
        bad = self.core.create_journal(self.a['id'], self.journal('linked-bad', day='2026-10-06'), 'teste')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE documents SET journal_id=? WHERE id=?', (good['id'], eligible['id']))
            conn.execute('UPDATE documents SET journal_id=? WHERE id=?', (bad['id'], protected['id']))
        self.core.set_period(self.a['id'], {'period': '2026-10', 'module': 'accounting', 'reason': 'Teste'}, 'teste', True)
        p = self.preview([], scope='company', include_linked_journals=True, include_reversal_pairs=True)
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual([eligible['id']], p['effective_ids'])
        self.assertEqual(1, p['preserved_count'])
        self.confirm(p)
        with self.core.db.read() as conn:
            self.assertEqual([protected['id']], [r[0] for r in conn.execute('SELECT id FROM documents WHERE company_id=?', (self.a['id'],))])
            self.assertEqual([bad['id']], [r[0] for r in conn.execute('SELECT id FROM journals WHERE company_id=?', (self.a['id'],))])
        self.integrity()

    def test_company_cleanup_changed_protected_state_invalidates_preview(self):
        eligible, protected = self.doc('eligible'), self.doc('protected')
        self.core.create_title(self.a['id'], {'kind': 'payable', 'description': 'Teste', 'partner_name': 'Teste', 'document': 'Teste', 'issue_date': '2026-11-01', 'due_date': '2026-11-05', 'amount': '10.00', 'document_id': protected['id']}, 'teste')
        p = self.preview([], scope='company')
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE documents SET version=version+1 WHERE id=?', (protected['id'],))
        with self.assertRaises(DomainError) as raised:
            self.confirm(p)
        self.assertEqual('stale_preview', raised.exception.code)
        self.assertEqual(2, len(self.core.documents(self.a['id'])))

    def test_company_cleanup_more_than_5000_and_no_sql_variable_limit(self):
        with self.core.db.transaction() as conn:
            for n in range(5001):
                self.core._create_journal(conn, self.a['id'], self.journal(f'all-{n}'), 'teste')
        p = self.preview([], kind='journals', scope='company')
        self.assertTrue(p['can_confirm'], p)
        self.assertEqual(5001, p['selected_count'])
        self.confirm(p)
        self.assertEqual([], self.core.journals(self.a['id']))
        self.integrity()

# Do not inherit duplicate test methods; keep only the synthetic fixture/helpers.
for _name in list(vars(fixtures.CoreApiTests)):
    if _name.startswith('test_') and _name not in BulkOperationsTests.__dict__:
        setattr(BulkOperationsTests, _name, None)
