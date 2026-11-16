"""Bounded HTTPS uploads, explicit credentials, no redirects or automatic retries."""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from .backup_archive import sha256
from . import backup_archive
from .core import DomainError


CHUNK_BYTES = 8 * 1024 * 1024  # Drive chunks must be multiples of 256 KiB.
DROPBOX_SINGLE_LIMIT = 150 * 1024 * 1024


@dataclass(frozen=True)
class FileSlice:
    path: Path
    offset: int
    length: int


def validate(config):
    allowed = {'provider', 'credential_ref', 'folder', 'bucket', 'prefix', 'region', 'endpoint', 'interval_hours', 'enabled', 'encryption_key_id'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise DomainError('Configuração inválida.', 422)
    c = {key: config.get(key, '') for key in allowed - {'interval_hours', 'enabled'}}
    if any(not isinstance(v, str) or len(v) > 300 or any(ord(ch) < 32 for ch in v) for v in c.values()):
        raise DomainError('Campos de configuração inválidos.', 422)
    if c['provider'] not in {'dropbox', 'drive', 's3', 'minio'} or not re.fullmatch(r'ESCRITURA_BACKUP_[A-Z0-9_]+', c['credential_ref']):
        raise DomainError('Provedor ou referência de credencial inválida.', 422)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', c['encryption_key_id']):
        raise DomainError('Informe o identificador da chave externa de criptografia.', 422, 'backup_key')
    hours = config.get('interval_hours', 24)
    if type(hours) is not int or not 1 <= hours <= 8760 or type(config.get('enabled', False)) is not bool:
        raise DomainError('Intervalo deve ser inteiro entre 1 e 8760 horas.', 422)
    c.update(interval_hours=hours, enabled=config.get('enabled', False))
    if c['provider'] in {'s3', 'minio'}:
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', c['bucket']) or not re.fullmatch(r'[a-z0-9-]{1,40}', c['region']):
            raise DomainError('Bucket ou região inválidos.', 422)
        if c['provider'] == 'minio':
            u = urlsplit(c['endpoint'])
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in {'', '/'}:
                raise DomainError('MinIO requer endpoint HTTPS sem credenciais ou caminho.', 422)
        elif c['endpoint']:
            raise DomainError('Endpoint customizado disponível somente para MinIO.', 422)
    if '..' in c['prefix'].split('/') or not re.fullmatch(r'[A-Za-z0-9_/-]*', c['prefix']):
        raise DomainError('Prefixo inválido.', 422)
    if c['provider'] == 'drive' and not re.fullmatch(r'[A-Za-z0-9_-]+', c['folder']):
        raise DomainError('Informe o ID da pasta Google Drive.', 422)
    if c['provider'] == 'dropbox' and (not c['folder'].startswith('/') or '..' in c['folder'].split('/')):
        raise DomainError('Informe a pasta Dropbox começando por /.', 422)
    return c


def credentials(ref):
    try:
        value = json.loads(os.environ[ref])
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (KeyError, ValueError):
        raise DomainError('Credencial externa ausente ou inválida. Configure a variável referenciada no servidor.', 422, 'backup_credentials') from None


def request(method, url, headers, body=b''):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        raise ValueError('HTTPS obrigatório')
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=60)
    size = body.length if isinstance(body, FileSlice) else body.stat().st_size if isinstance(body, Path) else len(body)
    try:
        connection.putrequest(method, parsed.path + ('?' + parsed.query if parsed.query else ''), skip_host='host' in headers)
        for name, value in {**headers, 'Content-Length': str(size)}.items():
            connection.putheader(name, value)
        connection.endheaders()
        if isinstance(body, (Path, FileSlice)):
            path = body.path if isinstance(body, FileSlice) else body
            with path.open('rb') as stream:
                stream.seek(body.offset if isinstance(body, FileSlice) else 0)
                remaining = size
                while remaining:
                    block = stream.read(min(1024*1024, remaining))
                    if not block: raise ValueError('Arquivo alterado durante envio.')
                    connection.send(block); remaining -= len(block)
        else:
            connection.send(body)
        response = connection.getresponse()
        data = response.read(65537)
        if response.status not in {200, 201, 308} or len(data) > 65536:
            raise RuntimeError('remote_response')
        return {**dict((k.lower(), v) for k, v in response.getheaders()), '_status': response.status}, json.loads(data) if data else {}
    finally:
        connection.close()


def access_token(c, secret, transport):
    if secret.get('refresh_token'):
        from urllib.parse import urlencode
        url = 'https://api.dropboxapi.com/oauth2/token' if c['provider'] == 'dropbox' else 'https://oauth2.googleapis.com/token'
        _, reply = transport('POST', url, {'Content-Type': 'application/x-www-form-urlencoded'}, urlencode({
            'grant_type': 'refresh_token', 'refresh_token': secret['refresh_token'],
            'client_id': secret['client_id'], 'client_secret': secret['client_secret']}).encode())
        return reply['access_token']
    return secret['access_token']


