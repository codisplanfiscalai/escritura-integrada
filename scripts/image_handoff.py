"""Transferência efêmera validate -> publish: mesmo commit, inputs e run confiável."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tarfile

from image_tools import IMAGE_NAMES, DIGEST, sha256_file, write_json

FIELDS = ('schema_version', 'source_sha', 'version', 'channel', 'platform', 'catalog_sha256')
IDENTITY = ('repository', 'tag', 'reference', 'content_id', 'dockerfile')


def check_context(env, run_id, job):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != 'codisplanfiscalai/escritura-integrada'
            or env.get('GITHUB_REF') not in ('refs/heads/main', 'refs/heads/develop')
            or env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch')
            or env.get('GITHUB_JOB') != job
            or env.get('GITHUB_WORKFLOW_REF') != env['GITHUB_REPOSITORY'] + '/.github/workflows/release.yml@' + env['GITHUB_REF']
            or not str(run_id).isdecimal() or int(run_id) < 1 or str(run_id) != env.get('GITHUB_RUN_ID')):
        raise ValueError('Handoff exige o próprio run de release confiável, nunca artefatos de PR.')


def archive_names(manifest):
    names = []
    for name in IMAGE_NAMES:
        digest = manifest['images'][name].get('digest')
        if digest is None:
            names.append(name)
        elif not DIGEST.fullmatch(digest):
            raise ValueError('Digest de imagem reutilizada inválido: ' + name)
    if 'app' not in names:
        raise ValueError('Handoff validate deve incluir o app recém-construído.')
    return names


def export_handoff(directory, manifest, run_id, env):
    from export_images import save_gzip
    check_context(env, run_id, 'docker')
    if manifest.get('status') != 'validated' or manifest.get('smoke', {}).get('status') != 'passed':
        raise ValueError('Handoff exige smoke aprovado das imagens exatas.')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / 'images.tar.gz'
    names = archive_names(manifest)
    save_gzip([manifest['images'][n]['reference'] for n in names], archive, compresslevel=1)
    write_json(directory / 'handoff.json', {'schema': 'escritura-image-handoff/1', 'run_id': str(run_id),
               'run_attempt': env.get('GITHUB_RUN_ATTEMPT'), 'archive_sha256': sha256_file(archive),
               'archive_size': archive.stat().st_size, 'archive_images': names, 'manifest': manifest})


def verify_handoff(directory, expected, run_id, env):
    check_context(env, run_id, 'publish')
    directory = Path(directory)
    receipt = json.loads((directory / 'handoff.json').read_text())
    if receipt.get('schema') != 'escritura-image-handoff/1' or receipt.get('run_id') != str(run_id):
        raise ValueError('Handoff pertence a outro run/schema.')
    # Retries may consume a prior successful validate gate from this same run.
    previous, current = receipt.get('run_attempt', ''), env.get('GITHUB_RUN_ATTEMPT', '')
    if not str(previous).isdecimal() or not current.isdecimal() or not 1 <= int(previous) <= int(current):
        raise ValueError('Handoff de tentativa inválida/futura.')
    manifest = receipt.get('manifest', {})
    if (manifest.get('status') != 'validated' or manifest.get('smoke', {}).get('status') != 'passed'
            or any(manifest.get(k) != expected.get(k) for k in FIELDS)
            or set(manifest.get('images', {})) != set(IMAGE_NAMES)):
        raise ValueError('Handoff obsoleto: versão, SHA, catálogo, plataforma ou smoke divergente.')
    for name in IMAGE_NAMES:
        item, wanted = manifest['images'][name], expected['images'][name]
        if any(item.get(k) != wanted.get(k) for k in IDENTITY) or not DIGEST.fullmatch(item.get('image_id') or ''):
            raise ValueError('Inputs/ID do handoff divergentes: ' + name)
    names = archive_names(manifest)
    if receipt.get('archive_images') != names:
        raise ValueError('Inventário do handoff diverge das imagens novas e dos digests reutilizáveis.')
    archive = directory / 'images.tar.gz'
    if archive.stat().st_size != receipt.get('archive_size') or sha256_file(archive) != receipt.get('archive_sha256'):
        raise ValueError('Arquivo handoff corrompido; nenhuma imagem será carregada/publicada.')
    # One streaming pass: random extractfile() seeks on gzip would repeatedly
    # decompress all layers for each config, defeating the handoff's purpose.
    configs, records, members = {}, None, set()
    with tarfile.open(archive, 'r|gz') as bundle:
        for member in bundle:
            if member.name in members or member.name.startswith('/') or '..' in Path(member.name).parts or member.issym() or member.islnk():
                raise ValueError('Handoff contém membro duplicado, link ou caminho inseguro.')
            members.add(member.name)
            if not member.isfile():
                continue
            if member.name == 'manifest.json':
                if member.size > 1024 * 1024:
                    raise ValueError('Inventário Docker excede o limite.')
                records = json.load(bundle.extractfile(member))
            elif member.size <= 4 * 1024 * 1024:
                raw = bundle.extractfile(member).read()
                try:
                    config = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(config, dict) and {'os', 'architecture', 'config'} <= config.keys():
                    configs[member.name] = ('sha256:' + hashlib.sha256(raw).hexdigest(), config)
    if not isinstance(records, list) or len(records) != len(names):
        raise ValueError('Inventário Docker ausente ou incompleto.')
    by_tag = {item['reference']: (name, item) for name, item in manifest['images'].items() if name in names}
    seen = set()
    for record in records:
        tags = record.get('RepoTags', [])
        if len(tags) != 1 or tags[0] not in by_tag or tags[0] in seen:
            raise ValueError('Handoff contém tags extras, ausentes ou duplicadas.')
        seen.add(tags[0]); name, item = by_tag[tags[0]]
        if record.get('Config') not in configs:
            raise ValueError('Config Docker ausente ou inválida: ' + name)
        config_digest, config = configs[record['Config']]
        labels = (config.get('config') or {}).get('Labels') or {}
        if (config_digest != item['image_id']
                or config.get('os') != 'linux' or config.get('architecture') != 'amd64'
                or labels.get('io.escritura.content-id') != item['content_id']
                or (name == 'app' and (labels.get('org.opencontainers.image.revision') != expected['source_sha']
                                      or labels.get('org.opencontainers.image.version') != expected['version']))):
            raise ValueError('Config/labels/plataforma não correspondem ao handoff: ' + name)
    if seen != set(by_tag):
        raise ValueError('Handoff incompleto.')
    return manifest, archive
