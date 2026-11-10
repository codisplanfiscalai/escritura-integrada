"""Synthetic packages in temporary databases only."""
import json
import test_fiscal_import as fiscal
from app.import_package_cleanup import run_due


class PackageCleanupTests(fiscal.FiscalImportTests):
    # Reuse helpers without inheriting the large test suite.
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
        self.assertIn('retention_period', self.cleanup_preview(b)['packages'][0]['blocked_reasons'])
        self.old(b); p = self.cleanup_preview(b)
        with self.core.db.transaction() as conn: conn.execute("UPDATE imports SET status='modified' WHERE id=?", (b['id'],))
        self.cleanup(p, 409)
        r = self.client.post(self.scope('/import-packages/cleanup-preview', self.b['id']), json={'ids': [b['id']]})
        self.assertNotEqual(200, r.status_code)

    def test_confirmed_fiscal_source_protected(self):
        self.mapping(); b = self.preview(); prepared = self.prepared(b); self.confirm(b, prepared); self.old(b)
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
        with sqlite3.connect(restored_dir / 'escritura.sqlite3') as conn:
            self.assertEqual(b'', conn.execute('SELECT original FROM imports WHERE id=?', (discarded['id'],)).fetchone()[0])
            for cid, year, category, sha, content in conn.execute('SELECT company_id,year,category,sha256,content FROM stored_files'):
                path = restored_dir / 'companies' / str(cid) / str(year) / category / sha
                self.assertEqual(bool(content), path.exists())
                if content: self.assertEqual(content, path.read_bytes())
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

    def test_reupload_removed_package_explicitly_blocked_without_replay(self):
        import base64
        b = self.preview(); self.old(b); self.cleanup(self.cleanup_preview(b))
        for filename in ('origem.xml', 'renamed.xml'):
            response = self.post('/imports/preview', {'filename': filename, 'period': '2026-11', 'content_base64': base64.b64encode(self.xml()).decode()}, 410)
            self.assertEqual('removed_package_reupload', response['code'])
        with self.core.db.read() as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM imports WHERE company_id=?', (self.a['id'],)).fetchone()[0])
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM documents WHERE company_id=?', (self.a['id'],)).fetchone()[0])

# unittest otherwise reruns inherited test methods: these helpers are intentional.
for name in dir(fiscal.FiscalImportTests):
    if name.startswith('test_') and name not in PackageCleanupTests.__dict__:
        setattr(PackageCleanupTests, name, None)
