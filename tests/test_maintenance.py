"""Atualização e migração com dados reais de teste, sem tocar no perfil do usuário."""
import configparser
import json
import os
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app.db import Database
from app.business import BusinessCore
from app.maintenance import prepare,finish,rollback,inspect,backup_before_schema,integrity


class MaintenanceTests(unittest.TestCase):
    def database_state(self):
        with closing(sqlite3.connect(self.data/'escritura.sqlite3')) as conn:
            tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {'dump':tuple(conn.iterdump()),
                    'records':{table:list(conn.execute('SELECT * FROM "'+table.replace('"','""')+'" ORDER BY rowid')) for table in tables},
                    'meta_rowids':list(conn.execute('SELECT rowid,key,value FROM meta ORDER BY rowid')),
                    'schema':list(conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"))}

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.profile=self.root/'perfil';self.data=self.profile/'data'
        self.core=BusinessCore(Database(self.data),demo=True)
        self.core.setup({'username':'operador-teste','password':'Senha-sintetica-123'})
        self.profile.joinpath('config.ini').write_text('[General]\nstart_minimized=true\nport=8765\n',encoding='utf-8')
        self.data.joinpath('documento-original.txt').write_text('Conteúdo preservado',encoding='utf-8')

    def tearDown(self):self.tmp.cleanup()

    def test_upgrade_preserves_data_settings_and_backup(self):
        before=integrity(self.data/'escritura.sqlite3')
        result=prepare(self.profile,'0.6.0-dev.1')
        self.assertTrue(result['ok']);self.assertTrue(Path(result['backup']).is_dir())
        self.assertEqual(before,integrity(self.data/'escritura.sqlite3'))
        self.assertEqual('Conteúdo preservado',(self.data/'documento-original.txt').read_text(encoding='utf-8'))
        self.assertTrue((self.profile/'maintenance.json').exists())
        finish(self.profile)
        config=configparser.ConfigParser();config.read(self.profile/'config.ini',encoding='utf-8')
        self.assertEqual('true',config['General']['start_minimized']);self.assertEqual('8765',config['General']['port'])
        self.assertFalse((self.profile/'maintenance.json').exists())
        self.assertTrue(list((self.profile/'maintenance-history').glob('*.json')))

    def test_reinstall_preserves_exact_dump_and_all_business_rows_like_windows_installer(self):
        self.core.save_group({'name':'Grupo preservado','company_ids':[1],
            'permissions':[{'company_id':1,'routine':'fiscal.*','action':'read','effect':'allow'}]},'operador-teste')
        self.core.create_exercise(1,{'module':'fiscal','year':2029},'operador-teste')
        self.core.save_master(1,'participant',{'code':'PRESERVED','name':'Terceiro sintético preservado',
            'tax_id':'11222333000181','data':{'roles':['supplier'],'email':'synthetic@example.test'}},'operador-teste')
        config=self.profile/'config.ini'
        config.write_text(config.read_text(encoding='utf-8')+'\n[Smoke]\nvalor=preservado\n',encoding='utf-8')
        before=self.database_state()
        # This is the same preparation/finish path called by the real Windows
        # installer, not an equivalent-data replacement for its strict digest.
        for _ in range(2):
            result=prepare(self.profile,'0.8.0-dev.66')
            self.assertEqual(before,self.database_state())
            with closing(sqlite3.connect(Path(result['backup'])/'escritura.sqlite3')) as backup:
                self.assertEqual(before['dump'],tuple(backup.iterdump()))
            finish(self.profile)
            self.assertEqual(before,self.database_state())
            settings=configparser.ConfigParser();settings.read(config,encoding='utf-8')
            self.assertEqual('preservado',settings['Smoke']['valor'])
            self.assertEqual('true',settings['General']['start_minimized'])

    def test_repeated_database_and_core_startup_preserve_marker_rowids_and_timestamps(self):
        self.core.save_master(1,'participant',{'code':'STARTUP','name':'Synthetic startup party',
            'tax_id':'11222333000181','data':{'roles':['customer']}},'operador-teste')
        before=self.database_state()
        for _ in range(3):
            BusinessCore(Database(self.data),demo=True)
            self.assertEqual(before,self.database_state())
        from app.migration_third_parties import migrate_third_parties
        with self.core.db.read() as conn:
            changes=conn.total_changes
            migrate_third_parties(conn)
            self.assertEqual(changes,conn.total_changes,'already-current third-party migration must not rewrite rows')
        self.assertEqual(before,self.database_state())

    def test_failed_install_restores_original_database(self):
        result=prepare(self.profile,'0.6.0-dev.1')
        with closing(sqlite3.connect(self.data/'escritura.sqlite3')) as conn, conn:conn.execute("UPDATE companies SET name='Alteração temporária'")
        rollback(self.profile)
        with closing(sqlite3.connect(self.data/'escritura.sqlite3')) as conn, conn:self.assertNotEqual('Alteração temporária',conn.execute('SELECT name FROM companies LIMIT 1').fetchone()[0])
        self.assertFalse(Path(result['backup']).exists())

    def test_portable_migration_copies_without_deleting_source(self):
        installed=self.root/'instalado'
        result=prepare(installed,'0.6.0-dev.1',source=self.data)
        finish(installed)
        self.assertEqual(2,result['companies']);self.assertEqual(1,result['users'])
        self.assertTrue((self.data/'escritura.sqlite3').exists())
        self.assertEqual(integrity(self.data/'escritura.sqlite3'),integrity(installed/'data/escritura.sqlite3'))
        self.assertEqual('Conteúdo preservado',(installed/'data/documento-original.txt').read_text(encoding='utf-8'))

    def test_existing_destination_never_merged_or_replaced_by_portable(self):
        other=self.root/'outro';BusinessCore(Database(other/'data'),demo=True)
        with self.assertRaisesRegex(RuntimeError,'não mescla'):prepare(other,'0.6.0-dev.1',source=self.data)

    def test_running_app_blocks_without_forced_termination(self):
        (self.profile/'aplicacao.lock').write_text(str(os.getpid())+'\nEscrituraIntegrada\nhost\n')
        with self.assertRaisesRegex(RuntimeError,'está aberta'):prepare(self.profile,'0.6.0-dev.1')
        self.assertFalse((self.profile/'maintenance.json').exists())

    def test_migration_failure_restores_and_removes_stage(self):
        with patch('app.migrations.migrate',side_effect=RuntimeError('Falha simulada')):
            with self.assertRaisesRegex(RuntimeError,'Falha simulada'):prepare(self.profile,'0.6.0-dev.1')
        self.assertEqual(2,inspect(self.profile)['companies'])
        self.assertFalse((self.profile/'maintenance.json').exists())
        self.assertEqual([],list(self.profile.glob('.escritura-atualizacao-*')))

    def test_runtime_schema_upgrade_creates_consistent_backup(self):
        with closing(sqlite3.connect(self.data/'escritura.sqlite3')) as conn, conn:conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        backup=backup_before_schema(self.data/'escritura.sqlite3')
        self.assertTrue(Path(backup).is_file());self.assertEqual(2,integrity(backup)['schema_version'])

    def test_newer_database_refuses_downgrade(self):
        with closing(sqlite3.connect(self.data/'escritura.sqlite3')) as conn, conn:conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        with self.assertRaisesRegex(RuntimeError,'mais nova'):Database(self.data)
        self.assertEqual(999,integrity(self.data/'escritura.sqlite3')['schema_version'])

    def test_interrupted_update_is_not_silently_overwritten(self):
        prepare(self.profile,'0.6.0-dev.1')
        with self.assertRaisesRegex(RuntimeError,'incompleta'):prepare(self.profile,'0.6.0-dev.1')
        rollback(self.profile);self.assertEqual(2,inspect(self.profile)['companies'])

    def test_integrity_and_backup_release_every_sqlite_handle(self):
        from app.maintenance import sqlite_backup
        original=sqlite3.connect;connections=[]
        def connect(*args,**kwargs):
            conn=original(*args,**kwargs);connections.append(conn);return conn
        with patch('app.maintenance.sqlite3.connect',side_effect=connect):
            integrity(self.data/'escritura.sqlite3')
            backup=self.root/'cópia #1.sqlite3'
            sqlite_backup(self.data/'escritura.sqlite3',backup)
        for conn in connections:
            with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
        backup.rename(self.root/'backup liberado.sqlite3')

    def test_recovery_waits_for_installer_owner_then_restores(self):
        from app.maintenance import recover
        prepare(self.profile,'0.6.0-dev.1',owner_pid=os.getpid())
        with self.assertRaisesRegex(RuntimeError,'ainda está em execução'):recover(self.profile)
        marker=self.profile/'maintenance.json';state=json.loads(marker.read_text(encoding='utf-8'));state['owner_pid']=0
        marker.write_text(json.dumps(state),encoding='utf-8')
        self.assertEqual('restored',recover(self.profile)['phase'])
        self.assertEqual(2,inspect(self.profile)['companies'])
