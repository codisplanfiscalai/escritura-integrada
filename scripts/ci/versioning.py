"""SemVer e sincronização de manifests; este módulo não acessa a rede."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping


class VersionError(ValueError):
    pass


PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")
MANIFESTS = ("VERSION", "app/__init__.py", "frontend/package.json", "frontend/package-lock.json", "package.json")
OPTIONAL_MANIFESTS = ("package-lock.json",)


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str):
        if not isinstance(value, str):
            raise VersionError("A versão deve ser texto SemVer.")
        match = PATTERN.fullmatch(value.strip())
        if not match:
            raise VersionError(f"Versão SemVer inválida: {value!r}.")
        pre = tuple(match.group(4).split('.')) if match.group(4) else ()
        if any(x.isdigit() and len(x) > 1 and x.startswith('0') for x in pre):
            raise VersionError("Identificador numérico de pré-release não pode ter zero inicial.")
        return cls(*(int(match.group(i)) for i in (1, 2, 3)), pre, tuple(match.group(5).split('.')) if match.group(5) else ())

    @property
    def core(self):
        return self.major, self.minor, self.patch

    @property
    def stable(self):
        return not self.prerelease and not self.build

    def without_suffix(self):
        return SemVer(*self.core)

    def next_patch(self):
        return SemVer(self.major, self.minor, self.patch + 1)

    def __str__(self):
        value = '.'.join(str(x) for x in self.core)
        if self.prerelease:
            value += '-' + '.'.join(self.prerelease)
        if self.build:
            value += '+' + '.'.join(self.build)
        return value

    def compare(self, other: 'SemVer'):
        if self.core != other.core:
            return 1 if self.core > other.core else -1
        if self.prerelease == other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return 1 if int(left) > int(right) else -1
            if left.isdigit() != right.isdigit():
                return -1 if left.isdigit() else 1
            return 1 if left > right else -1
        return 1 if len(self.prerelease) > len(other.prerelease) else -1


def release_version(value: str):
    result = SemVer.parse(value)
    if result.build:
        raise VersionError("Build metadata (+...) não integra os nomes de distribuição deste projeto.")
    return result


def choose_version(branch: str, current: str, main_version: str, stable_versions: list[str], run_number: int, same_head_tag: str | None = None):
    """Calculate a monotonic core while preserving explicit major/minor bumps."""
    if branch not in {"main", "develop"}:
        raise VersionError("Publicação permitida somente a partir de main ou develop.")
    if isinstance(run_number, bool) or not isinstance(run_number, int) or run_number < 1:
        raise VersionError("run_number deve ser inteiro positivo.")
    desired = release_version(current).without_suffix()
    main = release_version(main_version).without_suffix()
    reserved = [release_version(v) for v in stable_versions]
    if any(not v.stable for v in reserved):
        raise VersionError("A lista de versões estáveis contém uma pré-release.")
    highest = max(reserved, key=lambda v: v.core) if reserved else None
    if branch == "main":
        if highest and desired.core <= highest.core:
            if desired.core != highest.core or same_head_tag != 'v' + str(desired):
                desired = highest.next_patch()
        return str(desired)
    baseline = max([main] + reserved, key=lambda v: v.core)
    desired = max(desired, baseline.next_patch(), key=lambda v: v.core)
    return str(SemVer(*desired.core, ("dev", str(run_number))))


def develop_version_after_main(main_version: str, current_develop: str | None):
    main = release_version(main_version).without_suffix()
    minimum = main.next_patch()
    if current_develop:
        current = release_version(current_develop)
        if current.core >= minimum.core:
            if len(current.prerelease) == 2 and current.prerelease[0] == 'dev' and current.prerelease[1].isdigit():
                return str(current)
            minimum = current.without_suffix()
    return str(SemVer(*minimum.core, ("dev", "0")))


def transform(path: str, content: str, version: str):
    value = str(release_version(version))
    if path == "VERSION":
        return value + '\n'
    if path == "app/__init__.py":
        updated, count = re.subn(r'(?m)^__version__\s*=\s*([\'\"])[^\'\"]+\1\s*$', f'__version__ = "{value}"', content)
        if count != 1:
            raise VersionError("app/__init__.py deve conter uma atribuição explícita de __version__.")
        return updated.rstrip() + '\n'
    if path in {"frontend/package.json", "frontend/package-lock.json", "package.json", "package-lock.json"}:
        data = json.loads(content)
        data['version'] = value
        if path.endswith('package-lock.json') and isinstance(data.get('packages', {}).get(''), dict):
            data['packages']['']['version'] = value
        return json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    raise VersionError(f"Manifest fora da lista permitida: {path}.")


def manifest_versions(files: Mapping[str, str]):
    versions = {}
    for path in MANIFESTS:
        if path not in files:
            raise VersionError(f"Manifest obrigatório ausente: {path}.")
    for path, content in files.items():
        if path == "VERSION":
            versions[path] = str(release_version(content.strip()))
        elif path == "app/__init__.py":
            matches = re.findall(r'(?m)^__version__\s*=\s*[\'\"]([^\'\"]+)[\'\"]\s*$', content)
            if len(matches) != 1:
                raise VersionError("__version__ ausente ou ambígua.")
            versions[path] = str(release_version(matches[0]))
        elif path.endswith('package.json') or path.endswith('package-lock.json'):
            data = json.loads(content)
            versions[path] = str(release_version(data.get('version', '')))
            if path.endswith('package-lock.json') and isinstance(data.get('packages', {}).get(''), dict):
                versions[path + "#packages.root"] = str(release_version(data['packages'][''].get('version', '')))
    return versions


def read_manifests(root: Path):
    result = {path: (root / path).read_text(encoding='utf-8') for path in MANIFESTS}
    for path in OPTIONAL_MANIFESTS:
        if (root / path).is_file():
            result[path] = (root / path).read_text(encoding='utf-8')
    return result


def set_local(root: Path, version: str):
    files = read_manifests(root)
    changed = []
    for path, content in files.items():
        updated = transform(path, content, version)
        if updated != content:
            (root / path).write_text(updated, encoding='utf-8')
            changed.append(path)
    verify_local(root, version)
    return changed


def verify_local(root: Path, expected: str | None = None):
    versions = manifest_versions(read_manifests(root))
    expected = str(release_version(expected)) if expected else versions['VERSION']
    wrong = {path: value for path, value in versions.items() if value != expected}
    if wrong:
        raise VersionError("Versões divergentes: " + json.dumps(wrong, ensure_ascii=False))
    return expected


def dependency_hash(root: Path):
    """Project release numbers do not invalidate the npm dependency cache."""
    lock = json.loads((root / 'frontend/package-lock.json').read_text(encoding='utf-8'))
    lock.pop('version', None)
    if isinstance(lock.get('packages', {}).get(''), dict):
        lock['packages'][''].pop('version', None)
    return hashlib.sha256(json.dumps(lock, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest='command', required=True)
    write = sub.add_parser('set'); write.add_argument('version')
    check = sub.add_parser('check'); check.add_argument('--expected')
    sub.add_parser('dependency-hash')
    args = parser.parse_args()
    if args.command == 'set':
        print(json.dumps({'version': args.version, 'changed': set_local(args.root, args.version)}, ensure_ascii=False))
    elif args.command == 'check':
        print(verify_local(args.root, args.expected))
    else:
        print(dependency_hash(args.root))


if __name__ == '__main__':
    main()
