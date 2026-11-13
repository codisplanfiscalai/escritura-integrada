"""Final release-job promotion of develop, without rebuilding or touching latest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.image_tools import GHCR_PREFIX, validate_manifest
from . import image_aliases as aliases
from .github_api import GitHub
from .release import sha, write_json


class DevelopRegistry(aliases.Registry):
    def put_alias(self, alias, manifest):
        if alias != 'develop':
            raise ValueError('A promoção automática escreve somente develop.')
        return super().put_alias(alias, manifest)


class DevelopContext:
    """Separate live-run policy; the operational CLI keeps its completed-run guard."""
    def __init__(self, ci, images, publication, env=None, *, receipts):
        self.ci = ci
        self.env = dict(os.environ if env is None else env)
        expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': aliases.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/develop', 'GITHUB_JOB': 'promote-develop',
                    'GITHUB_WORKFLOW_REF': aliases.REPOSITORY + '/.github/workflows/release.yml@refs/heads/develop'}
        if any(self.env.get(k) != v for k, v in expected.items()) or self.env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch'):
            raise ValueError('Contexto GitHub não autorizado.')
        expected = {'schema': 'escritura-ci-plan/1', 'repository': aliases.REPOSITORY,
                    'branch': 'develop', 'channel': 'develop', 'tag': 'develop',
                    'proceed': True, 'needs_release': True, 'already_released': False}
        if any(ci.get(k) != v for k, v in expected.items()):
            raise ValueError('Plano não representa nova pré-release develop.')
        for key, envkey in [('run_id', 'GITHUB_RUN_ID'), ('run_number', 'GITHUB_RUN_NUMBER')]:
            if type(ci.get(key)) is not int or ci[key] < 1 or str(ci[key]) != self.env.get(envkey):
                raise ValueError('Plano pertence a outra execução.')
        attempt = self.env.get('GITHUB_RUN_ATTEMPT', '')
        if type(ci.get('run_attempt')) is not int or ci['run_attempt'] < 1 or not attempt.isdecimal() or int(attempt) < ci['run_attempt']:
            raise ValueError('Tentativa inválida ou superada.')
        self.current_attempt = int(attempt)
        if sha(ci.get('trigger_sha')) != self.env.get('GITHUB_SHA'):
            raise ValueError('SHA disparador não corresponde ao contexto.')
        validate_manifest(images)
        if images.get('channel') != 'develop' or any(images.get(k) != ci.get(k) for k in ('version', 'source_sha')):
            raise ValueError('Imagens divergem do plano CI.')
        app = images['images']['app']
        if app['tag'] != ci['version'] or app['reference'] != GHCR_PREFIX + ':' + ci['version']:
            raise ValueError('Imagem app não usa a versão exata.')
        if images.get('public_pullable') is not True or app.get('public_pullable') is not True:
            raise ValueError('Leitura pública não confirmada.')
        if publication.get('status') != 'published' or any(publication.get(k) != ci.get(k) for k in ('version', 'source_sha')):
            raise ValueError('Publicação não concluída para o plano exato.')
        if type(publication.get('release_id')) is not int or publication['release_id'] < 1:
            raise ValueError('ID da release inválido.')
        self.publication, self.image_id = publication, app['image_id']
        self.plan = {'schema_version': 1, 'repository': aliases.REPOSITORY, 'version': ci['version'],
                     'source_sha': ci['source_sha'], 'release_run_id': ci['run_id'],
                     'digest': app['digest'], 'aliases': ['develop']}
        aliases.validate_plan(self.plan)
        self.protected = None
        self.expected_assets = self.load_receipts(Path(receipts), images)

    def load_receipts(self, directory, images):
        prefix = 'EscrituraIntegrada-' + self.plan['version'] + '-'
        manifest_name, sums_name = prefix + 'manifest.json', prefix + 'SHA256SUMS.txt'
        raw, sums_raw = (directory / manifest_name).read_bytes(), (directory / sums_name).read_bytes()
        manifest = json.loads(raw)
        expected = {k: self.ci[k] for k in ('repository', 'version', 'source_sha', 'channel', 'tag', 'run_id', 'run_number')}
        if manifest.get('schema_version') != 1 or any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError('Manifesto de assets não corresponde à versão/source/run.')
        if manifest.get('images') != images['images']:
            raise ValueError('Manifesto de assets diverge das imagens publicadas.')
        entries = manifest.get('assets')
        if not isinstance(entries, list) or not entries:
            raise ValueError('Inventário vazio ou inválido.')
        wanted = {}
        for item in entries:
            name, size, digest = item.get('name', ''), item.get('size'), item.get('sha256', '')
            if (not isinstance(name, str) or not name.startswith(prefix) or '/' in name or '\\' in name
                or name in wanted or name in (manifest_name, sums_name)
                or type(size) is not int or size < 0 or not re.fullmatch(r'[0-9a-f]{64}', digest)):
                raise ValueError('Nome/tamanho/hash/duplicata inválidos no inventário.')
            wanted[name] = {'size': size, 'digest': 'sha256:' + digest}
        checksums = {}
        for line in sums_raw.decode('ascii').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
            if not match or match[2] in checksums:
                raise ValueError('SHA256SUMS inválido ou duplicado.')
            checksums[match[2]] = 'sha256:' + match[1]
        wanted[manifest_name] = {'size': len(raw), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
        if checksums != {name: item['digest'] for name, item in wanted.items()}:
            raise ValueError('SHA256SUMS diverge do inventário/manifesto.')
        wanted[sums_name] = {'size': len(sums_raw), 'digest': 'sha256:' + hashlib.sha256(sums_raw).hexdigest()}
        return wanted

    def snapshot(self, gh, registry):
        latest = registry.manifest('latest', missing=True)
        return {'main_sha': sha(gh.commit_sha(gh.ref('heads/main'))),
                'latest_digest': latest['digest'] if latest else None}

    def protect(self, gh):
        now = self.snapshot(gh, self.registry)
        if self.protected is not None and now != self.protected:
            raise RuntimeError('main/latest mudaram; não serão sobrescritos.')
        return now

    def check_head(self, gh, plan, branch):
        if plan != self.plan or branch != 'develop' or plan['aliases'] != ['develop']:
            raise ValueError('Somente plano develop exato pode ser promovido.')
        if gh.commit_sha(gh.ref('heads/develop')) != plan['source_sha']:
            raise RuntimeError('O head develop mudou; promoção obsoleta.')
        if plan['source_sha'] != self.ci['trigger_sha']:
            commit = gh.request('GET', gh.base + '/git/commits/' + plan['source_sha'])
            message = commit.get('message', '') + '\n'
            if ([p.get('sha') for p in commit.get('parents', [])] != [self.ci['trigger_sha']]
                or f"Escritura-CI-Run: {self.ci['run_id']}\n" not in message
                or f"Escritura-CI-Trigger: {self.ci['trigger_sha']}\n" not in message):
                raise RuntimeError('Commit preparado não pertence à execução.')
        release = gh.release('develop')
        if release.get('prerelease') is not True or release.get('id') != self.publication['release_id']:
            raise RuntimeError('Pré-release diverge do relatório.')
        if self.protected is not None:
            self.protect(gh)
        if gh.commit_sha(gh.ref('heads/develop')) != plan['source_sha']:
            raise RuntimeError('O head develop mudou antes da promoção.')

    def verify_run(self, run, plan, branch):
        expected = {'id': self.ci['run_id'], 'run_attempt': self.current_attempt, 'run_number': self.ci['run_number'],
                    'head_sha': self.ci['trigger_sha'], 'head_branch': 'develop', 'path': '.github/workflows/release.yml',
                    'status': 'in_progress', 'conclusion': None, 'event': self.env['GITHUB_EVENT_NAME']}
        if any(run.get(k) != v for k, v in expected.items()) or any(run.get(k, {}).get('full_name') != aliases.REPOSITORY for k in ('repository', 'head_repository')):
            raise RuntimeError('Execução corrente diverge do plano/contexto.')

    def verify_gate(self, job):
        # Latest projection retains prior successful gates for a final-job rerun;
        # a newer failed execution must not fall back to an older successful gate.
        attempt = job.get('run_attempt')
        if (job.get('run_id') != self.ci['run_id'] or type(attempt) is not int
            or not self.ci['run_attempt'] <= attempt <= self.current_attempt
            or job.get('head_sha') != self.ci['trigger_sha']):
            raise RuntimeError('Gate pertence a outra execução/tentativa.')

    def verify_assets(self, gh):
        found = {}
        prefix = 'EscrituraIntegrada-' + self.plan['version'] + '-'
        for asset in gh.pages(gh.base + '/releases/' + str(self.publication['release_id']) + '/assets'):
            name = asset.get('name')
            if not isinstance(name, str) or name in found:
                raise RuntimeError('Assets remotos contêm nomes inválidos/duplicados.')
            found[name] = asset
            if name.startswith(prefix) and name not in self.expected_assets:
                raise RuntimeError('Asset inesperado da versão corrente.')
        for name, expected in self.expected_assets.items():
            actual = found.get(name, {})
            if actual.get('state') != 'uploaded' or any(actual.get(k) != v for k, v in expected.items()):
                raise RuntimeError('Asset ausente/trocado/não confirmado: ' + name)
        # Historical receipts are intentionally not removed or rewritten.

    def verify_proof(self, gh, plan):
        aliases.verify_release(gh, plan, 'develop', context=self)
        self.verify_assets(gh)
        for registry, reference in ((self.registry, plan['digest']), (self.registry, plan['version']), (self.public, plan['digest'])):
            manifest = registry.manifest(reference)
            if manifest['digest'] != plan['digest'] or json.loads(manifest['raw']).get('config', {}).get('digest') != self.image_id:
                raise RuntimeError('Digest/config público ou versionado mudou.')
        # Recheck protected refs and head after the longer release/asset proof.
        self.check_head(gh, plan, 'develop')


def promote(context, gh, registry, public, output, *, pull=aliases.pull_identity):
    output = Path(output)
    context.registry, context.public = registry, public
    report = {'schema_version': 1, 'status': 'checking', 'plan': context.plan}
    write_json(output, report)
    try:
        context.protected = context.snapshot(gh, registry)
        context.verify_proof(gh, context.plan)
        def verified_pull(reference, plan, image_id):
            if image_id != context.image_id:
                raise RuntimeError('Image ID diverge do manifesto publicado.')
            return pull(reference, plan, image_id)
        report = aliases.promote(context.plan, gh, registry, public, output, pull=verified_pull, context=context)
    except Exception as exc:
        report = json.loads(output.read_text(encoding='utf-8'))
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        try:
            if context.protected is not None:
                report['protected_before'] = context.protected
                report['protected_after'] = context.protect(gh)
        except Exception as exc:
            report.update(status='failed', protection_error=str(exc))
            raise
        finally:
            write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ci-plan', 'images', 'publication', 'receipts', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    write_json(args.output, {'schema_version': 1, 'status': 'starting'})
    try:
        context = DevelopContext(*(json.loads(p.read_text(encoding='utf-8')) for p in (args.ci_plan, args.images, args.publication)), receipts=args.receipts)
        credential = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not credential:
            raise RuntimeError('Token temporário ausente.')
        registry, public = DevelopRegistry(), aliases.Registry()
        registry.authenticate(actor=os.environ.get('GHCR_ACTOR'), credential=credential)
        public.authenticate()
        promote(context, GitHub(), registry, public, args.output)
    except Exception as exc:
        report = json.loads(args.output.read_text(encoding='utf-8'))
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        write_json(args.output, report)
        raise


if __name__ == '__main__':
    main()
