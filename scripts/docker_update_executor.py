#!/usr/bin/env python3
"""Optional Linux host executor: inspect and pull ONLY. No cutover authority exposed.

Not installed, started or mounted by Compose. See docs/DOCKER_UPDATER.md.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import socketserver
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time
import uuid

REPOSITORY = 'ghcr.io/codisplanfiscalai/escritura-integrada'
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
IDENTIFIER = re.compile(r'[a-f0-9]{32}')
ACTIVE = ('queued', 'pulling', 'validating')
LIMITATION = ('Somente preparação: a imagem foi ou será baixada, sem substituir a aplicação. '
              'Corte bloqueado: faltam encerramento controlado de escritas, backup consistente e prova de compatibilidade de esquema/dados.')


class Refusal(Exception):
    def __init__(self, detail, code='executor_refused', status=409):
        self.detail, self.code, self.status = detail, code, status
        super().__init__(detail)


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def hashed(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def valid_digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise Refusal('Digest inválido recebido do Docker.', 'invalid_image')
    return value


class Docker:
    """Fixed local daemon, no shell, bounded output, no raw stderr in receipts."""
    def __init__(self, project, data_bind):
        self.project = project
        self.data_bind = str(data_bind.resolve(strict=True))
        self.executable = shutil.which('docker')
        if not self.executable:
            raise Refusal('Docker CLI ausente.', 'docker_unavailable', 503)

    def run(self, args, timeout=15):
        env = {k: v for k, v in os.environ.items() if k not in
               ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')}
        # Files, not pipes or capture_output: daemon output cannot exhaust memory.
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run([self.executable, '--host', 'unix:///var/run/docker.sock', *args],
                                        env=env, stdout=output, stderr=subprocess.DEVNULL,
                                        timeout=timeout, check=False, shell=False)
            except subprocess.TimeoutExpired as exc:
                raise Refusal('Docker excedeu o prazo. O daemon pode continuar o download; confira o histórico/cache antes de nova tentativa.', 'docker_timeout', 504) from exc
            if result.returncode:
                raise Refusal('Docker recusou a operação. Confira rede, autenticação GHCR, espaço e permissões do executor no host.', 'docker_failed', 503)
            output.seek(0)
            raw = output.read(2_000_001)
            if len(raw) > 2_000_000:
                raise Refusal('Resposta Docker excede o limite.', 'docker_response_limit', 503)
            return raw.decode('utf-8')

    def image(self, reference):
        return json.loads(self.run(['image', 'inspect', reference]))[0]

    def installed(self):
        ids = self.run(['ps', '--no-trunc', '-q', '--filter', f'label=com.docker.compose.project={self.project}',
                        '--filter', 'label=com.docker.compose.service=app']).splitlines()
        if len(ids) != 1 or not re.fullmatch(r'[a-f0-9]{64}', ids[0]):
            raise Refusal('É necessário exatamente um app em execução no projeto configurado.', 'installed_ambiguous')
        container = json.loads(self.run(['container', 'inspect', ids[0]]))[0]
        image = self.image(valid_digest(container['Image']))
        cfg = container['Config']
        if (cfg.get('Labels', {}).get('com.docker.compose.project') != self.project
                or cfg.get('Labels', {}).get('com.docker.compose.service') != 'app'):
            raise Refusal('Identidade Compose mudou.', 'installed_changed')
        mounts = container.get('Mounts', [])
        data = [m for m in mounts if m.get('Destination') == '/data']
        if len(data) != 1 or data[0].get('Type') != 'bind' or data[0].get('Source') != self.data_bind or data[0].get('RW') is not True:
            raise Refusal('Montagem /data não corresponde ao bind existente configurado. Nenhuma migração será executada.', 'mount_mismatch')
        if cfg.get('User') != '10001:10001' or image['Config'].get('User') != '10001:10001':
            raise Refusal('UID/GID da aplicação deve permanecer 10001:10001.', 'uid_mismatch')
        if image.get('Os') != 'linux' or image.get('Architecture') != 'amd64':
            raise Refusal('Este incremento exige Linux amd64.', 'platform_unsupported')
        labels = image['Config'].get('Labels') or {}
        source = labels.get('org.opencontainers.image.source')
        if source != 'https://github.com/codisplanfiscalai/escritura-integrada':
            raise Refusal('Origem da imagem instalada não comprovada.', 'invalid_image')
        digests = [r.split('@', 1)[1] for r in image.get('RepoDigests', []) if r.startswith(REPOSITORY + '@')]
        # No envs, host paths, credentials or mount listings leave the executor.
        return {'container_id': ids[0], 'image_id': valid_digest(image['Id']),
                'digest': valid_digest(digests[0]) if digests else None,
                'version': self.version(labels), 'uid_gid': cfg['User'],
                # Only the actual configured reference proves the update source.
                # Version labels, cached tags and digests cannot identify a channel.
                'configured_channel': next((c for c in ('develop','latest') if cfg.get('Image')==REPOSITORY+':'+c), None),
                'configuration_hash': hashed({'config': cfg, 'host': container['HostConfig'], 'mounts': mounts})}

    @staticmethod
    def version(labels):
        value = labels.get('org.opencontainers.image.version', '')
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9_.+-]+)?', value) or len(value) > 80:
            raise Refusal('Versão da imagem não verificável.', 'invalid_image')
        return value

    def resolve(self, channel):
        # buildx returns the registry descriptor (not a local mutable tag).
        descriptor = json.loads(self.run(['buildx', 'imagetools', 'inspect', '--format', '{{json .Manifest}}', REPOSITORY + ':' + channel]))
        digest = valid_digest(descriptor.get('digest'))
        raw = self.run(['buildx', 'imagetools', 'inspect', '--raw', REPOSITORY + '@' + digest])
        self.verify_manifest(raw, digest)
        manifest = json.loads(raw)
        if 'manifests' in manifest:
            candidates = [m for m in manifest['manifests'] if m.get('platform', {}).get('os') == 'linux'
                          and m.get('platform', {}).get('architecture') == 'amd64'
                          and m.get('platform', {}).get('variant', '') in ('', 'v1')]
            if len(candidates) != 1:
                raise Refusal('Alvo sem plataforma Linux amd64 única.', 'invalid_image')
            child = valid_digest(candidates[0]['digest'])
            raw = self.run(['buildx', 'imagetools', 'inspect', '--raw', REPOSITORY + '@' + child])
            self.verify_manifest(raw, child)
            manifest = json.loads(raw)
        else:
            child = digest
        config = valid_digest(manifest.get('config', {}).get('digest'))
        metadata = json.loads(self.run(['buildx', 'imagetools', 'inspect', '--format', '{{json .Image}}', REPOSITORY + '@' + child]))
        labels = metadata.get('config', {}).get('Labels') or {}
        if (metadata.get('os') != 'linux' or metadata.get('architecture') != 'amd64'
                or metadata.get('config', {}).get('User') != '10001:10001'
                or labels.get('org.opencontainers.image.source') != 'https://github.com/codisplanfiscalai/escritura-integrada'
                or not re.fullmatch(r'[a-f0-9]{40}', labels.get('org.opencontainers.image.revision', ''))):
            raise Refusal('Origem, plataforma, commit ou UID/GID do alvo não comprovados.', 'invalid_image')
        version = self.version(labels)
        if channel == 'latest' and ('-' in version or '+' in version):
            raise Refusal('latest não pode preparar uma pré-release.', 'invalid_channel_image')
        return {'digest': digest, 'platform_digest': child, 'image_id': config,
                'version': version, 'revision': labels['org.opencontainers.image.revision']}

    @staticmethod
    def verify_manifest(raw, digest):
        # buildx may add one display newline; accept only bytes matching the
        # registry descriptor, never a JSON reserialization or an unverified ID.
        candidates = [raw.encode()]
        if raw.endswith('\n'):
            candidates.append(raw[:-1].encode())
        if not any('sha256:' + hashlib.sha256(value).hexdigest() == digest for value in candidates):
            raise Refusal('Manifesto diverge do digest remoto.', 'invalid_image')

    def space(self):
        root = self.run(['info', '--format', '{{.DockerRootDir}}']).strip()
        if not Path(root).is_absolute():
            raise Refusal('Filesystem do armazenamento Docker não identificado.', 'disk_space')
        try:
            free = shutil.disk_usage(root).free
        except PermissionError:
            # On a host with rootless Docker, the service account may not search
            # the daemon's private home. Probe its filesystem mountpoint only;
            # do not open/chmod/chown/mount Docker data into another container.
            mountpoints = []
            for line in Path('/proc/self/mountinfo').read_text().splitlines():
                encoded = line.split()[4]
                point = Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), encoded))
                if Path(root).is_relative_to(point):
                    mountpoints.append(point)
            if not mountpoints:
                raise Refusal('Filesystem Docker não verificável. Executor deve rodar no host do daemon local.', 'disk_space')
            mountpoint = max(mountpoints, key=lambda p: len(p.parts))
            free = shutil.disk_usage(mountpoint).free
        except OSError as exc:
            raise Refusal('Filesystem Docker inacessível. Executor deve rodar no host do daemon local.', 'disk_space') from exc
        if free < 2 * 1024**3:
            raise Refusal('Reserve pelo menos 2 GiB livres no armazenamento Docker; o pull pode exigir mais.', 'disk_space')

    def pull(self, target, channel):
        reference = REPOSITORY + '@' + valid_digest(target['digest'])
        self.run(['pull', '--platform', 'linux/amd64', reference], timeout=600)
        image = self.image(reference)
        if (image.get('Id') != target['image_id'] or image.get('Os') != 'linux'
                or image.get('Architecture') != 'amd64' or image['Config'].get('User') != '10001:10001'
                or REPOSITORY + '@' + target['digest'] not in image.get('RepoDigests', [])):
            raise Refusal('Imagem baixada não corresponde ao digest, plataforma ou UID/GID aprovados.', 'invalid_image')
        labels = image['Config'].get('Labels') or {}
        if labels.get('org.opencontainers.image.source') != 'https://github.com/codisplanfiscalai/escritura-integrada':
            raise Refusal('Origem da imagem alvo não comprovada.', 'invalid_image')
        version = self.version(labels)
        if channel == 'latest' and ('-' in version or '+' in version):
            raise Refusal('latest não pode preparar uma pré-release.', 'invalid_channel_image')
        if not re.fullmatch(r'[a-f0-9]{40}', labels.get('org.opencontainers.image.revision', '')):
            raise Refusal('Commit da imagem alvo não verificável.', 'invalid_image')
        receipt = {'version': version, 'revision': labels['org.opencontainers.image.revision']}
        if any(receipt[k] != target[k] for k in receipt):
            raise Refusal('Metadados diferem do alvo aprovado.', 'invalid_image')
        return receipt


class Executor:
    def __init__(self, ledger, docker):
        self.ledger, self.docker = ledger, docker
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='docker-prepare')
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, created REAL, payload TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, idem TEXT UNIQUE, plan_id TEXT UNIQUE,
                    actor TEXT, created REAL, updated REAL, state TEXT, payload TEXT, error TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active ON jobs((1)) WHERE state IN ('queued','pulling','validating');''')
            db.execute("UPDATE jobs SET state='interrupted', error=?, updated=? WHERE state IN ('queued','pulling','validating')",
                       ('Executor reiniciado. Nenhum corte foi feito; confira o cache antes de preparar novamente.', time.time()))

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.ledger, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def close(self):
        self.pool.shutdown(wait=True)

    def job(self, row):
        return {**json.loads(row[7]), 'id': row[0], 'plan_id': row[2], 'actor_id': row[3], 'created_at': row[4],
                'updated_at': row[5], 'state': row[6], 'error': row[8],
                'application_updated': False}

    def status(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 10').fetchall()
        # Jobs remain readable even if the installed container disappears.
        try:
            installed, error = self.docker.installed(), None
        except Refusal as exc:
            installed, error = None, exc.detail
        return {'configured': True, 'installed': installed, 'installed_error': error,
                'preparation_supported': bool(installed and installed.get('configured_channel') in ('develop','latest')),
                'jobs': [self.job(r) for r in rows], 'cutover_supported': False, 'limitation': LIMITATION}

    def check(self, channel=None):
        with self.lock:
            with self.db() as db:
                if db.execute('SELECT count(*) FROM plans WHERE created>?', (time.time() - 3600,)).fetchone()[0] >= 12:
                    raise Refusal('Limite de 12 consultas de canal por hora atingido.', 'rate_limited', 429)
                # Reserve before contacting Docker so repeated failures are limited too.
                pid = uuid.uuid4().hex
                db.execute('DELETE FROM plans WHERE created<? AND id NOT IN (SELECT plan_id FROM jobs)', (time.time() - 3600,))
                db.execute('INSERT INTO plans VALUES(?,?,?)', (pid, time.time(), '{}'))
            installed = self.docker.installed()
            configured = installed.get('configured_channel')
            if configured not in ('develop','latest'):
                raise Refusal('Referência configurada não identifica develop/latest com segurança. Não há inferência por versão, digest ou cache.', 'channel_unresolved')
            if channel is not None and channel!=configured:
                raise Refusal('A consulta não pode mudar o canal configurado.', 'configured_channel_mismatch')
            channel=configured
            target = self.docker.resolve(channel)
            plan = {'id': pid, 'channel': channel, 'installed': installed, 'target': target,
                    'expires_at': time.time() + 300, 'cutover_supported': False}
            with self.db() as db:
                db.execute('UPDATE plans SET payload=? WHERE id=?', (packed(plan), pid))
            return plan

    def prepare(self, plan_id, idempotency_key, actor):
        if (not isinstance(plan_id, str) or not IDENTIFIER.fullmatch(plan_id)
                or not isinstance(idempotency_key, str) or not IDENTIFIER.fullmatch(idempotency_key)
                or not isinstance(actor, str) or not re.fullmatch(r'[1-9][0-9]{0,17}', actor)):
            raise Refusal('Identificador de preparação inválido.', 'invalid_request', 422)
        with self.lock, self.db() as db:
            old = db.execute('SELECT * FROM jobs WHERE idem=?', (idempotency_key,)).fetchone()
            if old:
                if old[2] != plan_id or old[3] != actor:
                    raise Refusal('Chave já utilizada por outra intenção.', 'idempotency_conflict')
                return self.job(old)
            # Same snapshot never schedules a second pull, even with a new key.
            old = db.execute('SELECT * FROM jobs WHERE plan_id=?', (plan_id,)).fetchone()
            if old:
                return self.job(old)
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','pulling','validating')").fetchone():
                raise Refusal('Já existe preparação em andamento.', 'operation_in_progress')
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0] >= 200:
                raise Refusal('Histórico atingiu 200 operações. Arquivamento administrativo necessário.', 'history_limit')
            if db.execute('SELECT count(*) FROM jobs WHERE created>?', (time.time() - 3600,)).fetchone()[0] >= 6:
                raise Refusal('Limite de seis preparações por hora atingido.', 'rate_limited', 429)
            row = db.execute('SELECT payload FROM plans WHERE id=?', (plan_id,)).fetchone()
            plan = json.loads(row[0]) if row else {}
            if plan.get('expires_at', 0) < time.time():
                raise Refusal('Consulta vencida ou inválida; consulte novamente.', 'stale_plan')
            jid, stamp = uuid.uuid4().hex, time.time()
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',
                       (jid, idempotency_key, plan_id, actor, stamp, stamp, 'queued', packed(plan), None))
            db.commit()  # Durable before returning or submitting work.
            self.pool.submit(self.work, jid, plan)
            return self.job(db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone())

    def transition(self, jid, state, plan=None, error=None):
        with self.db() as db:
            db.execute('UPDATE jobs SET state=?, updated=?, payload=COALESCE(?,payload), error=? WHERE id=?',
                       (state, time.time(), packed(plan) if plan else None, error, jid))

    def work(self, jid, plan):
        try:
            if self.docker.installed() != plan['installed']:
                raise Refusal('Instalação/configuração mudou desde a consulta. Consulte novamente.', 'installed_changed')
            if plan['channel']!=plan['installed'].get('configured_channel'):
                raise Refusal('Preparação não corresponde ao canal configurado.', 'configured_channel_mismatch')
            if self.docker.resolve(plan['channel']) != plan['target']:
                raise Refusal('O canal mudou desde a consulta. Consulte e confirme o novo digest.', 'target_changed')
            self.docker.space()
            self.transition(jid, 'pulling')
            receipt = self.docker.pull(plan['target'], plan['channel'])
            self.transition(jid, 'validating')
            if self.docker.installed() != plan['installed']:
                raise Refusal('Instalação mudou durante o download. Imagem em cache; corte não autorizado.', 'installed_changed')
            plan = {**plan, 'target': {**plan['target'], **receipt}}
            self.transition(jid, 'prepared', plan)
        except Refusal as exc:
            self.transition(jid, 'failed', error=exc.detail)
        except Exception:
            # No daemon stderr, env, filesystem paths or tracebacks in public jobs.
            self.transition(jid, 'failed', error='Preparação não confirmada. Administrador deve conferir Docker e cache; nenhum corte foi executado.')

    def dispatch(self, payload):
        if type(payload) is not dict:
            raise Refusal('Requisição inválida.', 'invalid_request', 422)
        action = payload.get('action')
        fields = {'status': {'action'}, 'check-current': {'action'}, 'check': {'action', 'channel'},
                  'prepare': {'action', 'plan_id', 'idempotency_key', 'actor'}}
        if not isinstance(action, str) or action not in fields or set(payload) != fields[action]:
            raise Refusal('Operação não suportada. Corte/rollback não estão implementados.', 'unsupported_operation', 422)
        if action == 'status':
            return self.status()
        if action == 'check-current':
            return self.check()
        if action == 'check':
            if payload['channel'] not in ('develop', 'latest'):
                raise Refusal('Canal inválido.', 'invalid_channel', 422)
            return self.check(payload['channel'])
        return self.prepare(payload['plan_id'], payload['idempotency_key'], payload['actor'])


def make_server(executor, socket_path, allowed_uid):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != allowed_uid:
                return
            try:
                raw = self.rfile.readline(4097)
                if len(raw) > 4096 or not raw.endswith(b'\n'):
                    raise Refusal('Requisição excede o limite.', 'invalid_request', 422)
                data = executor.dispatch(json.loads(raw))
                reply = {'status': 200, 'data': data}
            except Refusal as exc:
                reply = {'status': exc.status, 'data': {'detail': exc.detail, 'code': exc.code}}
            except Exception:
                reply = {'status': 503, 'data': {'detail': 'Executor não concluiu a solicitação.', 'code': 'executor_failed'}}
            self.wfile.write(packed(reply).encode() + b'\n')

    # Single request server bounds connections; downloads run in one worker.
    # status reads do not wait on the lock used by check/prepare.
    server = socketserver.UnixStreamServer(str(socket_path), Handler)
    os.chmod(socket_path, 0o660)
    return server


def serve(executor, socket_path, allowed_uid):
    with make_server(executor, socket_path, allowed_uid) as server:
        server.serve_forever(poll_interval=0.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-directory', type=Path, required=True)
    parser.add_argument('--project-name', required=True)
    parser.add_argument('--app-data-bind', default='./data/app')
    parser.add_argument('--allowed-uid', type=int, default=10001)
    args = parser.parse_args()
    if os.name != 'posix' or not hasattr(socket, 'SO_PEERCRED'):
        parser.error('Requer Linux com SO_PEERCRED.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', args.project_name):
        parser.error('Nome de projeto inválido.')
    project = args.project_directory.resolve(strict=True)
    bind = Path(args.app_data_bind)
    if bind.is_absolute() or '..' in bind.parts:
        parser.error('Bind deve ser relativo ao projeto, sem ..')
    data = (project / bind).resolve(strict=True)
    if not data.is_relative_to(project) or not data.is_dir():
        parser.error('Bind deve ser diretório existente dentro do projeto.')
    state = project / '.docker-updater'
    state.mkdir(mode=0o700, exist_ok=True)
    if state.is_symlink() or state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
        parser.error('.docker-updater deve pertencer ao executor com modo 0700.')
    import fcntl
    with (state / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = state / 'run'
        # Parent and socket permissions must be provisioned by administrator.
        if not run.is_dir() or run.is_symlink():
            parser.error('Administrador deve preparar .docker-updater/run e seu grupo antes de iniciar.')
        path = run / 'control.sock'
        if path.exists():
            if not path.is_socket():
                parser.error('control.sock existente não é socket.')
            path.unlink()  # Single executor lease already obtained.
        executor = Executor(state / 'state.sqlite3', Docker(args.project_name, data))
        try:
            serve(executor, path, args.allowed_uid)
        finally:
            executor.close()
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
