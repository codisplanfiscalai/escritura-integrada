"""Admin backup queue: durable intents, local process lock, no automatic upload retry."""
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from fastapi import Body, Request
from . import backup_archive, backup_providers, backup_crypto, backup_platform, backup_workspace
from .core import DomainError
from .permissions import require

ACTIVE = ('queued', 'snapshot', 'uploading')


class BackupService:
    def __init__(self, db, uploader=backup_providers.upload, clock=time.time):
        self.db, self.uploader, self.clock = db, uploader, clock
        self.root = db.data_dir / 'backup-control'
        backup_platform.private_directory(self.root, exist_ok=True)
        self.work_root = backup_platform.private_directory(self.root / 'work', exist_ok=True)
        self.state_path = self.root / 'state.sqlite3'
        self.stop = threading.Event()
        self.thread = None
        self.worker_error = ''
        with self.connection() as conn:
            conn.executescript('''CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, next_due REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, intent TEXT UNIQUE NOT NULL, config TEXT NOT NULL,
                  state TEXT NOT NULL, created REAL NOT NULL, finished REAL, actor TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                  checksum TEXT, cancel INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS single_backup ON jobs((1)) WHERE state IN ('queued','snapshot','uploading');''')
        self.state_path.chmod(0o600)
        backup_platform.private_directory(self.root / 'restores', exist_ok=True)

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.state_path, timeout=15)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    @contextmanager
    def lock(self):
        path = self.root / 'worker.lock'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o600)
        with os.fdopen(descriptor, 'r+b') as file:
            path.chmod(0o600)
            try:
                if backup_platform.WINDOWS:
                    import msvcrt
                    if os.fstat(file.fileno()).st_size == 0:
                        file.write(b'0'); file.flush()
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                yield False
                return
            try:
                yield True
            finally:
                if backup_platform.WINDOWS:
                    file.seek(0); msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    def status(self):
        with self.connection() as conn:
            settings = conn.execute('SELECT * FROM settings WHERE id=1').fetchone()
            jobs = [self.public(row) for row in conn.execute('SELECT * FROM jobs ORDER BY created DESC, rowid DESC LIMIT 100')]
        return {'config': json.loads(settings['config']) if settings else None, 'next_due': settings['next_due'] if settings else None,
                'jobs': jobs, 'worker_error': self.worker_error, 'retention': 'Sem exclusão automática local ou remota.', 'max_archive_mib': backup_archive.MAX_BYTES // (1024*1024)}

    @staticmethod
    def public(row):
        result = {key: row[key] for key in ('id', 'state', 'created', 'finished', 'actor', 'error', 'checksum', 'cancel')}
        config = json.loads(row['config'])
        result['encryption_key_id'] = config.get('encryption_key_id')
        result['destination'] = {key: config.get(key, '') for key in ('provider', 'folder', 'bucket', 'prefix', 'endpoint')}
        return result

    def configure(self, payload):
        config = backup_providers.validate(payload)
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT 1 FROM jobs WHERE state IN ('queued','snapshot','uploading')").fetchone():
                raise DomainError('Aguarde ou cancele o backup antes de alterar o destino.', 409)
            conn.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?)', (json.dumps(config), self.clock() + config['interval_hours'] * 3600))
        return self.status()

    def enqueue(self, intent, actor, scheduled=False):
        if not isinstance(intent, str) or len(intent) != 32 or any(ch not in '0123456789abcdef' for ch in intent):
            raise DomainError('Identificador de solicitação inválido.', 422)
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT * FROM jobs WHERE intent=?', (intent,)).fetchone()
            if previous:
                return self.public(previous)
            settings = conn.execute('SELECT * FROM settings WHERE id=1').fetchone()
            if not settings:
                raise DomainError('Configure um destino primeiro.', 422)
            config = json.loads(settings['config'])
            if scheduled and (not config['enabled'] or settings['next_due'] > self.clock()):
                return None
            if conn.execute("SELECT 1 FROM jobs WHERE state IN ('queued','snapshot','uploading')").fetchone():
                raise DomainError('Já existe um backup em andamento.', 409, 'backup_busy')
            job_id = uuid.uuid4().hex
            conn.execute('INSERT INTO jobs(id,intent,config,state,created,actor) VALUES(?,?,?,\'queued\',?,?)',
                         (job_id, intent, settings['config'], self.clock(), actor))
            if scheduled:
                # Coalesce missed slots: one job, next interval from admission; no catch-up storm.
                conn.execute('UPDATE settings SET next_due=? WHERE id=1', (self.clock() + config['interval_hours'] * 3600,))
            return self.public(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def cancel(self, job_id):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise DomainError('Backup não encontrado.', 404)
            if row['state'] == 'uploading':
                raise DomainError('Envio iniciado; cancelamento não garante remoção remota. Aguarde e confira o histórico.', 409, 'upload_started')
            if row['state'] in ('queued', 'snapshot'):
                conn.execute('UPDATE jobs SET cancel=1 WHERE id=?', (job_id,))
                if row['state'] == 'queued':
                    conn.execute("UPDATE jobs SET state='cancelled',finished=? WHERE id=?", (self.clock(), job_id))
        return self.status()

    def update(self, job_id, state, error='', checksum=None):
        with self.connection() as conn:
            conn.execute('UPDATE jobs SET state=?,error=?,checksum=COALESCE(?,checksum),finished=? WHERE id=?',
                         (state, error, checksum, None if state in ACTIVE else self.clock(), job_id))

    def tick(self):
        # The OS releases the lock on process death; never rely on a stale PID or lease expiry.
        with self.lock() as acquired:
            if not acquired:
                return
            with self.connection() as conn:
                conn.execute("UPDATE jobs SET state='interrupted',finished=?,error=? WHERE state IN ('snapshot','uploading')",
                    (self.clock(), 'Processo interrompido. Destino pode conter arquivo; não haverá repetição automática.'))
            backup_workspace.cleanup(self.work_root)
            try:
                self.enqueue(uuid.uuid4().hex, 'scheduler', scheduled=True)
            except DomainError:
                pass
            with self.connection() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                self.run(row)

    def run(self, row):
        job_id = row['id']
        config = json.loads(row['config'])
        path = self.root / (job_id + '.eibk')
        work = None
        def cancelled():
            with self.connection() as conn:
                return self.stop.is_set() or bool(conn.execute('SELECT cancel FROM jobs WHERE id=?', (job_id,)).fetchone()[0])
        try:
            # Cancellation and admission are serialized, including the queued->snapshot edge.
            with self.connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                current = conn.execute('SELECT state,cancel FROM jobs WHERE id=?', (job_id,)).fetchone()
                if current['state'] != 'queued' or current['cancel']:
                    return
                conn.execute("UPDATE jobs SET state='snapshot' WHERE id=?", (job_id,))
            backup_providers.credentials(json.loads(row['config'])['credential_ref'])
            secret = backup_crypto.load_key(config.get('encryption_key_id'), self.db.data_dir)
            work = backup_workspace.create(self.work_root, job_id)
            checksum = backup_crypto.build(self.db.path, path, config['encryption_key_id'], secret, cancelled, work_dir=work)
            verified = work / 'verified'
            backup_crypto.restore(path, verified, checksum, secret=secret, work_dir=work)
            (verified / 'escritura.sqlite3').unlink(); verified.rmdir()
            with self.connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                if cancelled():
                    raise DomainError('Backup cancelado antes do envio.', 409, 'cancelled')
                conn.execute("UPDATE jobs SET state='uploading',checksum=? WHERE id=?", (checksum, job_id))
            try:
                self.uploader(json.loads(row['config']), path, 'escritura-' + job_id + '.eibk')
            except Exception:
                # A timeout may follow a committed upload. Never auto retry this intent.
                self.update(job_id, 'uncertain', 'Envio sem confirmação de integridade. Confira o destino antes de solicitar outro backup.')
                return
            self.update(job_id, 'completed', checksum=checksum)
        except DomainError as exc:
            self.update(job_id, 'cancelled' if exc.code == 'cancelled' else 'failed', exc.detail)
        except Exception:
            self.update(job_id, 'failed', 'Falha local: confira espaço, permissões e integridade. Nenhum novo envio foi iniciado.')
        finally:
            if work is not None and work.exists():
                try: backup_platform.safe_remove(work)
                except (OSError, ValueError):
                    self.worker_error = 'Temporários privados pendentes de limpeza; confira permissões e a área de trabalho.'

    def restore_job(self, job_id):
        with self.lock() as acquired:
            if not acquired:
                raise DomainError('Backup ou recuperação em andamento. Aguarde antes de recuperar.', 409, 'backup_busy')
            try: backup_workspace.cleanup(self.work_root)
            except (OSError, ValueError):
                raise DomainError('Limpeza de temporários pendente; confira permissões e a área de trabalho antes de recuperar.', 503, 'backup_cleanup') from None
            return self._restore_job(job_id)

    def _restore_job(self, job_id):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row or row['state'] not in {'completed', 'uncertain', 'interrupted'} or not row['checksum']:
            raise DomainError('Backup verificado indisponível.', 409)
        target = self.root / 'restores' / job_id
        work = backup_workspace.create(self.work_root, job_id)
        try:
            config = json.loads(row['config'])
            if config.get('encryption_key_id'):
                backup_crypto.restore(self.root / (job_id + '.eibk'), target, row['checksum'],
                                      key_loader=lambda key_id: backup_crypto.load_key(key_id, self.db.data_dir), work_dir=work)
            else:
                # Explicit compatibility for historical ZIP jobs; new writes never fall back to plaintext.
                backup_archive.restore(self.root / (job_id + '.zip'), target, row['checksum'])
        except FileExistsError:
            raise DomainError('Extração isolada já existe; nenhum arquivo foi sobrescrito.', 409, 'restore_exists') from None
        except Exception:
            raise DomainError('Chave indisponível/incorreta, arquivo corrompido ou extração indisponível; dados operacionais preservados.', 422, 'restore_invalid') from None
        finally:
            try: backup_platform.safe_remove(work)
            except (OSError, ValueError):
                self.worker_error = 'Temporários privados pendentes de limpeza; a cópia isolada pode já existir.'
                raise DomainError(self.worker_error, 503, 'backup_cleanup') from None
        return {'directory': 'backup-control/restores/' + job_id, 'activated': False}

    def start(self):
        def loop():
            while not self.stop.is_set():
                try:
                    self.worker_error = ''
                    self.tick()
                except Exception:
                    # No provider messages or credentials in logs. Next tick checks durable state.
                    self.worker_error = 'Agendador indisponível: confira espaço e permissões do diretório de controle.'
                self.stop.wait(5)
        self.thread = threading.Thread(target=loop, name='backup-worker', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()  # Finite network timeout; never start another upload during shutdown.


class UnavailableBackupService:
    # Keep the existing application usable when Windows cannot secure the backup area.
    message = 'Backups indisponíveis: o ambiente Windows precisa de volume local com ACLs persistentes e permissões privadas.'
    def start(self): pass
    def close(self): pass
    def status(self):
        return {'config': None, 'jobs': [], 'worker_error': self.message, 'next_due': None,
                'max_archive_mib': backup_archive.MAX_BYTES // (1024*1024)}
    def reject(self, *args, **kwargs):
        raise DomainError(self.message, 503, 'backup_platform_unavailable')
    configure = enqueue = cancel = restore_job = reject


def register(application, core):
    try:
        service = BackupService(core.db)
    except (OSError, ValueError):
        if not backup_platform.WINDOWS: raise
        service = UnavailableBackupService()
    application.state.backups = service

    def admin(request):
        with core.db.read() as conn:
            require(conn, request.state.session['user']['id'], None, admin=True)
        if application.state.demo:
            raise DomainError('Backup remoto indisponível na demonstração.', 403)
        return str(request.state.session['user']['id'])

    @application.get('/api/backups')
    def status(request: Request):
        admin(request)
        return service.status()

    @application.put('/api/backups/config')
    def configure(request: Request, payload: dict = Body(...)):
        admin(request)
        return service.configure(payload)

    @application.post('/api/backups')
    def create(request: Request, payload: dict = Body(...)):
        actor = admin(request)
        return service.enqueue(payload.get('idempotency_key'), actor)

    @application.post('/api/backups/{job_id}/cancel')
    def cancel(request: Request, job_id: str):
        admin(request)
        return service.cancel(job_id)

    @application.post('/api/backups/{job_id}/restore')
    def restore(request: Request, job_id: str):
        admin(request)
        return service.restore_job(job_id)