def upload(config, path, name, transport=request):
    c = validate(config)
    secret = credentials(c['credential_ref'])
    path = Path(path)
    size = path.stat().st_size
    if not 0 < size <= backup_archive.MAX_BYTES:
        raise DomainError('Tamanho do pacote inválido; nenhum envio iniciado.', 422, 'backup_size')
    if c['provider'] == 'dropbox':
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                h.update(hashlib.sha256(block).digest())
        headers = {'Authorization': 'Bearer ' + access_token(c, secret, transport), 'Content-Type': 'application/octet-stream'}
        commit = {'path': c['folder'].rstrip('/') + '/' + name, 'mode': 'add', 'autorename': False, 'strict_conflict': True}
        if size <= DROPBOX_SINGLE_LIMIT:
            response, reply = transport('POST', 'https://content.dropboxapi.com/2/files/upload',
                {**headers, 'Dropbox-API-Arg': json.dumps(commit)}, path)
            if response.get('_status', 200) != 200: raise ValueError('unexpected_status')
        else:
            response, session = transport('POST', 'https://content.dropboxapi.com/2/files/upload_session/start',
                {**headers, 'Dropbox-API-Arg': json.dumps({'close': False})}, FileSlice(path, 0, CHUNK_BYTES))
            if response.get('_status', 200) != 200 or not isinstance(session.get('session_id'), str):
                raise ValueError('invalid_upload_session')
            offset = CHUNK_BYTES
            while offset < size:
                length = min(CHUNK_BYTES, size-offset)
                final = offset+length == size
                args = {'cursor': {'session_id': session['session_id'], 'offset': offset}}
                args.update({'commit': commit} if final else {'close': False})
                response, reply = transport('POST', 'https://content.dropboxapi.com/2/files/upload_session/' + ('finish' if final else 'append_v2'),
                    {**headers, 'Dropbox-API-Arg': json.dumps(args)}, FileSlice(path, offset, length))
                if response.get('_status', 200) != 200: raise ValueError('unexpected_status')
                offset += length
        if reply.get('content_hash') != h.hexdigest() or reply.get('size') != path.stat().st_size:
            raise ValueError('remote_checksum')
        return {'verified': True}
    if c['provider'] == 'drive':
        headers = {'Authorization': 'Bearer ' + access_token(c, secret, transport)}
        response, _ = transport('POST', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true&ignoreDefaultVisibility=true&fields=id,md5Checksum,size',
            {**headers, 'Content-Type': 'application/json', 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(path.stat().st_size)},
            json.dumps({'name': name, 'parents': [c['folder']]}).encode())
        if response.get('_status', 200) != 200: raise ValueError('invalid_upload_session')
        location = response['location']
        parsed = urlsplit(location)
        if parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or not parsed.path.startswith('/upload/drive/'):
            raise ValueError('invalid_upload_location')
        offset = 0
        while offset < size:
            length = min(CHUNK_BYTES, size-offset)
            end = offset+length
            response, reply = transport('PUT', location, {**headers, 'Content-Type': 'application/octet-stream',
                'Content-Range': f'bytes {offset}-{end-1}/{size}'}, FileSlice(path, offset, length))
            status = response.get('_status', 200)
            if end < size:
                # Never assume bytes were received: a partial or missing Range is ambiguous.
                if status != 308 or response.get('range') != f'bytes=0-{end-1}':
                    raise ValueError('unconfirmed_upload_range')
            elif status not in {200, 201}:
                raise ValueError('unconfirmed_upload_completion')
            offset = end
        digest = hashlib.md5(usedforsecurity=False)
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
        if reply.get('md5Checksum') != digest.hexdigest() or int(reply.get('size', -1)) != path.stat().st_size:
            raise ValueError('remote_checksum')
        return {'verified': True}
    # AWS Signature V4, single PUT with conditional create and server-validated checksum.
    endpoint = c['endpoint'].rstrip('/') if c['provider'] == 'minio' else 'https://s3.' + c['region'] + '.amazonaws.com'
    key = '/'.join(filter(None, [c['prefix'].strip('/'), name]))
    uri = '/' + c['bucket'] + '/' + quote(key, safe='/~')
    digest = sha256(path)
    checksum = base64.b64encode(bytes.fromhex(digest)).decode()
    def signed(method, extra, body=b''):
        date = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        payload_hash = digest if method == 'PUT' else hashlib.sha256(b'').hexdigest()
        headers = {'host': urlsplit(endpoint).netloc, 'x-amz-date': date, 'x-amz-content-sha256': payload_hash, **extra}
        if secret.get('session_token'): headers['x-amz-security-token'] = secret['session_token']
        names = ';'.join(sorted(headers))
        canonical = '\n'.join([method, uri, '', ''.join(k + ':' + headers[k] + '\n' for k in sorted(headers)), names, payload_hash])
        scope = date[:8] + '/' + c['region'] + '/s3/aws4_request'
        string = '\n'.join(['AWS4-HMAC-SHA256', date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        signing = ('AWS4' + secret['secret_access_key']).encode()
        for part in [date[:8], c['region'], 's3', 'aws4_request']:
            signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing, string.encode(), hashlib.sha256).hexdigest()
        headers['Authorization'] = 'AWS4-HMAC-SHA256 Credential=' + secret['access_key_id'] + '/' + scope + ', SignedHeaders=' + names + ', Signature=' + signature
        return transport(method, endpoint + uri, headers, body)
    extra = {'x-amz-checksum-sha256': checksum, 'if-none-match': '*'}
    if c['provider'] == 'minio': extra['x-amz-checksum-algorithm'] = 'SHA256'
    response, _ = signed('PUT', extra, path)
    if response.get('_status', 200) != 200: raise ValueError('unconfirmed_upload')
    if not response.get('x-amz-checksum-sha256'):
        # AIStor documents checksum on read; do not report failure solely for an absent PUT echo.
        response, _ = signed('HEAD', {'x-amz-checksum-mode': 'ENABLED'})
        if response.get('_status', 200) != 200 or int(response.get('content-length', -1)) != size:
            raise ValueError('remote_size')
    if response.get('x-amz-checksum-sha256') != checksum:
        raise ValueError('remote_checksum')
    return {'verified': True}
