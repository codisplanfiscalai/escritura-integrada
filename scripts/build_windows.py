"""Constrói e verifica o pacote gráfico Windows x64 no próprio Windows."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


def run(arguments, cwd=ROOT, env=None, timeout=None):
    subprocess.run([str(x) for x in arguments], cwd=cwd, env=env, timeout=timeout, check=True)


def source_revision() -> str | None:
    explicit = os.environ.get("ESCRITURA_SOURCE_SHA", "").strip()
    if explicit and not re.fullmatch(r"[0-9a-f]{40}", explicit):
        raise ValueError("ESCRITURA_SOURCE_SHA deve conter o SHA Git completo em hexadecimal.")
    try:
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                         stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        actual = ""
    if actual and not re.fullmatch(r"[0-9a-f]{40}", actual):
        raise ValueError("O checkout não forneceu um SHA Git completo reconhecido.")
    if explicit and actual and explicit != actual:
        raise ValueError("O commit do checkout diverge de ESCRITURA_SOURCE_SHA.")
    return explicit or actual or None


def version_resource(version: str) -> dict:
    match = SEMVER.fullmatch(version)
    if not match or any(part.isdigit() and len(part) > 1 and part.startswith("0")
                        for part in (match.group(4) or "").split(".")):
        raise ValueError("VERSION deve conter SemVer válida, por exemplo 0.4.1-dev.123.")
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    if any(number > 65535 for number in core):
        raise ValueError("Os três componentes principais da versão Windows devem caber em uint16.")
    suffix = re.search(r"(?:^|\.)(\d+)$", match.group(4) or "")
    build = int(suffix.group(1)) if suffix else 0
    return {"semver": version, "numeric": core + (min(build, 65535),),
            "prerelease": bool(match.group(4)), "revision_capped": build > 65535,
            "revision_original": build}


def write_version_info(path: Path, version: dict):
    semver, numeric = version["semver"], version["numeric"]
    path.write_text(f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r},
    mask=0x3f, flags={2 if version["prerelease"] else 0}, OS=0x40004,
    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041604B0', [
    StringStruct('CompanyName', 'Codisplan'),
    StringStruct('FileDescription', 'Escritura Integrada'),
    StringStruct('FileVersion', {semver!r}),
    StringStruct('InternalName', 'EscrituraIntegrada'),
    StringStruct('OriginalFilename', 'EscrituraIntegrada.exe'),
    StringStruct('ProductName', 'Escritura Integrada'),
    StringStruct('ProductVersion', {semver!r})
  ])]), VarFileInfo([VarStruct('Translation', [1046, 1200])])]
)
''', encoding="utf-8")


def pe_details(path: Path, *, gui: bool = False) -> dict:
    """Lê cabeçalhos PE; não usa o nome do arquivo como prova de arquitetura."""
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"Cabeçalho DOS ausente: {path.name}")
        stream.seek(0x3C)
        pointer = stream.read(4)
        if len(pointer) != 4:
            raise ValueError(f"Cabeçalho PE truncado: {path.name}")
        stream.seek(struct.unpack("<I", pointer)[0])
        header = stream.read(24)
        if len(header) != 24 or header[:4] != b"PE\0\0":
            raise ValueError(f"Assinatura PE inválida: {path.name}")
        machine = struct.unpack_from("<H", header, 4)[0]
        optional = stream.read(struct.unpack_from("<H", header, 20)[0])
        if len(optional) < 70:
            raise ValueError(f"Cabeçalho opcional PE truncado: {path.name}")
        magic, subsystem = struct.unpack_from("<H", optional)[0], struct.unpack_from("<H", optional, 68)[0]
        if machine != 0x8664 or magic != 0x20B:
            raise ValueError(f"O executável não é AMD64/PE32+: {path.name}")
        if gui and subsystem != 2:
            raise ValueError(f"O executável de entrada não é gráfico/windowed: {path.name}")
        return {"machine": "AMD64", "format": "PE32+", "subsystem": subsystem,
                "gui": subsystem == 2, "bytes": path.stat().st_size}


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag in {"script", "img"} and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"])


def frontend_assets(directory: Path) -> list[str]:
    index = directory / "index.html"
    parser = AssetParser()
    parser.feed(index.read_text(encoding="utf-8"))
    verified = []
    for reference in parser.assets:
        url = urlparse(reference)
        if url.scheme or url.netloc:
            raise ValueError(f"Asset externo incompatível com abertura offline: {reference}")
        relative = unquote(url.path).lstrip("/")
        asset = (directory / relative).resolve()
        if not asset.is_relative_to(directory.resolve()) or not asset.is_file():
            raise ValueError(f"Asset ausente ou fora da interface: {reference}")
        verified.append(relative)
    if not any(path.endswith(".js") for path in verified) or not any(path.endswith(".css") for path in verified):
        raise ValueError("A interface compilada deve conter JavaScript e CSS locais.")
    if not (directory / "brand.svg").is_file():
        raise ValueError("A marca frontend/dist/brand.svg está ausente.")
    return sorted(set(verified))


def verify_bundle(bundle: Path) -> dict:
    files = [path for path in bundle.rglob("*") if path.is_file()]
    by_name = {}
    for path in files:
        by_name.setdefault(path.name.casefold(), []).append(path)
    required = ("QtWebEngineProcess.exe", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
                "Qt6WebEngineCore.dll", "Qt6WebEngineWidgets.dll", "qwindows.dll",
                "icudtl.dat", "qtwebengine_resources.pak", "v8_context_snapshot.bin", "en-US.pak", "pt-BR.pak")
    missing = [name for name in required if name.casefold() not in by_name]
    if missing:
        raise RuntimeError("Runtime incompleto no pacote: " + ", ".join(missing))
    helper = by_name["qtwebengineprocess.exe"][0]
    entrypoint = pe_details(bundle / "EscrituraIntegrada.exe", gui=True)
    helper_pe = pe_details(helper)
    internal = bundle / "_internal"
    for relative in ("VERSION", "app/assets/app.ico", "docs/DISTRIBUICAO_WINDOWS.md",
                     "frontend/dist/third-party/NOTICE.txt", "frontend/dist/third-party/inventory.json"):
        if not (internal / relative).is_file():
            raise RuntimeError(f"Recurso ausente no pacote: {relative}")
    assets = frontend_assets(internal / "frontend/dist")
    forbidden = [path.relative_to(bundle).as_posix() for path in files
                 if path.name in {"config.ini", "aplicacao.lock", "aplicacao.log"}
                 or path.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}]
    if forbidden:
        raise RuntimeError("O pacote contém dados locais que não devem ser distribuídos: " + ", ".join(forbidden))
    return {"entrypoint": entrypoint, "webengine_helper": helper_pe,
            "runtime_files": {name: by_name[name.casefold()][0].relative_to(bundle).as_posix() for name in required},
            "frontend_assets": assets, "file_count": len(files)}


def collect_notices(bundle: Path) -> dict:
    """Preserva textos e metadados dos pacotes instalados, sem relicenciar o app."""
    from packaging.requirements import Requirement
    names = ["PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "pyinstaller",
             "fastapi", "pydantic", "uvicorn", "python-multipart", "py7zr", "rarfile"]
    licenses = bundle / "licenses"
    licenses.mkdir()
    seen, packages = set(), []
    while names:
        name = names.pop(0)
        canonical = re.sub(r"[-_.]+", "-", name).lower()
        if canonical in seen:
            continue
        seen.add(canonical)
        distribution = importlib.metadata.distribution(name)
        metadata = distribution.metadata
        item = {"name": metadata.get("Name", name), "version": distribution.version,
                "license_expression": metadata.get("License-Expression"),
                "license_metadata": metadata.get("License"),
                "project_urls": metadata.get_all("Project-URL", []),
                "homepage": metadata.get("Home-page"), "files": []}
        for entry in distribution.files or []:
            source = Path(distribution.locate_file(entry))
            parts = [part.casefold() for part in entry.parts]
            is_license = (source.name.casefold().startswith(("license", "licence", "copying", "notice", "copyright"))
                          or any(part in {"licenses", "licences"} for part in parts))
            if not is_license or not source.is_file() or source.suffix.lower() in {".pyc", ".dll", ".pyd", ".exe"}:
                continue
            safe = [part for part in entry.parts if part not in {"..", "."} and not Path(part).is_absolute()]
            destination = licenses / canonical / Path(*safe)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            item["files"].append(destination.relative_to(bundle).as_posix())
        packages.append(item)
        for dependency in distribution.requires or []:
            requirement = Requirement(dependency)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                names.append(requirement.name)
    python_license = next((path for path in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE") if path.is_file()), None)
    if python_license:
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    report = {"python": platform.python_version(), "python_license_included": bool(python_license),
              "components": sorted(packages, key=lambda item: item["name"].casefold()),
              "scope": "Metadados e textos de licença disponíveis nas distribuições instaladas; sem atribuição de licença ao código da aplicação."}
    frontend = json.loads((bundle / "_internal/frontend/dist/third-party/inventory.json").read_text(encoding="utf-8"))
    report["frontend"] = {"inventory": "_internal/frontend/dist/third-party/inventory.json",
                          "notices": "_internal/frontend/dist/third-party/NOTICE.txt",
                          "packages": frontend["package_count"], "notice_files": frontend["notice_file_count"],
                          "scope": frontend["scope"]}
    (licenses / "components.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["ESCRITURA INTEGRADA — COMPONENTES DE TERCEIROS", "",
             "Este aviso não define nem altera a licença do código da aplicação.",
             "Os componentes conservam suas próprias licenças, autores e avisos.",
             "A pasta licenses contém textos fornecidos pelos pacotes instalados e o inventário components.json.",
             "Os avisos Vue, Lucide e demais pacotes frontend ficam em _internal/frontend/dist/third-party/NOTICE.txt.",
             "O inventário frontend inclui também ferramentas de desenvolvimento, conforme identificado em seus metadados.",
             "A presença de um pacote de construção neste inventário não implica que todo seu código esteja no executável.", "",
             "Fontes e informações oficiais:",
             "Qt / PySide: https://www.qt.io/qt-licensing",
             "Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html",
             "Qt WebEngine / Chromium: https://doc.qt.io/qt-6/qtwebengine-licensing.html",
             "Código Qt: https://code.qt.io/cgit/qt/",
             "Código PySide: https://code.qt.io/cgit/pyside/pyside-setup.git/",
             "PyInstaller e exceção de distribuição: https://pyinstaller.org/en/stable/license.html",
             "Código PyInstaller: https://github.com/pyinstaller/pyinstaller",
             "Python: https://docs.python.org/3/license.html", "",
             "Componentes da construção:"]
    for package in report["components"]:
        expression = package["license_expression"] or "consulte os metadados e textos do componente"
        lines.append(f"- {package['name']} {package['version']}: {expression}; {len(package['files'])} arquivo(s) de avisos/licença disponível(is).")
    (bundle / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"components": len(packages), "license_files": sum(len(package["files"]) for package in packages),
            "python_license_included": bool(python_license),
            "frontend": report["frontend"],
            "components_without_license_files": [package["name"] for package in packages if not package["files"]]}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-frontend", action="store_true", help="Usa frontend/dist já compilado")
    parser.add_argument("--smoke", action="store_true", help="Testa o EXE extraído do ZIP, sua interface e o encerramento")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        parser.error("Execute com Python x64 em Windows. Não há cross-build nem emulação nesta construção.")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    metadata = {"ok": False, "stage": "preflight", "target": "windows-x64", "console": False,
                "packaging": "portable-directory", "entrypoint": "EscrituraIntegrada/EscrituraIntegrada.exe",
                "built_at_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
                "smoke_executed": False, "smoke_ok": None}
    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        windows_version = version_resource(version)
        metadata.update(version=version, windows_version=windows_version)
        metadata["source_sha"] = source_revision()
        for package in ("PySide6", "pyinstaller"):
            metadata[package] = importlib.metadata.version(package)
        from PySide6.QtCore import qVersion
        from PySide6 import QtWebEngineCore, QtWebEngineWidgets  # noqa: F401
        metadata["qt"] = qVersion()
        if not args.skip_frontend:
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm:
                raise RuntimeError("Node.js/npm não encontrado. Use Node.js 22 para construir a interface.")
            run([npm, "ci"], cwd=ROOT / "frontend")
            run([npm, "run", "build"], cwd=ROOT / "frontend")
        metadata["source_frontend_assets"] = frontend_assets(ROOT / "frontend/dist")
        for path in ("app/assets/app.ico", "app/api.py", "docs/DISTRIBUICAO_WINDOWS.md"):
            if not (ROOT / path).is_file():
                raise FileNotFoundError(f"Arquivo obrigatório ausente: {path}")
        (ROOT / "build").mkdir(exist_ok=True)
        write_version_info(ROOT / "build/windows-version.txt", windows_version)
        metadata["stage"] = "pyinstaller"
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", ROOT / "build/windows-dist", "--workpath", ROOT / "build/pyinstaller",
             ROOT / "escritura-integrada.spec"])
        bundle = ROOT / "build/windows-dist/EscrituraIntegrada"
        metadata["stage"] = "runtime-validation"
        metadata["bundle"] = verify_bundle(bundle)
        metadata["notices"] = collect_notices(bundle)
        shutil.copy2(ROOT / "docs/DISTRIBUICAO_WINDOWS.md", bundle / "LEIA-ME-WINDOWS.md")
        (bundle / "LEIA-ME.txt").write_text(
            f"ESCRITURA INTEGRADA {version} — WINDOWS x64\n\n"
            "Extraia TODO o ZIP e abra EscrituraIntegrada.exe com duplo clique.\n"
            "Mantenha a pasta _internal ao lado do executável. Não é preciso instalar Python, Node.js ou serviço.\n"
            "Fechar a janela mantém o aplicativo na área de notificações. Use Sair no menu do ícone para encerrar.\n"
            "Configurações permite escolher a pasta de dados e iniciar minimizado.\n"
            "Dados, configurações e registros ficam no perfil local do usuário, fora desta pasta portátil.\n"
            "O menu e a janela de administração oferecem Iniciar, Parar, Reiniciar e acesso aos registros.\n\n"
            "Consulte LEIA-ME-WINDOWS.md e THIRD_PARTY_NOTICES.txt.\n", encoding="utf-8")
        metadata["stage"] = "archive"
        archive_base = artifacts / f"EscrituraIntegrada-{version}-windows-x64"
        archive = Path(shutil.make_archive(str(archive_base), "zip", bundle.parent, bundle.name))
        digest = sha256(archive)
        archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        metadata.update(archive=archive.name, bytes=archive.stat().st_size, sha256=digest)
        if args.smoke:
            metadata.update(stage="packaged-smoke", smoke_executed=True)
            result = artifacts / "windows-smoke.json"
            completed = subprocess.run([sys.executable, str(ROOT / "scripts/smoke_windows.py"),
                                        "--archive", str(archive), "--result", str(result),
                                        "--expected-version", version], cwd=ROOT, timeout=240)
            smoke = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else {}
            metadata.update(smoke_ok=bool(smoke.get("ok")), smoke_report=result.name)
            if completed.returncode or not smoke.get("ok"):
                raise RuntimeError(smoke.get("detail") or "O executável não aprovou o smoke gráfico supervisionado.")
        metadata.update(ok=True, stage="complete")
        print(f"Pacote Windows x64 criado: {archive}")
        return 0
    except Exception as exc:
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        print(f"Falha na etapa {metadata['stage']}: {metadata['error']}", file=sys.stderr)
        return 1
    finally:
        metadata["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (artifacts / "windows-build.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
