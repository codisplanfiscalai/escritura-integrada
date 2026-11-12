"""Promove somente aliases explícitos do app, sem build ou mudança de release."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from scripts.image_tools import DIGEST, GHCR_PREFIX
from .github_api import GitHub, NoRedirect
from .release import release_marker, sha, write_json
from .versioning import release_version

REPOSITORY = 'codisplanfiscalai/escritura-integrada'
MEDIA_TYPES = ('application/vnd.docker.distribution.manifest.v2+json',
               'application/vnd.oci.image.manifest.v1+json')
GATES = {'Reservar SemVer e gravar manifests', 'Linux, testes e interface',
         'Windows x64 e smoke do binário distribuído',
         'macOS arm64 · instalação e interface nativas',
         'macOS x64 · instalação e interface nativas',
         'Construção e smoke Docker sem publicação', 'GHCR, bundles conferidos e release'}


def validate_plan(plan):
    if plan.get('schema_version') != 1 or plan.get('repository') != REPOSITORY:
        raise ValueError('Plano fora do repositório/schema autorizado.')
    version = release_version(plan.get('version', ''))
    if str(version) != plan['version']:
        raise ValueError('Versão deve estar normalizada.')
    sha(plan.get('source_sha'))
    if not DIGEST.fullmatch(plan.get('digest', '')):
        raise ValueError('Digest SHA-256 inválido.')
    run_id = plan.get('release_run_id')
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ValueError('Execução de release inválida.')
    aliases = plan.get('aliases')
    if not isinstance(aliases, list) or not aliases or any(x not in ('develop', 'latest') for x in aliases) or len(set(aliases)) != len(aliases):
        raise ValueError('Aliases permitidos: develop e latest, sem duplicatas.')
    if 'develop' in aliases and not version.prerelease:
        raise ValueError('O alias develop exige uma pré-release.')
    if version.prerelease and (len(version.prerelease) != 2 or version.prerelease[0] != 'dev' or not version.prerelease[1].isdigit()):
        raise ValueError('Pré-release deve usar X.Y.Z-dev.N.')
    if version.prerelease and 'latest' in aliases:
        raise ValueError('latest exige versão estável da main; pré-release usa develop.')
    return 'develop' if version.prerelease else 'main'


def check_head(gh, plan, branch, *, context=None):
    if context is not None:
        context.check_head(gh, plan, branch)
        return
    if gh.commit_sha(gh.ref('heads/' + branch)) != plan['source_sha']:
        raise RuntimeError('O head de origem mudou; promoção obsoleta bloqueada.')
    # A queued operational run must not supersede a newer promotion plan.
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        if os.environ.get('GITHUB_REF') != 'refs/heads/ops/ghcr-aliases':
            raise RuntimeError('Promoção exige a branch operacional autorizada.')
        if gh.commit_sha(gh.ref('heads/ops/ghcr-aliases')) != os.environ.get('GITHUB_SHA'):
            raise RuntimeError('Plano operacional superado por outro commit.')


def verify_release(gh, plan, branch, *, context=None):
    if gh.repository != REPOSITORY:
        raise ValueError('Conexão GitHub pertence a outro repositório.')
    check_head(gh, plan, branch, context=context)
    tag = 'develop' if branch == 'develop' else 'v' + plan['version']
    if gh.commit_sha(gh.ref('tags/' + tag)) != plan['source_sha']:
        raise RuntimeError('A tag da release não aponta para o commit solicitado.')
    release = gh.release(tag)
    marker = release_marker(release) or {}
    if release.get('draft') or any(marker.get(key) != plan[key] for key in ('version', 'source_sha')) or marker.get('run_id') != plan['release_run_id']:
        raise RuntimeError('Release publicada não corresponde à versão, SHA e execução.')
    if gh.file('VERSION', plan['source_sha']).strip() != plan['version']:
        raise RuntimeError('VERSION do commit não corresponde ao plano.')
    run_path = gh.base + '/actions/runs/' + str(plan['release_run_id'])
    run = gh.request('GET', run_path)
    if context is not None:
        context.verify_run(run, plan, branch)
    elif run.get('status') != 'completed' or run.get('conclusion') != 'success' or run.get('path') != '.github/workflows/release.yml' or run.get('head_branch') != branch:
        raise RuntimeError('A execução original da release não está aprovada.')
    jobs = list(gh.pages(run_path + '/jobs', key='jobs', params={'filter': 'latest'}))
    for name in GATES:
        matches = [job for job in jobs if job.get('name') == name]
        if len(matches) != 1 or matches[0].get('status') != 'completed' or matches[0].get('conclusion') != 'success':
            raise RuntimeError('Gate da release não aprovado: ' + name)
        if context is not None:
            context.verify_gate(matches[0])
    return {'release_url': release['html_url'], 'run_url': run['html_url'], 'gates': sorted(GATES)}


class Registry:
    """Registry v2 no host fixo; nunca segue redirects com credenciais."""
    def __init__(self):
        self.opener = build_opener(NoRedirect())
        self.token = None

    def authenticate(self, *, actor=None, credential=None):
        headers = {'User-Agent': 'escritura-ghcr-aliases'}
        scope = 'repository:' + REPOSITORY + (':pull,push' if credential else ':pull')
        if credential:
            if not actor:
                raise ValueError('Ator GitHub ausente.')
            headers['Authorization'] = 'Basic ' + base64.b64encode((actor + ':' + credential).encode()).decode()
        query = urlencode({'service': 'ghcr.io', 'scope': scope})
        try:
            with self.opener.open(Request('https://ghcr.io/token?' + query, headers=headers), timeout=30) as response:
                self.token = json.load(response)['token']
        except (HTTPError, URLError, ValueError, KeyError):
            raise RuntimeError('Não foi possível autenticar o acesso solicitado ao GHCR.') from None

    def manifest(self, reference, *, missing=False):
        if reference not in ('develop', 'latest') and not DIGEST.fullmatch(reference):
            release_version(reference)
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': ', '.join(MEDIA_TYPES)}
        request = Request('https://ghcr.io/v2/' + REPOSITORY + '/manifests/' + reference, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(4 * 1024 * 1024)
                digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
                if response.headers.get('Docker-Content-Digest') != digest:
                    raise RuntimeError('Digest do manifesto não confere com seus bytes.')
                media = response.headers.get('Content-Type', '').split(';')[0]
                if media not in MEDIA_TYPES:
                    raise RuntimeError('Somente manifesto simples linux/amd64 é suportado.')
                return {'raw': raw, 'digest': digest, 'media_type': media}
        except HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise RuntimeError('GHCR respondeu HTTP ' + str(exc.code) + ' ao consultar manifesto.') from None
        except URLError:
            raise RuntimeError('Falha de rede ao consultar manifesto GHCR.') from None

    def put_alias(self, alias, manifest):
        if alias not in ('develop', 'latest'):
            raise ValueError('Escrita permitida somente nos aliases develop/latest.')
        headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': manifest['media_type']}
        request = Request('https://ghcr.io/v2/' + REPOSITORY + '/manifests/' + alias,
                          data=manifest['raw'], headers=headers, method='PUT')
        # No implicit retries: if the result is uncertain, inspect the alias first.
        try:
            with self.opener.open(request, timeout=60) as response:
                if response.status != 201 or response.headers.get('Docker-Content-Digest') != manifest['digest']:
                    raise RuntimeError('GHCR não confirmou o digest da promoção.')
        except HTTPError as exc:
            raise RuntimeError('GHCR respondeu HTTP ' + str(exc.code) + ' ao promover alias.') from None
        except URLError:
            raise RuntimeError('Resultado da promoção incerto após falha de rede; confira o alias.') from None


def pull_identity(reference, plan, image_id):
    subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', reference], check=True)
    result = subprocess.run(['docker', 'image', 'inspect', reference], check=True, capture_output=True, text=True)
    image = json.loads(result.stdout)[0]
    labels = image.get('Config', {}).get('Labels') or {}
    if image.get('Id') != image_id or image.get('Os') != 'linux' or image.get('Architecture') != 'amd64':
        raise RuntimeError('Imagem baixada diverge do ID/plataforma aprovados.')
    if labels.get('org.opencontainers.image.version') != plan['version'] or labels.get('org.opencontainers.image.revision') != plan['source_sha']:
        raise RuntimeError('Labels da imagem divergem da versão/SHA solicitados.')
    if GHCR_PREFIX + '@' + plan['digest'] not in image.get('RepoDigests', []):
        raise RuntimeError('Pull não confirmou o digest solicitado.')
    return {'image_id': image['Id'], 'platform': 'linux/amd64', 'pull_verified': True}


def promote(plan, gh, registry, public_registry, output, *, pull=pull_identity, context=None):
    report = {'schema_version': 1, 'status': 'checking', 'plan': plan, 'aliases': {},
              'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        branch = validate_plan(plan)
        report['release'] = verify_release(gh, plan, branch, context=context)
        source = registry.manifest(plan['digest'])
        versioned = registry.manifest(plan['version'])
        if source['digest'] != plan['digest'] or versioned['digest'] != plan['digest']:
            raise RuntimeError('Tag versionada/digest divergentes; nada será promovido.')
        image_id = json.loads(source['raw']).get('config', {}).get('digest', '')
        if not DIGEST.fullmatch(image_id):
            raise RuntimeError('Manifesto não contém ID de imagem válido.')
        report['source_pull'] = pull(GHCR_PREFIX + '@' + plan['digest'], plan, image_id)
        # Read all previous values before the first mutation. A 403 is not absence.
        for alias in plan['aliases']:
            previous = registry.manifest(alias, missing=True)
            report['aliases'][alias] = {'previous_digest': previous['digest'] if previous else None, 'status': 'pending'}
        write_json(output, report)
        for alias in plan['aliases']:
            if context is not None:
                context.verify_proof(gh, plan)
            else:
                check_head(gh, plan, branch)
            item = report['aliases'][alias]
            if item['previous_digest'] != plan['digest']:
                item['status'] = 'writing'
                write_json(output, report)
                registry.put_alias(alias, source)
            if registry.manifest(alias)['digest'] != plan['digest']:
                raise RuntimeError('Alias não aponta para o digest solicitado: ' + alias)
            item.update(status='published', digest=plan['digest'])
            write_json(output, report)
            if public_registry.manifest(alias)['digest'] != plan['digest']:
                raise RuntimeError('Pull anônimo do manifesto divergente: ' + alias)
            item.update(public_pullable=True, **pull(GHCR_PREFIX + ':' + alias, plan, image_id))
            item['status'] = 'verified'
            write_json(output, report)
        if registry.manifest(plan['version'])['digest'] != plan['digest']:
            raise RuntimeError('Tag versionada mudou durante a promoção.')
        if context is not None:
            context.verify_proof(gh, plan)
        report['status'] = 'published'
        return report
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_json(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    write_json(args.output, {'schema_version': 1, 'status': 'starting'})
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        validate_plan(plan)
        credential = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if not credential:
            raise RuntimeError('Token temporário do workflow ausente.')
        registry, public = Registry(), Registry()
        registry.authenticate(actor=os.environ.get('GHCR_ACTOR'), credential=credential)
        public.authenticate()
        result = promote(plan, GitHub(), registry, public, args.output)
    except Exception as exc:
        report = json.loads(args.output.read_text(encoding='utf-8'))
        if report.get('status') != 'failed':
            report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
            write_json(args.output, report)
        raise
    print(json.dumps({'status': result['status'], 'aliases': result['aliases']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
