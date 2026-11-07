"""Manutenção usada pelo instalador e pela interface; dados nunca ficam em Program Files."""
from __future__ import annotations
import argparse
import configparser
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid

SCHEMA_VERSION = 3


def version_key(value):
    match=re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?',value)
    if not match:raise RuntimeError('Versão instalada não reconhecida. Confira a instalação antes de atualizar.')
    suffix=match.group(4)
    parts=tuple((0,int(p)) if p.isdigit() else (1,p) for p in suffix.split('.')) if suffix else ()
    return (*(int(match.group(i)) for i in (1,2,3)),not bool(suffix),parts)


def check_version(version,previous):
    if previous and version_key(version)<version_key(previous):
        raise RuntimeError('Uma versão mais nova já está instalada. A instalação de versão anterior foi impedida para proteger os dados.')
    return {'ok':True,'version':version,'previous_version':previous}


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]


def default_profile():
    if sys.platform=='win32':return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Codisplan'/'Escritura Integrada'
    if sys.platform=='darwin':return Path.home()/'Library'/'Application Support'/'Codisplan'/'Escritura Integrada'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'Codisplan'/'Escritura Integrada'


def configuration(profile):
    config=configparser.ConfigParser(interpolation=None);config.optionxform=str
    path=Path(profile)/'config.ini'
    if path.is_file():config.read(path,encoding='utf-8-sig')
    if not config.has_section('General'):config.add_section('General')
    return config


def configured_data(profile):
    config=configuration(profile)
    return Path(config.get('General','data_dir',fallback=str(Path(profile)/'data')).strip('"')).expanduser().resolve()


def running(pid):
    if pid<=0:return False
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        code=wintypes.DWORD();kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        try:return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:
            kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def refuse_running(profile,allow_pid=None):
    lock=Path(profile)/'aplicacao.lock'
    if lock.is_file():
        try:pid=int(lock.read_text(encoding='utf-8').splitlines()[0])
        except (ValueError,IndexError,OSError):raise RuntimeError('Não foi possível conferir o bloqueio da aplicação. Confira a instalação antes de continuar.')
        if pid!=allow_pid and running(pid):
            raise RuntimeError('A aplicação está aberta. Salve o trabalho e use Sair no menu do ícone antes de instalar ou migrar dados.')


def integrity(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('O banco de origem não passou na verificação de integridade.')
        if conn.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('O banco apresenta referências inválidas; a atualização foi cancelada.')
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'meta','companies','users'}<=tables:raise RuntimeError('A pasta não contém um banco do Escritura Integrada.')
        version=conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return {'schema_version':int(version[0]) if version else 1,
                'companies':conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
                'users':conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]}


def sqlite_backup(source,destination):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True,timeout=10)) as src:
        with closing(sqlite3.connect(destination)) as dst:src.backup(dst)
    integrity(destination)
    if os.name!='nt':destination.chmod(0o600)
    return str(destination)


def backup_before_schema(path):
    """Backup consistente antes da transação de migração, inclusive no Docker."""
    path=Path(path)
    if not path.exists():return None
    info=integrity(path)
    if info['schema_version']>SCHEMA_VERSION:
        raise RuntimeError('Este banco foi atualizado por uma versão mais nova. Instale uma versão compatível; nenhum dado foi alterado.')
    if info['schema_version']>=SCHEMA_VERSION:return None
    return sqlite_backup(path,path.parent/'backups'/('antes-schema-'+str(SCHEMA_VERSION)+'-'+stamp()+'.sqlite3'))


def find_data(source):
    source=Path(source).expanduser().resolve()
    for candidate in (source,source/'data'):
        if (candidate/'escritura.sqlite3').is_file():return candidate
    raise RuntimeError('Selecione a pasta que contém escritura.sqlite3 ou sua subpasta data.')


def inspect(profile,source=None):
    profile=Path(profile).resolve();candidate=find_data(source) if source else configured_data(profile)
    db=candidate/'escritura.sqlite3'
    return {'profile':str(profile),'data_dir':str(candidate),'existing':db.is_file(),
            **(integrity(db) if db.is_file() else {'companies':0,'users':0,'schema_version':0})}


