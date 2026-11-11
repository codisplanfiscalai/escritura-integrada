"""Publish additive, hash-verified Dockge deploy supplements; never replace assets."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

REPO = 'codisplanfiscalai/escritura-integrada'
MAX_DOWNLOAD = 2 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def gh(path, *, method='GET', body=None):
    # gh owns the Actions token; do not expose it to downloaded URLs.
    command = ['gh', 'api', '--method', method, f'repos/{REPO}/{path}']
    if body is not None:
        command += ['--input', '-']
    result = subprocess.run(command, input=json.dumps(body) if body is not None else None,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def download(url):
    if not url.startswith(f'https://github.com/{REPO}/releases/download/'):
        raise ValueError('Only public release asset URLs are allowed.')
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Asset too large.')
    return data


def verify_release(plan):
    release = gh('releases/' + str(plan['id']))
    if release['tag_name'] != plan['tag'] or release['draft'] or release.get('immutable'):
        raise ValueError('Release target is not the approved mutable published release.')
    if plan['source_sha'] not in release['body'] or plan['version'] not in release['body']:
        raise ValueError('Release source marker changed.')
    tag = gh('git/ref/tags/' + urllib.parse.quote(plan['tag'], safe=''))['object']
    if tag['type'] == 'tag':
        tag = gh('git/tags/' + tag['sha'])['object']
    if tag['type'] != 'commit' or tag['sha'] != plan['source_sha']:
        raise ValueError('Release tag changed.')
    original = {item['id']: item for item in release['assets']}
    for asset in plan['assets']:
        live = original.get(asset['id'], {})
        expected = {'name': asset['name'], 'size': asset['size'],
                    'browser_download_url': asset['url'], 'digest': 'sha256:' + asset['sha256']}
        if any(live.get(key) != value for key, value in expected.items()):
            raise ValueError('Original asset identity changed: ' + asset['name'])
    return release


def compare_compose(original_zip, corrected_zip, folder):
    # Read only known members after patcher has validated the original archive.
    old = zipfile.ZipFile(original_zip)
    new = zipfile.ZipFile(corrected_zip)
    prefix = Path(original_zip).stem
    folder.mkdir(parents=True)
    env = folder / 'release.env'
    env.write_bytes(old.read(prefix + '/.env'))
    config = folder / 'compose.yaml'
    results = []
    clean_env = {key: value for key, value in os.environ.items()
                 if not key.startswith(('ESCRITURA_', 'COMPOSE_', 'REDIS_', 'POSTGRES_', 'MYSQL_', 'MINIO_'))}
    for archive in (old, new):
        config.write_bytes(archive.read(prefix + '/compose.yaml'))
        command = ['docker', 'compose', '--project-directory', str(folder), '-p', 'dockge-compat-check',
                   '--env-file', str(env), '-f', str(config), '--profile', '*', 'config', '--format', 'json']
        result = subprocess.run(command, env=clean_env, capture_output=True, text=True, check=True)
        results.append(json.loads(result.stdout))
    old.close()
    new.close()
    if results[0] != results[1]:
        raise ValueError('Docker Compose normalized configuration changed.')


def prepare(plan, output, tool_commit):
    output.mkdir(parents=True, exist_ok=True)
    summary = {'schema_version': 1, 'tool_commit': tool_commit, 'releases': []}
    with tempfile.TemporaryDirectory(prefix='dockge-patch-') as tmp:
        temp = Path(tmp)
        for target in plan['releases']:
            verify_release(target)
            dest = output / target['tag']
            dest.mkdir()
            for asset in target['assets']:
                raw = download(asset['url'])
                if digest(raw) != asset['sha256'] or len(raw) != asset['size']:
                    raise ValueError('Downloaded source hash/size mismatch.')
                original = temp / asset['name']
                original.write_bytes(raw)
                subprocess.run(['python', '-m', 'scripts.ci.dockge_release_patch', '--zip', str(original),
                                '--expected-sha256', asset['sha256'], '--version', target['version'],
                                '--environment', asset['environment'], '--output-dir', str(dest),
                                '--tool-commit', tool_commit, '--expected-source-sha', target['source_sha']], check=True)
                patched = dest / (original.stem + '-dockge-r1.zip')
                compare_compose(original, patched, temp / original.stem)
            files = [{'name': f.name, 'sha256': digest(f.read_bytes()), 'size': f.stat().st_size}
                     for f in sorted(dest.iterdir()) if f.is_file()]
            if len(files) != 6:
                raise ValueError('Expected exactly two ZIPs and their checksum/report sidecars.')
            summary['releases'].append({'id': target['id'], 'tag': target['tag'], 'files': files})
    (output / 'publication.json').write_text(json.dumps(summary, indent=2) + '\n')


def publish(plan, output, tool_commit):
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/ops/dockge-release-patches':
        raise ValueError('Publishing is restricted to the approved operational Actions branch.')
    summary = json.loads((output / 'publication.json').read_text())
    if summary['tool_commit'] != tool_commit:
        raise ValueError('Prepared artifacts belong to another tool commit.')
    # Validate both release targets before creating even the first supplement.
    for target in plan['releases']:
        verify_release(target)
    for target, prepared in zip(plan['releases'], summary['releases'], strict=True):
        if (target['id'], target['tag']) != (prepared['id'], prepared['tag']):
            raise ValueError('Prepared release target mismatch.')
        for file in prepared['files']:
            path = output / target['tag'] / file['name']
            if path.name != file['name'] or digest(path.read_bytes()) != file['sha256'] or path.stat().st_size != file['size']:
                raise ValueError('Prepared file changed.')
        # Complete preflight before the first upload to this release.
        live = verify_release(target)
        existing = {item['name']: item for item in live['assets']}
        for file in prepared['files']:
            if file['name'] in existing and digest(download(existing[file['name']]['browser_download_url'])) != file['sha256']:
                raise ValueError('Existing supplement differs; no deletion or overwrite is permitted.')
        for file in prepared['files']:
            live = verify_release(target)
            existing = {item['name']: item for item in live['assets']}
            if file['name'] not in existing:
                # No --clobber: a race or uncertain prior outcome fails without replacing anything.
                subprocess.run(['gh', 'release', 'upload', target['tag'], str(output / target['tag'] / file['name']),
                                '--repo', REPO], check=True)
            refreshed = verify_release(target)
            published = next(item for item in refreshed['assets'] if item['name'] == file['name'])
            if digest(download(published['browser_download_url'])) != file['sha256']:
                raise ValueError('Published asset hash mismatch.')
        live = verify_release(target)
        marker = '<!-- dockge-r1-supplement -->'
        zips = [item for item in live['assets'] if item['name'] in {f['name'] for f in prepared['files'] if f['name'].endswith('.zip')}]
        note = '\n\n' + marker + '\n### Pacotes de deploy compatíveis com Dockge (r1)\n\n'
        note += 'Para Docker/Dockge, use os pacotes adicionais abaixo. Somente a sintaxe de `app.ports` foi corrigida. '
        note += 'Versão, imagens, `.env`, redes, volumes e arquivos originais permanecem preservados. '
        note += 'Em uma instalação existente, substitua somente `compose.yaml` no mesmo diretório da stack; mantenha seu `.env` e os volumes. Não use `down -v`.\n\n'
        note += '\n'.join('- [' + a['name'] + '](' + a['browser_download_url'] + ')' for a in sorted(zips, key=lambda a: a['name']))
        note += '\n\nCada ZIP possui SHA-256 e relatório próprios anexos. Os manifestos e hashes originais continuam descrevendo a distribuição original.\n'
        if marker not in live['body']:
            gh('releases/' + str(target['id']), method='PATCH', body={'body': live['body'] + note})
        print(json.dumps({'release': target['tag'], 'assets_verified': [f['name'] for f in prepared['files']]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'publish'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tool-commit', required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if plan['repository'] != REPO or plan['schema_version'] != 1:
        raise ValueError('Unexpected publication plan.')
    if args.mode == 'prepare':
        prepare(plan, args.output, args.tool_commit)
    else:
        publish(plan, args.output, args.tool_commit)


if __name__ == '__main__':
    main()
