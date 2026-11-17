"""Local PKCS#12 reading/TLS-context matrix, never external authorization proof."""
from datetime import datetime,timedelta,timezone
import os,platform,ssl,unittest,shutil,subprocess,tempfile
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,rsa
from cryptography.hazmat.primitives.serialization.pkcs12 import PBES,serialize_key_and_certificates
from cryptography.x509.oid import NameOID,ObjectIdentifier
from app.reception_credentials import load_a1
from app.core import DomainError
from test_reception_remote import MATRIX,PASSWORD

@unittest.skipIf(platform.system()=='Darwin' and platform.machine()=='x86_64','Native Intel helper has its own physical macOS fixture suite')
class A1FormatsTests(unittest.TestCase):
    def test_rsa_and_ec_keys_modern_legacy_and_unprotected_pfx_with_chain(self):
        now=datetime.now(timezone.utc)
        ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SYNTHETIC CA NO FISCAL VALUE')])
        ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(ca_key,hashes.SHA256()))
        for algorithm,key in [('RSA-2048',rsa.generate_private_key(public_exponent=65537,key_size=2048)),
                              ('RSA-3072',rsa.generate_private_key(public_exponent=65537,key_size=3072)),
                              ('EC-P256',ec.generate_private_key(ec.SECP256R1()))]:
            leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SYNTHETIC A1')]))
                  .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                  .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
                  .add_extension(x509.SubjectAlternativeName([x509.OtherName(ObjectIdentifier('2.16.76.1.3.3'),b'\x0c\x0e'+MATRIX.encode())]),critical=False)
                  .sign(ca_key,hashes.SHA256()))
            modern=(serialization.PrivateFormat.PKCS12.encryption_builder().kdf_rounds(20000)
                    .key_cert_algorithm(PBES.PBESv2SHA256AndAES256CBC).hmac_hash(hashes.SHA256()).build(PASSWORD))
            legacy=(serialization.PrivateFormat.PKCS12.encryption_builder().kdf_rounds(20000)
                    .key_cert_algorithm(PBES.PBESv1SHA1And3KeyTripleDESCBC).hmac_hash(hashes.SHA1()).build(PASSWORD))
            for protection,encryption,password in [('PBES2-AES256',modern,PASSWORD.decode()),('PBES1-3DES',legacy,PASSWORD.decode()),('unprotected',serialization.NoEncryption(),'')]:
                with self.subTest(key=algorithm,container=protection,signature='RSA-SHA256',chain=True):
                    raw=serialize_key_and_certificates(b'SYNTHETIC',key,leaf,[ca],encryption)
                    identity=load_a1(raw,password,MATRIX,'nfe_distribution','homologation')
                    self.assertEqual(MATRIX,identity.tax_id);self.assertTrue(identity.context.check_hostname)
                    self.assertEqual(ssl.CERT_REQUIRED,identity.context.verify_mode)
                    self.assertGreaterEqual(identity.context.minimum_version,ssl.TLSVersion.TLSv1_2)
                    if password:
                        with self.assertRaises(DomainError):load_a1(raw,'WRONG-SYNTHETIC',MATRIX,'nfe_distribution','homologation')

    @unittest.skipUnless(shutil.which('openssl'),'OpenSSL executable required to generate the RC2-40 synthetic fixture')
    def test_rc2_40_container_is_read_locally_without_enabling_legacy_tls(self):
        from test_reception_remote import make_certificate
        key,certificate=make_certificate()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,content in [('certificate.pem',certificate.public_bytes(serialization.Encoding.PEM)),
                                 ('key.pem',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(PASSWORD)))]:
                descriptor=os.open(root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(descriptor,'wb') as output:output.write(content)
            output=root/'SYNTHETIC.p12'
            result=subprocess.run([shutil.which('openssl'),'pkcs12','-export','-legacy','-certpbe','RC2-40-CBC',
                '-keypbe','PBE-SHA1-3DES','-in',str(root/'certificate.pem'),'-inkey',str(root/'key.pem'),'-out',str(output),
                '-passin','env:ESCRITURA_TEST_SYNTHETIC_PASSWORD','-passout','env:ESCRITURA_TEST_SYNTHETIC_PASSWORD'],
                env=dict(os.environ,ESCRITURA_TEST_SYNTHETIC_PASSWORD=PASSWORD.decode()),capture_output=True,timeout=20)
            if result.returncode:
                self.skipTest('OpenSSL CLI/provider cannot generate RC2-40 fixture here; no claim of reader compatibility on this platform.')
            identity=load_a1(output.read_bytes(),PASSWORD.decode(),MATRIX,'nfe_distribution','homologation')
            self.assertEqual(MATRIX,identity.tax_id);self.assertTrue(identity.context.check_hostname)
            self.assertEqual(ssl.CERT_REQUIRED,identity.context.verify_mode)
            self.assertGreaterEqual(identity.context.minimum_version,ssl.TLSVersion.TLSv1_2)
            with self.assertRaises(DomainError):load_a1(output.read_bytes(),'WRONG-SYNTHETIC',MATRIX,'nfe_distribution','homologation')
