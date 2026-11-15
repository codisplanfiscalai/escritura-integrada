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
            "# Develop segue :develop online; compose.release.yaml fixa a publicação para offline/rollback.",
            "COMPOSE_PROJECT_NAME=escritura-" + environment,
            "# Caminho HOST do bind do app. Vazio usa ./data/<projeto>/app; em bind existente, preserve ./data/app.",
            "ESCRITURA_APP_DATA_BIND=",
            "ESCRITURA_BIND=127.0.0.1", "ESCRITURA_PORT=" + port,
            "ESCRITURA_IMAGE=" + app_reference, "ESCRITURA_COOKIE_SECURE=0", "",
            "# Serviços opcionais internos; o aplicativo permanece em SQLite."]
    for name in OPTIONAL_NAMES:
        rows.append(name.upper() + "_IMAGE=" + manifest["images"][name]["reference"])
    rows += ["", "# Preencha somente quando ativar o perfil correspondente; mínimo 16 caracteres por senha.",
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
    port = "8000" if environment == "production" else "8001"
    version = manifest["version"]
    return f"""ESCRITURA INTEGRADA {version} — {environment}

Requisitos: Docker Engine/Desktop com containers Linux e Docker Compose v2.
Plataforma publicada: linux/amd64. Nenhum build ou código da aplicação no host.

INICIAR
Stack já usando ./data/app:/data: preserve esse caminho. Não execute init ou
migrate nem recopie o volume antigo. Leia a seção de bind existente em STORAGE.md.
compose.existing-bind.yaml é um override explícito para esse caminho, sem cópia
ou alteração de permissões. Não substitua mounts dos demais serviços sem revisão.
Nos templates novos, ESCRITURA_APP_DATA_BIND=./data/app no .env preserva esse
bind; vazio usa ./data/<projeto>/app. Não substitua seu .env privado pelo exemplo.
Antes de subir, use check-app conforme STORAGE.md; ownership incorreto pode
impedir UID 10001 de abrir SQLite mesmo quando a cópia preservou todos os bytes.

1. Extraia este pacote em um diretório próprio.
2. Instalação nova: baixe/carregue a imagem do app (docker compose pull app).
3. Prepare as pastas com Python 3.10+ e a imagem LOCAL da aplicação:
   python3 deploy_storage.py init --project escritura-{environment} --helper-image <imagem-do-app-no-.env>
   Use o mesmo COMPOSE_PROJECT_NAME do .env; não execute init numa stack existente.
4. Execute: docker compose up -d
5. Confira permissões e health (Started sozinho não valida startup):
   python3 deploy_storage.py check-app --compose-file compose.yaml --project escritura-{environment} --require-health --wait-health-seconds 120
6. Abra http://127.0.0.1:{port} e crie o administrador no primeiro acesso.

Apenas a porta da aplicação é publicada, com bind loopback por padrão.
Produção mantém a tag versionada; develop segue :develop. O app consulta o
registro em cada up nos dois pacotes, inclusive se ESCRITURA_IMAGE for :latest
(main estável) ou :develop (pré-release). Os aliases só avançam após promoção.
Não há senha padrão de administrador. images.json descreve a release fixada,
não necessariamente a imagem mais recente executada por um canal móvel.
Não compartilhe ./data/<projeto> entre stacks/ambientes.

GHCR E VISIBILIDADE
Pacotes GHCR novos podem ser privados. Se o pull exigir autenticação, faça
docker login ghcr.io com uma conta autorizada e token com read:packages.
A publicação não torna automaticamente as imagens públicas.
O manifesto images.json registra o resultado da sonda anônima, quando feita.

SEM ACESSO AO REGISTRO (IMAGENS OFFLINE)
Baixe também EscrituraIntegrada-{version}-linux-amd64-images.tar.gz e os hashes.
Confira o SHA-256 antes de carregar. Docker já deve estar instalado.
docker load -i /caminho/EscrituraIntegrada-{version}-linux-amd64-images.tar.gz
Em instalação nova, execute init com a tag versionada local presente no tar.
docker compose -f compose.yaml -f compose.release.yaml up -d --pull never

O bundle contém app, base Python, Redis, PostgreSQL, MySQL e MinIO.
O override compose.release.yaml usa tags imutáveis presentes no tar;
images.json guarda digests e IDs para conferência.
Não depende de RepoDigests serem preservados por docker save/load.

PERFIS OPCIONAIS
O backend desta versão usa SQLite. Estes serviços ainda NÃO estão integrados:
redis, postgres, mysql, minio. Ativá-los não migra nem muda a base da aplicação.
Preencha no .env as variáveis do perfil desejado; senhas com ao menos 16 caracteres.
Redis: REDIS_PASSWORD.
PostgreSQL: POSTGRES_PASSWORD (usuário/banco configuráveis).
MySQL: MYSQL_ROOT_PASSWORD e MYSQL_PASSWORD (usuário/banco configuráveis).
MinIO: MINIO_ROOT_USER (mínimo 3) e MINIO_ROOT_PASSWORD.
Exemplo: docker compose --profile redis up -d
Offline: docker compose -f compose.yaml -f compose.release.yaml --profile redis up -d --pull never
As próprias imagens rejeitam credenciais ausentes com mensagem explícita.
Nenhuma porta de banco, S3 ou console MinIO é publicada no host.

DADOS E ATUALIZAÇÕES
Cada serviço persiste em ./data/<COMPOSE_PROJECT_NAME>/<serviço>, junto à stack.
O app usa a subpasta app para SQLite, documentos, relatórios e demais arquivos /data.
PostgreSQL, MySQL, MinIO e Redis têm suas próprias subpastas, inclusive perfis inativos.
Bind mounts exigem diretórios preparados; não são criados silenciosamente pelo Compose.
O UID/GID do app e MinIO é 10001:10001; não use chmod 777.
init/migrate validam acesso do app com o USER real da imagem local antes de
publicar o destino. Não fazem reparo automático de owners de dados existentes.
STORAGE.md explica o diagnóstico de root:root 0600 e a correção condicionada
somente da pasta app, preservando imagem/dados e identidades dos outros serviços.
Depois de health e API, confira login, empresas e documentos na interface.

STACK EXISTENTE: trocar mounts por pastas vazias NÃO transfere os dados antigos.
Siga STORAGE.md: salve o Compose antigo, planeje, pare todos os escritores,
copie/verifique os volumes para destino novo e só então aplique o Compose novo.
A ferramenta gera também um override com os IDs das imagens instaladas; use-o
no primeiro corte para não atualizar imagens e armazenamento ao mesmo tempo.
A ferramenta recusa destinos existentes, mantém os volumes originais e não altera
os arquivos Compose. Não execute nenhuma cópia com bancos/serviços em execução.
Faça backup consistente e testado antes de atualizar. Nunca use down -v em dados
que deseja manter. Um rollback da imagem não desfaz migrações de banco.
Online: docker compose up -d. Com :develop/:latest, não é preciso trocar a tag
no .env a cada versão. docker compose pull app baixa a imagem, mas é o up que
aplica a atualização. No Dockge, salve o Compose e execute a ação de atualizar/
implantar que faz pull/up; reiniciar o container existente não busca imagem.
Em stacks já instaladas, inclusive as criadas pelo Compose da raiz/produção,
incorpore services.app.pull_policy: always no compose.yaml usado pela stack.
Para seguir um canal, ajuste ESCRITURA_IMAGE para
ghcr.io/codisplanfiscalai/escritura-integrada:develop (pré-release) ou
ghcr.io/codisplanfiscalai/escritura-integrada:latest (main estável).
Código/ZIP novo não modifica automaticamente stacks ou pacotes já publicados.
Não há atualização contínua em segundo plano: execute pull/up ou a ação Dockge.
Falhas de rede/autenticação precisam ser resolvidas antes de atualizar.
Preserve COMPOSE_PROJECT_NAME, .env, credenciais, bind, portas e dados existentes.
Para fixar/voltar à release deste pacote, use sempre os dois arquivos Compose:
docker compose -f compose.yaml -f compose.release.yaml up -d
Para voltar ao canal móvel configurado no .env, use apenas docker compose up -d.
Atualizar somente a imagem não exige down prévio; a migração de armazenamento
exige parar todos os escritores conforme STORAGE.md.
As instruções completas estão em DEPLOY.md, STORAGE.md e THIRD-PARTY.md neste pacote.
"""


def package(manifest, output_dir, root=ROOT):
    validate_manifest(manifest)
    root, output_dir = Path(root), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for environment in ("production", "develop"):
        stem = "EscrituraIntegrada-" + manifest["version"] + "-" + environment + "-deploy"
        files = {
            "compose.yaml": (root / "deploy" / environment / "compose.yaml").read_bytes(),
            "compose.release.yaml": (json.dumps(release_compose(manifest), ensure_ascii=False, indent=2) + "\n").encode(),
            "compose.existing-bind.yaml": (root / "deploy/compose.existing-bind.yaml").read_bytes(),
            ".env": deployment_env(manifest, environment).encode(),
            ".env.example": deployment_env(manifest, environment).encode(),
            "images.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
            "LEIA-ME.txt": readme(manifest, environment).encode(),
            "DEPLOY.md": (root / "docs/DEPLOY.md").read_text(encoding="utf-8").replace("(DOCKER_STORAGE.md", "(STORAGE.md").encode(),
            "deploy_storage.py": (root / "scripts/deploy_storage.py").read_bytes(),
            "STORAGE.md": (root / "docs/DOCKER_STORAGE.md").read_bytes(),
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
