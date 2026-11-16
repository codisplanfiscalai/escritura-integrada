"""Versioned AES-256-GCM envelope; external keys, bounded streaming, no plaintext release before authentication."""
import base64
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
import struct

from Cryptodome.Cipher import AES
from Cryptodome.Protocol.KDF import scrypt

from . import backup_archive, backup_platform as platform
from .core import DomainError

MAGIC = b'EIBK\x00\x01\r\n'
TAG_BYTES = 16
HEADER_MAX = 512
BLOCK = 1024 * 1024
KEY_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')


@dataclass(frozen=True)
class Secret:
    mode: str
    value: bytes = field(repr=False)

    def derive(self, salt):
        if self.mode == 'raw' and len(self.value) == 32:
            return self.value
        if self.mode == 'scrypt-17' and 20 <= len(self.value) <= 1024:
            return scrypt(self.value, salt, 32, N=2**17, r=8, p=1)
        raise ValueError('Chave ou senha inválida.')


def read_key(path):
    """Linux/Unix private regular file; never follow a key-file symlink."""
    if platform.reparse(path): raise ValueError('Arquivo indireto recusado.')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 8192 or
                (not platform.WINDOWS and (info.st_mode & 0o077 or info.st_uid not in {0, os.geteuid()}))):
            raise ValueError('Arquivo de chave deve ser privado e pertencer ao usuário do processo ou root.')
        payload = json.loads(platform.decode_key(stream.read(8193)))
    if set(payload) != {'version', 'mode', 'secret'} or payload['version'] != 1:
        raise ValueError('Formato de chave inválido.')
    if payload['mode'] == 'raw':
        value = base64.b64decode(payload['secret'], validate=True)
        if len(value) != 32:
            raise ValueError('Chave inválida.')
    elif payload['mode'] == 'scrypt-17':
        value = payload['secret'].encode('utf-8')
        if not 20 <= len(value) <= 1024:
            raise ValueError('Senha deve conter entre 20 e 1024 bytes UTF-8.')
    else:
        raise ValueError('Modo de chave inválido.')
    return Secret(payload['mode'], value)


