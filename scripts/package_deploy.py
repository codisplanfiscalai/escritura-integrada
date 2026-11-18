#!/usr/bin/env python3
"""Gera deploys sem fontes da aplicação, builds ou segredos predefinidos."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from image_tools import ROOT, OPTIONAL_NAMES, read_json, sha256_file, validate_manifest, write_json


def deployment_env(manifest, environment):
    if environment not in {"production", "develop"}:
        raise ValueError("Ambiente de deploy inválido.")
    port = "8000" if environment == "production" else "8001"
    app_reference = (manifest["images"]["app"]["repository"] + ":develop"
                     if environment == "develop" else manifest["images"]["app"]["reference"])
    rows = ["# Gerado da publicação verificada. Não contém usuários/senhas predefinidos.",
            "# Develop segue :develop online; para fixar release, use tags de images.json nas variáveis *_IMAGE.",
            "COMPOSE_PROJECT_NAME=escritura-" + environment,
            "# Mantenha o bind existente. Instalação nova: vazio usa volume persistente.",
            "ESCRITURA_APP_DATA_BIND=", "ESCRITURA_POSTGRES_DATA_BIND=", "ESCRITURA_DATABASE_SCHEMA=public",
            "ESCRITURA_BIND=127.0.0.1", "ESCRITURA_PORT=" + port,
            "ESCRITURA_IMAGE=" + app_reference, "ESCRITURA_COOKIE_SECURE=0", "",
            "# PostgreSQL operacional obrigatório; demais serviços opcionais."]
    for name in OPTIONAL_NAMES:
        rows.append(name.upper() + "_IMAGE=" + manifest["images"][name]["reference"])
    rows += ["", "# POSTGRES_PASSWORD obrigatório; mínimo 16 caracteres por senha.",
             "REDIS_PASSWORD=", "POSTGRES_DB=escritura", "POSTGRES_USER=escritura", "POSTGRES_PASSWORD=",
             "MYSQL_DATABASE=escritura", "MYSQL_USER=escritura", "MYSQL_PASSWORD=", "MYSQL_ROOT_PASSWORD=",
             "MINIO_ROOT_USER=", "MINIO_ROOT_PASSWORD=", ""]
    return "\n".join(rows)


def release_compose(manifest):
    """Override explícito: só imagens/pull policy, nunca dados ou configuração privada."""
    return {"services": {
        name: {"image": manifest["images"][name]["reference"], "pull_policy": "missing"}
        for name in ("app", *OPTIONAL_NAMES)
    }}


def readme(manifest, environment):
    return (f"ESCRITURA INTEGRADA {manifest['version']} — {environment}\n\n"
            + (ROOT / 'docs/POSTGRES_OPERACIONAL.md').read_text(encoding='utf-8'))


def package(manifest, output_dir, root=ROOT):
    validate_manifest(manifest)
    root, output_dir = Path(root), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for environment in ("production", "develop"):
        stem = "EscrituraIntegrada-" + manifest["version"] + "-" + environment + "-deploy"
        files = {
            "compose.yaml": (root / "deploy" / environment / "compose.yaml").read_bytes(),
            ".env": deployment_env(manifest, environment).encode(),
            ".env.example": deployment_env(manifest, environment).encode(),
            "images.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
            "LEIA-ME.txt": readme(manifest, environment).encode(),
            "DEPLOY.md": (root / "docs/DEPLOY.md").read_text(encoding="utf-8").replace("(DOCKER_STORAGE.md", "(STORAGE.md").encode(),
            "deploy_storage.py": (root / "scripts/deploy_storage.py").read_bytes(),
            "STORAGE.md": (root / "docs/DOCKER_STORAGE.md").read_bytes(),
            "COFRE_A1.md": (root / "docs/COFRE_A1_DOCKER.md").read_bytes(),
            "THIRD-PARTY.md": (root / "docker/THIRD-PARTY.md").read_bytes(),
        }
        # Allowlist fechada: não inclui app/, banco, `.env` local, logs ou material recuperado.
        archive = output_dir / (stem + ".zip")
        temp = archive.with_suffix(".zip.part")
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, data in files.items():
                info = zipfile.ZipInfo(stem + "/" + name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16 if name == ".env" else 0o100644 << 16
                bundle.writestr(info, data)
        temp.replace(archive)
        digest = sha256_file(archive)
        archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n")
        outputs.append({"environment": environment, "file": archive.name, "sha256": digest, "bytes": archive.stat().st_size})
    summary = {"version": manifest["version"], "channel": manifest["channel"], "source_sha": manifest["source_sha"],
               "packages": outputs, "contains_source": True, "contains_application_source": False,
               "contains_admin_helper": True, "contains_fixed_credentials": False}
    write_json(output_dir / ("EscrituraIntegrada-" + manifest["version"] + "-deploy-manifest.json"), summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=["production", "develop"], required=True)
    parser.add_argument("--images-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = read_json(args.images_manifest)
    if manifest["version"] != args.version or manifest["channel"] != args.channel:
        raise ValueError("Versão/canal não correspondem ao manifesto publicado.")
    summary = package(manifest, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print("ERRO: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
