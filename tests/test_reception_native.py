"""Native bridge policy/IPC with synthetic data; real Apple TLS is tested on CI."""
import base64
from dataclasses import replace
import hashlib
import json
import os
import platform
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.core import DomainError, cnpj_digits
from app.reception import adn_request, nfe_request
from app.reception_native import NativeA1Bridge, NativeIdentity
from app.reception_transport import MtlsTransport

MATRIX='11222333000181'
BRANCH='112223330002'+cnpj_digits('112223330002')
THIRD='998887770001'+cnpj_digits('998887770001')
PFX=b'SYNTHETIC-PFX-NOT-A-CERTIFICATE'
PASSWORD='SYNTHETIC-NOT-A-SECRET'
SHA='a'*64


def metadata(holder=MATRIX):
    return {'ok':True,'protocol':1,'build':'production','holder_tax_id':holder,'certificate_sha256':SHA,
            'not_before':time.time()-60,'not_after':time.time()+600}


class NativeBridgeTests(unittest.TestCase):
    def load(self,holder=MATRIX,target=MATRIX,allow=False,provider='nfse_adn',environment='restricted_production'):
        bridge=NativeA1Bridge()
        with patch.object(bridge,'_invoke',return_value=metadata(holder)):
            identity=bridge.load(PFX,PASSWORD,target,provider,environment,allow)
        return bridge,identity

    def test_identity_is_bound_to_company_provider_environment_and_hides_credentials(self):
        bridge,identity=self.load(target=BRANCH)
        self.assertEqual(MATRIX,identity.tax_id);self.assertEqual(BRANCH,identity.target)
        self.assertNotIn(PASSWORD,repr(identity));self.assertNotIn(PFX.decode(),repr(identity))
        for holder,target,allow in [(MATRIX,THIRD,False),(THIRD,MATRIX,False)]:
            with self.assertRaises(DomainError):self.load(holder,target,allow)
        self.assertTrue(self.load(THIRD,MATRIX,True)[1].allow_procuration)
        with self.assertRaises(DomainError):self.load(THIRD,MATRIX,True,'nfe_distribution','homologation')

    def test_invalid_dates_cnpj_or_fingerprint_refuse_before_transport(self):
        changes=[{'holder_tax_id':'00000000000000'},{'certificate_sha256':'invalid'},
                 {'not_before':time.time()+3600},{'not_after':time.time()-1},{'not_before':True},
                 {'not_before':float('nan')},{'not_after':None}]
        for change in changes:
            with self.subTest(change=change),patch.object(NativeA1Bridge,'_invoke',return_value=metadata()|change),self.assertRaises(DomainError):
                NativeA1Bridge().load(PFX,PASSWORD,MATRIX,'nfse_adn','production',False)

    def test_adn_plan_requires_exact_target_mode_and_environment(self):
        bridge,identity=self.load(target=BRANCH)
        plan=adn_request(BRANCH,'restricted_production','42',certificate_tax_id=MATRIX)|{'provider':'nfse_adn'}
        self.assertEqual({'last_nsu':'000000000000042'},bridge._parameters(plan,identity))
        for changed in [plan|{'method':'POST'},plan|{'body':b'fake'},plan|{'provider':'nfe_distribution'},
                        plan|{'url':plan['url'].replace(BRANCH,MATRIX)},plan|{'url':plan['url'].replace('.producaorestrita','')},
                        plan|{'url':plan['url']+'&cpfConsulta=12345678909'},plan|{'url':'https://evil.invalid/'}]:
            with self.subTest(plan=changed),self.assertRaises((DomainError,ValueError)):
                bridge._parameters(changed,identity)

    def test_nfe_plan_is_reduced_to_validated_distribution_parameters(self):
        bridge,identity=self.load(provider='nfe_distribution',environment='homologation')
        plan=nfe_request(MATRIX,'35','homologation','42')|{'provider':'nfe_distribution'}
        self.assertEqual({'last_nsu':'000000000000042','uf_code':'35'},bridge._parameters(plan,identity))
        for changed in [plan|{'body':b'<envEvento/>'},plan|{'body':plan['body'].replace(MATRIX.encode(),THIRD.encode())},
                        plan|{'url':plan['url'].replace('hom.','www1.')},plan|{'method':'DELETE'}]:
            with self.assertRaises((DomainError,ValueError)):bridge._parameters(changed,identity)

    def test_native_send_returns_bounded_original_and_binds_certificate_pin(self):
        bridge,identity=self.load()
        plan=adn_request(MATRIX,'restricted_production','0',certificate_tax_id=MATRIX)|{'provider':'nfse_adn'}
        response=metadata()|{'http_status':200,'retry_after':0,'body_base64':base64.b64encode(b'{"synthetic":true}').decode()}
        with patch.object(bridge,'_invoke',return_value=response) as invoke:
            reply=MtlsTransport().send(plan,identity)
        self.assertEqual(b'{"synthetic":true}',reply.body)
        sent=invoke.call_args.args[0]
        self.assertEqual(SHA,sent['certificate_sha256']);self.assertEqual('000000000000000',sent['last_nsu'])
        self.assertNotIn('url',sent);self.assertNotIn('body',sent);self.assertNotIn('ca',sent)
        for changed in [{'certificate_sha256':'b'*64},{'holder_tax_id':BRANCH},{'http_status':True},
                        {'body_base64':'invalid'},{'retry_after':-1},{'http_status':700}]:
            with patch.object(bridge,'_invoke',return_value=response|changed),self.assertRaises(DomainError):
                bridge.send(plan,identity)

    def test_shared_transport_rejects_bad_destination_before_native_call(self):
        bridge,identity=self.load()
        with patch.object(bridge,'send') as send,self.assertRaises(DomainError):
            MtlsTransport().send({'provider':'nfse_adn','method':'GET','url':'https://evil.invalid/'},identity)
        send.assert_not_called()

    @unittest.skipIf(os.name=='nt','Native helper uses POSIX permissions')
    def test_binary_manifest_hash_permissions_and_signature_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'EscrituraA1';path.write_bytes(b'SYNTHETIC-EXECUTABLE');path.chmod(0o755)
            manifest=path.with_name('manifest.json')
            data={'protocol':1,'build':'production','architecture':platform.machine(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            manifest.write_text(json.dumps(data));manifest.chmod(0o644)
            bridge=NativeA1Bridge(path)
            with patch('app.reception_native.subprocess.run',return_value=subprocess.CompletedProcess([],0)) as verify:
                self.assertEqual(path,bridge._binary())
                self.assertEqual(['/usr/bin/codesign','--verify','--strict',str(path)],verify.call_args.args[0])
                for change in [{'build':'testing'},{'sha256':'0'*64}]:
                    manifest.write_text(json.dumps(data|change))
                    with self.assertRaises(DomainError):bridge._binary()
                manifest.write_text(json.dumps(data));path.chmod(0o777)
                with self.assertRaises(DomainError):bridge._binary()
                path.chmod(0o755)
            with patch('app.reception_native.subprocess.run',return_value=subprocess.CompletedProcess([],1)),self.assertRaises(DomainError):bridge._binary()

    @unittest.skipIf(os.name=='nt','Synthetic POSIX executable; macOS helper is not used on Windows')
    def test_ipc_uses_stdin_not_argv_environment_or_stderr(self):
        # A trusted test executable stands in for the signed helper; no network.
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-helper'
            response=metadata()
            path.write_text('#!'+sys.executable+'\nimport json,sys\na=json.load(sys.stdin)\nassert a["password"]=='+repr(PASSWORD)+'\nprint('+repr(json.dumps(response))+')\n')
            path.chmod(0o700);bridge=NativeA1Bridge(path)
            actual=subprocess.Popen
            with patch.object(bridge,'_binary',return_value=path),patch('app.reception_native.subprocess.Popen',side_effect=actual) as start:
                result=bridge._invoke({'protocol':1,'action':'inspect','password':PASSWORD})
            self.assertEqual(MATRIX,result['holder_tax_id'])
            self.assertEqual([str(path)],start.call_args.args[0])
            self.assertEqual(subprocess.DEVNULL,start.call_args.kwargs['stderr'])
            self.assertNotIn(PASSWORD,str(start.call_args.kwargs['env']))
            path.write_text('#!'+sys.executable+'\nprint("not JSON")\n')
            with patch.object(bridge,'_binary',return_value=path),self.assertRaises(DomainError):bridge._invoke({'action':'inspect'})


if __name__=='__main__':unittest.main()