def load_key(key_id, data_dir):
    try:
        if not isinstance(key_id, str) or not KEY_ID.fullmatch(key_id):
            raise ValueError()
        root = Path(os.environ['ESCRITURA_BACKUP_KEYRING_DIR'])
        if platform.reparse(root):
            raise ValueError()
        root = root.resolve(strict=True)
        if root == Path(data_dir).resolve() or root.is_relative_to(Path(data_dir).resolve()):
            raise ValueError()
        if platform.WINDOWS:
            platform.private_directory(root, exist_ok=True)
        info = root.stat()
        if not platform.WINDOWS and (info.st_mode & 0o022 or info.st_uid not in {0, os.geteuid()}):
            raise ValueError()
        return read_key(root / (key_id + '.key'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise DomainError('Chave externa indisponível ou insegura. Confira o identificador, diretório fora dos dados e permissões privadas.', 422, 'backup_key') from None


def create_key(path, password=None):
    path = Path(path)
    if platform.WINDOWS and password is None:
        raise ValueError('Windows exige --passphrase e cópia offline da frase para recuperar em outro computador.')
    if password is None:
        payload = {'version': 1, 'mode': 'raw', 'secret': base64.b64encode(os.urandom(32)).decode('ascii')}
    else:
        if not 20 <= len(password.encode('utf-8')) <= 1024:
            raise ValueError('Use uma frase secreta longa: 20–1024 bytes UTF-8.')
        payload = {'version': 1, 'mode': 'scrypt-17', 'secret': password}
    encoded = platform.encode_key(json.dumps(payload).encode('utf-8'))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(encoded)
        stream.flush(); os.fsync(stream.fileno())


def _header(stream):
    prefix = stream.read(len(MAGIC) + 4)
    if len(prefix) != len(MAGIC) + 4 or prefix[:len(MAGIC)] != MAGIC:
        raise ValueError('Formato criptográfico inválido.')
    length = struct.unpack('>I', prefix[len(MAGIC):])[0]
    if not 1 <= length <= HEADER_MAX:
        raise ValueError('Cabeçalho inválido.')
    raw = stream.read(length)
    header = json.loads(raw)
    if set(header) != {'key_id', 'mode', 'salt', 'nonce', 'bytes'} or not KEY_ID.fullmatch(header['key_id']):
        raise ValueError('Cabeçalho inválido.')
    if header['mode'] not in {'raw', 'scrypt-17'} or type(header['bytes']) is not int or not 0 <= header['bytes'] <= backup_archive.MAX_BYTES:
        raise ValueError('Cabeçalho inválido.')
    salt = base64.b64decode(header['salt'], validate=True)
    nonce = base64.b64decode(header['nonce'], validate=True)
    if len(salt) != 16 or len(nonce) != 12:
        raise ValueError('Cabeçalho inválido.')
    return header, prefix + raw, salt, nonce


def encrypt(source, destination, key_id, secret, cancelled=lambda: False):
    if not KEY_ID.fullmatch(key_id):
        raise ValueError('Identificador de chave inválido.')
    salt, nonce = os.urandom(16), os.urandom(12)
    size = Path(source).stat().st_size
    header = json.dumps({'key_id': key_id, 'mode': secret.mode, 'salt': base64.b64encode(salt).decode('ascii'),
                         'nonce': base64.b64encode(nonce).decode('ascii'), 'bytes': size}, separators=(',', ':')).encode('ascii')
    aad = MAGIC + struct.pack('>I', len(header)) + header
    if size + len(aad) + TAG_BYTES > backup_archive.MAX_BYTES:
        raise DomainError(f'Pacote criptografado excede {backup_archive.MAX_BYTES // (1024*1024)} MiB; envio não iniciado.', 422, 'backup_size')
    cipher = AES.new(secret.derive(salt), AES.MODE_GCM, nonce=nonce, mac_len=TAG_BYTES)
    cipher.update(aad)
    destination = Path(destination)
    created = False
    try:
        with Path(source).open('rb') as src:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
            created = True
            with os.fdopen(fd, 'wb') as dst:
                dst.write(aad)
                count = 0
                for block in iter(lambda: src.read(BLOCK), b''):
                    if cancelled():
                        raise DomainError('Backup cancelado antes do envio.', 409, 'cancelled')
                    count += len(block)
                    if count > size:
                        raise ValueError('Arquivo alterado durante criptografia.')
                    dst.write(cipher.encrypt(block))
                if count != size:
                    raise ValueError('Arquivo alterado durante criptografia.')
                dst.write(cipher.digest()); dst.flush(); os.fsync(dst.fileno())
        return backup_archive.sha256(destination)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def restore(source, destination, expected_hash, *, secret=None, key_loader=None, work_dir=None):
    """Authenticate private staging in full BEFORE creating the destination directory."""
    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Destino já existe.')
    with source.open('rb') as src:
        import hashlib
        size = os.fstat(src.fileno()).st_size
        if size > backup_archive.MAX_BYTES:
            raise ValueError('Limite excedido.')
        if hashlib.file_digest(src, 'sha256').hexdigest() != expected_hash:
            raise ValueError('Checksum divergente.')
        src.seek(0)
        header, aad, salt, nonce = _header(src)
        if size != len(aad) + header['bytes'] + TAG_BYTES:
            raise ValueError('Arquivo truncado ou tamanho inválido.')
        if secret is None:
            secret = key_loader(header['key_id'])
        if secret.mode != header['mode']:
            raise ValueError('Chave ou senha incorreta.')
        cipher = AES.new(secret.derive(salt), AES.MODE_GCM, nonce=nonce, mac_len=TAG_BYTES)
        cipher.update(aad)
        # Unauthenticated bytes remain inaccessible under a private temporary directory.
        with platform.temporary_directory(work_dir or destination.parent, '.decrypt-') as work:
            plain = Path(work) / 'payload.zip'
            fd = os.open(plain, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
            with os.fdopen(fd, 'wb') as dst:
                remaining = header['bytes']
                while remaining:
                    block = src.read(min(BLOCK, remaining))
                    if not block:
                        raise ValueError('Arquivo truncado.')
                    remaining -= len(block)
                    dst.write(cipher.decrypt(block))
                cipher.verify(src.read(TAG_BYTES))
                dst.flush(); os.fsync(dst.fileno())
            return backup_archive.restore(plain, destination)


def build(database, destination, key_id, secret, cancelled=lambda: False, work_dir=None):
    with platform.temporary_directory(work_dir or Path(destination).parent, '.encrypt-') as work:
        plain = Path(work) / 'payload.zip'
        backup_archive.build(database, plain, cancelled)
        return encrypt(plain, destination, key_id, secret, cancelled)


def main():
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description='Chaves externas e recuperação isolada de backups autenticados.')
    sub = parser.add_subparsers(dest='command', required=True)
    generate = sub.add_parser('keygen')
    generate.add_argument('path', type=Path)
    generate.add_argument('--passphrase', action='store_true', help='Solicitar frase secreta sem eco; padrão: chave aleatória de 256 bits')
    recover = sub.add_parser('restore')
    recover.add_argument('archive', type=Path)
    recover.add_argument('destination', type=Path)
    recover.add_argument('--sha256', required=True)
    method = recover.add_mutually_exclusive_group(required=True)
    method.add_argument('--key-file', type=Path)
    method.add_argument('--password', action='store_true', help='Solicitar senha sem eco, apenas para arquivos scrypt')
    args = parser.parse_args()
    try:
        import sys
        if (getattr(args, 'passphrase', False) or getattr(args, 'password', False)) and not sys.stdin.isatty():
            raise ValueError('Senha exige terminal interativo sem eco.')
        if args.command == 'keygen':
            password = getpass.getpass('Frase secreta: ') if args.passphrase else None
            if password is not None and password != getpass.getpass('Repita a frase: '):
                raise ValueError()
            create_key(args.path, password)
            print('Arquivo de chave criado. Preserve uma cópia segura fora do backup.')
        else:
            secret = Secret('scrypt-17', getpass.getpass('Frase secreta: ').encode('utf-8')) if args.password else read_key(args.key_file)
            restore(args.archive, args.destination, args.sha256, secret=secret)
            print('Arquivo autenticado e cópia isolada validada; ativação não executada.')
    except (OSError, ValueError, KeyError, TypeError, DomainError):
        parser.exit(1, 'Operação recusada: confira chave/senha, integridade, limites e destino novo. Nenhum destino existente foi sobrescrito.\n')


if __name__ == '__main__':
    main()
