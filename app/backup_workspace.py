"""Owned backup workspaces; cleanup requires the same worker lock as backup/restore."""
import json
import os
from pathlib import Path
import re

from .backup_platform import private_directory, reparse, safe_remove

MARKER = '.backup-work-v1'
ID = re.compile(r'[a-f0-9]{32}')


def create(root, job_id):
    if not ID.fullmatch(job_id): raise ValueError('Identificador inválido.')
    root = private_directory(root, exist_ok=True)
    work = private_directory(root / job_id)
    marker = work / MARKER
    with marker.open('x', encoding='utf-8') as stream:
        marker.chmod(0o600)
        json.dump({'format': 1, 'job_id': job_id}, stream)
        stream.flush(); os.fsync(stream.fileno())
    return work


def cleanup(root):
    root = Path(root)
    if reparse(root): raise ValueError('Área de trabalho indireta recusada.')
    removed = 0
    for work in root.iterdir():
        if not ID.fullmatch(work.name): continue
        marker = work / MARKER
        if reparse(work) or not work.is_dir(): raise ValueError('Área de trabalho indireta recusada.')
        if not marker.exists(): continue  # Unknown directories are never adopted/deleted.
        if reparse(marker) or marker.stat().st_size > 1024: raise ValueError('Marcador inválido.')
        if json.loads(marker.read_text(encoding='utf-8')) != {'format': 1, 'job_id': work.name}:
            raise ValueError('Marcador inválido.')
        safe_remove(work); removed += 1
    return removed