def prepare(profile,version,source=None,allow_pid=None,owner_pid=None):
    """Valida em diretório temporário; troca diretórios no mesmo volume e retém o original."""
    profile=Path(profile).expanduser().resolve();profile.mkdir(parents=True,exist_ok=True)
    refuse_running(profile,allow_pid)
    marker=profile/'maintenance.json'
    if marker.exists():raise RuntimeError('Existe uma manutenção incompleta. Reexecute o instalador ou recupere a atualização anterior antes de continuar.')
    target=configured_data(profile);origin=find_data(source) if source else target
    if source and origin!=target and (target/'escritura.sqlite3').exists():
        raise RuntimeError('O destino já contém empresas. A migração não mescla nem substitui bancos existentes; escolha uma pasta de dados vazia nas configurações.')
    if origin.is_relative_to(target) and origin!=target:raise RuntimeError('A origem não pode estar dentro da pasta de destino.')
    if target.is_relative_to(origin) and target!=origin:raise RuntimeError('O destino não pode estar dentro da origem.')
    if origin.exists():
        for folder in [origin,origin.parent]:refuse_running(folder,allow_pid)
        for node in origin.rglob('*'):
            if node.is_symlink():raise RuntimeError('A pasta contém links simbólicos. Selecione uma cópia regular dos dados.')
    if (origin/'escritura.sqlite3').exists():integrity(origin/'escritura.sqlite3')
    target.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.escritura-atualizacao-',dir=target.parent))
    backup=target.parent/('.escritura-backup-'+stamp())
    state={'schema':1,'version':version,'target':str(target),'source':str(origin),'backup':str(backup),
           'owner_pid':owner_pid or os.getpid(),'stage':str(stage),'had_target':target.exists(),'phase':'preparing','config_before':(profile/'config.ini').read_text(encoding='utf-8') if (profile/'config.ini').exists() else None}
    marker.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        if origin.exists():
            for item in origin.iterdir():
                if item.name in {'escritura.sqlite3','escritura.sqlite3-wal','escritura.sqlite3-shm','aplicacao.lock'}:continue
                if item.is_dir():shutil.copytree(item,stage/item.name)
                else:shutil.copy2(item,stage/item.name)
            if (origin/'escritura.sqlite3').exists():sqlite_backup(origin/'escritura.sqlite3',stage/'escritura.sqlite3')
        from app.db import Database
        Database(stage)
        result=integrity(stage/'escritura.sqlite3')
        if target.exists():target.rename(backup)
        state['phase']='old_moved';marker.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        stage.rename(target)
        state['phase']='prepared';state['data']=result
        marker.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'ok':True,'phase':'prepared','data_dir':str(target),'backup':str(backup) if state['had_target'] else None,**result}
    except BaseException:
        rollback(profile)
        raise


def recover(profile):
    profile=Path(profile);refuse_running(profile)
    marker=profile/'maintenance.json'
    if marker.exists():
        state=json.loads(marker.read_text(encoding='utf-8'))
        if state.get('owner_pid') and running(state['owner_pid']):raise RuntimeError('A manutenção ainda está em execução. Aguarde o instalador concluir.')
    return rollback(profile)


def rollback(profile):
    profile=Path(profile);marker=profile/'maintenance.json'
    if not marker.exists():return {'ok':True,'phase':'nothing_to_restore'}
    state=json.loads(marker.read_text(encoding='utf-8'))
    target=Path(state['target']);backup=Path(state['backup']);stage=Path(state['stage'])
    # Somente caminhos produzidos por prepare; não aceitar um marcador apontando para outra árvore.
    if backup.parent!=target.parent or not backup.name.startswith('.escritura-backup-') or stage.parent!=target.parent or not stage.name.startswith('.escritura-atualizacao-'):
        raise RuntimeError('Marcador de manutenção inválido. Recuperação automática recusada.')
    if backup.exists():
        if target.exists():shutil.rmtree(target)
        backup.rename(target)
    elif not state['had_target'] and state['phase']=='prepared' and target.exists():shutil.rmtree(target)
    if stage.exists():shutil.rmtree(stage)
    config=profile/'config.ini'
    if state.get('config_before') is not None:config.write_text(state['config_before'],encoding='utf-8')
    marker.unlink()
    return {'ok':True,'phase':'restored','data_dir':str(target)}


def finish(profile):
    profile=Path(profile);marker=profile/'maintenance.json'
    if not marker.exists():return {'ok':True,'phase':'nothing_to_finish'}
    state=json.loads(marker.read_text(encoding='utf-8'))
    if state.get('phase')!='prepared':raise RuntimeError('Migração não concluída; finalize ou restaure a manutenção.')
    result=integrity(Path(state['target'])/'escritura.sqlite3')
    config=configuration(profile);config.set('General','data_dir',Path(state['target']).as_posix())
    config.set('General','installed_version',state['version'])
    with (profile/'config.ini').open('w',encoding='utf-8') as f:config.write(f,space_around_delimiters=False)
    report=profile/'maintenance-history';report.mkdir(exist_ok=True)
    state['phase']='completed';state['completed_at']=datetime.now(timezone.utc).isoformat()
    (report/(stamp()+'.json')).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    marker.unlink()
    return {'ok':True,'phase':'completed','version':state['version'],**result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inspect','prepare','finish','rollback','recover','version-check'])
    parser.add_argument('--profile',default=str(default_profile()));parser.add_argument('--source')
    parser.add_argument('--owner-pid',type=int);parser.add_argument('--version',default='');parser.add_argument('--previous-version',default='');parser.add_argument('--result');parser.add_argument('--message')
    args=parser.parse_args()
    try:
        if args.action=='version-check':result=check_version(args.version,args.previous_version)
        elif args.action=='inspect':result={'ok':True,**inspect(args.profile,args.source)}
        elif args.action=='prepare':
            check_version(args.version,args.previous_version)
            result=prepare(args.profile,args.version,args.source,owner_pid=args.owner_pid)
        elif args.action=='finish':result=finish(args.profile)
        elif args.action=='recover':result=recover(args.profile)
        else:result=rollback(args.profile)
        message='Manutenção concluída. Dados e permissões preservados.';code=0
    except Exception as exc:result={'ok':False,'error':str(exc)};message=str(exc);code=1
    if args.result:Path(args.result).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.message:Path(args.message).write_text(message,encoding='utf-8-sig')
    return code


if __name__=='__main__':
    project=str(Path(__file__).resolve().parents[1])
    if project not in sys.path:sys.path.insert(0,project)
    raise SystemExit(main())
