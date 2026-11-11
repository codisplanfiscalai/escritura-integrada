"""One-off dev.21 recovery. No builds, version reservation or normal gate reruns."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
import zipfile

from .github_api import GitHub, NoRedirect
from .image_aliases import GATES, Registry
from .release import file_hash, release_marker, write_json

REPOSITORY = 'codisplanfiscalai/escritura-integrada'
SOURCE = '1c686036d7e337632a7eb7b204b016063f6df32f'
VERSION = '0.8.0-dev.21'
RUN = 42978878696
BRANCH = 'ops/recover-release-dev21'
PUBLISH_JOB = 'GHCR, bundles conferidos e release'
FAIL_STEP = 'Montar assets com inventário e SHA-256'
SPEC_PATH = Path(__file__).resolve().parents[2] / '.github/recovery-dev21.json'
DESTINATIONS = {'ci-plan': 'build', 'windows-dist': 'artifacts/windows',
                'macos-arm64-dist': 'artifacts/macos/arm64', 'macos-x64-dist': 'artifacts/macos/x64',
                'linux-report': 'artifacts/reports', 'browser-evidence': 'artifacts/reports',
                'docker-validation': 'artifacts/reports', 'publication-reports': 'artifacts',
                'frontend-dist': 'frontend/dist'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_spec(path=SPEC_PATH):
    spec = json.loads(Path(path).read_text())
    fixed = dict(schema_version=1, repository=REPOSITORY, version=VERSION, source_sha=SOURCE,
                 original_run_id=RUN, original_run_attempt=2,
                 trigger_sha='b4f99fe1bb8752a10170c3563811041dfda0451e',
                 main_sha='2ab5d4ea49858b1f9e8716fe46bb478e2d848c88',
                 image_digest='sha256:e875f7402e474717340e73d6a1e6bbc95fbc6d72d34320dd0ced133b05b45c76',
                 latest_digest_unchanged='sha256:1c3dc4deb644ac735fa5c49d3d8ca7e410143659a7cb51a2acb2fa0e64e66c59')
    require(all(spec.get(k) == v for k, v in fixed.items()), 'Plano não corresponde à recuperação dev.21 autorizada.')
    require(len(spec['artifacts']) == len(DESTINATIONS) and {x['name'] for x in spec['artifacts']} == set(DESTINATIONS), 'Inventário incompleto.')
    require(len({x['id'] for x in spec['artifacts']}) == len(DESTINATIONS), 'IDs duplicados.')
    backup = spec['previous_release']
    require(backup.get('durable_backup_restored_verified') is True and len(backup['assets']) == 39
            and backup.get('backup_archive_sha256') == '47cb6509991303955bac5603ab3104010c6b8abb5b8d81cd82f4c00d8ff685a6', 'Backup durável não verificado.')
    return spec


def verify_heads(gh, spec):
    require(gh.repository == REPOSITORY, 'Repositório incorreto.')
    for branch, expected in [('develop', spec['source_sha']), ('main', spec['main_sha'])]:
        require(gh.commit_sha(gh.ref('heads/' + branch)) == expected, 'Head mudou: ' + branch)
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH,
            'Recuperação exige workflow na branch operacional autorizada.')
    require(gh.commit_sha(gh.ref('heads/' + BRANCH)) == os.environ.get('GITHUB_SHA'), 'Commit operacional superado.')


def verify_original(gh, spec):
    path = gh.base + '/actions/runs/' + str(RUN)
    run = gh.request('GET', path)
    expected = dict(id=RUN, run_attempt=2, status='completed', conclusion='failure',
                    path='.github/workflows/release.yml', head_branch='develop', head_sha=spec['trigger_sha'], run_number=21)
    require(all(run.get(k) == v for k, v in expected.items()), 'Execução original mudou ou não corresponde ao plano.')
    jobs = list(gh.pages(path + '/attempts/2/jobs', key='jobs'))
    by_name = {j['name']: j for j in jobs}
    require(len(by_name) == len(jobs), 'Jobs duplicados.')
    for name in GATES - {PUBLISH_JOB}:
        j = by_name.get(name, {})
        require(j.get('status') == 'completed' and j.get('conclusion') == 'success'
                and j.get('run_id') == RUN and j.get('head_sha') == spec['trigger_sha'], 'Gate original não aprovado: ' + name)
    require([j['name'] for j in jobs if j.get('conclusion') not in ('success', 'skipped')] == [PUBLISH_JOB], 'Falha além do empacotamento.')
    publish = by_name[PUBLISH_JOB]
    require(publish.get('status') == 'completed' and publish.get('conclusion') == 'failure', 'Publicação original inesperada.')
    steps = publish['steps']
    require([s['name'] for s in steps if s.get('conclusion') not in ('success', 'skipped')] == [FAIL_STEP], 'Falha original não restrita à montagem.')
    for name, conclusion in [(FAIL_STEP, 'failure'), ('Publicar tag e release do commit testado', 'skipped'),
                             ('Publicar imagens por versão e digest', 'success'), ('Exportar imagens e comprovar carga offline', 'success')]:
        matching = [s for s in steps if s['name'] == name]
        require(len(matching) == 1 and matching[0]['conclusion'] == conclusion, 'Etapa original inesperada: ' + name)
    require(gh.file('VERSION', SOURCE).strip() == VERSION, 'VERSION divergente.')
    return {'run_url': run['html_url'], 'gates': sorted(GATES - {PUBLISH_JOB}), 'original_conclusion': 'failure'}


def verify_published(gh, spec):
    verify_heads(gh, spec)
    release = gh.release('develop')
    marker = release_marker(release) or {}
    require(not release.get('draft') and release.get('prerelease') is True and
            marker.get('version') == VERSION and marker.get('source_sha') == SOURCE and marker.get('run_id') == RUN,
            'Release não corresponde à recuperação.')
    require(gh.commit_sha(gh.ref('tags/develop')) == SOURCE, 'Tag develop divergente.')
    return release


def check_registry(spec):
    registry = Registry()
    registry.authenticate()  # Anonymous; never writes a manifest.
    for ref, digest in [(VERSION, spec['image_digest']), (spec['image_digest'], spec['image_digest']),
                        ('latest', spec['latest_digest_unchanged'])]:
        require(registry.manifest(ref)['digest'] == digest, 'Digest GHCR divergente: ' + ref)


def verify_artifact_metadata(data, item, spec):
    require(all(data.get(k) == item[k] for k in ('id', 'name', 'digest', 'size_in_bytes')) and data.get('expired') is False,
            'Artefato alterado/expirado: ' + item['name'])
    run = data.get('workflow_run', {})
    require(run.get('id') == RUN and run.get('head_sha') == spec['trigger_sha'] and run.get('head_branch') == 'develop'
            and run.get('repository_id') == 1448900908 and run.get('head_repository_id') == 1448900908,
            'Proveniência do artefato divergente.')


def download(gh, path, destination, digest, size):
    """Token only on api.github.com; signed blob URL gets a fresh anonymous request."""
    require(path.startswith(gh.base + '/actions/artifacts/'), 'Endpoint não autorizado.')
    opener = build_opener(NoRedirect())
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'escritura-recovery'}
    if gh.token:
        headers['Authorization'] = 'Bearer ' + gh.token
    try:
        response = opener.open(Request('https://api.github.com' + path, headers=headers), timeout=90)
    except HTTPError as exc:
        if exc.code != 302:
            raise RuntimeError('Download GitHub HTTP ' + str(exc.code)) from None
        location = exc.headers.get('Location', '')
        url = urlsplit(location)
        require(url.scheme == 'https' and not url.username and not url.password and url.port in (None, 443)
                and (url.hostname == 'productionresultssa0.blob.core.windows.net' or
                     (url.hostname or '').endswith('.blob.core.windows.net')),
                'Destino de download inesperado.')
        response = opener.open(Request(location, headers={'User-Agent': 'escritura-recovery'}), timeout=90)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.exists(), 'Download já existe; não sobrescrever nem remover bytes anteriores.')
    h = hashlib.sha256()
    total = 0
    try:
        with response, destination.open('xb') as target:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                require(total <= size, 'Download excedeu tamanho aprovado.')
                h.update(chunk)
                target.write(chunk)
        require(total == size and 'sha256:' + h.hexdigest() == digest, 'Bytes do ZIP divergem do hash/tamanho aprovado.')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def safe_extract(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as z:
        seen = set()
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            require(not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
                    and ':' not in info.filename and p.parts and not any(x.startswith('.') for x in p.parts), 'Caminho ZIP inseguro.')
            require(info.filename not in seen and not stat.S_ISLNK(info.external_attr >> 16), 'ZIP duplicado/symlink.')
            seen.add(info.filename)
            target = destination / p
            require(not target.exists() or (info.is_dir() and target.is_dir()), 'Extração sobrescreveria arquivo: ' + str(p))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open('xb') as out:
                    shutil.copyfileobj(src, out)


def run_source(source, *args):
    subprocess.run([sys.executable, *args], cwd=source, check=True)


def validate_source(source, spec):
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    require(actual == SOURCE, 'Checkout não é o SHA testado.')
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD'], cwd=source, check=True)
    require((source / 'VERSION').read_text().strip() == VERSION, 'VERSION local divergente.')


def verify_plan(plan, spec):
    expected = dict(repository=REPOSITORY, version=VERSION, source_sha=SOURCE, run_id=RUN, run_number=21,
                    branch='develop', channel='develop', tag='develop')
    require(all(plan.get(k) == v for k, v in expected.items()), 'ci-plan original divergente.')


def recover_inputs(gh, spec, source, downloads):
    validate_source(source, spec)
    for item in spec['artifacts']:
        path = gh.base + '/actions/artifacts/' + str(item['id'])
        verify_artifact_metadata(gh.request('GET', path), item, spec)
        target = downloads / (item['name'] + '.zip')
        download(gh, path + '/zip', target, item['digest'], item['size_in_bytes'])
        safe_extract(target, source / DESTINATIONS[item['name']])
    plan = json.loads((source / 'build/ci-plan.json').read_text())
    verify_plan(plan, spec)
    # Publication artifact uses artifacts/ as its common root. The ZIP may have
    # a "release/" subdirectory only if partial manifest output existed.
    require((source / 'artifacts/reports/browser/report.json').is_file(), 'Browser report ausente no destino correto.')
    require((source / 'artifacts/reports/browser-workspace-tabs/report.json').is_file(), 'Evidência workspace ausente.')
    workspace = json.loads((source / 'artifacts/reports/browser-workspace-tabs/report.json').read_text())
    require(workspace.get('ok') is True and workspace.get('version') == VERSION and workspace.get('source_sha') == SOURCE
            and len(workspace.get('checks', [])) >= 9 and len(workspace.get('screenshots', [])) >= 9
            and not workspace.get('console_errors'), 'Gate workspace divergente.')
    for screenshot in workspace.get('screenshots', []):
        require(isinstance(screenshot, str) and Path(screenshot).name == screenshot
                and (source / 'artifacts/reports/browser-workspace-tabs' / screenshot).is_file(), 'Captura workspace ausente.')
    images = json.loads((source / 'artifacts/images-published.json').read_text())
    run_source(source, '-c', 'from scripts.ci.artifacts import validate_images; import json; p=json.load(open("build/ci-plan.json")); validate_images("artifacts/images-published.json",p,published=True); validate_images("artifacts/reports/images-validated.json",p,published=False)')
    require(images['images']['app']['digest'] == spec['image_digest'], 'Digest app fora do plano.')
    for name, item in images['images'].items():
        expected_repo = 'ghcr.io/' + REPOSITORY + ('' if name == 'app' else '-' + name)
        require(item['repository'] == expected_repo and item['reference'] == expected_repo + ':' + item['tag'], 'Referência de imagem inesperada.')
        reference = expected_repo + '@' + item['digest']
        subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', reference], check=True)
        actual = json.loads(subprocess.check_output(['docker', 'image', 'inspect', reference], text=True))[0]
        require(actual['Id'] == item['image_id'] and actual['Os'] == 'linux' and actual['Architecture'] == 'amd64', 'ID/plataforma diverge do aprovado.')
        subprocess.run(['docker', 'tag', reference, item['reference']], check=True)  # Local only, never push.
    run_source(source, 'scripts/package_deploy.py', '--version', VERSION, '--channel', 'develop', '--images-manifest', 'artifacts/images-published.json', '--output-dir', 'artifacts/deploy')
    run_source(source, 'scripts/export_images.py', '--images-manifest', 'artifacts/images-published.json', '--output', 'artifacts/deploy/EscrituraIntegrada-' + VERSION + '-linux-amd64-images.tar.gz', '--verify-load')
    validate_source(source, spec)
    run_source(source, '-m', 'scripts.ci.artifacts')
    return plan


def asset_identity(asset):
    return {k: asset[k] for k in ('id', 'name', 'size', 'digest')}


def check_backup(gh, spec):
    old = spec['previous_release']
    release = gh.release('develop')
    marker = release_marker(release) or {}
    require(release['id'] == old['release_id'] and marker.get('version') == '0.8.0-dev.20'
            and gh.commit_sha(gh.ref('tags/develop')) == old['target'], 'Release anterior mudou; revisão necessária.')
    actual = list(gh.pages(gh.base + '/releases/' + str(release['id']) + '/assets'))
    require(sorted(map(asset_identity, actual), key=lambda a: a['id']) == sorted(map(asset_identity, old['assets']), key=lambda a: a['id']), 'Assets atuais divergem do backup durável.')
    return release


# Imported exclusively from the separate source checkout in the child process.
# The original publisher runs unchanged; its DELETEs can only address the exact
# 39 backed-up asset IDs, and each identity is re-read immediately before deletion.
PUBLISH_SOURCE = '''
import json, sys
from scripts.ci.github_api import GitHub, GitHubError
from scripts.ci.release import publish, write_json
spec=json.load(open(sys.argv[1]))
allowed={str(a['id']):a for a in spec['previous_release']['assets']}
class BackedUpGitHub(GitHub):
    def request(self, method, path, *args, **kwargs):
        if method == 'DELETE':
            prefix=self.base+'/releases/assets/'
            key=path[len(prefix):] if path.startswith(prefix) else ''
            if key not in allowed:
                raise GitHubError('Exclusão fora do backup recusada.')
            current=super().request('GET',path)
            if any(current.get(k)!=allowed[key][k] for k in ('id','name','size','digest')):
                raise GitHubError('Asset mudou desde o backup; exclusão recusada.')
        return super().request(method,path,*args,**kwargs)
plan=json.load(open('build/ci-plan.json'))
result=publish(BackedUpGitHub(),plan,'artifacts/release',json.load(open('artifacts/images-published.json')))
write_json('artifacts/publication.json',result)
if result.get('cleanup_errors'):
    raise RuntimeError('Publicação concluída com limpeza bloqueada; revisar antes de promover.')
'''


def verify_remote_assets(gh, release, directory):
    expected = {p.name: p for p in directory.iterdir() if p.is_file()}
    actual = {a['name']: a for a in gh.pages(gh.base + '/releases/' + str(release['id']) + '/assets')}
    require(set(actual) == set(expected), 'Inventário remoto difere dos assets verificados.')
    for name, path in expected.items():
        a = actual[name]
        require(a.get('state') == 'uploaded' and a['size'] == path.stat().st_size and a.get('digest') == 'sha256:' + file_hash(path), 'Asset remoto não corresponde aos bytes: ' + name)
    return [{'name': p.name, 'size': p.stat().st_size, 'sha256': file_hash(p)} for p in expected.values()]


def publish_recovery(gh, spec, source, spec_path):
    verify_heads(gh, spec)
    evidence = verify_original(gh, spec)
    check_registry(spec)
    check_backup(gh, spec)
    validate_source(source, spec)
    # Verify the link from GitHub rather than constructing unverified metadata.
    recovery_id = int(os.environ['GITHUB_RUN_ID'])
    current = gh.request('GET', gh.base + '/actions/runs/' + str(recovery_id))
    link = 'https://github.com/' + REPOSITORY + '/actions/runs/' + str(recovery_id)
    require(current.get('path') == '.github/workflows/recover-dev21.yml' and current.get('head_sha') == os.environ['GITHUB_SHA']
            and current.get('head_branch') == BRANCH and current.get('html_url') == link, 'Execução de recuperação inesperada.')
    run_source(source, '-c', PUBLISH_SOURCE, str(spec_path.resolve()))
    release = verify_published(gh, spec)
    inventory = verify_remote_assets(gh, release, source / 'artifacts/release')
    note = ('\n\n### Recuperação operacional dev.21\n\n'
            'A execução original terminou com falha somente na montagem dos assets (destino de extração do navegador). '
            'Os seis gates originais foram aprovados. Os binários e evidências foram reutilizados por ID e SHA-256, sem rebuild. '
            'Somente os pacotes Compose e offline foram regenerados com as imagens existentes por digest e carga offline verificada.\n\n'
            'Recuperação: ' + link + '\nExecução original (failure): ' + evidence['run_url'] + '\n')
    gh.request('PATCH', gh.base + '/releases/' + str(release['id']), {'body': release['body'] + note})
    check_registry(spec)
    verify_heads(gh, spec)
    proof = dict(status='verified', version=VERSION, source_sha=SOURCE, original_run_id=RUN,
                 recovery_run_id=recovery_id, recovery_sha=os.environ['GITHUB_SHA'], recovery_run_url=link,
                 original_evidence=evidence, artifact_inputs=spec['artifacts'], assets=inventory,
                 latest_digest_unchanged=spec['latest_digest_unchanged'])
    proof_path = source / 'artifacts/recovery-proof.json'
    write_json(proof_path, proof)
    uploaded = gh.upload(release, proof_path)
    require(uploaded.get('state') == 'uploaded' and uploaded.get('digest') == 'sha256:' + file_hash(proof_path)
            and uploaded.get('size') == proof_path.stat().st_size, 'Receipt remoto não confirmado.')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'recover', 'publish'])
    parser.add_argument('--spec', type=Path, default=SPEC_PATH)
    parser.add_argument('--source', type=Path, default=Path('source'))
    args = parser.parse_args()
    spec = load_spec(args.spec)
    gh = GitHub()
    verify_heads(gh, spec)
    verify_original(gh, spec)
    check_registry(spec)
    check_backup(gh, spec)
    if args.action == 'recover':
        recover_inputs(gh, spec, args.source.resolve(), Path('artifacts/recovery-downloads'))
    elif args.action == 'publish':
        publish_recovery(gh, spec, args.source.resolve(), args.spec)


if __name__ == '__main__':
    main()
