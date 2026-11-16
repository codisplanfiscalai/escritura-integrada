"""Synthetic bounded size/recovery experiment. JSON metrics only, no keys or payloads retained."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import Database
from app import backup_crypto as crypto, backup_archive as archive
from app.core import DomainError


def main():
    results=[]
    for mib,randomized in [(8,False),(8,True),(160,True),(500,True)]:
        with tempfile.TemporaryDirectory(prefix='backup-size-synthetic-') as temporary:
            root=Path(temporary);db=Database(root/'data')
            digest=hashlib.sha256()
            with closing(sqlite3.connect(db.path)) as conn:
                conn.execute('CREATE TABLE synthetic_payload(id INTEGER PRIMARY KEY,content BLOB)')
                for i in range(mib):
                    block=os.urandom(1024*1024) if randomized else b'Z'*(1024*1024)
                    digest.update(block);conn.execute('INSERT INTO synthetic_payload VALUES(?,?)',(i,block))
                conn.commit()
            key=crypto.Secret('raw',os.urandom(32))
            encrypted=root/'fixture.eibk'
            start=time.monotonic();checksum=crypto.build(db.path,encrypted,'size-fixture',key)
            created=time.monotonic()-start
            start=time.monotonic();crypto.restore(encrypted,root/'restored',checksum,secret=key)
            restored=time.monotonic()-start
            actual=hashlib.sha256()
            with closing(sqlite3.connect(root/'restored'/'escritura.sqlite3')) as conn:
                for row in conn.execute('SELECT content FROM synthetic_payload ORDER BY id'):actual.update(row[0])
            assert actual.digest()==digest.digest()
            results.append({'synthetic_payload_mib':mib,'randomized':randomized,'database_bytes':db.path.stat().st_size,
                            'encrypted_bytes':encrypted.stat().st_size,'build_seconds':round(created,3),'restore_seconds':round(restored,3),'payload_verified':True})
    with tempfile.TemporaryDirectory(prefix='backup-boundary-synthetic-') as temporary:
        root=Path(temporary);source=root/'sparse-synthetic.bin'
        with source.open('wb') as stream:stream.truncate(archive.MAX_BYTES)
        try:crypto.encrypt(source,root/'must-not-exist.eibk','size-fixture',crypto.Secret('raw',os.urandom(32)))
        except DomainError as error:assert error.code=='backup_size'
        else:raise AssertionError('Envelope overhead did not enforce the configured boundary')
        assert not (root/'must-not-exist.eibk').exists()
    print(json.dumps({'ok':True,'limit_bytes':archive.MAX_BYTES,'overhead_boundary_refused':True,'cases':results},indent=2))


if __name__=='__main__':main()
