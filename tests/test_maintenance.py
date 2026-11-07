"""Atualização e migração com dados reais de teste, sem tocar no perfil do usuário."""
import configparser
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app.db import Database
from app.business import BusinessCore
from app.maintenance import prepare,finish,rollback,inspect,backup_before_schema,integrity


class MaintenanceTests(unittest.TestCase):
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
        self.assertEqual('Conteúdo preservado',(self.data/'documento-original.txt').read_text())
        self.assertTrue((self.profile/'maintenance.json').exists())
        finish(self.profile)
        config=configparser.ConfigParser();config.read(self.profile/'config.ini')
        self.assertEqual('true',config['General']['start_minimized']);self.assertEqual('8765',config['General']['port'])
        self.assertFalse((self.profile/'maintenance.json').exists())
        self.assertTrue(list((self.profile/'maintenance-history').glob('*.json')))

    def test_failed_install_restores_original_database(self):
        result=prepare(self.profile,'0.6.0-dev.1')
        with sqlite3.connect(self.data/'escritura.sqlite3') as conn:conn.execute("UPDATE companies SET name='Alteração temporária'")
        rollback(self.profile)
        with sqlite3.connect(self.data/'escritura.sqlite3') as conn:self.assertNotEqual('Alteração temporária',conn.execute('SELECT name FROM companies LIMIT 1').fetchone()[0])
        self.assertFalse(Path(result['backup']).exists())

    def test_portable_migration_copies_without_deleting_source(self):
        installed=self.root/'instalado'
        result=prepare(installed,'0.6.0-dev.1',source=self.data)
        finish(installed)
        self.assertEqual(2,result['companies']);self.assertEqual(1,result['users'])
        self.assertTrue((self.data/'escritura.sqlite3').exists())
        self.assertEqual(integrity(self.data/'escritura.sqlite3'),integrity(installed/'data/escritura.sqlite3'))
        self.assertEqual('Conteúdo preservado',(installed/'data/documento-original.txt').read_text())

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
        with sqlite3.connect(self.data/'escritura.sqlite3') as conn:conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        backup=backup_before_schema(self.data/'escritura.sqlite3')
        self.assertTrue(Path(backup).is_file());self.assertEqual(2,integrity(backup)['schema_version'])

    def test_newer_database_refuses_downgrade(self):
        with sqlite3.connect(self.data/'escritura.sqlite3') as conn:conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        with self.assertRaisesRegex(RuntimeError,'mais nova'):Database(self.data)
        self.assertEqual(999,integrity(self.data/'escritura.sqlite3')['schema_version'])

    def test_interrupted_update_is_not_silently_overwritten(self):
        prepare(self.profile,'0.6.0-dev.1')
        with self.assertRaisesRegex(RuntimeError,'incompleta'):prepare(self.profile,'0.6.0-dev.1')
        rollback(self.profile);self.assertEqual(2,inspect(self.profile)['companies'])
