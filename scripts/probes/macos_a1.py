"""Experimental native macOS A1 probe; synthetic credentials and loopback only.

Not a fiscal transport. No network downloads or installation, no production
credentials, no fallback cipher, no keychain import and no app runtime changes.
"""
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import uuid


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError('Synthetic probe command failed: '+str(command[0])+('\n'+result.stderr.decode(errors='replace')[:4000] if str(command[0]).endswith('swiftc') else ''))
    return result.stdout


def main():
    if sys.platform != 'darwin':
        print(json.dumps({'ok':False,'state':'not_executed','reason':'native_macos_required'}))
        return 2
    openssl = '/usr/bin/openssl'
    swift = shutil.which('swiftc')
    if not swift:
        raise RuntimeError('Native Swift toolchain unavailable')
    original_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-native-a1-probe-') as folder:
            root = Path(folder)
            def command(*args): return run([openssl,*map(str,args)],cwd=root)
            (root/'ca.conf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca\nprompt=no\n[dn]\nCN=SYNTHETIC PROBE CA\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n')
            print(json.dumps({'probe_start':True,'machine':platform.machine(),
                              'openssl':command('version').decode().strip()}),flush=True)
            command('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.pem','-days','1',
                    '-config','ca.conf')
            for name,extensions in [('server','subjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE'),
                                    ('client','subjectAltName=otherName:2.16.76.1.3.3;UTF8:11222333000181\nextendedKeyUsage=clientAuth\nbasicConstraints=CA:FALSE')]:
                label='SYNTHETIC-'+name+'-'+uuid.uuid4().hex
                command('req','-newkey','rsa:2048','-nodes','-keyout',name+'.key','-out',name+'.csr','-subj','/CN='+label)
                (root/(name+'.ext')).write_text(extensions+'\n')
                command('x509','-req','-in',name+'.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial',
                        '-out',name+'.pem','-days','1','-extfile',name+'.ext')
            # Modern PFX only; no -legacy, weak PBE or MAC verification bypass.
            password='SYNTHETIC-ONLY-'+uuid.uuid4().hex
            run([openssl,'pkcs12','-export','-in','client.pem','-inkey','client.key','-out','client.p12',
                 '-keypbe','AES-256-CBC','-certpbe','AES-256-CBC','-macalg','sha256','-passout','stdin'],
                cwd=root,input=(password+'\n').encode())
            der = command('x509','-in','client.pem','-outform','DER')
            (root/'ca.der').write_bytes(command('x509','-in','ca.pem','-outform','DER'))
            observed=[]
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path!='/probe': self.send_error(404);return
                    observed.append(self.connection.getpeercert(binary_form=True))
                    body=b'synthetic-mtls-ok'
                    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                def log_message(self,*args):pass
            server=HTTPServer(('127.0.0.1',0),Handler)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(root/'server.pem',root/'server.key')
            context.load_verify_locations(root/'ca.pem');context.verify_mode=ssl.CERT_REQUIRED
            server.socket=context.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                binary=root/'native-probe'
                source=Path(__file__).with_suffix('.swift').resolve()
                run([swift,'-swift-version','5',str(source),'-framework','Security','-o',str(binary)])
                payload={'pfx':str(root/'client.p12'),'password':password,'expectedDER':base64.b64encode(der).decode(),
                         'ca':str(root/'ca.der'),'port':server.server_port,'presentClient':True}
                def invoke(changes):
                    return subprocess.run([str(binary)],input=json.dumps(payload|changes).encode(),capture_output=True,timeout=25)
                positive=invoke({})
                if positive.returncode or observed!=[der]:
                    raise RuntimeError('Native memory-only/PBES2/mTLS probe failed: '+positive.stdout.decode(errors='replace')[:250])
                for changes,expected in [({'password':'WRONG-SYNTHETIC'},10),({'presentClient':False},20)]:
                    negative=invoke(changes)
                    if negative.returncode!=expected:raise RuntimeError('Native negative probe failed')
                print(json.dumps({'ok':True,'machine':platform.machine(),'macos':platform.mac_ver()[0],
                    'memory_only_identity':True,'modern_pfx':True,'local_mtls_peer_matches':True,
                    'wrong_password_rejected':True,'client_certificate_required':True,
                    'production_adapter_enabled':False}))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)
    finally:
        os.umask(original_umask)
    return 0


if __name__=='__main__':sys.exit(main())
