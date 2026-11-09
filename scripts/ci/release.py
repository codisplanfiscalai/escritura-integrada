"""Publicação auditável de main/develop. Nenhum comando usa shell=True.

Branch heads só avançam em fast-forward. A única referência autorizada a mover
é refs/tags/develop. Releases estáveis publicadas nunca têm assets substituídos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

from .github_api import GitHub, GitHubError
from .merge import MergeError, fetch_commits, merge_local, push_develop
from .versioning import MANIFESTS, OPTIONAL_MANIFESTS, SemVer, choose_version, develop_version_after_main, manifest_versions, read_manifests, release_version, set_local, transform

SHA = re.compile(r'^[0-9a-f]{40}$')
MARKER = re.compile(r'<!-- escritura-ci:(\{[^\n]+\}) -->')


class ReleaseError(RuntimeError):
    pass


class StaleRun(ReleaseError):
    pass


def sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ReleaseError('SHA de origem inválido.')
    return value


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def outputs(values):
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a', encoding='utf-8') as handle:
            for key, value in values.items():
                if not re.fullmatch(r'[a-z_]+', key):
                    raise ReleaseError('Nome de output não permitido.')
                value = str(value).lower() if isinstance(value, bool) else str(value)
                if '\n' in value or '\r' in value:
                    raise ReleaseError('Output contém quebra de linha inesperada.')
                handle.write(f'{key}={value}\n')


def remote_manifests(gh, commit):
    files = {p: gh.file(p, commit) for p in MANIFESTS}
    if any(value is None for value in files.values()):
        raise ReleaseError('Manifest obrigatório ausente no commit de origem.')
    for path in OPTIONAL_MANIFESTS:
        content = gh.file(path, commit, missing=True)
        if content is not None:
            files[path] = content
    return files


def stable_tags(gh):
    refs = gh.request('GET', gh.base + '/git/matching-refs/tags/v')
    result = {}
    for ref in refs:
        name = ref.get('ref', '').removeprefix('refs/tags/')
        try:
            version = release_version(name.removeprefix('v'))
        except ValueError:
            continue
        if name.startswith('v') and version.stable:
            result[str(version)] = ref
    return result


def head(gh, branch, missing=False):
    if branch not in {'main', 'develop'}:
        raise ReleaseError('Branch não autorizada.')
    return gh.commit_sha(gh.ref('heads/' + branch, missing=missing))


def commit_versions(gh, branch, base_sha, version, *, create_branch=False, commit_message=None):
    """Publish only the allowlisted manifests, preserving all application code."""
    sha(base_sha)
    files = remote_manifests(gh, base_sha)
    updates = {path: transform(path, content, version) for path, content in files.items()}
    changes = {path: value for path, value in updates.items() if value != files[path]}
    current = head(gh, branch, missing=create_branch)
    if create_branch:
        if current is not None:
            raise StaleRun('A branch develop foi criada por outra execução; não foi substituída.')
    elif current != base_sha:
        raise StaleRun('A branch avançou antes do commit de versão; nenhuma referência foi forçada.')
    if not changes:
        if create_branch:
            gh.request('POST', gh.base + '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': base_sha})
        return base_sha, []
    original_commit = gh.request('GET', gh.base + '/git/commits/' + base_sha)
    tree = gh.request('POST', gh.base + '/git/trees', {'base_tree': original_commit['tree']['sha'], 'tree': [{'path': path, 'mode': '100644', 'type': 'blob', 'content': content} for path, content in sorted(changes.items())]})
    commit = gh.request('POST', gh.base + '/git/commits', {'message': commit_message or f'chore(release): preparar {version}', 'tree': tree['sha'], 'parents': [base_sha]})
    new_sha = sha(commit['sha'])
    if create_branch:
        gh.request('POST', gh.base + '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': new_sha})
    else:
        # The API rejects a non-fast-forward if somebody pushed after our read.
        gh.request('PATCH', gh.base + '/git/refs/heads/' + branch, {'sha': new_sha, 'force': False})
    if head(gh, branch) != new_sha:
        raise StaleRun('A branch avançou após o commit de versão; publicação desta execução será descartada.')
    return new_sha, sorted(changes)


def prepare(gh, *, branch, event_sha, run_number, run_id, run_attempt=1, expected_sha=None):
    if branch not in {'main', 'develop'}:
        raise ReleaseError('Somente main/develop podem executar publicação.')
    event_sha = sha(event_sha)
    current = head(gh, branch)
    retry_own_commit = False
    if current != event_sha and int(run_attempt) > 1:
        candidate = gh.request('GET', gh.base + '/git/commits/' + current)
        retry_own_commit = ([p['sha'] for p in candidate.get('parents', [])] == [event_sha]
            and f'Escritura-CI-Run: {int(run_id)}\n' in candidate.get('message', '') + '\n'
            and f'Escritura-CI-Trigger: {event_sha}\n' in candidate.get('message', '') + '\n')
    if (current != event_sha and not retry_own_commit) or (expected_sha and sha(expected_sha) not in ({event_sha, current} if retry_own_commit else {current})):
        raise StaleRun('Execução superada por outro commit; nenhuma publicação será feita.')
    files = remote_manifests(gh, current)
    main_sha = head(gh, 'main')
    main_version = gh.file('VERSION', main_sha).strip()
    current_version = files['VERSION'].strip()
    reserved = stable_tags(gh)
    current_core = str(release_version(current_version).without_suffix())
    current_ref = reserved.get(current_core)
    coherent = all(v == current_core for v in manifest_versions(files).values())
    same_head_tag = 'v' + current_core if current_ref and gh.commit_sha(current_ref) == current and coherent else None
    version = choose_version(branch, current_version, main_version, list(reserved), int(run_number), same_head_tag)
    tag = 'v' + version if branch == 'main' else 'develop'
    existing = gh.release(tag, missing=True)
    already = bool(branch == 'main' and existing and not existing.get('draft') and not existing.get('prerelease') and same_head_tag == tag)
    if not already:
        message = f'chore(release): preparar {version}\n\nEscritura-CI-Run: {int(run_id)}\nEscritura-CI-Trigger: {event_sha}'
        current, changed = commit_versions(gh, branch, current, version, commit_message=message)
    else:
        changed = []
    if branch == 'main':
        main_sha, main_version = current, version
    return {'schema': 'escritura-ci-plan/1', 'repository': gh.repository, 'branch': branch, 'channel': 'production' if branch == 'main' else 'develop', 'version': version, 'tag': tag, 'source_sha': current, 'trigger_sha': event_sha, 'main_source_sha': main_sha, 'main_version': main_version, 'run_id': int(run_id), 'run_number': int(run_number), 'run_attempt': int(run_attempt), 'proceed': True, 'needs_release': not already, 'already_released': already, 'versioned_files': changed}


def validate_plan(plan, repository=None):
    if plan.get('schema') != 'escritura-ci-plan/1':
        raise ReleaseError('Formato de plano inválido.')
    if repository and plan.get('repository') != repository:
        raise ReleaseError('Plano pertence a outro repositório.')
    branch = plan.get('branch')
    if branch not in {'main', 'develop'}:
        raise ReleaseError('Branch de publicação inválida.')
    version = release_version(plan.get('version', ''))
    if branch == 'main' and (not version.stable or plan.get('tag') != 'v' + str(version) or plan.get('channel') != 'production'):
        raise ReleaseError('main exige tag estável vX.Y.Z e canal production.')
    if branch == 'develop' and (len(version.prerelease) != 2 or version.prerelease[0] != 'dev' or not version.prerelease[1].isdigit() or plan.get('tag') != 'develop' or plan.get('channel') != 'develop'):
        raise ReleaseError('develop exige X.Y.Z-dev.N e marcador develop.')
    sha(plan.get('source_sha'))
    return version


def release_marker(release):
    match = MARKER.search(release.get('body') or '')
    if not match:
        return None
    try:
        result = json.loads(match.group(1))
        release_version(result['version']); sha(result['source_sha'])
        return result
    except (ValueError, KeyError):
        return None


def guard(gh, plan):
    version = validate_plan(plan, gh.repository)
    if head(gh, plan['branch']) != plan['source_sha']:
        raise StaleRun('O head atual não é o commit testado; publicação bloqueada.')
    if plan['branch'] == 'develop':
        current_main = release_version(gh.file('VERSION', head(gh, 'main')).strip()).without_suffix()
        if version.compare(current_main) <= 0:
            raise StaleRun('A versão develop deixou de ser superior à main; gere uma nova execução.')
        current_release = gh.release('develop', missing=True)
        if current_release:
            marker = release_marker(current_release)
            if marker and release_version(marker['version']).compare(version) > 0:
                raise StaleRun('A pré-release atual é superior à desta execução; regressão recusada.')
    else:
        reference = gh.ref('tags/' + plan['tag'], missing=True)
        if reference and gh.commit_sha(reference) != plan['source_sha']:
            raise ReleaseError('A tag estável já aponta para outro commit e não será alterada.')
    return True


def set_develop_tag(gh, target, *, expected=None):
    """Only this exact tag may move. Branch heads never use force."""
    sha(target)
    reference = gh.ref('tags/develop', missing=True)
    current = gh.commit_sha(reference)
    if expected is not None and current != expected:
        raise StaleRun('A tag develop mudou fora desta publicação; atualização recusada.')
    if reference:
        if current != target:
            gh.request('PATCH', gh.base + '/git/refs/tags/develop', {'sha': target, 'force': True})
    else:
        gh.request('POST', gh.base + '/git/refs', {'ref': 'refs/tags/develop', 'sha': target})
    return current


def reserve(gh, plan):
    """Reserve a stable SemVer only after gates, before any immutable OCI push.

    If the branch advances during registry publication, the next main run sees
    the reserved tag and selects another patch instead of colliding with OCI.
    A reserved tag is never moved/deleted, even when the release remains pending.
    """
    guard(gh, plan)
    if plan['branch'] != 'main':
        return {'reserved': False, 'reason': 'develop uses its unique run number'}
    reference = gh.ref('tags/' + plan['tag'], missing=True)
    if reference is None:
        gh.request('POST', gh.base + '/git/refs', {'ref': 'refs/tags/' + plan['tag'], 'sha': plan['source_sha']})
    guard(gh, plan)
    return {'reserved': True, 'tag': plan['tag'], 'source_sha': plan['source_sha']}


def release_body(plan, manifest_name, checksums_name, image_manifest):
    marker = {'version': plan['version'], 'source_sha': plan['source_sha'], 'run_id': plan['run_id'], 'run_number': plan['run_number'], 'asset_prefix': 'EscrituraIntegrada-' + plan['version'] + '-'}
    images = image_manifest.get('images', {})
    visibility = []
    for name, item in images.items():
        if not isinstance(item, dict):
            continue
        pullable = item.get('public_pullable', image_manifest.get('public_pullable'))
        note = 'pull anônimo verificado' if pullable is True else 'pode exigir autenticação/ajuste de visibilidade; conferir manifest'
        visibility.append(f"- {name}: `{item.get('repository', '')}@{item.get('digest', '')}` — {note}.")
    title = 'Versão estável' if plan['branch'] == 'main' else 'Pré-release contínua de desenvolvimento'
    return f"""## {title} {plan['version']}

