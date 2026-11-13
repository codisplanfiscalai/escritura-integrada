"""Synthetic packages in temporary databases only."""
import json
from unittest.mock import patch
import test_fiscal_import as fiscal
from app.import_package_cleanup import run_due


class PackageCleanupTests(fiscal.FiscalImportTests):
    # Reuse helpers without inheriting the large test suite.
    def operational_settings(self, conn, cid, changes):
        from app.operational_settings import get_settings, save_settings
        row = conn.execute('SELECT version FROM company_operational_settings WHERE company_id=?', (cid,)).fetchone()
        return save_settings(conn, cid, {'settings': get_settings(conn, cid) | changes,
                                        'version': row['version'] if row else 0}, 'test')

    def old(self, batch):
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE imports SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (batch['id'],))

    def cleanup_preview(self, batch):
        return self.post('/import-packages/cleanup-preview', {'ids': [batch['id']], 'mode': 'originals_and_hide_history'})

    def cleanup(self, p, status=200):
        return self.post('/import-packages/cleanup-confirm', {'ids': p['ids'], 'mode': p['mode'], 'preview_hash': p['preview_hash'], 'acknowledge_irreversible': True}, status)

    def test_cleanup_preserves_normalized_data_and_movements(self):
        b = self.preview(); self.old(b)
        with self.core.db.read() as conn:
            before = {t: [tuple(r) for r in conn.execute('SELECT * FROM '+t)] for t in ('documents', 'journals', 'titles', 'bank_transactions')}
            parsed = conn.execute('SELECT parsed_json FROM imports WHERE id=?', (b['id'],)).fetchone()[0]
        p = self.cleanup_preview(b)
        self.assertGreater(p['estimated_bytes'], 0)
        self.assertTrue(self.cleanup(p)['movements_preserved'])
        with self.core.db.read() as conn:
            for t, rows in before.items(): self.assertEqual(rows, [tuple(r) for r in conn.execute('SELECT * FROM '+t)])
            row = conn.execute('SELECT * FROM imports WHERE id=?', (b['id'],)).fetchone()
            self.assertEqual(parsed, row['parsed_json']); self.assertEqual(b'', row['original'])
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual(410, self.client.get(self.scope(f"/imports/{b['id']}/original")).status_code)
        self.assertEqual(410, self.client.get(self.scope(f"/imports/{b['id']}/documents/0/danfe")).status_code)
        self.post(f"/imports/{b['id']}/confirm", {'preview_hash': b['preview_hash']}, 410)
        self.assertNotIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])

    def test_retention_stale_and_cross_company(self):
        b = self.preview()
        with self.core.db.transaction() as conn:
            self.operational_settings(conn, self.a['id'], {'enforce_package_retention': True})
        self.assertIn('retention_period', self.cleanup_preview(b)['packages'][0]['blocked_reasons'])
        self.old(b); p = self.cleanup_preview(b)
        with self.core.db.transaction() as conn: conn.execute("UPDATE imports SET status='modified' WHERE id=?", (b['id'],))
        self.cleanup(p, 409)
        r = self.client.post(self.scope('/import-packages/cleanup-preview', self.b['id']), json={'ids': [b['id']]})
        self.assertNotEqual(200, r.status_code)

    def test_confirmed_fiscal_source_protected(self):
        self.mapping(); b = self.preview(); prepared = self.prepared(b); self.confirm(b, prepared); self.old(b)
        with self.core.db.transaction() as conn:
            self.operational_settings(conn, self.a['id'], {'protect_fiscal_source': True})
        p = self.cleanup_preview(b)
        self.assertIn('sole_fiscal_source_evidence', p['packages'][0]['blocked_reasons'])
        self.cleanup(p, 409)

    def test_scheduler_disabled_then_enabled(self):
        b = self.preview(); self.old(b)
        run_due(self.core.db)
        self.assertEqual(200, self.client.get(self.scope(f"/imports/{b['id']}/original")).status_code)
        r = self.client.put(self.scope('/import-packages/settings'), json={'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'originals', 'acknowledge_irreversible': True})
        self.assertEqual(200, r.status_code, r.text)
        run_due(self.core.db)
        self.assertEqual(410, self.client.get(self.scope(f"/imports/{b['id']}/original")).status_code)

    def test_scheduler_revoked_configurator_and_shared_evidence(self):
        b = self.preview(); self.old(b)
        with self.core.db.transaction() as conn:
            fid = conn.execute("SELECT id FROM stored_files WHERE company_id=? AND sha256=?", (self.a['id'], b['sha256'])).fetchone()[0]
            conn.execute("INSERT INTO auditor_catalog_sources(company_id,file_id,preview_json,created_at) VALUES(?,?,'{}','2000-01-01')", (self.a['id'], fid))
        p = self.cleanup_preview(b)
        self.assertIn('shared_audit_or_module_evidence', p['packages'][0]['blocked_reasons'])
        self.cleanup(p, 409)
        r = self.client.put(self.scope('/import-packages/settings'), json={'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'originals', 'acknowledge_irreversible': True})
        self.assertEqual(200, r.status_code)
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE import_package_settings SET configured_by=NULL WHERE company_id=?', (self.a['id'],))
        run_due(self.core.db)
        with self.core.db.read() as conn:
            self.assertGreater(len(conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0]), 0)
            self.assertTrue(conn.execute("SELECT 1 FROM audit WHERE action='cleanup-skipped' AND company_id=?", (self.a['id'],)).fetchone())

    def test_stored_original_returns_gone_and_duplicate_confirmation_blocks(self):
        from app.file_store import read_file, inventory
        from app.core import DomainError
        b = self.preview(); self.old(b)
        with self.core.db.read() as conn:
            fid = conn.execute('SELECT id FROM stored_files WHERE company_id=? AND sha256=?', (self.a['id'], b['sha256'])).fetchone()[0]
        p = self.cleanup_preview(b); self.cleanup(p)
        self.cleanup(p, 409)
        with self.core.db.read() as conn:
            with self.assertRaises(DomainError) as caught: read_file(conn, self.a['id'], fid)
            self.assertEqual(410, caught.exception.status)
        self.assertNotIn(fid, [r['id'] for r in inventory(self.core.db, self.a['id'], 2026)['files']])

    def test_archive_confirmed_history_preserves_bytes_and_restores(self):
        self.mapping(); b = self.preview(); self.confirm(b, self.prepared(b))
        p = self.post('/import-packages/cleanup-preview', {'ids': [b['id']], 'mode': 'hide_history'})
        self.assertEqual([], p['blocked_ids']); self.assertEqual(0, p['estimated_bytes'])
        with self.core.db.read() as conn:
            before = {t: [tuple(r) for r in conn.execute('SELECT * FROM '+t)] for t in ('imports', 'stored_files', 'documents', 'journals', 'titles')}
        self.cleanup(p)
        with self.core.db.read() as conn:
            for t, rows in before.items(): self.assertEqual(rows, [tuple(r) for r in conn.execute('SELECT * FROM '+t)])
        self.assertEqual(200, self.client.get(self.scope(f"/imports/{b['id']}/original")).status_code)
        self.assertNotIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])
        self.post('/import-packages/restore-history', {'ids': [b['id']]})
        self.assertIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])

    def test_scheduler_history_respects_retention_on_recent_confirmed(self):
        self.mapping(); b = self.preview(); self.confirm(b, self.prepared(b))
        response = self.client.put(self.scope('/import-packages/settings'), json={'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'hide_history'})
        self.assertEqual(200, response.status_code, response.text)
        run_due(self.core.db)
        self.assertIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])
        self.old(b)
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE import_package_settings SET last_run=NULL WHERE company_id=?', (self.a['id'],))
        run_due(self.core.db)
        self.assertNotIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])
        self.assertEqual(200, self.client.get(self.scope(f"/imports/{b['id']}/original")).status_code)

    def test_scheduler_blocked_company_does_not_prevent_other_company_cleanup(self):
        import base64
        from app.import_package_cleanup import save_settings as save_cleanup
        a_batch = self.preview(); self.old(a_batch)
        b_batch = self.core.preview_import(self.b['id'], {'filename': 'invalid.zip', 'period': '2026-11', 'content_base64': base64.b64encode(b'other company package').decode()}, 'test')
        self.old(b_batch)
        with self.core.db.transaction() as conn:
            uid = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()[0]
            for cid in (self.a['id'], self.b['id']):
                save_cleanup(conn, cid, {'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'originals', 'acknowledge_irreversible': True}, 'test', uid)
            self.operational_settings(conn, self.a['id'], {'block_package_cleanup': True})
        run_due(self.core.db)
        with self.core.db.read() as conn:
            self.assertEqual(self.xml(), conn.execute('SELECT original FROM imports WHERE id=?', (a_batch['id'],)).fetchone()[0])
            self.assertEqual(b'', conn.execute('SELECT original FROM imports WHERE id=?', (b_batch['id'],)).fetchone()[0])
            self.assertTrue(conn.execute("SELECT 1 FROM audit WHERE company_id=? AND action='cleanup-skipped'", (self.a['id'],)).fetchone())
            self.assertTrue(conn.execute('SELECT last_run FROM import_package_settings WHERE company_id=?', (self.a['id'],)).fetchone()[0])

    def test_scheduler_selection_limit_drains_at_next_interval(self):
        batches = [self.preview(raw=('invalid source '+str(i)).encode(), filename='invalid.zip') for i in range(3)]
        for batch in batches: self.old(batch)
        response = self.client.put(self.scope('/import-packages/settings'), json={'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'originals', 'acknowledge_irreversible': True})
        self.assertEqual(200, response.status_code)
        with self.core.db.transaction() as conn:
            self.operational_settings(conn, self.a['id'], {'limit_batch_selection': True, 'batch_selection_limit': 2})
        run_due(self.core.db)
        with self.core.db.transaction() as conn:
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM import_package_tombstones WHERE company_id=?', (self.a['id'],)).fetchone()[0])
            conn.execute('UPDATE import_package_settings SET last_run=NULL WHERE company_id=?', (self.a['id'],))
        run_due(self.core.db)
        with self.core.db.read() as conn:
            self.assertEqual(3, conn.execute('SELECT COUNT(*) FROM import_package_tombstones WHERE company_id=?', (self.a['id'],)).fetchone()[0])

    def test_scheduler_rechecks_import_permission_even_with_delete_allowed(self):
        b = self.preview(); self.old(b)
        response = self.client.put(self.scope('/import-packages/settings'), json={'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'originals', 'acknowledge_irreversible': True})
        self.assertEqual(200, response.status_code)
        from app.permissions import require
        from app.core import DomainError
        with self.core.db.transaction() as conn:
            uid = conn.execute("INSERT INTO users(username,password_hash,created_at,role,active) VALUES('revoked-cleaner','not-a-password','2000-01-01','operator',1)").lastrowid
            conn.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)', (uid, self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','delete','allow')", (uid, self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'fiscal.imports','import','deny')", (uid, self.a['id']))
            conn.execute('UPDATE import_package_settings SET configured_by=? WHERE company_id=?', (uid, self.a['id']))
            require(conn, uid, self.a['id'], 'fiscal.imports', 'delete')
            with self.assertRaises(DomainError): require(conn, uid, self.a['id'], 'fiscal.imports', 'import')
            original = conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0]
        run_due(self.core.db)
        with self.core.db.read() as conn:
            self.assertEqual(original, conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0])
            self.assertIsNotNone(conn.execute('SELECT last_run FROM import_package_settings WHERE company_id=?', (self.a['id'],)).fetchone()[0])
            self.assertTrue(conn.execute("SELECT 1 FROM audit WHERE action='cleanup-skipped' AND entity='import' AND entity_id=?", (str(b['id']),)).fetchone())
            self.assertFalse(conn.execute('SELECT 1 FROM import_package_tombstones WHERE import_id=?', (b['id'],)).fetchone())

    def test_failed_package_listed_and_immediately_archivable(self):
        b = self.preview(raw=b'Not a supported fiscal file', filename='invalid.zip')
        packages = self.client.get(self.scope('/import-packages')).json()['packages']
        self.assertIn(b['id'], [r['id'] for r in packages])
        p = self.post('/import-packages/cleanup-preview', {'ids': [b['id']], 'mode': 'hide_history'})
        self.assertEqual([], p['blocked_ids'])
        self.cleanup(p)
        self.assertEqual(200, self.client.get(self.scope(f"/imports/{b['id']}/original")).status_code)

    def test_financial_only_outside_fiscal_listing_and_scheduler(self):
        b = self.preview(); self.old(b)
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE imports SET parsed_json=? WHERE id=?', (json.dumps({'documents': [], 'transactions': [{'id': 'synthetic-financial'}]}), b['id']))
            original = conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0]
        packages = self.client.get(self.scope('/import-packages')).json()['packages']
        self.assertNotIn(b['id'], [r['id'] for r in packages])
        self.post('/import-packages/cleanup-preview', {'ids': [b['id']], 'mode': 'originals'}, 409)
        response = self.client.put(self.scope('/import-packages/settings'), json={'enabled': True, 'retention_days': 1, 'interval_hours': 1, 'mode': 'originals', 'acknowledge_irreversible': True})
        self.assertEqual(200, response.status_code)
        run_due(self.core.db)
        with self.core.db.read() as conn:
            self.assertEqual(original, conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0])
            self.assertFalse(conn.execute('SELECT 1 FROM import_package_tombstones WHERE import_id=?', (b['id'],)).fetchone())

    def test_snapshot_roundtrip_after_cleanup_keeps_totals_and_tombstones(self):
        from app.snapshots import create_snapshot, restore_snapshot, manifest
        from pathlib import Path
        import sqlite3
        from contextlib import closing
        self.mapping(); live = self.preview(); self.confirm(live, self.prepared(live))
        discarded = self.preview(raw=b'invalid original package', filename='invalid.zip'); self.old(discarded)
        self.assertNotIn('removed_originals', manifest(self.core.db.path))
        self.cleanup(self.cleanup_preview(discarded))
        archive = Path(self.tmp.name) / 'cleanup-backup.zip'
        saved = create_snapshot(self.core.db.path, archive)
        self.assertEqual(2, len(saved['removed_originals']))
        self.assertGreater(saved['money']['documents'], 0)
        restored_dir = Path(self.tmp.name) / 'restored-cleanup'
        restored = restore_snapshot(archive, restored_dir)
        for key in ('records', 'money', 'originals', 'removed_originals'):
            self.assertEqual(saved[key], restored[key])
        with closing(sqlite3.connect(restored_dir / 'escritura.sqlite3')) as conn:
            self.assertEqual(b'', conn.execute('SELECT original FROM imports WHERE id=?', (discarded['id'],)).fetchone()[0])
            for cid, year, category, sha, content in conn.execute('SELECT company_id,year,category,sha256,content FROM stored_files'):
                path = restored_dir / 'companies' / str(cid) / str(year) / category / sha
                self.assertEqual(bool(content), path.exists())
                if content: self.assertEqual(content, path.read_bytes())
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute('SELECT 1')
        self.assertEqual(saved['removed_originals'], manifest(restored_dir / 'escritura.sqlite3')['removed_originals'])

    def test_snapshot_refuses_unmarked_empty_or_inconsistent_tombstone(self):
        from app.snapshots import manifest
        b = self.preview(); self.old(b)
        with self.core.db.transaction() as conn:
            original = conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0]
            conn.execute("UPDATE imports SET original=X'' WHERE id=?", (b['id'],))
        with self.assertRaises(RuntimeError): manifest(self.core.db.path)
        with self.core.db.transaction() as conn: conn.execute('UPDATE imports SET original=? WHERE id=?', (original, b['id']))
        self.cleanup(self.cleanup_preview(b))
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE import_package_tombstones SET sha256=? WHERE import_id=?", ('0' * 64, b['id']))
        with self.assertRaises(RuntimeError): manifest(self.core.db.path)

    def test_reupload_restores_same_identity_bytes_and_hidden_history(self):
        from app.file_store import read_file, inventory
        b = self.preview(); self.cleanup(self.cleanup_preview(b))
        with self.core.db.read() as conn:
            before = dict(conn.execute('SELECT * FROM imports WHERE id=?', (b['id'],)).fetchone())
            fid = conn.execute('SELECT id FROM stored_files WHERE company_id=? AND sha256=?', (self.a['id'], b['sha256'])).fetchone()[0]
        for filename in ('renamed.xml', 'origem.xml'):
            restored = self.preview(filename=filename)
            self.assertEqual(b['id'], restored['id'])
            self.assertTrue(restored['original_restored'])
        with self.core.db.read() as conn:
            after = dict(conn.execute('SELECT * FROM imports WHERE id=?', (b['id'],)).fetchone())
            self.assertEqual({k: v for k, v in before.items() if k != 'original'}, {k: v for k, v in after.items() if k != 'original'})
            self.assertEqual(self.xml(), after['original'])
            self.assertEqual(self.xml(), read_file(conn, self.a['id'], fid)['content'])
            self.assertFalse(conn.execute('SELECT 1 FROM import_package_tombstones').fetchone())
            self.assertFalse(conn.execute('SELECT 1 FROM stored_file_tombstones').fetchone())
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM imports WHERE company_id=?', (self.a['id'],)).fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM audit WHERE action='restore-original'").fetchone()[0])
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertIn(fid, [r['id'] for r in inventory(self.core.db, self.a['id'], 2026)['files']])
        self.assertNotIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])
        self.post('/import-packages/restore-history', {'ids': [b['id']]})
        self.assertIn(b['id'], [r['id'] for r in self.client.get(self.scope('/imports')).json()])

    def test_default_cleanup_confirmed_source_and_restore_preserve_movements(self):
        self.mapping(); b = self.preview(); self.confirm(b, self.prepared(b))
        with self.core.db.read() as conn:
            before = {t: [tuple(r) for r in conn.execute('SELECT * FROM '+t)] for t in ('documents', 'journals', 'titles', 'bank_transactions')}
        p = self.cleanup_preview(b)
        self.assertEqual([], p['blocked_ids'])
        self.cleanup(p)
        restored = self.preview(filename='reenviado.xml')
        self.assertEqual(b['id'], restored['id'])
        self.assertEqual('confirmed', restored['status'])
        with self.core.db.read() as conn:
            for t, rows in before.items(): self.assertEqual(rows, [tuple(r) for r in conn.execute('SELECT * FROM '+t)])

    def test_restore_hash_and_company_isolation(self):
        from app.import_package_cleanup import restore_upload
        b = self.preview(); self.cleanup(self.cleanup_preview(b))
        with self.core.db.transaction() as conn:
            self.assertIsNone(restore_upload(conn, self.b['id'], self.xml(), 'test'))
            self.assertIsNone(restore_upload(conn, self.a['id'], self.xml() + b' ', 'test'))
            self.assertEqual(b'', conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0])
            self.assertTrue(conn.execute('SELECT 1 FROM import_package_tombstones WHERE import_id=?', (b['id'],)).fetchone())

    def test_restore_requires_original_import_permission(self):
        from app.core import DomainError
        from app.import_package_cleanup import restore_upload
        b = self.preview(); self.cleanup(self.cleanup_preview(b))
        with patch('app.permissions.import_access', side_effect=DomainError('Sem permissão', 403, 'forbidden')):
            with self.assertRaises(DomainError):
                with self.core.db.transaction() as conn: restore_upload(conn, self.a['id'], self.xml(), 'test')
        with self.core.db.read() as conn:
            self.assertEqual(b'', conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0])
            self.assertTrue(conn.execute('SELECT 1 FROM stored_file_tombstones').fetchone())
            self.assertFalse(conn.execute("SELECT 1 FROM audit WHERE action='restore-original'").fetchone())

    def test_restore_rejects_corrupt_tombstone_without_mutation(self):
        from app.core import DomainError
        from app.import_package_cleanup import restore_upload
        b = self.preview(); self.cleanup(self.cleanup_preview(b))
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE import_package_tombstones SET original_bytes=1 WHERE import_id=?', (b['id'],))
        with self.assertRaises(DomainError):
            with self.core.db.transaction() as conn: restore_upload(conn, self.a['id'], self.xml(), 'test')
        with self.core.db.read() as conn:
            self.assertEqual(b'', conn.execute('SELECT original FROM imports WHERE id=?', (b['id'],)).fetchone()[0])
            self.assertTrue(conn.execute('SELECT 1 FROM stored_file_tombstones').fetchone())


# unittest otherwise reruns inherited test methods: these helpers are intentional.
for name in dir(fiscal.FiscalImportTests):
    if name.startswith('test_') and name not in PackageCleanupTests.__dict__:
        setattr(PackageCleanupTests, name, None)
