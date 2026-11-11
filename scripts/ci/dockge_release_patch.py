"""Cria um ZIP Dockge r1 aditivo a partir de um deploy publicado e fixado por SHA-256.

Somente services.app.ports muda no JSON de compose.yaml. Os outros seis arquivos,
o prefixo interno, as imagens, o ambiente e os dados de origem são preservados.
Não baixa, extrai, executa Compose, publica nem substitui arquivos existentes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import zipfile

from scripts.image_tools import validate_manifest, validate_version


FILES = frozenset({"compose.yaml", ".env", ".env.example", "images.json",
                   "LEIA-ME.txt", "DEPLOY.md", "THIRD-PARTY.md"})
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
APP_IMAGE = "${ESCRITURA_IMAGE:?Use a imagem publicada ou o pacote de deploy da release}"


class PatchError(ValueError):
    """Entrada inesperada: nenhum pacote deve ser publicado."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require_hex(value, length, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise PatchError(label + " deve ser um hash hexadecimal completo em minúsculas.")


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PatchError("JSON contém chave duplicada: " + key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise PatchError("Constante JSON inválida: " + value)

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PatchError("JSON inválido: " + str(exc)) from exc
    if not isinstance(value, dict):
        raise PatchError("JSON deve conter um objeto.")
    return value


def read_bundle(raw, prefix):
    """Lê somente sete arquivos pequenos em memória; nunca extrai caminhos."""
    if not 0 < len(raw) <= MAX_ARCHIVE_BYTES:
        raise PatchError("ZIP vazio ou acima do limite de tamanho.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            entries = bundle.infolist()
            expected = {prefix + name for name in FILES}
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise PatchError("ZIP contém nomes duplicados.")
            if len(entries) != len(FILES) or set(names) != expected:
                raise PatchError("ZIP fora da allowlist de sete arquivos/prefixo esperado.")
            total = 0
            for entry in entries:
                # The exact allowlist also rejects traversal, absolute paths,
                # alternate separators, nested paths and directory entries.
                if entry.orig_filename != entry.filename:
                    raise PatchError("ZIP contém nome truncado ou inválido.")
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or entry.external_attr & 0x10:
                    raise PatchError("ZIP contém link ou entrada não regular.")
                if entry.flag_bits & 1:
                    raise PatchError("ZIP criptografado não é permitido.")
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise PatchError("Método de compressão ZIP não permitido.")
                if not 0 < entry.file_size <= MAX_FILE_BYTES:
                    raise PatchError("Arquivo vazio ou acima do limite de tamanho.")
                total += entry.file_size
                if total > MAX_TOTAL_BYTES:
                    raise PatchError("ZIP excede o limite total descomprimido.")
                if entry.file_size > MAX_COMPRESSION_RATIO * max(1, entry.compress_size):
                    raise PatchError("ZIP excede o limite de razão de compressão.")
            contents = {}
            for entry in entries:
                with bundle.open(entry) as handle:
                    value = handle.read(MAX_FILE_BYTES + 1)
                if len(value) != entry.file_size or len(value) > MAX_FILE_BYTES:
                    raise PatchError("Tamanho descomprimido ZIP divergente.")
                contents[entry.filename.removeprefix(prefix)] = value
            return entries, contents, bundle.comment
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
        raise PatchError("ZIP inválido: " + str(exc)) from exc


def validate_identity(files, version, environment, expected_source_sha):
    manifest = strict_json(files["images.json"])
    try:
        validate_manifest(manifest)
        if manifest["version"] != version:
            raise PatchError("Versão de images.json diverge da versão esperada.")
        if expected_source_sha and manifest["source_sha"] != expected_source_sha:
            raise PatchError("source_sha de images.json diverge do plano.")
        app = manifest["images"]["app"]
        if app["tag"] != validate_version(version):
            raise PatchError("Tag da imagem app diverge da versão esperada.")
        if app.get("source_sha", manifest["source_sha"]) != manifest["source_sha"]:
            raise PatchError("source_sha da imagem app diverge do manifesto.")
        expected_env = {
            "COMPOSE_PROJECT_NAME": "escritura-" + environment,
            "ESCRITURA_IMAGE": app["reference"],
            "ESCRITURA_BIND": "127.0.0.1",
            "ESCRITURA_PORT": "8000" if environment == "production" else "8001",
        }
        for filename in (".env", ".env.example"):
            rows = files[filename].decode("utf-8").splitlines()
            for key, expected in expected_env.items():
                matches = [row for row in rows if row.startswith(key + "=")]
                if matches != [key + "=" + expected]:
                    raise PatchError(filename + ": identidade/ambiente divergente em " + key)
    except (KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise PatchError("Identidade de imagens/ambiente inválida.") from exc
    return manifest


def patch_compose(data, environment):
    original = strict_json(data)
    port = "8000" if environment == "production" else "8001"
    published = "${ESCRITURA_PORT:-" + port + "}"
    long_port = {"target": 8000, "published": published,
                 "host_ip": "${ESCRITURA_BIND:-127.0.0.1}", "protocol": "tcp"}
    short_port = "${ESCRITURA_BIND:-127.0.0.1}:" + published + ":8000/tcp"
    try:
        app = original["services"]["app"]
        if app["image"] != APP_IMAGE:
            raise PatchError("Referência de imagem app do Compose inesperada.")
        if original["name"] != "${COMPOSE_PROJECT_NAME:-escritura-" + environment + "}":
            raise PatchError("Ambiente/nome do projeto Compose inesperado.")
        if app["ports"] != [long_port] or type(app["ports"][0]["target"]) is not int:
            raise PatchError("services.app.ports não é o objeto original esperado.")
    except (KeyError, TypeError, IndexError) as exc:
        raise PatchError("Estrutura Compose inesperada.") from exc
    patched = copy.deepcopy(original)
    patched["services"]["app"]["ports"] = [short_port]
    encoded = (json.dumps(patched, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    restored = strict_json(encoded)
    restored["services"]["app"]["ports"] = [long_port]
    if restored != original:
        raise PatchError("Compose alterado além de services.app.ports.")
    return encoded


def patch_archive(zip_path, *, expected_sha256, version, environment,
                  output_dir, tool_commit, expected_source_sha=None):
    """Gera ZIP, sidecar SHA-256 e relatório próprio; nunca altera o original."""
    validate_version(version)
    if environment not in {"production", "develop"}:
        raise PatchError("Ambiente deve ser production ou develop.")
    require_hex(expected_sha256, 64, "SHA-256 esperado")
    require_hex(tool_commit, 40, "Commit da ferramenta")
    if expected_source_sha is not None:
        require_hex(expected_source_sha, 40, "Source SHA esperado")
    zip_path, output_dir = Path(zip_path), Path(output_dir)
    if zip_path.is_symlink() or not zip_path.is_file():
        raise PatchError("Entrada ZIP deve ser arquivo regular, não link.")
    with zip_path.open("rb") as handle:
        raw = handle.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise PatchError("ZIP acima do limite de tamanho.")
    if digest(raw) != expected_sha256:
        raise PatchError("SHA-256 do ZIP original diverge do plano.")
    stem = "EscrituraIntegrada-" + version + "-" + environment + "-deploy"
    prefix = stem + "/"
    entries, before, comment = read_bundle(raw, prefix)
    manifest = validate_identity(before, version, environment, expected_source_sha)
    after = dict(before)
    after["compose.yaml"] = patch_compose(before["compose.yaml"], environment)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.comment = comment
        for entry in entries:
            bundle.writestr(copy.copy(entry), after[entry.filename.removeprefix(prefix)])
    patched_raw = output.getvalue()
    _, verified, _ = read_bundle(patched_raw, prefix)
    if verified != after or {name for name in FILES if before[name] != verified[name]} != {"compose.yaml"}:
        raise PatchError("Conteúdo do ZIP final não corresponde à alteração única esperada.")
    filename = stem + "-dockge-r1.zip"
    report = {
        "schema": "escritura-dockge-patch/1", "patch_revision": "dockge-r1",
        "version": version, "environment": environment,
        "source_sha": manifest["source_sha"], "expected_source_sha": expected_source_sha,
        "tool_commit": tool_commit, "tool_sha256": digest(Path(__file__).read_bytes()),
        "original": {"file": stem + ".zip", "sha256": expected_sha256, "bytes": len(raw)},
        "patched": {"file": filename, "sha256": digest(patched_raw), "bytes": len(patched_raw)},
        "internal_prefix": prefix, "changed_path": "services.app.ports",
        "app_image": manifest["images"]["app"],
        "files": [{"path": prefix + name, "sha256_before": digest(before[name]),
                   "sha256_after": digest(verified[name]), "bytes_before": len(before[name]),
                   "bytes_after": len(verified[name]), "changed": before[name] != verified[name]}
                  for name in sorted(FILES)],
    }
    payloads = {
        filename: patched_raw,
        filename + ".sha256": (digest(patched_raw) + "  " + filename + "\n").encode("ascii"),
        filename + ".report.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    if any((output_dir / name).exists() or (output_dir / name).is_symlink() for name in payloads):
        raise PatchError("Destino já existe; nenhuma saída será substituída.")
    created = []
    try:
        for name, content in payloads.items():
            path = output_dir / name
            with path.open("xb") as handle:
                created.append(path)
                handle.write(content)
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="zip_path", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--environment", choices=("production", "develop"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tool-commit", required=True, help="Commit completo da ferramenta de correção, não da imagem.")
    parser.add_argument("--expected-source-sha", help="Commit completo de origem declarado pelo plano da release.")
    args = parser.parse_args()
    try:
        report = patch_archive(**vars(args))
    except (OSError, ValueError, RecursionError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
