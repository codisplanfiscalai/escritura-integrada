"""Backup verificável e restauração em diretório novo, sem sobrescrever a origem."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
from zipfile import ZipFile,ZIP_DEFLATED
from .maintenance import sqlite_backup, integrity


def manifest(path):
    info=integrity(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory=sqlite3.Row
        tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        info['records']={t:conn.execute('SELECT COUNT(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
        info['money']={}
        for t,col in [('documents','total_cents'),('journals','total_cents'),('titles','amount_cents'),('settlements','amount_cents')]:
            info['money'][t]=conn.execute(f'SELECT COALESCE(SUM({col}),0) FROM {t}').fetchone()[0]
        info['originals']=[]
        for table,blob,hashcol in [('imports','original','sha256'),('stored_files','content','sha256')]:
            if table not in tables:continue
            for r in conn.execute(f'SELECT id,company_id,{blob},{hashcol} FROM {table}'):
                tomb = None
                if table == 'imports' and 'import_package_tombstones' in tables:
                    tomb = conn.execute('SELECT * FROM import_package_tombstones WHERE import_id=?', (r['id'],)).fetchone()
                elif table == 'stored_files' and 'stored_file_tombstones' in tables:
                    tomb = conn.execute('SELECT * FROM stored_file_tombstones WHERE file_id=?', (r['id'],)).fetchone()
                if tomb is not None:
                    # An empty blob is legitimate only with a consistent retained
                    # identity and an explicitly recorded removal, never by size alone.
                    if r[blob] != b'' or not tomb['removed_at']:
                        raise RuntimeError('Marcador de original removido inconsistente; backup recusado.')
                    if table == 'imports':
                        origin = tomb
                    else:
                        origin = conn.execute('''SELECT * FROM import_package_tombstones
                            WHERE company_id=? AND sha256=? ORDER BY import_id LIMIT 1''',
                            (r['company_id'], r[hashcol])).fetchone() if 'import_package_tombstones' in tables else None
                    if (origin is None or origin['company_id'] != r['company_id'] or
                        origin['sha256'] != r[hashcol] or origin['original_bytes'] <= 0 or
                        not origin['removed_by'] or len(r[hashcol]) != 64 or
                        any(c not in '0123456789abcdef' for c in r[hashcol])):
                        raise RuntimeError('Identidade do original removido inconsistente; backup recusado.')
                    info.setdefault('removed_originals', []).append({
                        'table': table, 'id': r['id'], 'company_id': r['company_id'],
                        'sha256': r[hashcol], 'removed_at': tomb['removed_at'],
                        'source_import_id': origin['import_id'],
                        'original_bytes': origin['original_bytes'], 'removed_by': origin['removed_by']})
                    continue
                actual=hashlib.sha256(r[blob]).hexdigest()
                if actual!=r[hashcol]:raise RuntimeError('Original com hash divergente; backup recusado.')
                info['originals'].append({'table':table,'id':r['id'],'company_id':r['company_id'],'sha256':actual,'bytes':len(r[blob])})
    info['sha256']=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return info


def create_snapshot(db_path,destination):
    destination=Path(destination)
    if destination.exists():raise RuntimeError('O destino do backup já existe.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='escritura-backup-') as tmp:
        db=Path(tmp)/'escritura.sqlite3';sqlite_backup(db_path,db)
        data=manifest(db);data['format']='escritura-complete-1';data['scope']='all-companies-all-years'
        with ZipFile(destination,'x',ZIP_DEFLATED) as z:
            z.write(db,'escritura.sqlite3');z.writestr('manifest.json',json.dumps(data,ensure_ascii=False,sort_keys=True))
    if os.name!='nt':destination.chmod(0o600)
    return data


def restore_snapshot(archive,destination):
    """Nunca restaura sobre dados vivos: valida tudo antes da promoção do diretório."""
    destination=Path(destination)
    if destination.exists():raise RuntimeError('Escolha uma pasta nova. A origem e instalações existentes serão preservadas.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.escritura-restore-',dir=destination.parent) as tmp:
        stage=Path(tmp)/'data';stage.mkdir()
        with ZipFile(archive) as z:
            if sorted(z.namelist())!=['escritura.sqlite3','manifest.json']:raise RuntimeError('Pacote de backup inválido.')
            if z.getinfo('manifest.json').file_size>20*1024*1024 or z.getinfo('escritura.sqlite3').file_size>100*1024**3:raise RuntimeError('Backup excede limites de restauração.')
            expected=json.loads(z.read('manifest.json'))
            if expected.get('format')!='escritura-complete-1':raise RuntimeError('Versão de backup não reconhecida.')
            with z.open('escritura.sqlite3') as src,(stage/'escritura.sqlite3').open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
        actual=manifest(stage/'escritura.sqlite3')
        if any(actual[k]!=expected.get(k) for k in actual) or actual.get('removed_originals') != expected.get('removed_originals'):raise RuntimeError('Backup não confere: registros, totais, vínculos ou hashes divergentes.')
        # As cópias organizadas são regeneradas; nenhum XML/PDF depende de cache externo.
        from .db import Database
        from .file_store import materialize
        db=Database(stage)
        with db.read() as conn:
            for row in conn.execute('SELECT * FROM stored_files WHERE id NOT IN (SELECT file_id FROM stored_file_tombstones)'):materialize(db,row)
        os.rename(stage,destination)
    return actual


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['backup','restore','verify']);p.add_argument('source',type=Path);p.add_argument('destination',nargs='?',type=Path);args=p.parse_args()
    if args.action=='verify':print(json.dumps(manifest(args.source),ensure_ascii=False));return
    if args.destination is None:p.error('Informe o destino.')
    result=create_snapshot(args.source,args.destination) if args.action=='backup' else restore_snapshot(args.source,args.destination)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
