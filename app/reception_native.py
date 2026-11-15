"""macOS A1 bridge: bounded private IPC to the bundled, signed native helper.

Only Intel selects this backend automatically. Domain/RBAC/lease/storage remain
in ReceptionService. Password/PFX never appear in argv, repr, logs or receipts.
"""
from dataclasses import dataclass, field
import base64
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from .core import DomainError
from .importers import MAX_FILE_BYTES, _xml_tree
from .reception import (ADN_ENDPOINTS, NFE_ENDPOINTS, NFE_NS, adn_nsu, adn_request,
                        nfe_request, nsu)
from .reception_credentials import _cnpj, adn_access_mode

PROTOCOL = 1
MAX_IPC = 30 * 1024 * 1024


def _error(code='reception_native_invalid', status=503):
    raise DomainError('A1 nativo não concluiu a validação/operação. Confira a instalação e a configuração local; cursor preservado.',status,code)


@dataclass(frozen=True)
class NativeIdentity:
    tax_id: str
    allow_procuration: bool
    target: str
    provider: str
    environment: str
    certificate_sha256: str
    pfx: bytes = field(repr=False,compare=False)
    password: str = field(repr=False,compare=False)
    bridge: object = field(repr=False,compare=False)


class NativeA1Bridge:
    def __init__(self, binary=None):
        self.binary = Path(binary) if binary is not None else None

    def _binary(self):
        if self.binary is not None:
            path = self.binary
        elif getattr(sys,'frozen',False):
            path = Path(sys.executable).parent/'EscrituraA1'
        else:
            path = Path(__file__).resolve().parents[1]/'build/native-a1/EscrituraA1'
        manifest = (path.parent.parent/'Resources/native/manifest.json' if path.parent.name=='MacOS' and path.parent.parent.name=='Contents' else path.with_name('manifest.json'))
        try:
            for entry in (path,manifest):
                info=entry.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
                    _error('reception_native_installation')
            if not path.is_absolute() or not os.access(path,os.X_OK) or path.stat().st_size>30*1024*1024 or manifest.stat().st_size>4096:
                _error('reception_native_installation')
            metadata=json.loads(manifest.read_bytes())
            if not isinstance(metadata,dict) or metadata.get('protocol')!=PROTOCOL or metadata.get('build')!='production' or metadata.get('architecture')!=platform.machine() or metadata.get('sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():
                _error('reception_native_installation')
            result=subprocess.run(['/usr/bin/codesign','--verify','--strict',str(path)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,check=False)
            if result.returncode:
                _error('reception_native_installation')
            return path
        except DomainError:
            raise
        except (OSError,ValueError,subprocess.SubprocessError):
            _error('reception_native_installation')

    def _invoke(self, payload):
        path=self._binary()
        request=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        if len(request)>8*1024*1024:
            _error('reception_native_size')
        # Output is private and immediately removed; a bounded read additionally
        # protects Python independently of the native response streaming limit.
        try:
            with tempfile.TemporaryFile() as output:
                process=subprocess.Popen([str(path)],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.DEVNULL,
                    close_fds=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
                try:
                    process.communicate(request,timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate();_error('reception_transport_uncertain',502)
                output.seek(0);raw=output.read(MAX_IPC+1)
                if len(raw)>MAX_IPC:
                    _error('reception_native_size',502)
            result=json.loads(raw)
            if not isinstance(result,dict) or result.get('protocol')!=PROTOCOL or result.get('build')!='production':
                _error()
            if process.returncode or result.get('ok') is not True:
                allowed={'reception_certificate_identity','reception_certificate_expired','reception_credentials',
                         'reception_operation','reception_endpoint','reception_response_size','reception_response_encoding',
                         'reception_transport_uncertain','reception_native_pin'}
                code=result.get('code')
                _error(code if isinstance(code,str) and code in allowed else 'reception_native_invalid',502 if payload['action']=='query' else (409 if code=='reception_certificate_expired' else 503))
            return result
        except DomainError:
            raise
        except (OSError,ValueError,subprocess.SubprocessError):
            _error('reception_transport_uncertain' if payload['action']=='query' else 'reception_native_invalid',502 if payload['action']=='query' else 503)

    def load(self, raw, password, target, provider, environment, allow):
        if not isinstance(raw,bytes) or not 0<len(raw)<=5_000_000 or not isinstance(password,str) or not 0<len(password.encode())<=4096:
            _error('reception_credentials')
        result=self._invoke({'protocol':PROTOCOL,'action':'inspect','pfx_base64':base64.b64encode(raw).decode(),'password':password})
        holder=_cnpj(result.get('holder_tax_id'))
        fingerprint=result.get('certificate_sha256')
        dates=[result.get('not_before'),result.get('not_after')]
        if not isinstance(fingerprint,str) or not re.fullmatch('[0-9a-f]{64}',fingerprint) or any(type(v) not in (int,float) or not math.isfinite(v) for v in dates):
            _error('reception_certificate_identity')
        if not dates[0]<=time.time()<dates[1]:
            _error('reception_certificate_expired',409)
        if provider=='nfse_adn':
            adn_access_mode(target,holder,allow)
        elif provider=='nfe_distribution' and _cnpj(target)[:8]==holder[:8]:
            pass
        else:
            _error('reception_certificate_identity',409)
        return NativeIdentity(holder,allow,target,provider,environment,fingerprint,raw,password,self)

    def _parameters(self, plan, identity):
        provider=plan.get('provider')
        if provider!=identity.provider:
            _error('reception_operation',400)
        if provider=='nfse_adn':
            number=adn_nsu(urlsplit(plan.get('url','')).path.rsplit('/',1)[-1])
            expected=adn_request(identity.target,identity.environment,number,certificate_tax_id=identity.tax_id,allow_procuration=identity.allow_procuration)
            if plan.get('url')!=expected['url'] or plan.get('method')!='GET' or plan.get('body'):
                _error('reception_operation',400)
            return {'last_nsu':number}
        if provider=='nfe_distribution':
            if plan.get('method')!='POST' or plan.get('url')!=NFE_ENDPOINTS.get(identity.environment):
                _error('reception_operation',400)
            root=_xml_tree(plan.get('body',b''))
            selectors=list(root.iter('{'+NFE_NS+'}distDFeInt'))
            if len(selectors)!=1:
                _error('reception_operation',400)
            selected=selectors[0]
            def value(name):
                matches=selected.findall('{'+NFE_NS+'}'+name)
                if len(matches)!=1 or not matches[0].text:_error('reception_operation',400)
                return matches[0].text
            number=nsu(value('distNSU/{'+NFE_NS+'}ultNSU'))
            uf=value('cUFAutor')
            if value('CNPJ')!=identity.target or value('tpAmb')!=('1' if identity.environment=='production' else '2'):
                _error('reception_operation',400)
            nfe_request(identity.target,uf,identity.environment,number)
            return {'last_nsu':number,'uf_code':uf}
        _error('reception_operation',400)

    def send(self, plan, identity):
        try:
            parameters=self._parameters(plan,identity)
        except (ValueError,TypeError,AttributeError):
            _error('reception_operation',400)
        result=self._invoke({'protocol':PROTOCOL,'action':'query','pfx_base64':base64.b64encode(identity.pfx).decode(),
            'password':identity.password,'target':identity.target,'provider':identity.provider,'environment':identity.environment,
            'allow_procuration':identity.allow_procuration,'expected_holder':identity.tax_id,
            'certificate_sha256':identity.certificate_sha256,**parameters})
        if result.get('certificate_sha256')!=identity.certificate_sha256 or result.get('holder_tax_id')!=identity.tax_id:
            _error('reception_native_pin',502)
        status=result.get('http_status');retry=result.get('retry_after',0)
        try:
            body=base64.b64decode(result.get('body_base64',''),validate=True)
        except (ValueError,TypeError):
            _error('reception_native_invalid',502)
        if type(status) is not int or not 100<=status<=599 or len(body)>MAX_FILE_BYTES or type(retry) is not int or not 0<=retry<=86400:
            _error('reception_native_invalid',502)
        from .reception_transport import RemoteReply
        return RemoteReply(status,body,retry)
