"""Monta uma release correspondente ao commit testado e verifica seus gates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

from .release import ReleaseError, file_hash, validate_assets, validate_plan, write_json
from .versioning import verify_local

MAX_ASSET_BYTES = 2 * 1024**3  # Each GitHub release asset must be smaller than 2 GiB.


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require_report(path, plan, *, source=True):
    data = read_json(path)
    if data.get('ok') is not True or data.get('version') != plan['version']:
        raise ReleaseError('Gate não aprovado ou versão divergente: ' + Path(path).name)
    if source and data.get('source_sha') != plan['source_sha']:
        raise ReleaseError('Gate pertence a outro commit: ' + Path(path).name)
    return data


def copy_file(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ReleaseError('Asset deve ser arquivo regular: ' + source.name)
    if source.stat().st_size < 1 or source.stat().st_size >= MAX_ASSET_BYTES:
        raise ReleaseError('Asset vazio ou excede o limite de 2 GiB: ' + source.name)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def archive_source(root, plan, destination):
    """git archive reads only tracked blobs at the tested SHA, never the workdir."""
    verify_local(root, plan['version'])
    actual = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    if actual != plan['source_sha']:
        raise ReleaseError('O source ZIP exige checkout no commit exato testado.')
    subprocess.run(['git', 'archive', '--format=zip', '--prefix=EscrituraIntegrada-' + plan['version'] + '/', '--output=' + str(destination.resolve()), plan['source_sha']], cwd=root, check=True)
    with zipfile.ZipFile(destination) as bundle:
        version = bundle.read('EscrituraIntegrada-' + plan['version'] + '/VERSION').decode().strip()
        if version != plan['version']:
            raise ReleaseError('VERSION dentro do source ZIP não confere.')


def validate_images(path, plan, *, published):
    data = read_json(path)
    expected = 'published' if published else 'validated'
    if data.get('version') != plan['version'] or data.get('source_sha') != plan['source_sha'] or data.get('channel') != plan['channel'] or data.get('status') != expected:
        raise ReleaseError('Manifest de imagens não corresponde ao gate/commit: ' + Path(path).name)
    if set(data.get('images', {})) != {'app', 'base', 'redis', 'postgres', 'mysql', 'minio'}:
        raise ReleaseError('Manifest de imagens incompleto.')
    smoke = data.get('smoke', {})
    if smoke.get('status') != 'passed':
        raise ReleaseError('Smoke das imagens não foi aprovado.')
    if published:
        for name, item in data['images'].items():
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', item.get('digest') or ''):
                raise ReleaseError('Imagem publicada sem digest válido: ' + name)
    return data


def assemble(plan, *, root, windows_dir, reports_dir, images_manifest, deploy_dir, output_dir, macos_dir=None):
    validate_plan(plan)
    root, windows_dir, reports_dir, deploy_dir, output_dir = map(Path, (root, windows_dir, reports_dir, deploy_dir, output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = 'EscrituraIntegrada-' + plan['version'] + '-'
    if list(output_dir.iterdir()):
        raise ReleaseError('O diretório final deve estar vazio para evitar assets de outra execução.')
    linux = require_report(reports_dir / 'linux-checks.json', plan)
    if linux.get('tests_run', 0) < 1:
        raise ReleaseError('Gate Linux não executou testes.')
    browser_dir = reports_dir / 'browser'
    browser = require_report(browser_dir / 'report.json', plan)
    screenshots = browser.get('screenshots', [])
    if len(browser.get('checks', [])) < 12 or len(screenshots) < 3 or browser.get('console_errors'):
        raise ReleaseError('Gate do navegador não completou os fluxos e capturas.')
    for name in screenshots:
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.png') or not (browser_dir / name).is_file():
            raise ReleaseError('Captura do navegador ausente ou inválida.')
    windows = require_report(windows_dir / 'windows-build.json', plan)
    smoke = require_report(windows_dir / 'windows-smoke.json', plan, source=False)
    if windows.get('smoke_executed') is not True or windows.get('smoke_ok') is not True or not smoke.get('packaged') or not smoke.get('shutdown_complete'):
        raise ReleaseError('O aplicativo Windows empacotado não aprovou abertura e encerramento.')
    supervisor = smoke.get('supervisor', {})
    if supervisor.get('forced_cleanup') is not False or supervisor.get('remaining_processes') != 0 or supervisor.get('root_exit_code') != 0:
        raise ReleaseError('O smoke Windows deixou processos ou precisou de encerramento forçado.')
    archive_name = prefix + 'windows-x64.zip'
    if windows.get('archive') != archive_name or windows.get('sha256') != file_hash(windows_dir / archive_name):
        raise ReleaseError('O ZIP Windows não corresponde ao pacote testado.')
    installer = require_report(windows_dir / 'windows-installer-build.json', plan)
    installed = require_report(windows_dir / 'windows-installer-smoke.json', plan, source=False)
    installer_name = prefix + 'windows-x64-setup.exe'
    if installer.get('installer') != installer_name or installer.get('sha256') != file_hash(windows_dir / installer_name) or len(installed.get('checks',[])) < 7:
        raise ReleaseError('Instalador Windows não corresponde aos testes de instalação/atualização.')
    installed_gui=require_report(windows_dir / 'windows-installed-gui.json',plan,source=False)
    installed_processes=installed_gui.get('supervisor',{})
    if not installed_gui.get('packaged') or not installed_gui.get('shutdown_complete') or installed_processes.get('forced_cleanup') is not False or installed_processes.get('remaining_processes')!=0 or installed_processes.get('root_exit_code')!=0:
        raise ReleaseError('Aplicativo instalado não concluiu abertura/encerramento sem processos remanescentes.')
    macos_dir=Path(macos_dir) if macos_dir else reports_dir.parent/'macos'
    for arch in ('arm64','x64'):
        folder=macos_dir/arch
        build=require_report(folder/f'macos-{arch}-build.json',plan)
        native=require_report(folder/f'macos-{arch}-smoke.json',plan)
        package=prefix+f'macos-{arch}.pkg'
        if build.get('package')!=package or build.get('sha256')!=file_hash(folder/package) or not native.get('installed') or not native.get('updated') or native.get('forced_cleanup') is not False or native.get('remaining_processes')!=0:
            raise ReleaseError('Pacote macOS sem instalação, atualização ou encerramento nativos comprovados: '+arch)
        for name in (package,f'macos-{arch}-build.json',f'macos-{arch}-smoke.json',f'macos-{arch}-smoke.png'):
            copy_file(folder/name,output_dir/(name if name==package else prefix+name))
    copy_file(windows_dir/installer_name,output_dir/installer_name)
    for name in ('windows-installer-build.json','windows-installer-smoke.json','windows-installed-gui.json','windows-installed-gui.png'):
        copy_file(windows_dir/name,output_dir/(prefix+name))
    images = validate_images(images_manifest, plan, published=True)
    validate_images(reports_dir / 'images-validated.json', plan, published=False)
    deployment = read_json(deploy_dir / (prefix + 'deploy-manifest.json'))
    if deployment.get('version') != plan['version'] or deployment.get('source_sha') != plan['source_sha'] or deployment.get('channel') != plan['channel']:
        raise ReleaseError('Os pacotes de implantação pertencem a outra versão/commit.')
    expected_deploy = {prefix + env + '-deploy.zip' for env in ('production', 'develop')}
    if {item['file'] for item in deployment.get('packages', [])} != expected_deploy:
        raise ReleaseError('São necessários os dois ambientes de implantação.')
    for item in deployment['packages']:
        if item['sha256'] != file_hash(deploy_dir / item['file']):
            raise ReleaseError('Checksum do pacote Compose não confere.')
    offline_name = prefix + 'linux-amd64-images.tar.gz'
    offline = read_json(deploy_dir / (offline_name + '.manifest.json'))
    # export_images owns this contract and performs a load + --pull never smoke.
    if offline.get('version') != plan['version'] or offline.get('source_sha') != plan['source_sha'] or offline.get('offline_load_verified') is not True or offline.get('load_smoke', {}).get('status') != 'passed':
        raise ReleaseError('O bundle offline não tem exportação e docker load verificados.')
    if offline.get('sha256') != file_hash(deploy_dir / offline_name):
        raise ReleaseError('Checksum do bundle offline não confere.')
    for path in sorted(deploy_dir.iterdir()):
        if path.is_file() and path.name.startswith(prefix):
            copy_file(path, output_dir / path.name)
    copy_file(windows_dir / archive_name, output_dir / archive_name)
    for filename in ('windows-build.json', 'windows-smoke.json', 'windows-smoke.png', 'windows-smoke-app.json', 'windows-smoke-logs.log'):
        path = windows_dir / filename
        if path.is_file():
            copy_file(path, output_dir / (prefix + filename))
        elif filename in {'windows-build.json', 'windows-smoke.json', 'windows-smoke.png'}:
            raise ReleaseError('Evidência Windows ausente: ' + filename)
    for filename in ('linux-checks.json', 'linux-checks.log', 'images-validated.json'):
        copy_file(reports_dir / filename, output_dir / (prefix + filename))
    copy_file(images_manifest, output_dir / (prefix + 'images.json'))
    with zipfile.ZipFile(output_dir / (prefix + 'browser-evidence.zip'), 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in ['report.json', *screenshots]:
            path = browser_dir / name
            if path.is_symlink() or path.stat().st_size < 1:
                raise ReleaseError('Evidência do navegador inválida: ' + name)
            bundle.write(path, arcname=name)
    archive_source(root, plan, output_dir / (prefix + 'source.zip'))
    files = sorted(path for path in output_dir.iterdir() if path.is_file())
    for path in files:
        if path.stat().st_size >= MAX_ASSET_BYTES:
            raise ReleaseError('Asset excede o limite de upload: ' + path.name)
    manifest = {'schema_version': 1, 'application': 'Escritura Integrada', 'version': plan['version'], 'channel': plan['channel'], 'repository': plan['repository'], 'source_sha': plan['source_sha'], 'tag': plan['tag'], 'run_id': plan['run_id'], 'run_number': plan['run_number'], 'created_at': datetime.now(timezone.utc).isoformat(), 'gates': {'linux': True, 'windows_packaged': True, 'docker_validation': True, 'docker_published_smoke': True, 'offline_load': True}, 'images': images['images'], 'public_pullable': images.get('public_pullable'), 'platforms': ['windows/x64', 'macos/arm64', 'macos/x64', 'linux/amd64'], 'assets': [{'name': path.name, 'size': path.stat().st_size, 'sha256': file_hash(path)} for path in files]}
    manifest['gates'].update(browser_flows=True,windows_installer=True,macos_arm64=True,macos_x64=True)
    write_json(output_dir / (prefix + 'manifest.json'), manifest)
    checksums = ''.join(file_hash(path) + '  ' + path.name + '\n' for path in sorted(output_dir.iterdir()) if path.is_file())
    (output_dir / (prefix + 'SHA256SUMS.txt')).write_text(checksums, encoding='ascii')
    validate_assets(plan, output_dir)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path('build/ci-plan.json'))
    parser.add_argument('--windows-dir', type=Path, default=Path('artifacts/windows'))
    parser.add_argument('--macos-dir',type=Path,default=Path('artifacts/macos'))
    parser.add_argument('--reports-dir', type=Path, default=Path('artifacts/reports'))
    parser.add_argument('--images-manifest', type=Path, default=Path('artifacts/images-published.json'))
    parser.add_argument('--deploy-dir', type=Path, default=Path('artifacts/deploy'))
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts/release'))
    args = parser.parse_args()
    try:
        manifest = assemble(read_json(args.plan), root=Path.cwd(), windows_dir=args.windows_dir, macos_dir=args.macos_dir, reports_dir=args.reports_dir, images_manifest=args.images_manifest, deploy_dir=args.deploy_dir, output_dir=args.output_dir)
        print(json.dumps({'version': manifest['version'], 'assets': len(manifest['assets']), 'output_dir': str(args.output_dir)}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, ReleaseError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
