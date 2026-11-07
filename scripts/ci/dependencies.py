"""Prepara cache npm e constraints comuns, preservando marcadores de plataforma."""
from pathlib import Path
import re

from .versioning import dependency_hash


def runtime_constraints(content):
    pins = []
    for line in content.splitlines():
        if re.match(r'^[A-Za-z0-9_.-]+==', line):
            pin = line.rstrip().removesuffix('\\').rstrip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]+==[^\s;]+(?:\s*;\s*[^\n]+)?', pin):
                raise ValueError('Pin de runtime inválido.')
            pins.append(pin)
    if not pins:
        raise ValueError('Lock de runtime vazio.')
    return '\n'.join(pins) + '\n'


def main():
    root = Path.cwd()
    output = root / 'build'
    output.mkdir(exist_ok=True)
    (output / 'npm-cache-key.txt').write_text(dependency_hash(root) + '\n', encoding='ascii')
    lock = (root / 'docker/runtime.lock').read_text(encoding='utf-8')
    (output / 'runtime-constraints.txt').write_text(runtime_constraints(lock), encoding='utf-8')


if __name__ == '__main__':
    main()
