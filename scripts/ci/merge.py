"""Merge real de main em develop, com resolução limitada a versões.

O Git calcula a árvore integrada. Em conflitos nos manifests, normalizamos
somente a versão do projeto nas três etapas e repetimos o merge textual. Uma
divergência de dependência/código continua sendo conflito e exige intervenção.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tempfile

from .versioning import MANIFESTS, OPTIONAL_MANIFESTS, set_local, transform


class MergeError(RuntimeError):
    pass


def git(root, *args, check=True, env=None):
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', '-c', 'user.name=github-actions[bot]', '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com', *args]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding='utf-8')
    if check and result.returncode:
        raise MergeError('Git não concluiu ' + args[0] + ': ' + result.stderr.strip()[-3000:])
    return result


def authenticated_env(token):
    """Credentials are scoped to Git's HTTPS transport and never command args."""
    env = dict(os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'
    # These entries override a runner's inherited credential helper/config.
    entries = [('credential.helper', ''), ('http.followRedirects', 'false')]
    if token:
        basic = base64.b64encode(('x-access-token:' + token).encode()).decode('ascii')
        entries.append(('http.https://github.com/.extraheader', 'AUTHORIZATION: basic ' + basic))
    env['GIT_CONFIG_COUNT'] = str(len(entries))
    for index, (key, value) in enumerate(entries):
        env['GIT_CONFIG_KEY_' + str(index)] = key
        env['GIT_CONFIG_VALUE_' + str(index)] = value
    return env


def fetch_commits(root, repository, commits, token=''):
    # Repository is validated by GitHub.__init__; refs are full validated SHAs.
    git(root, 'fetch', '--no-tags', '--no-recurse-submodules', 'https://github.com/' + repository + '.git', *commits, env=authenticated_env(token))


def push_develop(root, repository, commit, token=''):
    # No force/lease option: a concurrent change must cause non-fast-forward.
    try:
        git(root, 'push', '--porcelain', 'https://github.com/' + repository + '.git', commit + ':refs/heads/develop', env=authenticated_env(token))
    except MergeError as exc:
        raise MergeError(str(exc) + '\nA branch não foi forçada. Confira avanço concorrente, proteção de branch e permissão para alterações de workflows.') from None


@dataclass(frozen=True)
class MergeResult:
    commit: str
    merged_main: bool
    changed: list[str]
    parents: list[str]


def merge_local(root: Path, main_sha: str, develop_sha: str, version: str):
    """Create a commit in a temporary worktree; never publish from this function."""
    root = Path(root).resolve()
    allowed = set(MANIFESTS) | set(OPTIONAL_MANIFESTS)
    with tempfile.TemporaryDirectory(prefix='escritura-sync-') as temporary:
        worktree = Path(temporary) / 'worktree'
        git(root, 'worktree', 'add', '--detach', str(worktree), develop_sha)
        try:
            merged = git(worktree, 'merge', '--no-commit', '--no-ff', '--no-edit', main_sha, check=False)
            if merged.returncode not in {0, 1}:
                raise MergeError('O merge não iniciou: ' + merged.stderr.strip()[-3000:])
            conflicted = [x for x in git(worktree, 'diff', '--name-only', '--diff-filter=U', '-z').stdout.split('\0') if x]
            outside = sorted(set(conflicted) - allowed)
            if outside:
                raise MergeError('Conflito de código; main não foi integrada e develop não foi alterada: ' + ', '.join(outside))
            for index, path in enumerate(conflicted):
                contents = []
                for stage in (2, 1, 3):
                    item = git(worktree, 'show', ':' + str(stage) + ':' + path, check=False)
                    if item.returncode:
                        raise MergeError('Manifest removido/adicionado de forma conflitante; resolução manual necessária: ' + path)
                    contents.append(transform(path, item.stdout, version))
                names = []
                for label, content in zip(('develop', 'base', 'main'), contents):
                    target = Path(temporary) / (str(index) + '-' + label)
                    target.write_text(content, encoding='utf-8')
                    names.append(str(target))
                result = git(worktree, 'merge-file', '-p', '-L', 'develop', '-L', 'base', '-L', 'main', *names, check=False)
                if result.returncode:
                    raise MergeError('Conflito além do número da versão; resolução manual necessária: ' + path)
                (worktree / path).write_text(result.stdout, encoding='utf-8')
                git(worktree, 'add', '--', path)
            if merged.returncode and not conflicted:
                raise MergeError('Merge recusado sem conflitos resolvíveis: ' + merged.stderr.strip()[-3000:])
            changed = set_local(worktree, version)
            if changed:
                git(worktree, 'add', '--', *changed)
            merging = git(worktree, 'rev-parse', '-q', '--verify', 'MERGE_HEAD', check=False).returncode == 0
            dirty = bool(git(worktree, 'diff', '--cached', '--name-only').stdout.strip())
            if merging or dirty:
                message = f'chore(release): integrar main em develop e preparar {version}' if merging else f'chore(release): preparar develop {version}'
                git(worktree, 'commit', '-m', message)
            commit = git(worktree, 'rev-parse', 'HEAD').stdout.strip()
            parents = git(worktree, 'show', '-s', '--format=%P', 'HEAD').stdout.strip().split()
            changed_all = git(worktree, 'diff', '--name-only', develop_sha, commit).stdout.splitlines()
            # A real ancestor relation, not fabricated parents over develop's tree.
            if git(worktree, 'merge-base', '--is-ancestor', main_sha, commit, check=False).returncode:
                raise MergeError('A integração não preservou a ancestralidade de main.')
            return MergeResult(commit, merging, changed_all, parents)
        finally:
            git(root, 'worktree', 'remove', '--force', str(worktree), check=False)
