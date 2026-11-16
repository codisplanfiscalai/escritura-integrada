"""Experimental logical backup for explicitly synthetic, loopback PostgreSQL fixtures.

NOT wired to Database, HTTP, scheduler, providers or Docker. No migration/cutover.
Only public.backup_probe_* data tables plus empty authentication tables are admitted.
Trusted dump SQL can execute code: use a disposable cluster and restricted fixture role.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import selectors
import stat
import subprocess
import time
import uuid
import zipfile

from . import backup_crypto as crypto, backup_archive as archive, backup_platform as platform

EMPTY_TABLES = ('session_contexts', 'sessions', 'login_attempts')
MAX_DUMP = 64 * 1024 * 1024
MAX_PACKAGE = MAX_DUMP + 64 * 1024
MAX_LOG = 1024 * 1024
SUPPORTED_MAJOR = 17  # Deliberately narrower than pg_dump's upstream compatibility.


class ProbeError(RuntimeError):
    def __init__(self, code, target=None):
        self.code, self.target = code, target
        super().__init__('Ensaio PostgreSQL recusado: ' + code +
                         ('. Banco isolado pode existir: ' + target if target else ''))


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    database: str
    user: str
    passfile: Path = field(repr=False)

    def validate(self):
        if (self.host not in {'127.0.0.1', '::1'} or type(self.port) is not int or not 1 <= self.port <= 65535 or
                not re.fullmatch(r'backup_fixture_[a-z0-9_]{1,40}', self.database) or
                not re.fullmatch(r'backup_fixture_[a-z0-9_]{1,40}', self.user)):
            raise ProbeError('synthetic_endpoint_required')
        path = Path(self.passfile)
        try:
            info = path.lstat()
            if (os.name != 'posix' or not path.is_absolute() or not stat.S_ISREG(info.st_mode) or
                    info.st_mode & 0o077 or info.st_uid != os.geteuid() or info.st_size > 8192):
                raise ValueError()
        except (OSError, ValueError):
            raise ProbeError('private_passfile_required') from None
        return self

    def environment(self, database=None):
        # Do not inherit PGPASSWORD, PGSERVICE, PGOPTIONS, SSL keys, LD_PRELOAD or HOME.
        self.validate()
        return {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                'PGHOST': self.host, 'PGPORT': str(self.port), 'PGUSER': self.user,
                'PGDATABASE': database or self.database, 'PGPASSFILE': str(self.passfile),
                'PGSSLMODE': 'disable', 'PGCONNECT_TIMEOUT': '5',
                'PGOPTIONS': '-c statement_timeout=60000 -c lock_timeout=5000'}


@dataclass(frozen=True)
class Tools:
    pg_dump: Path
    pg_restore: Path
    psql: Path

    def command(self, name):
        path = Path(getattr(self, name))
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ProbeError('postgres_tools_unavailable')
        return str(path)


def run(argv, *, env, output, cancelled=lambda: False, timeout=60, limit=MAX_LOG, stdin=b''):
    """No shell; private bounded output, generic errors, terminate/reap on all failures."""
    output = Path(output)
    process = None
    try:
        if len(stdin) > 16384: raise ProbeError('input_limit')
        with output.open('xb') as out:
            output.chmod(0o600)
            if cancelled(): raise ProbeError('cancelled')
            process = subprocess.Popen(argv, shell=False, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
            process.stdin.write(stdin); process.stdin.close()
            deadline = time.monotonic() + timeout
            total, errors = 0, 0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, 'out')
                selector.register(process.stderr, selectors.EVENT_READ, 'err')
                while selector.get_map():
                    if cancelled(): raise ProbeError('cancelled')
                    if time.monotonic() >= deadline: raise ProbeError('timeout')
                    if shutil.disk_usage(output.parent).free < 16 * 1024 * 1024:
                        raise ProbeError('disk_space')
                    for ready, _ in selector.select(.05):
                        block = os.read(ready.fileobj.fileno(), 65536)
                        if not block:
                            selector.unregister(ready.fileobj); continue
                        if ready.data == 'out':
                            total += len(block)
                            if total > limit: raise ProbeError('output_limit')
                            out.write(block)
                        else:
                            errors += len(block)  # Never persist or expose tool diagnostics/secrets.
                            if errors > MAX_LOG: raise ProbeError('output_limit')
            try: process.wait(timeout=max(.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired: raise ProbeError('timeout') from None
            if cancelled(): raise ProbeError('cancelled')
            if process.returncode or errors: raise ProbeError('tool_failed_or_warned')
            out.flush(); os.fsync(out.fileno())
    except ProbeError:
        raise
    except (OSError, ValueError):
        raise ProbeError('tool_io') from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed: stream.close()


class Probe:
    def __init__(self, tools, *, runner=run, cancelled=lambda: False):
        self.tools, self.runner, self.cancelled = tools, runner, cancelled

    def _call(self, tool, args, endpoint, work, *, database=None, limit=MAX_LOG, stdin=b''):
        output = Path(work) / (uuid.uuid4().hex + '.out')
        self.runner([self.tools.command(tool), *args], env=endpoint.environment(database),
                    output=output, cancelled=self.cancelled, timeout=60, limit=limit, stdin=stdin)
        if output.stat().st_size > limit: raise ProbeError('output_limit')
        return output

    def _query(self, endpoint, work, query, database=None):
        path = self._call('psql', ['-X', '--no-password', '--no-psqlrc', '-At', '-v', 'ON_ERROR_STOP=1'],
                          endpoint, work, database=database, stdin=query.encode('ascii'))
        return path.read_text(encoding='ascii').strip()

    def _versions(self, endpoint, work):
        versions = {}
        for name in ('pg_dump', 'pg_restore', 'psql'):
            value = self._call(name, ['--version'], endpoint, work).read_text().strip()
            match = re.fullmatch(r'(?:pg_dump|pg_restore|psql) \(PostgreSQL\) (17\.\d+)(?: [^\r\n]*)?', value)
            if not match: raise ProbeError('unsupported_tool_version')
            versions[name] = match[1]
        version = self._query(endpoint, work, 'SHOW server_version_num;')
        if not re.fullmatch(r'17\d{4}', version): raise ProbeError('unsupported_server_version')
        return {'server_version_num': int(version), 'tools': versions}

    @staticmethod
    def _tables(tables):
        if (not isinstance(tables, (tuple, list)) or not 1 <= len(tables) <= 20 or
                any(not isinstance(t, str) for t in tables) or len(set(tables)) != len(tables) or any(
                not re.fullmatch(r'backup_probe_[a-z0-9_]{1,40}', t) or
                re.search(r'secret|credential|cert|password|token|key', t) for t in tables)):
            raise ProbeError('synthetic_table_allowlist_required')
        return sorted(tables)

    def capture(self, endpoint, tables, output, secret, key_id, *, work_parent):
        tables = self._tables(tables); endpoint.validate()
        output = Path(output)
        if output.exists() or output.is_symlink(): raise FileExistsError('Saída existente.')
        if shutil.disk_usage(work_parent).free < 3 * MAX_PACKAGE + 16 * 1024 * 1024:
            raise ProbeError('disk_space')
        with platform.temporary_directory(work_parent, '.pg-probe-') as work:
            versions = self._versions(endpoint, work)
            args = ['--format=custom', '--compress=0', '--no-password', '--no-owner', '--no-acl',
                    '--no-comments', '--no-security-labels', '--no-tablespaces', '--strict-names',
                    '--lock-wait-timeout=5000', '--no-large-objects']
            args += ['--table=public.' + t for t in tables + list(EMPTY_TABLES)]
            args += ['--exclude-table-data=public.' + t for t in EMPTY_TABLES]
            dump = self._call('pg_dump', args, endpoint, work, limit=MAX_DUMP)
            with dump.open('rb') as stream:
                if stream.read(5) != b'PGDMP': raise ProbeError('invalid_dump')
            self._call('pg_restore', ['--list', str(dump)], endpoint, work)
            manifest = {'format': 1, 'backend': 'postgresql-logical-probe',
                        'created_at': datetime.now(timezone.utc).isoformat(), **versions,
                        'scope': {'schema': 'public', 'data_tables': tables, 'empty_tables': list(EMPTY_TABLES)},
                        'file': {'name': 'database.dump', 'bytes': dump.stat().st_size, 'sha256': archive.sha256(dump)},
                        'excludes': ['globals', 'roles', 'tablespaces', 'large_objects', 'external_files',
                                     'credentials', 'minio_objects', 'pitr'],
                        'application_backend_migrated': False}
            package = Path(work) / 'payload.zip'
            with zipfile.ZipFile(package, 'x', zipfile.ZIP_STORED) as z:
                z.write(dump, 'database.dump'); z.writestr('manifest.json', json.dumps(manifest))
            if package.stat().st_size > MAX_PACKAGE: raise ProbeError('output_limit')
            checksum = crypto.encrypt(package, output, key_id, secret, self.cancelled)
            return {'sha256': checksum, 'manifest': manifest, 'restore_tested': False}

    def _unpack(self, package, work):
        if package.stat().st_size > MAX_PACKAGE: raise ProbeError('output_limit')
        with zipfile.ZipFile(package) as z:
            if len(z.infolist()) != 2 or set(z.namelist()) != {'manifest.json', 'database.dump'}:
                raise ProbeError('invalid_inventory')
            if z.getinfo('manifest.json').file_size > 8192 or not 0 < z.getinfo('database.dump').file_size <= MAX_DUMP:
                raise ProbeError('output_limit')
            manifest = json.loads(z.read('manifest.json'))
            if (not isinstance(manifest, dict) or type(manifest.get('format')) is not int or manifest.get('format') != 1 or manifest.get('backend') != 'postgresql-logical-probe' or
                    manifest.get('application_backend_migrated') is not False or
                    manifest.get('scope', {}).get('schema') != 'public' or
                    manifest.get('scope', {}).get('empty_tables') != list(EMPTY_TABLES)):
                raise ProbeError('invalid_manifest')
            expected_keys = {'format', 'backend', 'created_at', 'server_version_num', 'tools',
                             'scope', 'file', 'excludes', 'application_backend_migrated'}
            if (set(manifest) != expected_keys or set(manifest.get('tools', {})) != {'pg_dump', 'pg_restore', 'psql'} or
                    any(not isinstance(v, str) or not re.fullmatch(r'17\.\d+', v) for v in manifest['tools'].values())):
                raise ProbeError('invalid_manifest')
            self._tables(manifest['scope']['data_tables'])
            if not re.fullmatch(r'17\d{4}', str(manifest.get('server_version_num'))):
                raise ProbeError('unsupported_server_version')
            expected = manifest['file']
            if expected['name'] != 'database.dump': raise ProbeError('invalid_manifest')
            dump = Path(work) / 'database.dump'
            with z.open('database.dump') as src, dump.open('xb') as dst:
                count = 0
                while block := src.read(1024 * 1024):
                    if self.cancelled(): raise ProbeError('cancelled')
                    count += len(block)
                    if count > MAX_DUMP: raise ProbeError('output_limit')
                    dst.write(block)
            if count != expected['bytes'] or archive.sha256(dump) != expected['sha256']:
                raise ProbeError('checksum')
        return manifest, dump

    def restore_new(self, endpoint, source, checksum, secret=None, *, work_parent, on_target=lambda target: None, key_loader=None):
        """Only new random databases; never DROP, --clean, --create, or a supplied target."""
        endpoint.validate()
        if Path(source).stat().st_size > MAX_PACKAGE + 1024: raise ProbeError('output_limit')
        if shutil.disk_usage(work_parent).free < 3 * MAX_PACKAGE + 16 * 1024 * 1024:
            raise ProbeError('disk_space')
        target = None
        with platform.temporary_directory(work_parent, '.pg-probe-') as work:
            # No database commands, even version queries, before authentication and SHA checks.
            with crypto.authenticated_payload(source, checksum, secret=secret, key_loader=key_loader, work_dir=work, cancelled=self.cancelled) as package:
                manifest, dump = self._unpack(package, work)
                self._versions(endpoint, work)  # Same-major only; no cross-version promise.
                safe = self._query(endpoint, work, "SELECT (NOT rolsuper AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls AND rolcreatedb AND NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid))::int FROM pg_roles WHERE rolname=current_user;")
                if safe != '1': raise ProbeError('restricted_fixture_role_required')
                self._call('pg_restore', ['--list', str(dump)], endpoint, work)
                if self.cancelled(): raise ProbeError('cancelled')
                target = 'backup_restore_' + uuid.uuid4().hex
                on_target(target)  # Caller persists the target BEFORE any CREATE DATABASE.
                try:
                    # UUID identifier generated here; no user SQL, no existing database adopted.
                    self._query(endpoint, work, 'CREATE DATABASE "' + target + '" TEMPLATE template0;')
                    self._call('pg_restore', ['--no-password', '--single-transaction', '--exit-on-error',
                               '--no-owner', '--no-acl', '--no-comments', '--no-security-labels',
                               '--no-tablespaces', '--dbname=' + target, str(dump)], endpoint, work,
                               database=target)
                    for table in EMPTY_TABLES:
                        if self._query(endpoint, work, 'SELECT count(*) FROM public.' + table + ';', target) != '0':
                            raise ProbeError('sessions_not_empty')
                except Exception:
                    # A timeout after CREATE/COMMIT is ambiguous. Keep target for operator inspection.
                    raise ProbeError('restore_incomplete_or_uncertain', target) from None
        return {'database': target, 'activated': False, 'status': 'restored_probe_only',
                'logical_payload_reconciliation': False, 'manifest': manifest}
