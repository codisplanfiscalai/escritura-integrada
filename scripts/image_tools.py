"""Catálogo e utilitários da distribuição Docker; apenas biblioteca padrão."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_NAMES = ("base", "app", "redis", "postgres", "mysql", "minio")
OPTIONAL_NAMES = ("redis", "postgres", "mysql", "minio")
GHCR_PREFIX = "ghcr.io/codisplanfiscalai/escritura-integrada"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_version(value):
    if not SEMVER.fullmatch(value) or len(value) > 110:
        raise ValueError("Versão deve ser SemVer, com no máximo 110 caracteres.")
    # '+' é válido em SemVer, mas não em tags OCI.
    return value.replace("+", "_")


def load_catalog(root=ROOT):
    root = Path(root)
    catalog = read_json(root / "docker/images.lock.json")
    if catalog.get("schema_version") != 1 or catalog.get("platforms") != ["linux/amd64"]:
        raise ValueError("Catálogo deve declarar schema 1 e linux/amd64.")
    if set(catalog["images"]) != set(IMAGE_NAMES):
        raise ValueError("Catálogo deve conter app, base, redis, postgres, mysql e minio.")
    for name, item in catalog["images"].items():
        expected = GHCR_PREFIX + ("" if name == "app" else "-" + name)
        if item["repository"] != expected or not (root / item["dockerfile"]).is_file():
            raise ValueError("Repositório ou Dockerfile inválido: " + name)
    for name, item in catalog["upstreams"].items():
        if not DIGEST.fullmatch(item["digest"]) or "latest" in item["tag"]:
            raise ValueError("Upstream sem versão/digest fixo: " + name)
        if item["reference"] != item["repository"] + ":" + item["tag"] + "@" + item["digest"]:
            raise ValueError("Referência upstream incoerente: " + name)
    source = catalog["minio_source"]
    if not SHA.fullmatch(source["commit"]) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
        raise ValueError("Fonte MinIO sem commit/checksum fixo.")
    if source["url"] != "https://codeload.github.com/minio/minio/tar.gz/" + source["commit"]:
        raise ValueError("Fonte MinIO fora do upstream esperado.")
    direct = re.findall(r"(?m)^([\w-]+)==([^\s]+)$", (root / "requirements.txt").read_text())
    locked = dict(re.findall(r"(?m)^([\w-]+)==([^\s]+)", (root / "docker/runtime.lock").read_text()))
    for name, version in direct:
        if locked.get(name.lower().replace("_", "-")) != version:
            raise ValueError("requirements.txt e runtime.lock divergentes: " + name)
    return catalog


def content_id(parts):
    value = hashlib.sha256()
    for label, data in parts:
        value.update(label.encode() + b"\0" + data + b"\0")
    return value.hexdigest()


def image_plan(version, channel, revision, root=ROOT):
    root = Path(root)
    tag = validate_version(version)
    if channel not in {"production", "develop"} or not SHA.fullmatch(revision):
        raise ValueError("Canal inválido ou source SHA não completo.")
    cat = load_catalog(root)
    images = {}
    for name in IMAGE_NAMES:
        item = dict(cat["images"][name])
        paths = [item["dockerfile"]]
        values = []
        if name == "base":
            paths += ["docker/runtime.lock"]
            values += [("python", cat["upstreams"]["python"]["reference"].encode())]
        elif name == "app":
            paths += [".dockerignore", "VERSION", "scripts/run_container.py", "frontend/package.json",
                      "frontend/package-lock.json", "frontend/index.html", "frontend/vite.config.js"]
            paths += sorted(p.relative_to(root).as_posix() for p in (root / "app").glob("*.py"))
            for directory in ("frontend/src", "frontend/public", "frontend/scripts"):
                paths += sorted(p.relative_to(root).as_posix() for p in (root / directory).rglob("*") if p.is_file())
            values += [("source_sha", revision.encode()), ("version", version.encode()),
                       ("base", images["base"]["content_id"].encode()),
                       ("node", cat["upstreams"]["node"]["reference"].encode())]
        elif name == "minio":
            paths += ["docker/minio-entrypoint.sh"]
            values += [("source", json.dumps(cat["minio_source"], sort_keys=True).encode()),
                       ("golang", cat["upstreams"]["golang"]["reference"].encode()),
                       ("base", images["base"]["content_id"].encode())]
        else:
            paths += ["docker/mirrors/" + name + "-entrypoint.sh"]
            values += [("upstream", cat["upstreams"][name]["reference"].encode())]
        values += [(path, (root / path).read_bytes()) for path in paths]
        item["content_id"] = content_id(values)
        if name == "app":
            item["tag"] = tag
        elif name == "base":
            item["tag"] = "py" + cat["upstreams"]["python"]["tag"].split("-")[0] + "-" + item["content_id"][:16]
        else:
            upstream_tag = cat["minio_source"]["version"] if name == "minio" else cat["upstreams"][name]["tag"]
            item["tag"] = upstream_tag + "-" + item["content_id"][:16]
        item.update(reference=item["repository"] + ":" + item["tag"], digest=None, image_id=None)
        images[name] = item
    return {"schema_version": 1, "version": version, "channel": channel,
            "source_sha": revision, "platform": "linux/amd64", "images": images,
            "catalog_sha256": sha256_file(root / "docker/images.lock.json")}


def validate_manifest(data, require_published=True):
    validate_version(data["version"])
    if data.get("schema_version") != 1 or data.get("channel") not in {"production", "develop"}:
        raise ValueError("Manifesto de imagens inválido.")
    if data.get("platform") != "linux/amd64" or not SHA.fullmatch(data.get("source_sha", "")):
        raise ValueError("Plataforma/SHA inválidos no manifesto.")
    if set(data.get("images", {})) != set(IMAGE_NAMES):
        raise ValueError("Manifesto deve incluir as seis imagens.")
    if require_published and data.get("status") != "published":
        raise ValueError("Pacote distribuível exige manifesto de publicação, não de planejamento/validação.")
    for name, item in data["images"].items():
        repository = GHCR_PREFIX + ("" if name == "app" else "-" + name)
        if item.get("repository") != repository or not re.fullmatch(r"[\w][\w.-]{0,127}", item.get("tag", "")):
            raise ValueError("Imagem fora do catálogo GHCR: " + name)
        if item.get("reference") != repository + ":" + item["tag"]:
            raise ValueError("Referência/tag divergentes: " + name)
        if require_published and (not DIGEST.fullmatch(item.get("digest") or "") or not DIGEST.fullmatch(item.get("image_id") or "")):
            raise ValueError("Imagem publicada sem digest/ID: " + name)
    return data


def run(command, *, capture=False, check=True, env=None):
    # Nunca imprime variáveis de ambiente, tokens ou conteúdo do .env.
    print("+ " + " ".join(str(x) for x in command), flush=True)
    result = subprocess.run([str(x) for x in command], cwd=ROOT, text=True,
                            capture_output=capture, check=False, env=env)
    if check and result.returncode:
        if capture:
            print((result.stderr or result.stdout)[-5000:], flush=True)
        raise RuntimeError("Comando falhou (código " + str(result.returncode) + "): " + str(command[0]))
    return result
