"""Run the opt-in backup proof in a new local PostgreSQL 17 cluster, then remove it.

Requires official initdb/postgres/psql/pg_dump/pg_restore binaries already available.
No package installation, Docker, production DSN, existing cluster or cloud access.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindir',required=True,type=Path)
    parser.add_argument('--work-parent',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    bindir=args.bindir.resolve(strict=True)
    for name in ('initdb','postgres','psql','pg_dump','pg_restore'):
        if not (bindir/name).is_file():raise SystemExit('Official PostgreSQL tools missing.')
    if os.name!='posix' or os.geteuid()==0:raise SystemExit('Requires an unprivileged POSIX account.')
    parent=args.work_parent.resolve(strict=True)
    if shutil.disk_usage(parent).free<1024**3:raise SystemExit('Requires at least 1 GiB free.')
    work=Path(tempfile.mkdtemp(prefix='pg-backup-disposable-',dir=parent))
    data=work/'cluster'
    env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'}
    server=None;stopped=True
    result={'ok':False,'engine':'postgresql','scope':'synthetic-disposable-cluster',
            'production_connected':False,'docker_used':False}
    try:
        admin_password=secrets.token_hex(32);user_password=secrets.token_hex(32)
        password_file=work/'bootstrap-password'
        password_file.write_text(admin_password+'\n');password_file.chmod(0o600)
        initlog=work/'initdb.log'
        with initlog.open('wb') as log:
            completed=subprocess.run([str(bindir/'initdb'),'-D',str(data),'--username=backup_fixture_admin',
                                      '--pwfile='+str(password_file),'--auth-local=reject',
                                      '--auth-host=scram-sha-256','--encoding=UTF8','--locale=C'],
                                     env=env,stdout=log,stderr=log,timeout=60)
        if completed.returncode:raise RuntimeError('initdb_failed; private diagnostic retained only during this run')
        password_file.unlink()
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        # TCP-only from the outset, matching Endpoint. No Unix socket or Docker access.
        with (work/'server.log').open('wb') as log:
            server=subprocess.Popen([str(bindir/'postgres'),'-D',str(data),'-h','127.0.0.1',
                                     '-p',str(port),'-k','','-c','jit=off',
                                     '-c','log_statement=none','-c','log_min_error_statement=panic',
                                     '-c','log_min_messages=panic'],env=env,stdout=log,stderr=log)
        stopped=False
        passfile=work/'fixture.pgpass'
        passfile.write_text(f'127.0.0.1:{port}:*:backup_fixture_admin:{admin_password}\n'
                            f'127.0.0.1:{port}:*:backup_fixture_user:{user_password}\n')
        passfile.chmod(0o600)
        pg_env={**env,'PGHOST':'127.0.0.1','PGPORT':str(port),'PGUSER':'backup_fixture_admin',
                'PGDATABASE':'postgres','PGPASSFILE':str(passfile),'PGSSLMODE':'disable',
                'PGCONNECT_TIMEOUT':'2','PGOPTIONS':'-c statement_timeout=10000'}
        command=[str(bindir/'psql'),'-X','--no-password','-At','-v','ON_ERROR_STOP=1']
        def query(sql):
            return subprocess.run(command,input=sql.encode('ascii'),env=pg_env,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        for _ in range(100):
            if server.poll() is not None:raise RuntimeError('postgres_start_failed; no retry with weaker restrictions')
            check=query('SHOW data_directory;')
            if check.returncode==0:
                if Path(check.stdout.decode().strip())!=data:raise RuntimeError('unexpected_server')
                break
            time.sleep(.1)
        else:raise RuntimeError('postgres_not_ready')
        # Generated hex secret is sent only through stdin, never argv/log output.
        setup=query("CREATE ROLE backup_fixture_user LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '"+user_password+"';\n"
                    "CREATE DATABASE backup_fixture_control OWNER backup_fixture_user TEMPLATE template0;")
        if setup.returncode:raise RuntimeError('fixture_provisioning_failed')
        version=query('SHOW server_version_num;')
        result['server_version_num']=int(version.stdout.decode().strip())
        test_env={**env,'PYTHONPATH':str(ROOT),'ESCRITURA_DATA_DIR':str(work/'unused-app-data'),
                  'ESCRITURA_PG_PROBE_DISPOSABLE':'yes','ESCRITURA_PG_PROBE_BINDIR':str(bindir),
                  'ESCRITURA_PG_PROBE_WORK_PARENT':str(work),'ESCRITURA_PG_PROBE_PORT':str(port),
                  'ESCRITURA_PG_PROBE_PASSFILE':str(passfile),'ESCRITURA_PG_PROBE_RESULT':str(work/'native-details.json')}
        started=time.monotonic()
        test=subprocess.run([sys.executable,'-m','tests.test_postgres_backup_probe_integration','-v'],
                            cwd=ROOT,env=test_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
        result.update(test_exit_code=test.returncode,duration_seconds=round(time.monotonic()-started,3))
        # unittest diagnostics contain no tool stderr or connection secrets; still suppress on failure.
        result['test_summary']=test.stderr.decode('utf-8').replace(admin_password,'[redacted]').replace(user_password,'[redacted]')
        if test.returncode:raise RuntimeError('native_backup_test_failed')
        result['proofs']=json.loads((work/'native-details.json').read_text())
        leftover=query("SELECT count(*) FROM pg_database WHERE datname LIKE 'backup_restore_%' OR (datname LIKE 'backup_fixture_%' AND datname<>'backup_fixture_control');")
        if leftover.returncode or leftover.stdout.strip()!=b'0':raise RuntimeError('fixture_database_cleanup_failed')
        result['created_databases_removed']=True
        result['ok']=True
    except (OSError,RuntimeError,subprocess.TimeoutExpired,ValueError) as error:
        result['error']=type(error).__name__+': '+str(error) if isinstance(error,RuntimeError) else type(error).__name__
    finally:
        if server is not None and server.poll() is None:
            server.send_signal(signal.SIGINT)  # Fast shutdown of this process's disposable cluster only.
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:result.update(ok=False,error='shutdown_timeout; workspace retained')
        stopped=server is None or server.poll() is not None
        if stopped:
            shutil.rmtree(work)
            result['workspace_removed']=not work.exists()
        else:
            result['workspace_removed']=False
        args.report.write_text(json.dumps(result,indent=2))
    print(json.dumps({key:result.get(key) for key in ('ok','server_version_num','test_exit_code','workspace_removed','error')}))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