Commit testado: [`{plan['source_sha']}`](https://github.com/{plan['repository']}/commit/{plan['source_sha']}).
Execução: https://github.com/{plan['repository']}/actions/runs/{plan['run_id']}.

### Entrega

- Instalador Windows x64 `.exe` com atualização, backup, migração da distribuição portátil e preservação dos dados; ZIP portátil mantido.
- Aplicativo e instaladores `.pkg` nativos para macOS 15 ou superior: Apple Silicon (`arm64`) e Intel (`x64`).
- Exercícios com doze meses por empresa/módulo; fechamento e reabertura independentes; grupos, acessos individuais e permissões efetivas auditáveis.
- Menus por área; finalização e transporte segregado de apurações; livros auxiliares e relatórios com PDF/Excel.
- Auditor Fiscal nativo: auditorias interna/avulsa, catálogos revisáveis, documentos/itens, achados, conciliação e relatórios PDF/Excel persistidos. Cobertura e limitações descritas abaixo.
- Experiência do Auditor: painel executivo, análise crítica, grade de documentos e inspeção por abas; PDF analítico/sintético e Excel com painel, componentes e diferenças recuperados do modelo original.
- Fontes do commit testado, pacotes Compose/.env de produção/desenvolvimento e imagens Linux amd64 para uso offline.
- Integridade e inventário: `{manifest_name}` e `{checksums_name}`. Relatórios anexos comprovam os gates Linux, interface, instalação/atualização Windows, macOS nas duas arquiteturas e imagens Docker.
- Exportação preserva a área de trabalho e a janela maximizada; prévia PDF no Fiscal, Contábil, Financeiro, apurações e Auditor.
- Consultas em lote e paginação reduzem trabalho repetido sem alterar totais ou permissões.
- Consulte [as correções e medições](https://github.com/{plan['repository']}/blob/{plan['source_sha']}/docs/EXPORTACAO_DESEMPENHO_0_7_3.md) e [a instalação](https://github.com/{plan['repository']}/blob/{plan['source_sha']}/docs/DISTRIBUICAO_DESKTOP.md).
- Assinatura Authenticode/Developer ID e notarização não estão configuradas. O teste no runner não homologa o download pelo SmartScreen/Gatekeeper.
- Dados de demonstração são fictícios. Social cobre somente competências; apuração fiscal legal, livros oficiais e integração Prosoft dependem da homologação documentada.

### Imagens GHCR

{chr(10).join(visibility) or '- Consulte o manifest de imagens.'}

A publicação autenticada não altera automaticamente a visibilidade de novos packages. O bundle de imagens permite `docker load` sem depender de pull anônimo.

{'Este marcador develop será atualizado pela próxima execução aprovada; nomes e manifest dos assets identificam esta SemVer.' if plan['branch'] == 'develop' else 'Esta tag e os assets publicados são preservados pelo fluxo; uma alteração exige outra SemVer.'}

<!-- escritura-ci:{json.dumps(marker, ensure_ascii=True, separators=(',', ':'))} -->
"""


def validate_assets(plan, directory):
    prefix = 'EscrituraIntegrada-' + plan['version'] + '-'
    directory = Path(directory)
    manifest_name = prefix + 'manifest.json'
    checksums_name = prefix + 'SHA256SUMS.txt'
    manifest = json.loads((directory / manifest_name).read_text(encoding='utf-8'))
    if manifest.get('version') != plan['version'] or manifest.get('source_sha') != plan['source_sha'] or manifest.get('repository') != plan['repository']:
        raise ReleaseError('Manifest não corresponde ao plano de publicação.')
    wanted = {entry['name']: entry for entry in manifest.get('assets', [])}
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files or any(not p.name.startswith(prefix) for p in files):
        raise ReleaseError('Todos os assets precisam do prefixo exato da versão.')
    if set(p.name for p in files) != set(wanted) | {manifest_name, checksums_name}:
        raise ReleaseError('Arquivos extras/ausentes no conjunto de publicação.')
    for filename, entry in wanted.items():
        path = directory / filename
        if path.name != filename or path.stat().st_size != entry['size']:
            raise ReleaseError('Nome ou tamanho divergente no manifest.')
        actual = file_hash(path)
        if actual != entry['sha256']:
            raise ReleaseError('SHA-256 divergente em ' + filename)
    checksum_lines = {}
    for line in (directory / checksums_name).read_text(encoding='ascii').splitlines():
        checksum, name = line.split('  ', 1)
        checksum_lines[name] = checksum
    if set(checksum_lines) != {p.name for p in files if p.name != checksums_name}:
        raise ReleaseError('Lista SHA256SUMS incompleta ou com nomes inesperados.')
    for path in files:
        if path.name != checksums_name and checksum_lines[path.name] != file_hash(path):
            raise ReleaseError('SHA256SUMS não confere com ' + path.name)
    return files, manifest_name, checksums_name


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def stage_assets(gh, release, files, *, replace_allowed):
    existing = {asset['name']: asset for asset in gh.pages(gh.base + f"/releases/{release['id']}/assets")}
    for path in files:
        asset = existing.get(path.name)
        if asset:
            same = asset.get('size') == path.stat().st_size and asset.get('digest') == 'sha256:' + file_hash(path)
            if same:
                continue
            if not replace_allowed:
                raise ReleaseError('Asset estável publicado não pode ser substituído: ' + path.name)
            gh.request('DELETE', gh.base + '/releases/assets/' + str(asset['id']))
        uploaded = gh.upload(release, path)
        if uploaded.get('state') != 'uploaded' or uploaded.get('size') != path.stat().st_size:
            raise ReleaseError('Upload não foi confirmado integralmente: ' + path.name)
        if uploaded.get('digest') and uploaded['digest'] != 'sha256:' + file_hash(path):
            raise ReleaseError('Digest retornado pelo GitHub não corresponde ao arquivo: ' + path.name)


def publish(gh, plan, directory, image_manifest):
    validate_plan(plan, gh.repository)
    files, manifest_name, checksums_name = validate_assets(plan, directory)
    guard(gh, plan)
    tag, stable = plan['tag'], plan['branch'] == 'main'
    release = gh.release(tag, missing=True)
    if release and release.get('immutable') and not stable:
        raise ReleaseError('A política global de releases imutáveis impede o marcador develop. Não será desabilitada automaticamente.')
    if release and not release.get('draft') and stable:
        if release.get('prerelease'):
            raise ReleaseError('Tag estável já vinculada a pré-release inesperada.')
        # A retry never rewrites stable assets, even if a rebuild has timestamps.
        return {'status': 'already_published', 'release_id': release['id'], 'url': release['html_url'], 'version': plan['version']}
    if release and not stable and not release.get('prerelease'):
        raise ReleaseError('O marcador develop aponta para uma release estável; nenhuma alteração foi feita.')
    old_ref = gh.ref('tags/' + tag, missing=True)
    old_tag_sha = gh.commit_sha(old_ref)
    if stable and old_ref is None:
        gh.request('POST', gh.base + '/git/refs', {'ref': 'refs/tags/' + tag, 'sha': plan['source_sha']})
    if not stable and old_ref is None:
        set_develop_tag(gh, plan['source_sha'])
    if release is None:
        release = gh.request('POST', gh.base + '/releases', {'tag_name': tag, 'target_commitish': plan['source_sha'], 'name': 'Preparando ' + plan['version'], 'body': 'Assets em preparação; publicação depende de conferência integral.', 'draft': True, 'prerelease': not stable, 'make_latest': 'false'})
    stage_assets(gh, release, files, replace_allowed=bool(release.get('draft')) or not stable)
    guard(gh, plan)
    if not stable:
        set_develop_tag(gh, plan['source_sha'], expected=old_tag_sha or plan['source_sha'])
    body = release_body(plan, manifest_name, checksums_name, image_manifest)
    try:
        published = gh.request('PATCH', gh.base + '/releases/' + str(release['id']), {'tag_name': tag, 'target_commitish': plan['source_sha'], 'name': 'Escritura Integrada ' + plan['version'], 'body': body, 'draft': False, 'prerelease': not stable, 'make_latest': 'true' if stable else 'false'})
    except Exception:
        # Keep the previous rolling version usable if metadata publication fails.
        if not stable and old_tag_sha and gh.commit_sha(gh.ref('tags/develop', missing=True)) == plan['source_sha']:
            set_develop_tag(gh, old_tag_sha, expected=plan['source_sha'])
        raise
    removed, cleanup_errors = [], []
    if not stable:
        wanted = {path.name for path in files}
        for asset in gh.pages(gh.base + f"/releases/{release['id']}/assets"):
            if asset['name'].startswith('EscrituraIntegrada-') and asset['name'] not in wanted:
                try:
                    gh.request('DELETE', gh.base + '/releases/assets/' + str(asset['id']))
                    removed.append(asset['name'])
                except GitHubError as exc:
                    cleanup_errors.append(str(exc))
    return {'status': 'published', 'release_id': published['id'], 'url': published['html_url'], 'version': plan['version'], 'source_sha': plan['source_sha'], 'obsolete_prerelease_assets_removed': removed, 'cleanup_errors': cleanup_errors}


def sync_develop(gh, plan, root=None):
    validate_plan(plan, gh.repository)
    if plan['branch'] != 'main':
        raise ReleaseError('A sincronização é disparada somente após main.')
    guard(gh, plan)
    stable = gh.release(plan['tag'], missing=True)
    if not stable or stable.get('draft') or stable.get('prerelease'):
        raise ReleaseError('A release estável deve estar publicada antes de atualizar develop.')
    main_sha = head(gh, 'main')
    main_version = gh.file('VERSION', main_sha).strip()
    dev_sha = head(gh, 'develop', missing=True)
    dev_version = gh.file('VERSION', dev_sha).strip() if dev_sha else None
    desired = develop_version_after_main(main_version, dev_version)
    merged = False
    if dev_sha is None:
        new_sha, changed = commit_versions(gh, 'develop', main_sha, desired, create_branch=True)
    else:
        root = Path(root or Path.cwd())
        fetch_commits(root, gh.repository, [sha(main_sha), sha(dev_sha)], gh.token)
        result = merge_local(root, main_sha, dev_sha, desired)
        guard(gh, plan)
        if head(gh, 'develop') != dev_sha:
            raise StaleRun('develop avançou durante o merge; nada foi forçado. Execute novamente a sincronização.')
        if result.commit != dev_sha:
            push_develop(root, gh.repository, sha(result.commit), gh.token)
        if head(gh, 'develop') != result.commit:
            raise StaleRun('develop avançou após o merge; não será disparado um build de contexto antigo.')
        new_sha, changed, merged = result.commit, result.changed, result.merged_main
    # GITHUB_TOKEN pushes do not trigger push workflows. This event explicitly does.
    gh.request('POST', gh.base + '/actions/workflows/release.yml/dispatches', {'ref': 'develop', 'inputs': {'expected_sha': new_sha, 'reason': 'Atualização após release ' + plan['version']}})
    return {'branch': 'develop', 'version': desired, 'source_sha': new_sha, 'created': dev_sha is None, 'merged_main': merged, 'changed_files': changed, 'workflow_dispatched': 'release.yml'}


def plan_pr(output):
    current = read_manifests(Path.cwd())['VERSION'].strip()
    result = subprocess.run(['git', 'show', 'origin/main:VERSION'], check=False, capture_output=True, text=True)
    main = result.stdout.strip() if result.returncode == 0 else current
    baseline = max(release_version(main).without_suffix().next_patch(), release_version(current).without_suffix(), key=lambda v: v.core)
    number = int(os.environ.get('PR_NUMBER', '0'))
    run_number = int(os.environ.get('GITHUB_RUN_NUMBER', '1'))
    if number < 1 or run_number < 1:
        raise ReleaseError('Número de PR/run inválido.')
    version = str(SemVer(*baseline.core, ('pr', str(number), str(run_number))))
    set_local(Path.cwd(), version)
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    plan = {'schema': 'escritura-ci-plan/1', 'branch': 'pr', 'channel': 'ci', 'version': version, 'source_sha': sha(commit), 'repository': os.environ.get('GITHUB_REPOSITORY', ''), 'publish': False}
    write_json(output, plan)
    outputs({'version': version, 'source_sha': commit, 'channel': 'ci'})
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--output', default='build/ci-plan.json')
    p = sub.add_parser('plan-pr'); p.add_argument('--output', default='build/ci-plan.json')
    for command in ('guard', 'reserve', 'sync-develop'):
        p = sub.add_parser(command); p.add_argument('--plan', default='build/ci-plan.json'); p.add_argument('--output')
    p = sub.add_parser('publish'); p.add_argument('--plan', default='build/ci-plan.json'); p.add_argument('--assets', default='artifacts/release'); p.add_argument('--images-manifest', default='artifacts/images-published.json'); p.add_argument('--output', default='artifacts/publication.json')
    args = parser.parse_args()
    try:
        if args.command == 'plan-pr':
            result = plan_pr(args.output)
        else:
            gh = GitHub()
            if args.command == 'prepare':
                try:
                    result = prepare(gh, branch=os.environ.get('GITHUB_REF_NAME', ''), event_sha=os.environ.get('GITHUB_SHA', ''), run_number=int(os.environ['GITHUB_RUN_NUMBER']), run_id=int(os.environ['GITHUB_RUN_ID']), run_attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')), expected_sha=os.environ.get('EXPECTED_SHA') or None)
                except StaleRun as exc:
                    result = {'proceed': False, 'needs_release': False, 'reason': str(exc)}
                write_json(args.output, result)
                outputs({key: result.get(key, '') for key in ('proceed', 'needs_release', 'already_released', 'version', 'source_sha', 'branch', 'channel')})
            else:
                plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
                if args.command == 'guard':
                    result = {'current': guard(gh, plan), 'source_sha': plan['source_sha']}
                elif args.command == 'reserve':
                    result = reserve(gh, plan)
                elif args.command == 'sync-develop':
                    result = sync_develop(gh, plan)
                else:
                    images = json.loads(Path(args.images_manifest).read_text(encoding='utf-8'))
                    result = publish(gh, plan, args.assets, images)
                if args.output:
                    write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ReleaseError, GitHubError, MergeError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
