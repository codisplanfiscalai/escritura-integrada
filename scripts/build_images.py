#!/usr/bin/env python3
"""Build/teste/publicação de imagens fixadas. Nenhum push no modo validate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from image_tools import DIGEST, ROOT, IMAGE_NAMES, image_plan, load_catalog, run, write_json
from image_handoff import archive_names, export_handoff, verify_handoff


def inspect_image(reference):
    result = run(["docker", "image", "inspect", reference], capture=True)
    data = json.loads(result.stdout)[0]
    digests = data.get("RepoDigests", [])
    repository = reference.split("@", 1)[0] if "@" in reference else reference.rsplit(":", 1)[0]
    digest = next((x.split("@", 1)[1] for x in digests if x.startswith(repository + "@")), None)
    return {"image_id": data["Id"], "digest": digest, "labels": data["Config"].get("Labels") or {},
            "platform": data.get("Os", "") + "/" + data.get("Architecture", "")}


def remote_exists(reference):
    result = run(["docker", "manifest", "inspect", reference], capture=True, check=False)
    if result.returncode == 0:
        return True
    message = (result.stderr + result.stdout).lower()
    if any(x in message for x in ("manifest unknown", "no such manifest", "manifest_unknown", "not found")):
        return False
    raise RuntimeError("Não foi possível verificar a imutabilidade de " + reference + ". Confira autenticação/permissões GHCR e conectividade. Nenhuma tag será sobrescrita sem essa verificação.")


def assert_identity(name, wanted, actual, revision):
    labels = actual["labels"]
    if actual.get("platform") != "linux/amd64":
        raise RuntimeError("Plataforma inesperada: " + wanted["reference"])
    if labels.get("io.escritura.content-id") != wanted["content_id"]:
        raise RuntimeError("Tag já publicada com outro conteúdo; incremente a versão: " + wanted["reference"])
    if name == "app" and labels.get("org.opencontainers.image.version") != wanted["tag"]:
        raise RuntimeError("Versão da imagem divergente: " + wanted["reference"])
    if name == "app" and labels.get("org.opencontainers.image.revision") != revision:
        raise RuntimeError("A tag da aplicação já pertence a outro commit: " + wanted["reference"])


def public_pull_probe(repository, digest):
    """Sonda anônima do Registry v2; nunca usa GITHUB_TOKEN ou credenciais Docker."""
    path = repository.removeprefix("ghcr.io/")
    query = urllib.parse.urlencode({"service": "ghcr.io", "scope": "repository:" + path + ":pull"})
    try:
        with urllib.request.urlopen("https://ghcr.io/token?" + query, timeout=20) as response:
            token = json.load(response)["token"]
        request = urllib.request.Request("https://ghcr.io/v2/" + path + "/manifests/" + digest,
                                        headers={"Authorization": "Bearer " + token,
                                                 "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"public_pullable": response.status == 200, "http_status": response.status}
    except urllib.error.HTTPError as exc:
        return {"public_pullable": False, "http_status": exc.code,
                "note": "Pode exigir login no GHCR ou ajuste manual de visibilidade do pacote."}
    except (OSError, ValueError, KeyError) as exc:
        return {"public_pullable": False, "http_status": None,
                "note": "Verificação anônima inconclusiva: " + type(exc).__name__}


def pinned_remote(reference, *, optional=False):
    """Resolve once, then pull by digest; never trust an alias or a tag alone."""
    result = run(["docker", "buildx", "imagetools", "inspect", "--raw", reference], capture=True, check=False)
    if result.returncode:
        if optional:
            print("Cache remoto indisponível; construção e smoke continuam: " + reference, flush=True)
            return None
        raise RuntimeError("Falha ao resolver manifesto imutável: " + reference)
    raw = result.stdout.strip().encode()
    data = json.loads(raw)
    if data.get("mediaType") not in ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"):
        raise ValueError("Cache remoto não é uma imagem de plataforma única: " + reference)
    # --raw preserves registry bytes, including a possible final newline.
    # The descriptor's digest is obtained independently, avoiding whitespace normalization.
    descriptor = run(["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{json .Manifest}}"], capture=True)
    digest = json.loads(descriptor.stdout)["digest"]
    if not DIGEST.fullmatch(digest) or digest not in {"sha256:" + hashlib.sha256(result.stdout.encode()).hexdigest(), "sha256:" + hashlib.sha256(raw).hexdigest()}:
        raise ValueError("Digest do manifesto remoto não confere: " + reference)
    return digest


def build_args(name, manifest, catalog, publish):
    images = manifest["images"]
    args = {"CONTENT_ID": images[name]["content_id"], "SOURCE_REVISION": manifest["source_sha"]}
    if name == "base":
        args["PYTHON_IMAGE"] = catalog["upstreams"]["python"]["reference"]
    elif name in {"redis", "postgres", "mysql"}:
        args["UPSTREAM_IMAGE"] = catalog["upstreams"][name]["reference"]
    else:
        base = images["base"]
        args["RUNTIME_IMAGE"] = base["repository"] + "@" + base["digest"] if publish else base["reference"]
        if name == "app":
            args["NODE_IMAGE"] = catalog["upstreams"]["node"]["reference"]
            args["APP_VERSION"] = manifest["version"]
        else:
            source = catalog["minio_source"]
            args.update(GOLANG_IMAGE=catalog["upstreams"]["golang"]["reference"],
                        MINIO_SOURCE_URL=source["url"], MINIO_SOURCE_SHA256="sha256:" + source["sha256"],
                        MINIO_COMMIT=source["commit"], MINIO_VERSION=source["version"])
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "publish"])
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=["production", "develop"], required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Somente plano JSON; não publica nem atesta testes.")
    parser.add_argument("--proxy-ca", type=Path, help="CA adicional via secret BuildKit; não fica na imagem.")
    parser.add_argument("--export-handoff", type=Path, help="Exporta somente após smoke, no próprio run confiável de release.")
    parser.add_argument("--handoff", type=Path, help="Importa imagens validadas do mesmo run; erro de prova bloqueia publicação.")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    args = parser.parse_args()
    if (args.handoff and args.action != "publish") or (args.export_handoff and args.action != "validate"):
        parser.error("Handoff de entrada somente publish; exportação somente validate.")
    manifest = image_plan(args.version, args.channel, args.revision)
    manifest.update(status="planned", generated_at=datetime.now(timezone.utc).isoformat())
    if args.dry_run:
        write_json(args.output, manifest)
        print("Plano salvo; nenhum Docker/build/push/teste foi executado.")
        return 0
    if (ROOT / "VERSION").read_text().strip() != args.version:
        raise ValueError("Aplique a versão no checkout antes de construir imagens (VERSION divergente).")
    actual_revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    if actual_revision != args.revision:
        raise ValueError("O checkout não corresponde ao SHA solicitado; nenhuma imagem será construída/publicada.")
    catalog = load_catalog()
    run(["docker", "version"])
    run(["docker", "buildx", "version"])
    builder = run(["docker", "buildx", "inspect", "default"], capture=True).stdout
    if "docker-container" in builder:
        raise RuntimeError("Use o builder default com driver docker: validate resolve a base no daemon local.")
    publish = args.action == "publish"
    try:
        handed = None
        if args.handoff:
            handed, archive = verify_handoff(args.handoff, manifest, args.run_id, os.environ)
            run(["docker", "image", "load", "--input", archive.resolve()])
            for name in archive_names(handed):
                actual = inspect_image(manifest["images"][name]["reference"])
                assert_identity(name, manifest["images"][name], actual, args.revision)
                if actual["image_id"] != handed["images"][name]["image_id"]:
                    raise ValueError("ID carregado diverge do handoff: " + name)
        for name in IMAGE_NAMES:
            started = time.monotonic()
            image = manifest["images"][name]
            exists = publish and remote_exists(image["reference"])
            digest = pinned_remote(image["reference"]) if exists else (pinned_remote(image["reference"], optional=True) if not publish and name != "app" else None)
            cached = handed['images'][name] if handed else None
            if cached and cached.get('digest'):
                if not exists or digest != cached['digest']:
                    raise ValueError("Tag/digest remoto mudou desde validate: " + image['reference'])
            if digest:
                pinned = image["repository"] + "@" + digest
                run(["docker", "pull", "--platform", "linux/amd64", pinned])
                run(["docker", "tag", pinned, image["reference"]])
                actual = inspect_image(image["reference"])
                assert_identity(name, image, actual, args.revision)
                if cached and cached.get('digest') and actual['image_id'] != cached['image_id']:
                    raise ValueError("ID remoto mudou desde validate: " + image['reference'])
                image.update(reused=True, image_id=actual["image_id"], digest=digest, reuse_source="registry_digest")
            elif handed:
                actual = inspect_image(image["reference"])
                assert_identity(name, image, actual, args.revision)
                image.update(reused=True, image_id=actual["image_id"], reuse_source="same_run_handoff")
            else:
                command = ["docker", "buildx", "build", "--builder", "default", "--load", "--platform", "linux/amd64",
                           "--provenance=false", "--file", image["dockerfile"], "--tag", image["reference"]]
                for key, value in build_args(name, manifest, catalog, publish).items():
                    command += ["--build-arg", key + "=" + value]
                if args.proxy_ca:
                    command += ["--secret", "id=proxy_ca,src=" + str(args.proxy_ca.resolve())]
                command += ["."]
                run(command)
                actual = inspect_image(image["reference"])
                assert_identity(name, image, actual, args.revision)
                image.update(reused=False, image_id=actual["image_id"])
                if publish and name == "base":
                    # A base precisa estar disponível por digest para app/MinIO.
                    # Os gates Linux/Windows e validate são executados antes deste modo pelo workflow.
                    run(["docker", "run", "--rm", "--pull", "never", "--network", "none", image["reference"], "python", "-m", "pip", "check"])
                    run(["docker", "push", image["reference"]])
                    actual = inspect_image(image["reference"])
                    image["digest"] = actual["digest"]
            image["duration_seconds"] = round(time.monotonic() - started, 3)
            if publish and not handed and name == "base" and not image["digest"]:
                raise RuntimeError("Push sem digest verificável: " + image["reference"])
        # Smoke executa em validate e novamente nas imagens exatas publicadas/reutilizadas.
        interim = args.output.with_suffix(".pending.json")
        write_json(interim, manifest)
        smoke_output = args.output.with_suffix(".smoke.json")
        run([sys.executable, "scripts/smoke_images.py", "--images-manifest", interim, "--output", smoke_output])
        manifest["smoke"] = json.loads(smoke_output.read_text())
        interim.unlink(missing_ok=True)
        if publish:
            for name in IMAGE_NAMES:
                image = manifest["images"][name]
                if not image["digest"]:
                    # App e serviços só são enviados após o smoke das imagens exatas.
                    run(["docker", "push", image["reference"]])
                    image["digest"] = inspect_image(image["reference"])["digest"]
                if not image["digest"]:
                    raise RuntimeError("Push sem digest verificável: " + image["reference"])
                # Pull autenticado real por digest; o daemon pode reaproveitar layers locais.
                run(["docker", "pull", "--platform", "linux/amd64", image["repository"] + "@" + image["digest"]])
                pulled = inspect_image(image["reference"])
                if pulled["image_id"] != image["image_id"]:
                    raise RuntimeError("ID mudou após o pull: " + image["reference"])
            for image in manifest["images"].values():
                image.update(public_pull_probe(image["repository"], image["digest"]))
            manifest["public_pullable"] = all(x["public_pullable"] for x in manifest["images"].values())
        manifest["status"] = "published" if publish else "validated"
        write_json(args.output, manifest)
        if args.export_handoff:
            export_handoff(args.export_handoff, manifest, args.run_id, os.environ)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        manifest.update(status="failed", error=str(exc))
        write_json(args.output, manifest)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERRO: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
