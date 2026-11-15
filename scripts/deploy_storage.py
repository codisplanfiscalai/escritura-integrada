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
import uuid

SCHEMA = "escritura-storage/1"
TARGETS = {"app": "/data", "redis": "/data", "postgres": "/var/lib/postgresql/data",
           "mysql": "/var/lib/mysql", "minio": "/data"}
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
STAGE = re.compile(r"\.staging-[a-f0-9]{32}\Z")


class StorageError(RuntimeError):
    pass


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
    folder = stage if action == "commit" else target
    if folder is None or folder.is_symlink():
        raise StorageError("Staging/destino inválido.")
    manifest = json.loads((folder / ".storage-manifest.json").read_text(encoding="utf-8"))
    if manifest["plan"] != plan:
        raise StorageError("O manifesto pertence a outro plano/projeto.")
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
        return worker(plan, "commit", staged)
    except BaseException:
        worker(plan, "abort", staged)
        raise


def main():
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
    args = parser.parse_args()
    local_daemon()
    if args.action in {"init", "plan"}:
        plan = make_plan(args.directory, args.project, args.helper_image, getattr(args, "compose_file", None))
    else:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if plan.get("schema") != SCHEMA or not plan.get("compose_file"):
            raise StorageError("Plano de migração inválido.")
        current = make_plan(plan["directory"], plan["project"], plan["helper_image"], plan["compose_file"])
        if current != {key: value for key, value in plan.items() if key != "image_lock"}:
            raise StorageError("Configuração/volumes mudaram; gere e confira outro plano.")
        lock = args.plan.resolve().with_suffix(".images.yaml")
        if plan.get("image_lock") != str(lock) or json.loads(lock.read_text(encoding="utf-8")) != image_lock(plan):
            raise StorageError("O override de imagens diverge do plano; nenhum dado foi copiado.")
    if args.action == "plan":
        plan["image_lock"] = str(args.output.resolve().with_suffix(".images.yaml"))
        created = []
        try:
            for path, data in ((args.output, plan), (Path(plan["image_lock"]), image_lock(plan))):
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
                  "image_lock": plan["image_lock"], "destination": "./data/" + plan["project"], "data_copied": False}
    else:
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
