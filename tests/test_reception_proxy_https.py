"""Incoming HTTP/HTTPS A1 enrollment and independent proxy trust; synthetic only."""
import json,unittest,socket,threading,time
from unittest.mock import patch
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import test_reception_vault as vault
from app.reverse_proxy import forwarded_allow_ips

class ProxyHttpsTests(unittest.TestCase):
    baseSetUp=vault.VaultTests.baseSetUp
    setUp=vault.VaultTests.setUp
    tearDown=vault.VaultTests.tearDown
    tearDownBase=vault.VaultTests.tearDownBase
    create_company=vault.VaultTests.create_company
    activate=vault.VaultTests.activate
    scope=vault.VaultTests.scope
    def upload(self,peer,headers,scheme='http'):
        middleware=ProxyHeadersMiddleware(self.app,trusted_hosts=forwarded_allow_ips({'FORWARDED_ALLOW_IPS':'10.20.0.2'}))
        with TestClient(middleware,base_url=scheme+'://testserver',client=(peer,1234),headers=dict(self.client.headers),cookies=self.client.cookies) as client:
            return client.post(self.scope('/reception-credential'),headers=headers,
                data={'password':vault.PASSWORD.decode(),'options':json.dumps(self.options|{'version':self.vault.status(self.a['id'],self.uid)['version']})},
                files={'certificate':('SYNTHETIC.P12',self.raw,'application/x-pkcs12')})
    def test_authenticated_http_upload_does_not_require_proxy_or_https_headers(self):
        for peer,headers in [('203.0.113.7',{}),('203.0.113.7',{'X-Forwarded-Proto':'https'}),
                             ('10.20.0.2',{}),('10.20.0.2',{'X-Forwarded-Proto':'http'}),
                             ('203.0.113.7',{'Forwarded':'proto=https;for=10.20.0.2','X-Forwarded-For':'10.20.0.2'})]:
            r=self.upload(peer,headers);self.assertEqual(200,r.status_code,r.text)
            self.assertEqual(vault.MATRIX,self.vault.load(self.a['id'],vault.MATRIX,'nfe_distribution','homologation').tax_id)
        r=self.upload('10.20.0.2',{'X-Forwarded-Proto':'https','X-Forwarded-For':'203.0.113.7'})
        self.assertEqual(200,r.status_code,r.text)
        self.assertEqual(vault.MATRIX,self.vault.load(self.a['id'],vault.MATRIX,'nfe_distribution','homologation').tax_id)
        self.assertFalse(self.vault.status(self.b['id'],self.uid)['configured'])
    def test_native_https_does_not_require_forwarded_headers(self):
        self.assertEqual(200,self.upload('203.0.113.7',{},scheme='https').status_code)
    def test_real_http_listener_accepts_authenticated_a1_without_forwarded_https(self):
        import httpx,uvicorn
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
        server=uvicorn.Server(uvicorn.Config(self.app,host='127.0.0.1',port=listener.getsockname()[1],
            proxy_headers=True,forwarded_allow_ips='10.20.0.2',lifespan='off',log_level='critical',access_log=False))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.02)
            self.assertTrue(server.started)
            with httpx.Client(base_url='http://127.0.0.1:'+str(listener.getsockname()[1]),
                              cookies=dict(self.client.cookies),headers=dict(self.client.headers),trust_env=False,timeout=5) as client:
                r=client.post(self.scope('/reception-credential'),
                    headers={'Host':'public.example.invalid'},
                    data={'password':vault.PASSWORD.decode(),'options':json.dumps(self.options)},
                    files={'certificate':('SYNTHETIC.P12',self.raw,'application/x-pkcs12')})
            self.assertEqual(200,r.status_code,r.text)
            self.assertEqual(vault.MATRIX,self.vault.load(self.a['id'],vault.MATRIX,'nfe_distribution','homologation').tax_id)
        finally:
            server.should_exit=True;thread.join(timeout=5);listener.close()
        self.assertFalse(thread.is_alive())
    def test_container_entry_accepts_explicit_ips_and_cidrs_and_rejects_global_trust(self):
        self.assertEqual('127.0.0.1',forwarded_allow_ips({}))
        self.assertEqual('',forwarded_allow_ips({'FORWARDED_ALLOW_IPS':''}))
        self.assertEqual('10.20.0.2,2001:db8::1,10.20.0.0/28',forwarded_allow_ips({'FORWARDED_ALLOW_IPS':'10.20.0.2, 2001:db8::1,10.20.0.0/28'}))
        for invalid in ['*','0.0.0.0/0','::/0','proxy.example.invalid','10.20.0.2,','unknown']:
            with self.assertRaises(ValueError):forwarded_allow_ips({'FORWARDED_ALLOW_IPS':invalid})
        from scripts import run_container
        with patch.dict('os.environ',{'FORWARDED_ALLOW_IPS':'10.20.0.2'}),patch.object(run_container,'create_app',return_value=object()),patch.object(run_container.uvicorn,'run') as run:
            run_container.main()
        self.assertTrue(run.call_args.kwargs['proxy_headers']);self.assertEqual('10.20.0.2',run.call_args.kwargs['forwarded_allow_ips'])
