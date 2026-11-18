"""Durable automation integration; fake fiscal services and exact real DB receipts."""
import asyncio
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_reception_adn as adn
import test_reception_remote as remote
from app.core import DomainError
from app.reception_automation import ReceptionAutomation
from app.reception_transport import RemoteReply


class AutomationTests(unittest.TestCase):
    setUpBase = adn.AdnCaptureTests.setUpBase
    tearDown = adn.AdnCaptureTests.tearDown
    create_company = adn.AdnCaptureTests.create_company
    activate = adn.AdnCaptureTests.activate
    scope = adn.AdnCaptureTests.scope
    state = adn.AdnCaptureTests.state

    def setUp(self):
        adn.AdnCaptureTests.setUp(self)
        self.worker = ReceptionAutomation(self.core, self.service, lambda: self.clock[0])
        self.app.state.reception_automation = self.worker

    def configure(self, provider='nfse_adn', enabled=True, minutes=1440, version=None):
        if version is None:
            version = self.worker.settings(self.a['id'], self.uid)['services'][provider]['version']
        return self.worker.save(self.a['id'], self.uid, 'synthetic', provider,
                                {'version': version, 'enabled': enabled, 'interval_minutes': minutes})

    def job(self, provider='nfse_adn'):
        with self.core.db.read() as conn:
            return self.worker._row(conn, self.a['id'], provider)

    def end(self):
        return RemoteReply(404, json.dumps({'StatusProcessamento': 'NENHUM_DOCUMENTO_LOCALIZADO',
            'TipoAmbiente': 'HOMOLOGACAO', 'Erros': [{'Codigo': 'E2220'}]}).encode())

    def test_default_is_opt_in_24_hours_without_credentials_or_network(self):
        response = self.client.get(self.scope('/reception-automation'))
        self.assertEqual(200, response.status_code, response.text)
        self.assertNotIn('lease_id', response.text)
        self.assertNotIn('configuration_revision', response.text)
        for row in response.json()['services'].values():
            self.assertFalse(row['enabled'])
            self.assertEqual(1440, row['interval_minutes'])
        self.worker.tick()
        self.assertEqual([], self.transport.plans)
        self.assertEqual(0, self.service.credentials.calls)

    def test_api_validates_interval_version_csrf_and_service(self):
        body = {'version': 0, 'enabled': True, 'interval_minutes': 1440}
        url = self.scope('/reception-automation/nfse_adn')
        self.assertEqual(403, self.client.put(url, json=body, headers={'X-CSRF-Token': ''}).status_code)
        for bad in (0, -1, True, 1.5, 525601):
            self.assertEqual(400, self.client.put(url, json=body | {'interval_minutes': bad}).status_code)
        r = self.client.put(url, json=body)
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(409, self.client.put(url, json=body).status_code)
        self.assertEqual(400, self.client.put(self.scope('/reception-automation/fake'), json=body).status_code)
        self.assertEqual([], self.transport.plans)

    def test_two_pages_then_explicit_end_and_daily_schedule_survive_restart(self):
        self.configure()
        for n in (1, 2):
            self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(n)])).encode())
            self.assertTrue(self.worker.run_one(self.a['id'], 'nfse_adn'))
        self.transport.reply = self.end()
        self.worker = ReceptionAutomation(self.core, self.service, lambda: self.clock[0])
        self.worker.run_one(self.a['id'], 'nfse_adn')
        row = self.job()
        self.assertEqual('idle', row['status'])
        self.assertEqual((2, 2), (row['pages'], row['downloaded']))
        self.assertEqual(self.clock[0] + 86400, row['next_run_at'])
        self.assertEqual('000000000000002', self.state()['cursor'])
        self.worker.tick()
        self.assertEqual(3, len(self.transport.plans))
        self.clock[0] += 86401
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(3)])).encode())
        self.worker.tick()
        self.assertIn('/DFe/000000000000002', self.transport.plans[-1]['url'])
        self.assertEqual([], self.core.documents(self.a['id']))

    def test_both_services_operate_independently_and_respect_nfe_exhaustion(self):
        self.configure('nfse_adn', minutes=120)
        self.configure('nfe_distribution', minutes=2880)
        # Use a protocol-level empty NF-e response with validated environment.
        nfexml = b'<retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01"><tpAmb>2</tpAmb><verAplic>SYNTHETIC</verAplic><cStat>137</cStat><xMotivo>Sem documentos</xMotivo><dhResp>2026-11-01T12:00:00-03:00</dhResp><ultNSU>000000000000000</ultNSU><maxNSU>000000000000000</maxNSU></retDistDFeInt>'
        def send(plan, identity):
            self.transport.plans.append(plan)
            return self.end() if plan['provider'] == 'nfse_adn' else RemoteReply(200, nfexml)
        self.transport.send = send
        self.worker.tick()
        self.assertEqual(2, len(self.transport.plans))
        self.assertEqual('idle', self.job()['status'])
        self.assertEqual('idle', self.job('nfe_distribution')['status'])
        self.assertEqual(self.clock[0] + 172800, self.job('nfe_distribution')['next_run_at'])
        self.assertEqual(self.clock[0] + 7200, self.job()['next_run_at'])

    def test_service_pause_wins_over_short_user_interval(self):
        self.configure(minutes=1)
        self.transport.reply = self.end()
        self.worker.tick()
        self.assertEqual(self.clock[0] + 3600, self.job()['next_run_at'])
        self.clock[0] += 61
        self.worker.tick()
        self.assertEqual(1, len(self.transport.plans))

    def test_positive_retry_after_waits_without_losing_active_run(self):
        self.configure()
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(1)])).encode(), 120)
        self.worker.tick()
        self.assertEqual(self.clock[0] + 120, self.job()['next_run_at'])
        run = self.job()['run_id']
        self.worker.tick()
        self.assertEqual(1, len(self.transport.plans))
        self.clock[0] += 121
        self.transport.reply = self.end()
        self.worker.tick()
        self.assertIsNone(self.job()['run_id'])
        self.assertIsNotNone(run)

    def test_disable_in_flight_allows_archive_commit_but_no_next_page(self):
        self.configure()
        def send(plan, identity):
            self.transport.plans.append(plan)
            self.configure(enabled=False)
            return RemoteReply(200, json.dumps(adn.page([adn.packet(1)])).encode())
        self.transport.send = send
        self.worker.tick()
        self.worker.tick()
        self.assertEqual('disabled', self.job()['status'])
        self.assertEqual('000000000000001', self.state()['cursor'])
        self.assertEqual(1, len(self.transport.plans))

    def test_reconfigured_environment_and_revoked_user_block_before_network(self):
        self.configure()
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE users SET active=0 WHERE id=?', (self.uid,))
        self.worker.tick()
        with self.core.db.read() as conn:
            self.assertEqual('blocked', self.worker._row(conn, self.a['id'], 'nfse_adn')['status'])
        self.assertEqual([], self.transport.plans)

    def test_timeout_blocks_and_preserves_attempt_cursor_and_opaque_details(self):
        self.configure()
        def send(*args):
            raise RuntimeError('PRIVATE_SECRET_MUST_NOT_ESCAPE')
        self.transport.send = send
        self.worker.tick()
        self.assertEqual('blocked', self.job()['status'])
        self.assertNotIn('PRIVATE_SECRET', json.dumps(self.job()))
        self.assertEqual('000000000000000', self.state()['cursor'])
        self.assertIsNotNone(self.job()['attempt_id'])

    def test_crash_after_service_commit_replays_receipt_once_without_redownload(self):
        self.configure()
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(1)])).encode())
        with patch.object(self.worker, '_finish', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                self.worker.run_one(self.a['id'], 'nfse_adn')
        self.assertEqual('000000000000001', self.state()['cursor'])
        self.clock[0] += 601
        self.worker = ReceptionAutomation(self.core, self.service, lambda: self.clock[0])
        self.worker.run_one(self.a['id'], 'nfse_adn')
        self.assertEqual(1, len(self.transport.plans))
        self.assertEqual(1, self.job()['pages'])

    def test_two_workers_share_lease_and_only_send_once(self):
        self.configure()
        entered, release = threading.Event(), threading.Event()
        original = self.transport.send
        def send(plan, identity):
            entered.set()
            self.assertTrue(release.wait(5))
            return original(plan, identity)
        self.transport.send = send
        other = ReceptionAutomation(self.core, self.service, lambda: self.clock[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.worker.run_one, self.a['id'], 'nfse_adn')
            self.assertTrue(entered.wait(5))
            self.assertFalse(other.run_one(self.a['id'], 'nfse_adn'))
            release.set()
            first.result(5)
        self.assertEqual(1, len(self.transport.plans))

    def test_nfe_positive_page_retry_after_is_applied_without_fixed_wait(self):
        from test_reception import response, SUMMARY
        self.configure('nfe_distribution')
        self.transport.reply = RemoteReply(200, response([('1', 'resNFe_v1.01.xsd', SUMMARY)], last='1', maximum='2'), 90)
        self.worker.tick()
        self.assertEqual('pending', self.job('nfe_distribution')['status'])
        self.assertEqual(self.clock[0] + 90, self.job('nfe_distribution')['next_run_at'])
        self.worker.tick()
        self.assertEqual(1, len(self.transport.plans))
        self.clock[0] += 91
        self.transport.reply = RemoteReply(200, response(status='137', last='1', maximum='1'))
        self.worker.tick()
        self.assertEqual('idle', self.job('nfe_distribution')['status'])
        self.assertEqual(2, len(self.transport.plans))

    def test_expired_in_progress_receipt_blocks_without_a_second_send(self):
        self.configure()
        claimed = self.worker._claim(self.a['id'], 'nfse_adn')
        from app.core import digest, pack, now
        from app.reception_service import RUN_SCOPE
        identity = digest({'provider': 'nfse_adn', 'environment': claimed['environment'],
                           'period': claimed['period'], 'target': remote.MATRIX})
        with self.core.db.transaction() as conn:
            conn.execute('INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)',
                (self.a['id'], RUN_SCOPE, claimed['attempt_id'], identity, pack({'state': 'in_progress'}), now()))
        self.clock[0] += 601
        self.worker.tick()
        self.assertEqual('blocked', self.job()['status'])
        self.assertEqual([], self.transport.plans)

    def test_configuration_change_requires_explicit_resave_and_resumes_same_cursor(self):
        self.configure()
        self.transport.reply = RemoteReply(200, json.dumps(adn.page([adn.packet(1)])).encode())
        self.worker.tick()
        from app.reception_workspace import ReceptionWorkspace
        workspace = ReceptionWorkspace(self.core, self.service)
        prefs = workspace.settings(self.a['id'], self.uid)['preferences']
        workspace.save_settings(self.a['id'], self.uid, 'synthetic', prefs)
        self.worker.tick()
        self.assertEqual('blocked', self.job()['status'])
        self.assertEqual(1, len(self.transport.plans))
        self.configure()
        self.transport.reply = self.end()
        self.worker.tick()
        self.assertEqual('idle', self.job()['status'])
        self.assertIn('/DFe/000000000000001', self.transport.plans[-1]['url'])

    def test_background_loop_runs_without_browser_session_and_stops_cleanly(self):
        self.configure()
        completed = threading.Event()
        tick = self.worker.tick
        def observe():
            tick()
            completed.set()
        self.worker.tick = observe
        async def scenario():
            from app.db import request_context
            token = request_context.set({'token_hash': 'expired-browser-session'})
            try:
                task = asyncio.create_task(self.worker.run())
                self.assertTrue(await asyncio.to_thread(completed.wait, 5))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                request_context.reset(token)
        asyncio.run(scenario())
        self.assertTrue(self.worker.stopping.is_set())
        self.assertEqual(1, len(self.transport.plans))
        self.assertEqual('000000000000002', self.state()['cursor'])

    def test_company_scope_and_optimistic_version_are_preserved(self):
        self.configure()
        self.assertFalse(self.worker.settings(self.b['id'], self.uid)['services']['nfse_adn']['enabled'])
        with self.assertRaises(DomainError):
            self.configure(version=0)
        self.worker.tick()
        self.assertTrue(all('cnpjConsulta=' + remote.BRANCH not in p['url'] for p in self.transport.plans))


if __name__ == '__main__':
    unittest.main()
