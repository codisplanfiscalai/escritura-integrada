"""Local A1 credentials. Never accepts certificates or secrets from HTTP."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import platform
import sys
from pathlib import Path
import re
import secrets
import ssl
import stat
import tempfile

from .core import DomainError, normalize_cnpj


def _private_file(path, limit):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or (os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
            raise ValueError()
        with path.open('rb') as source:
            raw = source.read(limit + 1)
        if not raw or len(raw) > limit:
            raise ValueError()
        return raw
    except (OSError, ValueError):
        raise DomainError('Arquivo de credencial ausente, inseguro ou fora do limite. Confira a configuração local.', 503, 'reception_credentials') from None


def _cnpj(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{14}', value):
        raise DomainError('O transporte A1 deste incremento exige CNPJ numérico válido.', 422, 'reception_tax_id')
    return normalize_cnpj(value)


def adn_access_mode(target, holder, allow_procuration=False):
    target, holder = _cnpj(target), _cnpj(holder)
    if type(allow_procuration) is not bool:
        raise DomainError('Configuração de procuração inválida.', 503, 'reception_credentials')
    if target == holder:
        return 'InscricaoCertificado'
    if target[:8] == holder[:8]:
        return 'CnpjBase'
    if not allow_procuration:
        raise DomainError('Certificado de outra raiz: configure separadamente a consulta mediante procuração válida. A autorização será verificada pelo ADN.', 409, 'reception_procuration_required')
    return 'Procuracao'


def certificate_cnpj(cert):
    from cryptography import x509
    from cryptography.x509.oid import ObjectIdentifier
    try:
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        values = [n.value for n in names if isinstance(n, x509.OtherName) and n.type_id == ObjectIdentifier('2.16.76.1.3.3')]
        if len(values) != 1:
            raise ValueError()
        # DER primitive UTF8String / PrintableString / IA5String, exactly 14 bytes.
        raw = values[0]
        if len(raw) != 16 or raw[0] not in {0x0c, 0x13, 0x16} or raw[1] != 14:
            raise ValueError()
        return _cnpj(raw[2:].decode('ascii'))
    except (x509.ExtensionNotFound, ValueError, UnicodeError, DomainError):
        raise DomainError('Certificado sem CNPJ único e válido no campo ICP-Brasil esperado. CPF/A3 e outras variantes ainda não estão habilitados.', 503, 'reception_certificate_identity') from None


@dataclass(frozen=True)
class ClientIdentity:
    tax_id: str
    context: ssl.SSLContext = field(repr=False, compare=False)
    allow_procuration: bool = False


class LocalA1Credentials:
    """Operator-managed directory, outside application backups and Git artifacts."""
    def __init__(self, directory=None):
        self.directory = directory

    def load(self, company_id, target, provider, environment):
        configured = self.directory or os.environ.get('ESCRITURA_RECEPTION_CREDENTIALS_DIR')
        if not configured:
            raise DomainError('Recepção remota não configurada. Configure o A1 localmente de forma segura; não envie certificado ou senha pelo chat.', 503, 'reception_not_configured')
        root = Path(configured).expanduser()
        try:
            info = root.lstat()
            if not root.is_absolute() or not stat.S_ISDIR(info.st_mode) or root.is_symlink() or (os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
                raise ValueError()
            config = json.loads(_private_file(root / 'profiles.json', 100_000))
            profile = config['companies'][str(company_id)]
            if not isinstance(profile, dict) or set(profile) - {'tax_id','pfx_file','password_env','environments','allow_adn_procuration'}:
                raise ValueError()
            if profile['tax_id'] != _cnpj(target):
                raise ValueError()
            enabled = profile['environments']
            if not isinstance(enabled, dict) or provider not in enabled or not isinstance(enabled[provider], list) or environment not in enabled[provider]:
                raise DomainError('Provedor/ambiente não habilitado para esta empresa na configuração local.', 409, 'reception_environment_disabled')
            filename = profile['pfx_file']
            if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,120}\.(?:pfx|p12)', filename):
                raise ValueError()
            variable = profile['password_env']
            if not isinstance(variable, str) or not re.fullmatch(r'ESCRITURA_RECEPTION_PASSWORD_[A-Z0-9_]{1,80}', variable):
                raise ValueError()
            password = os.environ.get(variable)
            if not password:
                raise ValueError()
            allow = profile.get('allow_adn_procuration', False)
            if type(allow) is not bool:
                raise ValueError()
        except DomainError:
            raise
        except (OSError, KeyError, TypeError, ValueError):
            raise DomainError('Perfil local de recepção inválido ou senha local indisponível.', 503, 'reception_credentials') from None
        raw = _private_file(root / filename, 5_000_000)
        if sys.platform == 'darwin' and platform.machine() == 'x86_64':
            from .reception_native import NativeA1Bridge
            return NativeA1Bridge().load(raw,password,target,provider,environment,allow)
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
        except ImportError:
            raise DomainError('Runtime A1 incompleto. Confira a instalação do aplicativo antes de habilitar o transporte.', 503, 'reception_dependency_missing') from None
        try:
            key, cert, chain = load_key_and_certificates(raw, password.encode())
            if key is None or cert is None:
                raise ValueError()
            holder = certificate_cnpj(cert)
            clock = datetime.now(timezone.utc)
            if not cert.not_valid_before_utc <= clock < cert.not_valid_after_utc:
                raise DomainError('Certificado fora da validade; consulta não executada.', 409, 'reception_certificate_expired')
            if provider == 'nfe_distribution':
                if _cnpj(target)[:8] != holder[:8]:
                    raise DomainError('Distribuição NF-e exige certificado da mesma raiz da empresa consultada neste adaptador.', 409, 'reception_certificate_identity')
            else:
                adn_access_mode(target, holder, allow)
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            # SSLContext accepts files. Only encrypted ephemeral PEM is written,
            # with owner-only permissions, removed before returning the context.
            temporary_password = secrets.token_urlsafe(32).encode()
            encrypted_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.BestAvailableEncryption(temporary_password))
            public_chain = b''.join(c.public_bytes(serialization.Encoding.PEM) for c in [cert, *(chain or [])])
            with tempfile.TemporaryDirectory(prefix='escritura-a1-') as directory:
                for name, content in [('key.pem', encrypted_key), ('chain.pem', public_chain)]:
                    path = Path(directory) / name
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'wb') as output:
                        output.write(content)
                context.load_cert_chain(str(Path(directory) / 'chain.pem'), str(Path(directory) / 'key.pem'), lambda: temporary_password)
            return ClientIdentity(holder, context, allow)
        except DomainError:
            raise
        except (OSError, TypeError, ValueError, ssl.SSLError):
            raise DomainError('Não foi possível carregar o A1. Confira arquivo, senha e compatibilidade local.', 503, 'reception_credentials') from None
