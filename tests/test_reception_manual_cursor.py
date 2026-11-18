"""Manual NSU parameters share automatic state; synthetic data, no fiscal network."""
import json
import unittest
from unittest.mock import patch
import test_reception_remote as remote
import test_reception_adn as adn
from app.core import pack
from app.reception_service import STATE_SCOPE
from app.reception_transport import RemoteReply

class ManualCursorTests(unittest.TestCase):
    setUpBase=remote.base.CoreApiTests.setUp
    setUp=remote.CaptureApiTests.setUp
    tearDown=remote.base.CoreApiTests.tearDown
    create_company=remote.base.CoreApiTests.create_company
    activate=remote.base.CoreApiTests.activate
    scope=remote.base.CoreApiTests.scope
    def settings(self):
        r=self.client.get(self.scope('/reception-settings'))
        self.assertEqual(200,r.status_code,r.text)
        return r.json()
    def body(self,provider='nfe_distribution',environment='homologation',cursor='12'):
        snapshot=self.settings()['cursors'][provider][environment]
        return {'provider':provider,'environment':environment,'cursor':cursor,'expected_revision':snapshot['revision'],'confirmed':True}
    def adjust(self,body,status=200):
        r=self.client.put(self.scope('/reception-settings/cursor'),json=body)
        self.assertEqual(status,r.status_code,r.text)
        return r.json()
    def query(self,key='manual-auto-nfe',provider='nfe_distribution',environment='homologation'):
        r=self.client.post(self.scope('/imports/reception/query'),json={'provider':provider,'environment':environment,'period':'2026-11','idempotency_key':key})
        self.assertEqual(200,r.status_code,r.text)
        return r.json()
    def test_four_independent_parameters_and_company_isolation(self):
        settings=self.settings()['cursors']
        self.assertEqual({'homologation','production'},set(settings['nfe_distribution']))
        self.assertEqual({'restricted_production','production'},set(settings['nfse_adn']))
        self.adjust(self.body(cursor='123'))
        self.adjust(self.body('nfse_adn','production','9007199254740993'))
        settings=self.settings()['cursors']
        self.assertEqual('000000000000123',settings['nfe_distribution']['homologation']['cursor'])
        self.assertEqual('9007199254740993',settings['nfse_adn']['production']['cursor'])
        self.assertEqual('000000000000000',settings['nfe_distribution']['production']['cursor'])
        self.assertEqual('000000000000000',settings['nfse_adn']['restricted_production']['cursor'])
        self.activate(self.b['id']);self.a=self.b
        for envs in self.settings()['cursors'].values():
            for snapshot in envs.values():self.assertEqual('000000000000000',snapshot['cursor'])
        self.assertEqual([],self.transport.plans)
    def test_automatic_update_is_reflected_and_old_editor_cannot_overwrite(self):
        stale=self.body(cursor='7')
        self.query()
        self.assertEqual('000000000000002',self.settings()['cursors']['nfe_distribution']['homologation']['cursor'])
        self.assertEqual('stale_reception_cursor',self.adjust(stale,409)['code'])
        self.adjust(self.body(cursor='1'))
        self.transport.reply=RemoteReply(200,remote.response([('2','resNFe_v1.01.xsd',remote.SUMMARY)],last='2',maximum='3'))
        self.query(key='manual-auto-next')
        self.assertEqual('000000000000002',self.settings()['cursors']['nfe_distribution']['homologation']['cursor'])
        self.assertIn(b':ultNSU>000000000000001',self.transport.plans[-1]['body'])
    def test_adjustment_never_deletes_originals_or_bypasses_cooldown(self):
        self.transport.reply=RemoteReply(200,remote.response([('1','resNFe_v1.01.xsd',remote.SUMMARY)],last='1',maximum='1'))
        self.query()
        before=self.settings()['cursors']['nfe_distribution']['homologation']
        with self.core.db.read() as conn:
            originals=[tuple(r) for r in conn.execute('SELECT * FROM stored_files')]
        result=self.adjust(self.body(cursor='0'))
        self.assertEqual(before['next_allowed_at'],result['next_allowed_at'])
        with self.core.db.read() as conn:
            self.assertEqual(originals,[tuple(r) for r in conn.execute('SELECT * FROM stored_files')])
            records=conn.execute("SELECT result_json FROM operations WHERE scope='reception-nsu-adjustment-v1'").fetchall()
            self.assertEqual('backward',json.loads(records[0][0])['direction'])
        r=self.client.post(self.scope('/imports/reception/query'),json={'provider':'nfe_distribution','environment':'homologation','period':'2026-11','idempotency_key':'cooldown-still-active'})
        self.assertEqual(429,r.status_code)
    def test_inflight_query_blocks_adjustment_and_old_finish_cannot_overwrite(self):
        body=self.body()
        seen=[]
        original=self.transport.send
        def send(*args):
            seen.append(self.adjust(body,409)['code'])
            return original(*args)
        with patch.object(self.transport,'send',side_effect=send):self.query()
        self.assertEqual(['reception_busy'],seen)
        self.assertEqual('000000000000002',self.settings()['cursors']['nfe_distribution']['homologation']['cursor'])
    def test_cursor_change_invalidates_pending_configured_query(self):
        overview=self.client.get(self.scope('/reception/nfe_distribution'),params={'year':2026}).json()
        self.adjust(self.body(cursor='1'))
        r=self.client.post(self.scope('/reception/nfe_distribution/query'),json={'environment':'homologation','period':'2026-11','idempotency_key':'stale-manual-config','configuration_revision':overview['configuration']['revision']})
        self.assertEqual(409,r.status_code,r.text);self.assertEqual([],self.transport.plans)
    def test_validation_confirmation_and_permissions(self):
        base=self.body()
        for value in [None,12,1.2,True,'-1','1e2','1.2','１２','1'*16]:self.adjust(base|{'cursor':value},400)
        self.adjust(base|{'confirmed':False},400)
        self.adjust(self.body('nfse_adn','production','9223372036854775808'),400)
        self.adjust(base|{'environment':'restricted_production'},400)
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
            conn.execute('INSERT OR IGNORE INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
            conn.execute("INSERT INTO user_permissions VALUES(?,?,'system.companies','edit','deny')",(self.uid,self.a['id']))
        self.adjust(base,403)
    def test_adn_automatic_cursor_remains_precise_after_manual_seed(self):
        self.adjust(self.body('nfse_adn','restricted_production','9007199254740992'))
        self.transport.reply=RemoteReply(200,json.dumps(adn.page([adn.packet(9007199254740993)])).encode())
        self.query('manual-auto-adn','nfse_adn','restricted_production')
        self.assertEqual('9007199254740993',self.settings()['cursors']['nfse_adn']['restricted_production']['cursor'])
