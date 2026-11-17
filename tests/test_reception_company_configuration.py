"""Persisted company defaults and dispatch races; synthetic/injected transport only."""
import unittest
from unittest.mock import patch
import test_reception_remote as remote
from app.reception_service import RUN_SCOPE, STATE_SCOPE
from app.reception_workspace import ReceptionWorkspace

class CompanyConfigurationTests(unittest.TestCase):
    setUpBase=remote.base.CoreApiTests.setUp
    setUp=remote.CaptureApiTests.setUp
    tearDown=remote.base.CoreApiTests.tearDown
    create_company=remote.base.CoreApiTests.create_company
    activate=remote.base.CoreApiTests.activate
    scope=remote.base.CoreApiTests.scope
    def overview(self,provider='nfe_distribution',cid=None):
        r=self.client.get(self.scope('/reception/'+provider,cid),params={'year':2026})
        self.assertEqual(200,r.status_code,r.text)
        return r.json()
    def save_preferences(self,cid,nfe='production',nfse='production'):
        old=self.client.get(self.scope('/reception-settings',cid)).json()['preferences']
        r=self.client.put(self.scope('/reception-settings',cid),json={'version':old['version'],'nfe_environment':nfe,'nfse_environment':nfse})
        self.assertEqual(200,r.status_code,r.text)
    def body(self,provider='nfe_distribution',key='synthetic-configured-001'):
        selected=self.overview(provider)['configuration']
        return {'environment':selected['environment'],'configuration_revision':selected['revision'],'period':'2026-11','idempotency_key':key}
    def query(self,body):
        return self.client.post(self.scope('/reception/nfe_distribution/query'),json=body)
    def assert_not_reserved(self):
        self.assertEqual([],self.transport.plans)
        with self.core.db.read() as conn:
            self.assertEqual(0,conn.execute('SELECT count(*) FROM operations WHERE scope IN (?,?)',(RUN_SCOPE,STATE_SCOPE)).fetchone()[0])
    def test_saved_defaults_survive_reopening_and_follow_only_the_selected_company(self):
        self.save_preferences(self.a['id'])
        self.save_preferences(self.b['id'],nfe='homologation',nfse='restricted_production')
        for cid,envs in [(self.a['id'],('production','production')),(self.b['id'],('homologation','restricted_production'))]:
            self.activate(cid)
            for provider,environment in zip(('nfe_distribution','nfse_adn'),envs):
                result=self.overview(provider,cid)
                self.assertEqual(environment,result['environment']);self.assertEqual(environment,result['configuration']['environment'])
                workspace=ReceptionWorkspace(self.core,self.service)
                reopened=workspace.overview(cid,self.uid,provider,None,2026)
                self.assertEqual(result['configuration'],reopened['configuration'])
                self.assertEqual([],result['documents']);self.assertEqual('000000000000000',result['state']['cursor'])
        self.assertEqual(0,self.service.credentials.calls);self.assert_not_reserved()
    def test_new_view_cannot_override_company_environment_or_reuse_another_company_revision(self):
        old=self.body();self.save_preferences(self.a['id'])
        for payload in [old,self.body()|{'environment':'homologation'},self.body()|{'configuration_revision':None}]:
            r=self.query(payload);self.assertIn(r.status_code,(400,409),r.text)
        revision=self.overview()['configuration']['revision'];self.activate(self.b['id'])
        r=self.query(self.body()|{'configuration_revision':revision});self.assertEqual(409,r.status_code,r.text)
        self.assertEqual(0,self.service.credentials.calls);self.assert_not_reserved()
    def test_configured_environment_and_certificate_are_used_only_after_explicit_query(self):
        self.save_preferences(self.a['id']);body=self.body();self.assert_not_reserved()
        self.transport.reply=remote.RemoteReply(200,remote.response([('1','procNFe_v4.00.xsd',self.raw.replace(b'<tpAmb>2</tpAmb>',b'<tpAmb>1</tpAmb>'))],environment='1',last='1',maximum='2'))
        load=self.service.credentials.load
        with patch.object(self.service.credentials,'load',wraps=load) as credential:
            r=self.query(body)
        self.assertEqual(200,r.status_code,r.text);self.assertEqual('received',r.json()['state'])
        credential.assert_called_once_with(self.a['id'],remote.MATRIX,'nfe_distribution','production')
        self.assertEqual(1,len(self.transport.plans))
        self.assertIn('www1.nfe.fazenda.gov.br',self.transport.plans[0]['url'])
        self.assertEqual([],self.core.documents(self.a['id']))
        # Configuration changes cannot redirect an explicit retry to another environment.
        self.save_preferences(self.a['id'],nfe='homologation')
        again=self.query(body);self.assertEqual(200,again.status_code,again.text)
        self.assertEqual(r.json()|{'duplicate':True},again.json());self.assertEqual(1,len(self.transport.plans))
    def test_preferences_changed_while_loading_a1_prevent_reservation_and_send(self):
        body=self.body();load=self.service.credentials.load
        def changed(*args):
            identity=load(*args);self.save_preferences(self.a['id']);return identity
        with patch.object(self.service.credentials,'load',side_effect=changed):r=self.query(body)
        self.assertEqual(409,r.status_code,r.text);self.assertEqual('stale_reception_configuration',r.json()['code']);self.assert_not_reserved()
    def test_company_uf_change_while_loading_a1_prevents_send(self):
        body=self.body();load=self.service.credentials.load
        def changed(*args):
            identity=load(*args)
            with self.core.db.transaction() as conn:conn.execute("UPDATE companies SET state='RJ' WHERE id=?",(self.a['id'],))
            return identity
        with patch.object(self.service.credentials,'load',side_effect=changed):r=self.query(body)
        self.assertEqual(409,r.status_code,r.text);self.assertEqual('stale_reception_configuration',r.json()['code']);self.assert_not_reserved()
    def test_local_check_uses_saved_defaults_and_rejects_a_concurrent_change(self):
        self.save_preferences(self.a['id']);selected=self.overview()['configuration'];load=self.service.credentials.load
        with patch.object(self.service.credentials,'load',wraps=load) as credential:
            r=self.client.post(self.scope('/reception/nfe_distribution/check'),json={'configuration_revision':selected['revision']})
        self.assertEqual(200,r.status_code,r.text);self.assertTrue(r.json()['ready']);self.assertFalse(r.json()['remote_checked'])
        credential.assert_called_once_with(self.a['id'],remote.MATRIX,'nfe_distribution','production')
        legacy=self.client.post(self.scope('/reception/nfe_distribution/check'),json={'environment':'homologation'})
        self.assertEqual(409,legacy.status_code,legacy.text)
        def changed(*args):
            identity=load(*args);self.save_preferences(self.a['id'],nfe='homologation');return identity
        with patch.object(self.service.credentials,'load',side_effect=changed):
            r=self.client.post(self.scope('/reception/nfe_distribution/check'),json={'configuration_revision':selected['revision']})
        self.assertEqual(409,r.status_code,r.text);self.assert_not_reserved()

    def test_permission_revoked_during_a1_preparation_prevents_send(self):
        body=self.body();load=self.service.credentials.load
        def revoked(*args):
            identity=load(*args)
            with self.core.db.transaction() as conn:
                conn.execute("UPDATE users SET role='operator' WHERE id=?",(self.uid,))
                conn.execute('INSERT OR IGNORE INTO user_companies(user_id,company_id) VALUES(?,?)',(self.uid,self.a['id']))
                conn.execute('INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,?,?,?)',
                             (self.uid,self.a['id'],'fiscal.imports','read','allow'))
                conn.execute('INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,?,?,?)',
                             (self.uid,self.a['id'],'fiscal.imports','import','deny'))
            return identity
        with patch.object(self.service.credentials,'load',side_effect=revoked):r=self.query(body)
        self.assertEqual(403,r.status_code,r.text);self.assert_not_reserved()
