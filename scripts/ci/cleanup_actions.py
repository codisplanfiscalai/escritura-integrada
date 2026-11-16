"""Retenção conservadora de caches Actions; nunca remove releases ou seus assets."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from .github_api import GitHub, GitHubError
from .release import write_json

ACTIVE_STATUSES = ('queued', 'in_progress', 'waiting', 'requested', 'pending')
STABLE_REF = re.compile(r'^refs/tags/v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$')


def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def cache_family(key):
    # setup-node/setup-python use a final dependency hash. Keep two variants of
    # each OS/runtime/tool family on main/develop, without including app SemVer.
    return re.sub(r'(?i)[a-f0-9]{32,}$', '<hash>', str(key))


def active_refs(gh):
    refs, protect_all_pr = set(), False
    for status in ACTIVE_STATUSES:
        for run in gh.pages(gh.base + '/actions/runs', key='workflow_runs', params={'status': status}):
            if run.get('head_branch'):
                refs.add('refs/heads/' + run['head_branch'])
            prs = run.get('pull_requests') or []
            for pr in prs:
                number = pr.get('number')
                if isinstance(number, int) and number > 0:
                    refs.update({'refs/pull/' + str(number) + '/merge', 'refs/pull/' + str(number) + '/head'})
            if run.get('event') == 'pull_request' and not prs:
                protect_all_pr = True
    # Open PRs remain useful even while no runner is active. Do not evict them
    # merely because a review took longer than the retention window.
    for pr in gh.pages(gh.base + '/pulls', params={'state': 'open'}):
        number = pr.get('number')
        if type(number) is not int or number < 1:
            raise ValueError('PR aberta sem identificação; limpeza bloqueada.')
        refs.update({'refs/pull/' + str(number) + '/merge', 'refs/pull/' + str(number) + '/head'})
        head = pr.get('head') or {}
        if (head.get('repo') or {}).get('full_name') == gh.repository and head.get('ref'):
            refs.add('refs/heads/' + head['ref'])
    return refs, protect_all_pr


def select_caches(caches, refs, *, now=None, protect_all_pr=False, max_delete=100):
    now = now or datetime.now(timezone.utc)
    keep_recent = set()
    groups = defaultdict(list)
    for cache in caches:
        if cache.get('ref') in ('refs/heads/develop', 'refs/heads/main'):
            groups[(cache['ref'], cache_family(cache.get('key', '')))].append(cache)
    for group in groups.values():
        ordered = sorted(group, key=lambda item: parse_time(item.get('last_accessed_at')) or datetime.max.replace(tzinfo=timezone.utc), reverse=True)
        keep_recent.update(item['id'] for item in ordered[:2]
                           if parse_time(item.get('last_accessed_at')) is None
                           or now - parse_time(item['last_accessed_at']) < timedelta(days=90))
    candidates, protected = [], defaultdict(int)
    for cache in caches:
        identifier = cache.get('id')
        if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 1:
            raise ValueError('Cache com ID inválido; nenhuma exclusão deve iniciar.')
        ref = cache.get('ref', '')
        last = parse_time(cache.get('last_accessed_at'))
        if STABLE_REF.fullmatch(ref):
            reason = 'cache de tag estável preservado'
        elif ref in refs or (protect_all_pr and ref.startswith('refs/pull/')):
            reason = 'execução ativa'
        elif identifier in keep_recent:
            reason = 'duas variantes recentes da branch principal'
        elif last is None:
            reason = 'data desconhecida'
        else:
            days = 7 if ref.startswith('refs/pull/') else (14 if ref == 'refs/heads/develop' else 30)
            if now - last < timedelta(days=days):
                reason = 'dentro da retenção'
            else:
                candidates.append({'id': identifier, 'ref': ref, 'key': cache.get('key', ''), 'size_in_bytes': int(cache.get('size_in_bytes', 0)), 'last_accessed_at': cache.get('last_accessed_at'), 'created_at': cache.get('created_at'), 'version': cache.get('version'), 'retention_days': days})
                continue
        protected[reason] += 1
    candidates.sort(key=lambda item: (item['last_accessed_at'], item['id']))
    return {'candidates': candidates[:max_delete], 'deferred': max(0, len(candidates) - max_delete), 'protected': dict(protected)}


def cleanup(gh, *, execute=False, max_delete=100, now=None):
    if not 1 <= max_delete <= 500:
        raise ValueError('max-delete deve estar entre 1 e 500.')
    caches = list(gh.pages(gh.base + '/actions/caches', key='actions_caches'))
    refs, protect_all_pr = active_refs(gh)  # All reads finish before the first DELETE.
    selected = select_caches(caches, refs, now=now, protect_all_pr=protect_all_pr, max_delete=max_delete)
    report = {'schema_version': 1, 'repository': gh.repository, 'execute': execute, 'cache_count': len(caches), 'active_refs': sorted(refs), 'protect_all_pr': protect_all_pr, **selected, 'deleted': [], 'skipped_after_refresh': [], 'errors': [], 'stable_releases_touched': False}
    if execute and selected['candidates']:
        # A cache recently restored or a workflow started during planning is kept.
        for cache in selected['candidates']:
            # Refresh before EACH deletion; a restored cache or a newly active/open
            # ref invalidates the plan. Read errors abort; DELETE is never retried.
            try:
                refreshed = list(gh.pages(gh.base + '/actions/caches', key='actions_caches'))
                new_refs, new_pr = active_refs(gh)
                allowed = {item['id']: item for item in select_caches(refreshed, refs | new_refs, now=now, protect_all_pr=protect_all_pr or new_pr, max_delete=500)['candidates']}
            except (GitHubError, ValueError, KeyError) as exc:
                report['errors'].append({'id': cache['id'], 'stage': 'refresh', 'error': str(exc),
                                         'outcome': 'not_attempted', 'retried': False})
                break  # Preserve confirmed prior deletions in the partial report.
            current = allowed.get(cache['id'])
            if current != cache:
                report['skipped_after_refresh'].append(cache['id'])
                continue
            try:
                gh.request('DELETE', gh.base + '/actions/caches/' + str(cache['id']), missing=True)
                report['deleted'].append(cache['id'])
            except GitHubError as exc:
                report['errors'].append({'id': cache['id'], 'error': str(exc),
                                         'outcome': 'uncertain' if exc.status is None else 'rejected', 'retried': False})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Exclui somente os IDs elegíveis; sem esta opção apenas apresenta o plano.')
    parser.add_argument('--max-delete', type=int, default=100)
    parser.add_argument('--output', type=Path, default=Path('artifacts/cache-cleanup.json'))
    args = parser.parse_args()
    try:
        result = cleanup(GitHub(), execute=args.execute, max_delete=args.max_delete)
        write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['errors'] else 0
    except (GitHubError, ValueError, KeyError) as exc:
        write_json(args.output, {'ok': False, 'error': str(exc), 'execute': args.execute})
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
