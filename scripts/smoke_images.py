#!/usr/bin/env python3
"""Smoke real no Docker: GUI web compilada, sessão/SQLite e perfis opcionais."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from image_tools import OPTIONAL_NAMES, read_json, run, validate_manifest, write_json
from image_tools import ROOT
from package_deploy import deployment_env


def validate_compose_templates(manifest):
    """Compose real, inclusive app-only com todas as senhas opcionais vazias."""
    run(["docker", "compose", "version"])
    with tempfile.TemporaryDirectory(prefix="escritura-compose-check-") as temporary:
        for environment in ("production", "develop"):
            env_file = Path(temporary) / (environment + ".env")
            env_file.write_text(deployment_env(manifest, environment), encoding="utf-8")
            base = ["docker", "compose", "--env-file", env_file,
                    "--file", ROOT / "deploy" / environment / "compose.yaml"]
            run([*base, "config", "--quiet"])
            for profile in OPTIONAL_NAMES:
                run([*base, "--profile", profile, "config", "--quiet"])


def wait_healthy(name, timeout=180):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = run(["docker", "inspect", "--format", "{{json .State}}", name], capture=True)
        state = json.loads(result.stdout)
        if state.get("Health", {}).get("Status") == "healthy":
            return
        if state.get("Status") in {"exited", "dead"}:
            raise RuntimeError("Container encerrou antes do healthcheck: " + name)
        time.sleep(2)
    raise RuntimeError("Healthcheck não aprovou no prazo: " + name)


def http_json(opener, url, data=None):
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=10) as response:
        return json.load(response)


def assert_no_public_ports(name):
    result = run(["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", name], capture=True)
    ports = json.loads(result.stdout) or {}
    if any(ports.values()):
        raise RuntimeError("Serviço opcional publicou porta no host: " + name)


def smoke(manifest):
    images = manifest["images"]
    prefix = "escritura-smoke-" + uuid.uuid4().hex[:10]
    volume, network = prefix + "-data", prefix + "-internal"
    names = []
    results = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "running", "checks": []}
    validate_compose_templates(manifest)
    results["checks"].append("compose: produção/develop válidos em app-only e nos quatro perfis")
    run(["docker", "volume", "create", volume])
    run(["docker", "network", "create", "--internal", network])
    try:
        run(["docker", "run", "--rm", "--pull", "never", "--network", "none", images["base"]["reference"], "python", "-m", "pip", "check"])
        results["checks"].append("base: dependências Python consistentes")
        name = prefix + "-app"
        names.append(name)
        run(["docker", "run", "--detach", "--pull", "never", "--name", name, "--read-only", "--cap-drop", "ALL",
             "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
             "--mount", "type=volume,src=" + volume + ",dst=/data", "--publish", "127.0.0.1::8000",
             "--env", "ESCRITURA_DEMO=0", images["app"]["reference"]])
        wait_healthy(name)
        port = run(["docker", "port", name, "8000/tcp"], capture=True).stdout.strip()
        if not re.fullmatch(r"127\.0\.0\.1:\d+", port):
            raise RuntimeError("Porta do smoke não está restrita a loopback.")
        url = "http://" + port
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        health = http_json(opener, url + "/api/health")
        if health != {"status": "ok", "version": manifest["version"], "demo": False}:
            raise RuntimeError("Saúde/versão/modo inesperados na imagem da aplicação.")
        with opener.open(url + "/", timeout=10) as response:
            page = response.read().decode()
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page)
        if 'id="app"' not in page or not assets or not any(x.endswith(".js") for x in assets):
            raise RuntimeError("Interface compilada não foi servida pela imagem.")
        for asset in assets:
            with opener.open(url + asset, timeout=10) as response:
                if response.status != 200 or len(response.read()) < 50:
                    raise RuntimeError("Asset não foi servido: " + asset)
        first = http_json(opener, url + "/api/session")
        if not first.get("setup_required") or first.get("authenticated"):
            raise RuntimeError("Imagem não iniciou sem dados/usuário predefinidos.")
        session = http_json(opener, url + "/api/setup", {"username": "smoke-ci", "password": secrets.token_urlsafe(32)})
        if not session.get("authenticated"):
            raise RuntimeError("Configuração inicial falhou.")
        run(["docker", "restart", name])
        wait_healthy(name)
        again = http_json(opener, url + "/api/session")
        if not again.get("authenticated") or again.get("setup_required"):
            raise RuntimeError("Sessão/SQLite não persistiram após reinício.")
        run(["docker", "exec", name, "python", "-c",
             "from pathlib import Path; assert Path('/data/escritura.sqlite3').stat().st_size > 0"])
        config_user = run(["docker", "inspect", "--format", "{{.Config.User}}", name], capture=True).stdout.strip()
        if config_user != "10001:10001":
            raise RuntimeError("Aplicação deve executar sem root.")
        results["checks"] += ["app: health/versão/demo desligado", "app: HTML/JS/CSS compilados",
                              "app: configuração inicial sem credencial predefinida", "app: sessão/SQLite persistem após reinício",
                              "app: usuário 10001, filesystem de raiz somente leitura, porta loopback"]
        credentials = {
            "redis": {"REDIS_PASSWORD": secrets.token_hex(24)},
            "postgres": {"POSTGRES_PASSWORD": secrets.token_hex(24), "POSTGRES_USER": "escritura", "POSTGRES_DB": "escritura"},
            "mysql": {"MYSQL_ROOT_PASSWORD": secrets.token_hex(24), "MYSQL_PASSWORD": secrets.token_hex(24),
                      "MYSQL_USER": "escritura", "MYSQL_DATABASE": "escritura"},
            "minio": {"MINIO_ROOT_USER": "smoke-admin", "MINIO_ROOT_PASSWORD": secrets.token_hex(24)},
        }
        for service in OPTIONAL_NAMES:
            # Guard ocorre dentro da imagem, inclusive em docker compose direto.
            missing = run(["docker", "run", "--rm", "--pull", "never", "--network", "none", images[service]["reference"]], capture=True, check=False)
            if missing.returncode != 64 or "Perfil " not in (missing.stderr + missing.stdout):
                raise RuntimeError("Perfil " + service + " não rejeitou credenciais ausentes de forma explícita.")
            name = prefix + "-" + service
            names.append(name)
            command = ["docker", "run", "--detach", "--pull", "never", "--name", name, "--network", network]
            for variable in credentials[service]:
                command += ["--env", variable]
            command.append(images[service]["reference"])
            run(command, env={**os.environ, **credentials[service]})
            wait_healthy(name, timeout=300 if service == "mysql" else 180)
            assert_no_public_ports(name)
            results["checks"].append(service + ": credencial obrigatória, health e nenhuma porta publicada")
        results["status"] = "passed"
        results["finished_at"] = datetime.now(timezone.utc).isoformat()
        return results
    finally:
        # Remove somente recursos efêmeros que este processo criou.
        for name in reversed(names):
            run(["docker", "rm", "--force", "--volumes", name], capture=True, check=False)
        run(["docker", "network", "rm", network], capture=True, check=False)
        run(["docker", "volume", "rm", volume], capture=True, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = validate_manifest(read_json(args.images_manifest), require_published=False)
    try:
        result = smoke(manifest)
        write_json(args.output, result)
        return 0
    except Exception as exc:
        write_json(args.output, {"status": "failed", "error": str(exc), "finished_at": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print("ERRO: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
