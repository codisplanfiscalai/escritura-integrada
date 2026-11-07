#!/usr/bin/env python3
"""Build/teste/publicação de imagens fixadas. Nenhum push no modo validate."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from image_tools import ROOT, IMAGE_NAMES, image_plan, load_catalog, run, write_json


def inspect_image(reference):
    result = run(["docker", "image", "inspect", reference], capture=True)
    data = json.loads(result.stdout)[0]
    digests = data.get("RepoDigests", [])
    repository = reference.rsplit(":", 1)[0]
    digest = next((x.split("@", 1)[1] for x in digests if x.startswith(repository + "@")), None)
    return {"image_id": data["Id"], "digest": digest, "labels": data["Config"].get("Labels") or {}}


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
    if labels.get("io.escritura.content-id") != wanted["content_id"]:
        raise RuntimeError("Tag já publicada com outro conteúdo; incremente a versão: " + wanted["reference"])
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
    args = parser.parse_args()
    manifest = image_plan(args.version, args.channel, args.revision)
    manifest.update(status="planned", generated_at=datetime.now(timezone.utc).isoformat())
    if args.dry_run:
        write_json(args.output, manifest)
        print("Plano salvo; nenhum Docker/build/push/teste foi executado.")
        return 0
    if (ROOT / "VERSION").read_text().strip() != args.version:
        raise ValueError("Aplique a versão no checkout antes de construir imagens (VERSION divergente).")
    catalog = load_catalog()
    run(["docker", "version"])
    run(["docker", "buildx", "version"])
    builder = run(["docker", "buildx", "inspect", "default"], capture=True).stdout
    if "docker-container" in builder:
        raise RuntimeError("Use o builder default com driver docker: validate resolve a base no daemon local.")
    publish = args.action == "publish"
    try:
        for name in IMAGE_NAMES:
            image = manifest["images"][name]
            exists = publish and remote_exists(image["reference"])
            if exists:
                run(["docker", "pull", "--platform", "linux/amd64", image["reference"]])
                actual = inspect_image(image["reference"])
                assert_identity(name, image, actual, args.revision)
                image.update(reused=True, image_id=actual["image_id"], digest=actual["digest"])
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
            if publish and name == "base" and not image["digest"]:
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
