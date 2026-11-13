"""Originais imutáveis: registro transacional canônico e diretórios regeneráveis."""
from pathlib import Path
import hashlib
import os
import uuid
from .core import DomainError, now, select_one

CATEGORIES = {'originals', 'auxiliary', 'audit', 'reports'}

def file_path(db, row):
    return db.data_dir / 'companies' / str(row['company_id']) / str(row['year']) / row['category'] / row['sha256']

def store_file(db, conn, cid, year, category, filename, content, actor):
    if category not in CATEGORIES or not 1900 <= int(year) <= 2199:
        raise DomainError('Categoria ou exercício de arquivo inválido.')
    filename = Path(str(filename).replace('\\','/')).name
    from .operational_settings import MAX_UPLOAD_BYTES
    maximum = MAX_UPLOAD_BYTES if category == 'originals' else 20*1024*1024
    if not filename or len(filename)>255 or not content or len(content)>maximum:
        raise DomainError(f'Arquivo inválido ou maior que {maximum//(1024*1024)} MiB.')
    sha = hashlib.sha256(content).hexdigest()
    if category == 'originals':
        from .import_package_cleanup import reject_removed_upload
        reject_removed_upload(conn, cid, sha)
    conn.execute('INSERT OR IGNORE INTO stored_files(company_id,year,category,filename,sha256,content,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)', (cid,year,category,filename,sha,content,now(),actor))
    row = conn.execute('SELECT * FROM stored_files WHERE company_id=? AND year=? AND category=? AND sha256=?',(cid,year,category,sha)).fetchone()
    materialize(db,row)
    return row['id']

def materialize(db,row):
    if not row['content']:
        raise DomainError('Original removido por limpeza autorizada.',410,'original_removed')
    path=file_path(db,row)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']: return path
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+uuid.uuid4().hex)
    try:
        with temporary.open('xb') as f:
            f.write(row['content']);f.flush();os.fsync(f.fileno())
        temporary.chmod(0o600);os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
    return path

def read_file(conn,cid,fid):
    row=select_one(conn,'stored_files',cid,fid)
    if conn.execute('SELECT 1 FROM stored_file_tombstones WHERE file_id=?',(fid,)).fetchone():
        raise DomainError('Original removido por limpeza autorizada.',410,'original_removed')
    if hashlib.sha256(row['content']).hexdigest()!=row['sha256']:
        raise DomainError('Integridade do arquivo original comprometida.',409,'file_integrity')
    return row

def inventory(db,cid,year):
    with db.read(snapshot=True) as conn:
        rows=[dict(r) for r in conn.execute('SELECT * FROM stored_files WHERE company_id=? AND year=? AND id NOT IN (SELECT file_id FROM stored_file_tombstones) ORDER BY id',(cid,year))]
    result=[]
    for r in rows:
        path=materialize(db,r)
        result.append({k:r[k] for k in ('id','year','category','filename','sha256','created_at')}|{'bytes':len(r['content']),'verified':hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256']})
    return {'files':result,'persistence':'SQLite transacional único; arquivos organizados por empresa/exercício. O backup do banco inclui os originais; diretórios são reconstruídos por hash.'}
