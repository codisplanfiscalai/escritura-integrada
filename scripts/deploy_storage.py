#!/usr/bin/env python3
"""Prepare bind directories or cold-copy Compose volumes, without deleting originals.

Standalone administrative helper: Python 3.10+ and local Docker, no app imports.
The filesystem worker runs in an already loaded app image, without network.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = "escritura-storage/1"
TARGETS = {"app": "/data", "redis": "/data", "postgres": "/var/lib/postgresql/data",
           "mysql": "/var/lib/mysql", "minio": "/data"}
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
STAGE = re.compile(r"\.staging-[a-f0-9]{32}\Z")


class StorageError(RuntimeError):
    pass


def select_app_bind(root, project, explicit='', fresh=False, include_plan=False):
    """Metadata only. Never create a directory, open SQLite, or choose by mtime."""
    root = Path(root)
    project_name(project)
    standard = './data/' + project + '/app'
    def inspect(source):
        if not re.fullmatch(r'\./[A-Za-z0-9_./ -]+', source) or '..' in Path(source).parts:
            raise StorageError('O bind deve ser relativo à stack, sem links ou componentes externos.')
        parts = Path(source).parts
        if not parts:
            raise StorageError('A raiz da stack não pode ser o diretório de dados do app.')
        if len(parts) == 3 and parts[0] == 'data' and parts[2] == 'app' and parts[1] != project:
            raise StorageError('O bind pertence ao namespace de outro projeto.')
        path = root
        for part in parts:
            path /= part
            try:
                st = path.lstat()
            except FileNotFoundError:
                return None
            if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
                raise StorageError('Bind inválido: diretório regular sem links é obrigatório.')
        try:
            db = (path / 'escritura.sqlite3').lstat()
        except FileNotFoundError:
            db = None
        if db and not stat.S_ISREG(db.st_mode):
            raise StorageError('SQLite deve ser um arquivo regular, sem link.')
        if db and db.st_size < 100:
            raise StorageError('SQLite vazio/truncado; não será inicializado como banco novo.')
        return {'directory': [st.st_dev, st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)],
                'database': [db.st_dev, db.st_ino, db.st_uid, db.st_gid, stat.S_IMODE(db.st_mode)] if db else None}
    if fresh:
        if explicit and explicit != standard:
            raise StorageError('Instalação nova exige o namespace do projeto; bind existente usa prepare-app.')
        if any(inspect(p) is not None for p in ('./data/app', standard)):
            raise StorageError('Há diretório de app existente. init não pode escolher uma instalação vazia ao lado dele.')
        return {'source': standard, 'reason': 'new', 'identity': None}
    candidates = [explicit] if explicit else ['./data/app', standard]
    found = [(p, inspect(p)) for p in candidates]
    found = [(p, value) for p, value in found if value is not None]
    if len(found) != 1:
        raise StorageError('Bind ausente ou ambíguo. Nenhum dado/configuração alterado; confira os caminhos e defina um override explícito quando houver duas instalações.')
    source, identity = found[0]
    if identity['database'] is None:
        raise StorageError('Diretório existente sem escritura.sqlite3; não será criada uma instalação vazia. Use init somente numa instalação nova.')
    result = {'source': source, 'reason': 'explicit' if explicit else 'detected', 'identity': identity}
    if source == standard and include_plan:
        manifest = root / 'data' / project / '.storage-manifest.json'
        try:
            mode = manifest.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(mode):
                raise StorageError('Manifesto de migração precisa ser arquivo regular.')
            result['migration_plan'] = json.loads(manifest.read_text(encoding='utf-8'))['plan']
    return result


def bind_configuration(compose, directory):
    """Let Compose parse dotenv/precedence, without evaluating a missing-bind guard."""
    args = ('compose', '--project-directory', directory, '-f', compose)
    raw = json.loads(docker(*args, 'config', '--no-interpolate', '--format', 'json'))
    app = raw.get('services', {}).get('app', {})
    mounts = [m for m in app.get('volumes', []) if m.get('target') == '/data']
    if len(mounts) != 1 or mounts[0].get('type') != 'bind':
        raise StorageError('prepare-app exige bind /data. Volumes nomeados precisam do fluxo plan/migrate.')
    original = mounts[0]['source']
    mounts[0]['source'] = str(directory / 'data/.configuration-only')
    app.setdefault('environment', {})['ESCRITURA_BIND_SELECTION_ONLY'] = '${ESCRITURA_APP_DATA_BIND:-}'
    with tempfile.TemporaryDirectory(prefix='escritura-bind-config-') as temporary:
        file = Path(temporary) / 'compose.json'
        file.write_text(json.dumps(raw), encoding='utf-8')
        file.chmod(0o600)
        resolved = json.loads(docker('compose', '--project-directory', directory, '-f', file, 'config', '--format', 'json'))
    explicit = resolved['services']['app']['environment'].get('ESCRITURA_BIND_SELECTION_ONLY', '')
    if 'ESCRITURA_APP_DATA_BIND' not in original:
        path = Path(original)
        try:
            literal = './' + path.relative_to(directory).as_posix()
        except ValueError as exc:
            raise StorageError('Bind literal fora da stack; preparação automática recusada.') from exc
        if explicit and explicit != literal:
            raise StorageError('Override diverge do bind literal do Compose; não será aplicado silenciosamente.')
        explicit = literal
    return resolved['name'], explicit


def bind_scan(directory, project, helper, explicit='', fresh=False, include_plan=False):
    if ',' in str(directory):
        raise StorageError('Caminhos com vírgula não são suportados.')
    # Read-only metadata scanner, no Docker socket, network, app entrypoint or data writes.
    return json.loads(docker('run', '--rm', '-i', '--pull', 'never', '--no-healthcheck', '--network', 'none',
        '--read-only', '--user', '0:0', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE',
        '--security-opt', 'no-new-privileges:true', '--mount', 'type=bind,src=' + str(directory) + ',dst=/stack,readonly',
        '--entrypoint', 'python', helper, '-B', '-', '_bind_scan', project, explicit, 'new' if fresh else 'existing',
        'plan' if include_plan else 'metadata',
        stdin=Path(__file__).read_text(encoding='utf-8')))


def env_snapshot(path):
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(value.st_mode):
        raise StorageError('.env precisa ser arquivo regular, sem link.')
    return ((value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
             value.st_size, value.st_mtime_ns, value.st_ctime_ns), path.read_bytes())


def record_app_bind(directory, project, source, fresh=False, expected=None):
    """Replace only one dotenv key; keep credentials, ownership and private modes."""
    path = directory / '.env'
    if expected is not None and env_snapshot(path) != expected[0]:
        raise StorageError('.env mudou durante a preparação; não sobrescrito.')
    before = path.lstat() if path.exists() or path.is_symlink() else None
    if before and not stat.S_ISREG(before.st_mode):
        raise StorageError('.env precisa ser um arquivo regular, sem link.')
    original = path.read_bytes().decode('utf-8') if before else ''
    lines, matches, project_matches = original.splitlines(keepends=True), [], []
    for i, line in enumerate(lines):
        match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)', line)
        if not match:
            continue
        value = match[2].strip()
        if value.startswith(('"', "'")) and not re.fullmatch(r'''"(?:[^"\\]|\\.)*"\s*(?:#.*)?|'[^']*'\s*(?:#.*)?''', value):
            raise StorageError('.env com valor multilinha não será reescrito automaticamente.')
        if match[1] == 'ESCRITURA_APP_DATA_BIND':
            matches.append(i)
        if match[1] == 'COMPOSE_PROJECT_NAME':
            project_matches.append(i)
    if len(matches) > 1 or len(project_matches) > 1:
        raise StorageError('.env contém bind duplicado; nenhuma alteração feita.')
    entry = 'ESCRITURA_APP_DATA_BIND=' + json.dumps(source, ensure_ascii=True) + '\n'
    if matches:
        lines[matches[0]] = entry
        wanted = ''.join(lines)
    else:
        wanted = original + ('\n' if original and not original.endswith('\n') else '') + entry
    if fresh and project_matches:
        lines[project_matches[0]] = 'COMPOSE_PROJECT_NAME=' + project + '\n'
        if not matches:
            lines.append(entry)
        wanted = ''.join(lines)
    elif fresh or not before:
        wanted = 'COMPOSE_PROJECT_NAME=' + project + '\n' + wanted
    if wanted == original:
        return
    fd, temporary = tempfile.mkstemp(prefix='.env.bind-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
            os.chmod(temporary, stat.S_IMODE(before.st_mode) if before else 0o600)
            if before and os.name == 'posix':
                current = os.fstat(handle.fileno())
                if (current.st_uid, current.st_gid) != (before.st_uid, before.st_gid):
                    os.fchown(handle.fileno(), before.st_uid, before.st_gid)
            handle.write(wanted); handle.flush(); os.fsync(handle.fileno())
        if before:
            if expected is not None and env_snapshot(path) != expected[0]:
                raise StorageError('.env mudou durante a preparação; não sobrescrito.')
            current = path.lstat()
            if ((current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) !=
                    (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) or
                    path.read_bytes() != original.encode('utf-8')):
                raise StorageError('.env mudou durante a preparação; não sobrescrito.')
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Exclusive publication; no replacement of a concurrent .env.
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare_app(directory, project, reference, compose=None, fresh=False):
    directory = Path(directory).resolve(strict=True)
    compose = Path(compose or directory / 'compose.yaml').resolve(strict=True)
    env_before = env_snapshot(directory / '.env')
    if compose.parent != directory:
        raise StorageError('O Compose precisa estar no diretório da stack.')
    if 'ESCRITURA_APP_DATA_BIND' in os.environ and not os.environ['ESCRITURA_APP_DATA_BIND']:
        raise StorageError('A variável vazia exportada no processo sobrepõe .env; remova esse override antes de preparar.')
    configured_project, explicit = bind_configuration(compose, directory)
    if configured_project != project and not fresh:
        raise StorageError('Nome do projeto diverge da configuração efetiva; não compartilhar dados entre stacks.')
    if fresh and os.environ.get('COMPOSE_PROJECT_NAME', project) != project:
        raise StorageError('COMPOSE_PROJECT_NAME do processo diverge da instalação nova.')
    helper = image_id(reference)
    selection = bind_scan(directory, project, helper, explicit, fresh)
    installed, copied_volume = helper, False
    others = docker('ps', '-aq', '--filter', 'label=com.docker.compose.service=app').split()
    if others:
        projection = '{"project":{{json (index .Config.Labels "com.docker.compose.project")}},"mounts":{{json .Mounts}}}'
        for line in docker('inspect', '--format', projection, *others).splitlines():
            container = json.loads(line)
            owner = container['project']
            if owner != project and any(m.get('Type') == 'bind' and m.get('Source') == str(directory / selection['source'])
                                        for m in container['mounts']):
                raise StorageError('O bind já pertence a outro projeto Docker; não compartilhar o banco entre stacks.')
    ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project,
                 '--filter', 'label=com.docker.compose.service=app').split()
    if len(ids) > 1 or (fresh and ids):
        raise StorageError('Projeto com containers existentes/ambíguos; preparação recusada.')
    if ids:
        actual = json.loads(docker('inspect', ids[0]))[0]
        mounts = [m for m in actual['Mounts'] if m['Destination'] == '/data']
        if len(mounts) == 1 and mounts[0]['Type'] == 'volume':
            selection = bind_scan(directory, project, helper, explicit, include_plan=True)
            plan = selection.get('migration_plan')
            if (plan and selection['source'] == './data/' + project + '/app' and plan['project'] == project and
                    plan['directory'] == str(directory) and plan['images'].get('app') == actual['Image'] and
                    plan['sources']['app']['name'] == mounts[0].get('Name')):
                execute(plan, verify=True)  # Only a previously requested, stopped, verified migration.
                copied_volume = True
        if not copied_volume and (len(mounts) != 1 or mounts[0]['Type'] != 'bind' or
                mounts[0]['Source'] != str(directory / selection['source'])):
            raise StorageError('Bind selecionado diverge do container instalado. Nenhum corte/migração será feito.')
        installed = image_id(actual['Image'])
        image = json.loads(docker('image', 'inspect', installed))[0]
        if actual['Config'].get('User') != image['Config'].get('User'):
            raise StorageError('Container sobrescreve USER da imagem; preparação recusada.')
    if not fresh:
        permissions = probe_app_image(installed, str(directory / selection['source']))
        if not permissions['permissions_ok']:
            uid = permissions['identity']
            blocked = [key for key, value in permissions.get('checks', {}).items()
                       if value.get('errors') or value.get('unreadable_entries') or
                       (value.get('exists') and (not value.get('read') or not value.get('write')))]
            raise StorageError('Permissões do bind incompatíveis com USER UID/GID ' + str(uid['uid']) + ':' + str(uid['gid']) +
                ' (' + ', '.join(blocked) + '). .env intacto; consulte STORAGE.md, sem chmod 777 ou chown global.')
        if bind_scan(directory, project, helper, explicit, include_plan=copied_volume) != selection:
            raise StorageError('Identidade dos dados mudou durante a validação; .env intacto.')
        if copied_volume:
            worker(plan, 'restore_probe_mtime')
            execute(plan, verify=True)
    record_app_bind(directory, project, selection['source'], fresh, expected=(env_before,))
    return {'project': project, 'source': selection['source'], 'reason': selection['reason'],
            'app_identity': permissions['identity'] if not fresh else None,
            'configuration_recorded': True, 'data_moved': False, 'containers_started': False,
            'runtime_health_verified': False}


def project_name(value):
    if not PROJECT.fullmatch(value):
        raise StorageError("Nome de projeto inválido; use o nome atual da stack Compose.")
    return value


def docker(*args, stdin=None, missing_volume=False):
    # Never echo commands, config/inspect output or Docker stderr: they may contain secrets.
    result = subprocess.run(["docker", *map(str, args)], input=stdin, text=True,
                            capture_output=True, encoding="utf-8", check=False)
    if result.returncode:
        if missing_volume and "no such volume" in result.stderr.lower():
            return None
        if args[0] == "run":
            try:
                error = json.loads(result.stdout).get("storage_error")
            except (ValueError, AttributeError):
                error = None
            if error:
                raise StorageError(error)
        raise StorageError("Docker recusou a operação " + str(args[0]) + "; confira o daemon, os arquivos e as imagens locais.")
    return result.stdout


def local_daemon():
    endpoint = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
    if not endpoint:
        endpoint = json.loads(docker("context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"))
    if not endpoint.startswith(("unix://", "npipe://")):
        raise StorageError("Use o daemon Docker local; bind mounts de daemon remoto não são suportados.")


def image_id(reference):
    data = json.loads(docker("image", "inspect", reference))[0]
    value = data["Id"]
    if not IMAGE_ID.fullmatch(value) or data.get("Os") != "linux":
        raise StorageError("A imagem auxiliar deve ser uma imagem Linux da aplicação já carregada.")
    return value


def volume_info(name, project, logical):
    raw = docker("volume", "inspect", name, missing_volume=True)
    if raw is None:
        return None
    value = json.loads(raw)[0]
    labels = value.get("Labels") or {}
    if (value.get("Driver") != "local" or value.get("Options") or
            labels.get("com.docker.compose.project") != project or
            labels.get("com.docker.compose.volume") != logical):
        raise StorageError("Volume não pertence ao projeto esperado ou usa armazenamento não suportado: " + name)
    return {"name": name, "created_at": value.get("CreatedAt"), "logical": logical}


def make_plan(directory, project, reference, compose_file=None):
    directory = Path(directory).resolve(strict=True)
    project_name(project)
    helper = image_id(reference)
    plan = {"schema": SCHEMA, "directory": str(directory), "project": project,
            "helper_image": helper, "compose_file": None, "sources": {}, "images": {}}
    if compose_file is None:
        if (docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project).strip() or
                docker("volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + project).strip()):
            raise StorageError("A stack já tem containers/volumes. Use plan/migrate para preservar os dados existentes.")
        default_compose = directory / "compose.yaml"
        if default_compose.is_file():
            _, explicit = bind_configuration(default_compose, directory)
            if explicit and explicit != './data/' + project + '/app':
                raise StorageError("init prepara somente o layout padrão novo. Preserve binds existentes e use check-app para validar suas permissões.")
        return plan
    compose = Path(compose_file).resolve(strict=True)
    if compose.parent != directory:
        raise StorageError("O Compose antigo deve estar no diretório da stack.")
    config = json.loads(docker("compose", "--project-directory", directory, "-p", project,
                               "-f", compose, "--profile", "*", "config", "--format", "json"))
    if config.get("name") != project or set(config.get("services", {})) != set(TARGETS):
        raise StorageError("O Compose antigo não corresponde aos cinco serviços/projeto esperados.")
    plan["compose_file"] = str(compose)
    for name, target in TARGETS.items():
        mounts = config["services"][name].get("volumes", [])
        vault = None
        if name == 'app':
            extras = [m for m in mounts if m.get('target') != target]
            if extras:
                if (len(extras) != 1 or extras[0].get('type') != 'volume' or
                        extras[0].get('source') != 'reception_vault' or
                        extras[0].get('target') != '/run/escritura/reception-vault'):
                    raise StorageError('Mount adicional do app desconhecido; cofre não será migrado por inferência.')
                spec = config.get('volumes', {}).get('reception_vault', {})
                if spec.get('external') or not spec.get('name'):
                    raise StorageError('Identidade do volume do cofre não comprovada.')
                vault = volume_info(spec['name'], project, 'reception_vault')
                if not vault:
                    raise StorageError('Volume do cofre existente não localizado; preserve sua chave antes de migrar.')
                plan['preserved_volumes'] = {'reception_vault': vault}
                mounts = [m for m in mounts if m.get('target') == target]
        if name == "app" and len(mounts) == 1 and mounts[0].get("type") == "bind":
            raise StorageError("O app já usa bind mount. Preserve o caminho atual; para ./data/app configure ESCRITURA_APP_DATA_BIND no .env e preserve o mount no compose.yaml conforme STORAGE.md. Não execute init nem recopie o volume de backup.")
        if len(mounts) != 1 or mounts[0].get("type") != "volume" or mounts[0].get("target") != target:
            raise StorageError("O Compose antigo precisa usar os volumes nomeados originais: " + name)
        logical = mounts[0]["source"]
        if logical != name + "-data":
            raise StorageError("Volume lógico inesperado; não troque dados entre serviços: " + name)
        spec = config.get("volumes", {}).get(logical, {})
        if spec.get("external") or not spec.get("name"):
            raise StorageError("Volume externo/sem identidade explícita recusado: " + name)
        info = volume_info(spec["name"], project, logical)
        if info:
            ids = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project,
                         "--filter", "label=com.docker.compose.service=" + name).split()
            if not ids:
                raise StorageError("Mantenha os containers originais parados (stop, não down) para conferir mounts e imagens: " + name)
            installed = set()
            for container in json.loads(docker("inspect", *ids)):
                actual = [m for m in container.get("Mounts", []) if m.get("Destination") == target]
                if len(actual) != 1 or actual[0].get("Type") != "volume" or actual[0].get("Name") != info["name"]:
                    raise StorageError("Compose antigo diverge do mount do container existente: " + name)
                if vault:
                    actual_vault = [m for m in container.get('Mounts', []) if m.get('Destination') == '/run/escritura/reception-vault']
                    if (len(actual_vault) != 1 or actual_vault[0].get('Type') != 'volume' or
                            actual_vault[0].get('Name') != vault['name']):
                        raise StorageError('Compose diverge do volume do cofre instalado; nenhuma chave será movida.')
                installed.add(container["Image"])
            if len(installed) != 1 or not IMAGE_ID.fullmatch(next(iter(installed))):
                raise StorageError("Imagens divergentes para o mesmo serviço; confira os containers: " + name)
            plan["images"][name] = image_id(next(iter(installed)))
            plan["sources"][name] = info
        elif name == "app":
            raise StorageError("O volume original da aplicação não existe; nenhuma cópia foi iniciada.")
    return plan


def image_lock(plan):
    """Freeze the images actually installed, so alias movement cannot upgrade a DB during copying."""
    return {"services": {name: {"image": value, "pull_policy": "never"} for name, value in plan["images"].items()}}


def assert_stopped(plan):
    for info in plan.get('preserved_volumes', {}).values():
        if volume_info(info['name'], plan['project'], info['logical']) != info:
            raise StorageError('A identidade do cofre preservado mudou; nenhum dado será copiado.')
    for info in plan["sources"].values():
        ids = docker("ps", "-aq", "--filter", "volume=" + info["name"]).split()
        if ids:
            containers = json.loads(docker("inspect", *ids))
            if any(c["State"]["Status"] not in {"exited", "created", "dead"} for c in containers):
                raise StorageError("Há container ativo usando " + info["name"] + "; pare todos os escritores antes da cópia.")
        if volume_info(info["name"], plan["project"], info["logical"]) != info:
            raise StorageError("A identidade de um volume original mudou; gere e confira outro plano.")


def worker(plan, action, stage=None):
    script = Path(__file__).resolve()
    if "," in str(script) or "," in plan["directory"]:
        raise StorageError("Diretórios com vírgula não são suportados por --mount.")
    command = ["run", "--rm", "-i", "--name", "escritura-storage-helper-" + uuid.uuid4().hex[:12],
               "--no-healthcheck", "--pull", "never", "--network", "none", "--read-only",
               "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "FOWNER",
               "--cap-add", "DAC_OVERRIDE", "--security-opt", "no-new-privileges:true",
               "--tmpfs", "/data:rw,noexec,nosuid,size=1m", "--entrypoint", "python",
               "--mount", "type=bind,src=" + str(script) + ",dst=/tool/storage.py,readonly",
               "--mount", "type=bind,src=" + plan["directory"] + ",dst=/project"]
    for name, info in plan["sources"].items():
        command += ["--mount", "type=volume,src=" + info["name"] + ",dst=/source/" + name + ",readonly,volume-nocopy"]
    command += [plan["helper_image"], "-B", "/tool/storage.py", "_worker"]
    request = {"plan": plan, "action": action, "stage": stage}
    return json.loads(docker(*command, stdin=json.dumps(request)))


def inventory(root):
    """Hash every regular file and record permissions/owners/mtime and hard links.

    External data symlinks/special files are refused. The official MySQL image's
    runtime socket symlink is copied as a link, never followed or treated as data.
    """
    root = Path(root)
    entries, links = {}, {}
    paths = [root, *sorted(root.rglob("*"))]
    for path in paths:
        st = path.lstat()
        key = path.relative_to(root).as_posix()
        item = {"mode": stat.S_IMODE(st.st_mode), "uid": st.st_uid, "gid": st.st_gid,
                "mtime_ns": st.st_mtime_ns}
        if stat.S_ISDIR(st.st_mode):
            item["type"] = "directory"
        elif (stat.S_ISLNK(st.st_mode) and root.name == "mysql" and key == "mysql.sock" and
              os.readlink(path) in {"/var/run/mysqld/mysqld.sock", "/run/mysqld/mysqld.sock"}):
            item.update(type="symlink", target=os.readlink(path))
        elif stat.S_ISREG(st.st_mode):
            item.update(type="file", size=st.st_size)
            hashed = hashlib.sha256()
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise StorageError("Arquivo mudou durante a leitura.")
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hashed.update(block)
            item["sha256"] = hashed.hexdigest()
            inode = (st.st_dev, st.st_ino)
            if st.st_nlink > 1:
                item["hardlink"] = links.setdefault(inode, key)
        else:
            raise StorageError("Link simbólico ou arquivo especial recusado; origem preservada: " + key)
        entries[key] = item
    return entries


def copy_tree(source, target):
    before = inventory(source)
    shutil.copytree(source, target, copy_function=shutil.copyfile, symlinks=True)
    for key, item in before.items():
        path = target if key == "." else target / key
        if "hardlink" in item and item["hardlink"] != key:
            path.unlink()
            os.link(target / item["hardlink"], path)
        os.chown(path, item["uid"], item["gid"], follow_symlinks=False)
        if item["type"] != "symlink":
            os.chmod(path, item["mode"])
    # Creating/relinking children changes directory mtime; restore it last.
    for key, item in before.items():
        path = target if key == "." else target / key
        os.utime(path, ns=(item["mtime_ns"], item["mtime_ns"]), follow_symlinks=False)
    if inventory(source) != before or inventory(target) != before:
        raise StorageError("Inventário da cópia divergiu; nada foi publicado.")
    return before


def publish(stage, target):
    # Atomic and exclusive, even if another operator creates an empty destination
    # after our initial check. Plain POSIX rename could replace that directory.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise StorageError("Este filesystem/runtime não oferece renameat2; destino não publicado.")
    result = rename(-100, os.fsencode(stage), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    if result:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise StorageError("Destino já existe; ele não será sobrescrito.")
        raise OSError(error, "Publicação exclusiva recusada")
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_tree(root):
    paths = [root, *root.rglob("*")]
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            continue  # Link metadata is persisted by fsync of its parent; never open its target.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def filesystem_action(root, request, source_root=Path("/source")):
    plan, action = request["plan"], request["action"]
    project_name(plan["project"])
    parent = Path(root) / "data"
    if parent.is_symlink():
        raise StorageError("data não pode ser um link simbólico.")
    parent.mkdir(mode=0o700, exist_ok=True)
    target = parent / plan["project"]
    stage_name = request.get("stage")
    if stage_name is not None and not STAGE.fullmatch(stage_name):
        raise StorageError("Identificador de staging inválido.")
    if action == "stage":
        if os.path.lexists(target):
            raise StorageError("Destino já existe, mesmo que vazio; não será sobrescrito.")
        stage = parent / (".staging-" + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        try:
            inventories = {}
            for name in TARGETS:
                path = stage / name
                if name in plan["sources"]:
                    inventories[name] = copy_tree(source_root / name, path)
                else:
                    path.mkdir(mode=0o700)
                    owner = 10001 if name in {"app", "minio"} else 0
                    os.chown(path, owner, owner)
                    inventories[name] = inventory(path)
            manifest = {"schema": SCHEMA, "plan": plan, "inventories": inventories}
            report = stage / ".storage-manifest.json"
            with report.open("x", encoding="utf-8") as handle:
                os.chmod(report, 0o600)
                json.dump(manifest, handle, ensure_ascii=False, sort_keys=True)
            sync_tree(stage)
            return {"stage": stage.name, "verified": True}
        except BaseException:
            shutil.rmtree(stage)
            raise
    stage = parent / stage_name if stage_name else None
    if action == "abort":
        if stage and stage.exists() and not stage.is_symlink():
            shutil.rmtree(stage)  # Only the staging directory made by this invocation.
        return {"aborted": True}
    folder = stage if action == 'commit' or (action == 'restore_probe_mtime' and stage is not None) else target
    if folder is None or folder.is_symlink():
        raise StorageError("Staging/destino inválido.")
    manifest = json.loads((folder / ".storage-manifest.json").read_text(encoding="utf-8"))
    if manifest["plan"] != plan:
        raise StorageError("O manifesto pertence a outro plano/projeto.")
    if action == "restore_probe_mtime":
        expected = manifest["inventories"]["app"]
        current = inventory(folder / "app")
        def comparable(entries):
            return {key: {k: v for k, v in value.items() if k != "mtime_ns" or value["type"] != "directory"}
                    for key, value in entries.items()}
        if comparable(current) != comparable(expected):
            raise StorageError("A pré-validação alterou a cópia além de mtimes de diretórios; destino não publicado.")
        for key, value in expected.items():
            if value["type"] == "directory":
                os.utime(folder / "app" / key, ns=(value["mtime_ns"], value["mtime_ns"]))
        return {"probe_mtimes_restored": True}
    for name, expected in manifest["inventories"].items():
        if inventory(folder / name) != expected:
            raise StorageError("Destino divergiu do manifesto: " + name)
        if name in plan["sources"] and inventory(source_root / name) != expected:
            raise StorageError("Origem mudou desde a cópia: " + name)
    if action == "commit":
        publish(stage, target)
    return {"verified": True, "directory": "./data/" + plan["project"], "original_volumes_preserved": True}


def execute(plan, verify=False):
    assert_stopped(plan)
    if verify:
        return worker(plan, "verify")
    staged = worker(plan, "stage")["stage"]
    try:
        assert_stopped(plan)  # Recheck writers and volume identities after copying.
        probe = probe_app_image(plan.get("images", {}).get("app", plan["helper_image"]),
                                str(Path(plan["directory"]) / "data" / staged / "app"), allow_new="app" not in plan["sources"])
        if not probe["permissions_ok"]:
            failed = [name for name, value in probe.get("checks", {}).items()
                      if value.get("errors") or value.get("unreadable_entries") or
                      (value.get("exists") and (not value.get("read") or not value.get("write")))]
            identity = probe["identity"]
            raise StorageError("Pré-validação app UID/GID " + str(identity["uid"]) + ":" + str(identity["gid"]) +
                " recusada (" + ", ".join(failed or [probe.get("identity_error", "database_required")]) +
                "). Staging descartado; volumes originais intactos. Preservar owners/modos incompatíveis não os corrige. "
                "Confira somente os dados do app conforme STORAGE.md; sem chmod 777 ou root no runtime.")
        worker(plan, "restore_probe_mtime", staged)
        assert_stopped(plan)
        result = worker(plan, "commit", staged)
        result.update(app_permissions_verified=True, app_identity=probe["identity"], runtime_health_verified=False)
        return result
    except BaseException:
        worker(plan, "abort", staged)
        raise


def app_permissions(root, database_required=True):
    """Run as the image's default identity, never as the privileged copy worker.

    Existing database/sidecar/backup bytes and ownership/modes are never written.
    Exclusive temporary directory/file probes check create/write/delete access.
    """
    root = Path(root)
    identity = {"uid": os.geteuid(), "gid": os.getegid(), "groups": os.getgroups()}
    report = {"identity": identity, "checks": {}, "permissions_ok": False,
              "database_required": database_required,
              "database_bytes_written": False, "ownership_or_modes_changed": False,
              "temporary_write_probes": True}
    if identity["uid"] == 0:
        report["identity_error"] = "root_runtime_refused"
        report["temporary_write_probes"] = False
        return report

    def metadata(path):
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode):
            raise OSError(errno.ELOOP, "Symlink refused")
        return {"uid": value.st_uid, "gid": value.st_gid, "mode": oct(stat.S_IMODE(value.st_mode))}

    def directory(path):
        result = {"exists": True, "read": False, "traverse": False, "write": False, "errors": []}
        try:
            result["metadata"] = metadata(path)
            if not path.is_dir():
                raise OSError(errno.ENOTDIR, "Directory required")
            with os.scandir(path) as entries:
                next(entries, None)
            result["read"] = True
            result["traverse"] = os.access(path, os.X_OK)
        except OSError as exc:
            result["exists"] = exc.errno != errno.ENOENT
            result["errors"].append({"operation": "read/traverse", "errno": exc.errno})
        if result.get("metadata") and result["traverse"]:
            probe = path / (".escritura-preflight-" + uuid.uuid4().hex)
            made = False
            try:
                probe.mkdir(mode=0o700)
                made = True
                with (probe / "probe").open("xb") as handle:
                    handle.write(b"permission probe")
                    handle.flush()
                    os.fsync(handle.fileno())
                (probe / "probe").unlink()
                probe.rmdir()
                made = False
                result["write"] = True
            except OSError as exc:
                result["errors"].append({"operation": "create/write/delete", "errno": exc.errno})
            finally:
                if made:
                    try:
                        shutil.rmtree(probe)  # Exclusively created by this probe, never user data.
                    except OSError as exc:
                        result["write"] = False
                        result["errors"].append({"operation": "cleanup temporary probe", "errno": exc.errno})
        return result

    def file_access(path, write):
        result = {"exists": True, "read": False, "write": None if not write else False, "errors": []}
        try:
            result["metadata"] = metadata(path)
            if not path.is_file():
                raise OSError(errno.EINVAL, "Regular file required")
        except OSError as exc:
            result["exists"] = exc.errno != errno.ENOENT
            result["errors"].append({"operation": "stat", "errno": exc.errno})
            return result
        for operation, flags in (("read", os.O_RDONLY), ("write", os.O_RDWR)):
            if operation == "write" and not write:
                continue
            try:
                fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
                os.close(fd)  # No write, truncate, SQLite connection or journal creation.
                result[operation] = True
            except OSError as exc:
                result["errors"].append({"operation": operation, "errno": exc.errno})
        return result

    checks = report["checks"]
    checks["root"] = directory(root)
    checks["database"] = file_access(root / "escritura.sqlite3", True)
    if not checks["database"]["exists"] and not database_required:
        checks["database"] = {"exists": False, "creation_permitted_by_root_probe": checks["root"]["write"], "not_created": True}
    for name, suffix in (("wal", "-wal"), ("shm", "-shm")):
        item = file_access(root / ("escritura.sqlite3" + suffix), True)
        if not item["exists"]:
            item = {"exists": False, "creation_permitted_by_root_probe": checks["root"]["write"], "not_created": True}
        checks[name] = item
    backups = root / "backups"
    item = directory(backups)
    if not item["exists"]:
        item = {"exists": False, "creation_permitted_by_root_probe": checks["root"]["write"], "not_created": True}
    elif item["read"] and item["traverse"]:
        item["unreadable_entries"] = []
        try:
            for path in backups.rglob("*"):
                if path.is_symlink() or (not path.is_dir() and not file_access(path, False)["read"]):
                    item["unreadable_entries"].append(path.relative_to(backups).as_posix())
                elif path.is_dir():
                    with os.scandir(path) as entries:
                        next(entries, None)
        except OSError as exc:
            item["errors"].append({"operation": "read backup tree", "errno": exc.errno})
    checks["backups"] = item
    def allowed(value, is_directory=False):
        if not value["exists"]:
            return value.get("creation_permitted_by_root_probe", False)
        return bool(value["read"] and value["write"] and
                    (not is_directory or value["traverse"]) and
                    not value.get("errors") and not value.get("unreadable_entries"))
    report["permissions_ok"] = bool((checks["database"]["exists"] or not database_required) and allowed(checks["root"], True) and
        allowed(checks["database"]) and allowed(checks["wal"]) and allowed(checks["shm"]) and allowed(checks["backups"], True))
    return report


def probe_app_image(installed, source, read_only=False, allow_new=False):
    installed = image_id(installed)
    script = Path(__file__).resolve()
    if "," in source:
        raise StorageError("Caminhos com vírgula não são suportados.")
    command = ["run", "--rm", "-i", "--pull", "never", "--no-healthcheck", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=4m",
               "--mount", "type=bind,src=" + source + ",dst=/data" + (",readonly" if read_only else ""),
               "--entrypoint", "python", installed, "-B", "-", "_app_check_new" if allow_new else "_app_check"]
    # stdin keeps the administrative source private on the host (e.g. extracted 0600).
    return json.loads(docker(*command, stdin=script.read_text(encoding='utf-8')))  # Actual image USER.


def check_app(compose_file, project, require_health=False, wait_health=0):
    """Diagnose the actual bind/image. Never stop, recreate, chown, chmod or pull."""
    project_name(project)
    compose = Path(compose_file).resolve(strict=True)
    config = json.loads(docker("compose", "-p", project, "-f", compose, "config", "--format", "json"))
    mounts = [m for m in config.get("services", {}).get("app", {}).get("volumes", []) if m.get("target") == "/data"]
    ids = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project,
                 "--filter", "label=com.docker.compose.service=app").split()
    if len(mounts) != 1 or mounts[0].get("type") != "bind" or len(ids) != 1:
        raise StorageError("check-app exige exatamente um app existente e um bind /data explícito.")
    container = json.loads(docker("inspect", ids[0]))[0]
    actual = [m for m in container["Mounts"] if m["Destination"] == "/data"]
    if len(actual) != 1 or actual[0]["Type"] != "bind" or actual[0]["Source"] != mounts[0]["source"]:
        raise StorageError("O mount efetivo diverge do Compose; não altere permissões até conferir o Source.")
    installed = image_id(container["Image"])
    image = json.loads(docker("image", "inspect", installed))[0]
    configured_user = image["Config"].get("User", "")
    if configured_user != container["Config"].get("User", ""):
        raise StorageError("O app sobrescreve USER da imagem; confira a identidade sem rodar como root.")
    result = probe_app_image(installed, actual[0]["Source"], not actual[0].get("RW"))
    result.update(schema="escritura-app-preflight/1", image_id=installed, image_user=configured_user,
                  source=actual[0]["Source"], health_requested=require_health, health_checked=False, runtime_healthy=None,
                  interface_validation="pending", recovery_complete=False)
    if require_health and result["permissions_ok"]:
        result["health_checked"] = True
        until = time.monotonic() + wait_health
        while True:
            container = json.loads(docker("inspect", ids[0]))[0]
            state = container["State"]
            healthy = state.get("Running", False) and state.get("Health", {}).get("Status") == "healthy"
            if healthy or time.monotonic() >= until or state["Status"] in {"exited", "dead"}:
                break
            time.sleep(2)
        endpoint = False
        if healthy:
            try:
                response = docker("exec", ids[0], "python", "-c",
                    "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)); assert r.get('status')=='ok'; print('ok')")
                endpoint = response.strip() == "ok"
            except StorageError:
                pass
        result["runtime_healthy"] = bool(healthy and endpoint)
        result["health_endpoint_ok"] = endpoint
    else:
        container = json.loads(docker("inspect", ids[0]))[0]
    result["container_state"] = container["State"]["Status"]
    result["docker_health"] = container["State"].get("Health", {}).get("Status", "absent")
    if not result["permissions_ok"]:
        result["status"] = "blocked"
        result["guidance"] = "Confira Source e identidade da imagem; preserve ./data/app e a imagem instalada. Pare o app antes de qualquer correção específica de ownership. Não recopie backup antigo, não use chmod 777/root no runtime nem chown de outros serviços. Consulte STORAGE.md."
    elif require_health:
        result["status"] = "runtime_healthy" if result["runtime_healthy"] else "runtime_not_ready"
    else:
        result["status"] = "permissions_passed"
    return result


def main():
    if sys.argv[1:2] == ['_bind_scan']:
        try:
            print(json.dumps(select_app_bind(Path('/stack'), sys.argv[2], sys.argv[3], sys.argv[4] == 'new', sys.argv[5] == 'plan')))
        except (OSError, StorageError) as exc:
            print(json.dumps({'storage_error': str(exc) if isinstance(exc, StorageError) else 'Não foi possível ler metadados do bind.'}))
            raise SystemExit(1)
        return
    if sys.argv[1:] in (["_app_check"], ["_app_check_new"]):
        print(json.dumps(app_permissions(Path("/data"), database_required=sys.argv[1] == "_app_check")))
        return
    if sys.argv[1:] == ["_worker"]:
        print(json.dumps(filesystem_action(Path("/project"), json.load(sys.stdin))))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("init", "plan"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--directory", type=Path, default=Path.cwd())
        cmd.add_argument("--project", required=True)
        cmd.add_argument("--helper-image", required=True, help="Imagem local do app; nunca é baixada pela ferramenta.")
        if action == "plan":
            cmd.add_argument("--compose-file", type=Path, required=True)
            cmd.add_argument("--output", type=Path, required=True)
    for action in ("migrate", "verify"):
        sub.add_parser(action).add_argument("--plan", type=Path, required=True)
    cmd = sub.add_parser('prepare-app')
    cmd.add_argument('--directory', type=Path, default=Path.cwd())
    cmd.add_argument('--project', required=True)
    cmd.add_argument('--helper-image', required=True, help='Imagem local; nenhuma imagem será baixada.')
    cmd.add_argument('--compose-file', type=Path)
    cmd = sub.add_parser("check-app")
    cmd.add_argument("--compose-file", type=Path, required=True)
    cmd.add_argument("--project", required=True)
    cmd.add_argument("--output", type=Path)
    cmd.add_argument("--require-health", action="store_true")
    cmd.add_argument("--wait-health-seconds", type=int, choices=range(121), default=0, metavar="0..120")
    args = parser.parse_args()
    local_daemon()
    if args.action == 'prepare-app':
        print(json.dumps(prepare_app(args.directory, args.project, args.helper_image, args.compose_file), ensure_ascii=False))
        return
    if args.action == "check-app":
        result = check_app(args.compose_file, args.project, args.require_health, args.wait_health_seconds)
        if args.output:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=False))
        if not result["permissions_ok"] or (args.require_health and not result["runtime_healthy"]):
            raise SystemExit(1)
        return
    if args.action in {"init", "plan"}:
        plan = make_plan(args.directory, args.project, args.helper_image, getattr(args, "compose_file", None))
    else:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if plan.get("schema") != SCHEMA or not plan.get("compose_file"):
            raise StorageError("Plano de migração inválido.")
        current = make_plan(plan["directory"], plan["project"], plan["helper_image"], plan["compose_file"])
        if current != {key: value for key, value in plan.items() if key != "image_lock"}:
            raise StorageError("Configuração/volumes mudaram; gere e confira outro plano.")
        # Legacy plans retain their original lock validation. New plans keep
        # installed IDs in plan["images"] and never need another Compose file.
        if "image_lock" in plan:
            lock = args.plan.resolve().with_suffix(".images.yaml")
            if plan["image_lock"] != str(lock) or json.loads(lock.read_text(encoding="utf-8")) != image_lock(plan):
                raise StorageError("O lock legado de imagens diverge do plano; nenhum dado foi copiado.")
    if args.action == "plan":
        created = []
        try:
            for path, data in ((args.output, plan),):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created.append(path)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
        except BaseException:
            for path in created:
                path.unlink()  # Only files exclusively created by this attempt, never existing plans.
            raise
        result = {"plan": str(args.output), "project": plan["project"], "sources": plan["sources"],
                  "images": plan["images"], "destination": "./data/" + plan["project"], "data_copied": False}
    else:
        if args.action == 'init' and (args.directory / 'compose.yaml').is_file():
            prepare_app(args.directory, args.project, args.helper_image, fresh=True)
        result = execute(plan, verify=args.action == "verify")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, StorageError) as exc:
        if sys.argv[1:] == ["_worker"]:
            message = str(exc) if isinstance(exc, StorageError) else "Falha no filesystem; staging não publicado."
            print(json.dumps({"storage_error": message}))
            raise SystemExit(1)
        # No config/inspect output, credentials or file contents in error output.
        print("Armazenamento: operação recusada (" + type(exc).__name__ + "). Nenhum volume original foi removido.", file=sys.stderr)
        if isinstance(exc, StorageError):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)
