"""Verifica o EXE extraído do ZIP portátil e supervisiona toda sua árvore.

Nenhum servidor Python externo é iniciado pelo teste. Saúde, autenticação de
demonstração e DOM são exercitados pelo próprio aplicativo empacotado.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import time
import zipfile

try:
    from .windows_job import WindowsJobProcess
except ImportError:
    from windows_job import WindowsJobProcess


def load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def extract_bundle(archive: Path, directory: Path) -> Path:
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            name = PurePosixPath(member.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] != "EscrituraIntegrada":
                raise ValueError(f"Caminho inválido no pacote: {member.filename}")
        source.extractall(directory)
    executable = directory / "EscrituraIntegrada/EscrituraIntegrada.exe"
    if not executable.is_file():
        raise ValueError("O ZIP não contém a entrada EscrituraIntegrada.exe.")
    return executable


def run_smoke(archive: Path, result: Path, expected_version: str, timeout: float = 150, *, installed_executable: Path | None = None, existing_profile: Path | None = None) -> dict:
    result.parent.mkdir(parents=True, exist_ok=True)
    raw = result.with_name("windows-smoke-app.json")
    screenshot = result.with_suffix(".png")
    for stale in (raw, raw.with_suffix(".png"), result, screenshot):
        stale.unlink(missing_ok=True)
    started = time.monotonic()
    report = {"schema_version": 2, "ok": False, "status": "failed", "version": expected_version,
              "archive": archive.name, "started_at_utc": datetime.now(timezone.utc).isoformat()}
    supervision = {"job_object": True, "started_suspended": True, "root_exit_code": None,
                   "timed_out": False, "forced_cleanup": False, "remaining_processes": None}
    failures = []
    with tempfile.TemporaryDirectory(prefix="escritura-windows-smoke-", ignore_cleanup_errors=True) as temporary:
        temporary = Path(temporary)
        profile = existing_profile or (temporary / "Perfil de teste — isolado")
        profile.mkdir(parents=True, exist_ok=True)
        cwd = temporary / "Diretório de trabalho vazio"
        cwd.mkdir()
        try:
            executable = installed_executable or extract_bundle(archive, temporary / "Aplicativo portátil")
            report["installation_test"] = bool(installed_executable)
            environment = dict(os.environ)
            for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH",
                        "QTWEBENGINEPROCESS_PATH", "QTWEBENGINE_RESOURCES_PATH", "QTWEBENGINE_LOCALES_PATH"):
                environment.pop(key, None)
            environment.update({
                "ESCRITURA_DESKTOP_SMOKE_RESULT": str(raw),
                "ESCRITURA_DESKTOP_SMOKE_PROFILE": str(profile),
                "ESCRITURA_DESKTOP_SMOKE_TIMEOUT": str(max(30, timeout - 25)),
                "ESCRITURA_DATA_DIR": str(profile / "data"),
                "ESCRITURA_DEMO": "1",
            })
            # O runner não precisa de uma GPU física. O sandbox do Chromium permanece ativo.
            flags = environment.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
            if "--disable-gpu" not in flags:
                environment["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --disable-gpu").strip()
            with WindowsJobProcess() as process:
                process.start(executable, environment=environment, cwd=cwd)
                supervision["pid"] = process.pid
                deadline = time.monotonic() + timeout
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.2)
                exit_code = process.poll()
                supervision["root_exit_code"] = exit_code
                if exit_code is None:
                    supervision["timed_out"] = True
                    failures.append("O executável excedeu o tempo de abertura/encerramento.")
                elif exit_code != 0:
                    failures.append(f"O executável terminou com código 0x{exit_code:08X}.")
                grace = time.monotonic() + 8
                while process.accounting()["active_processes"] and time.monotonic() < grace and exit_code is not None:
                    time.sleep(0.1)
                accounting = process.accounting()
                supervision.update(accounting)
                if accounting["active_processes"]:
                    supervision["forced_cleanup"] = True
                    failures.append("Foi necessário encerrar processos remanescentes do aplicativo.")
                    process.terminate()
                    cleanup_deadline = time.monotonic() + 8
                    while process.accounting()["active_processes"] and time.monotonic() < cleanup_deadline:
                        time.sleep(0.1)
                supervision["remaining_processes"] = process.accounting()["active_processes"]
                if supervision["remaining_processes"]:
                    failures.append("A contagem do job não chegou a zero antes de fechar seus handles.")
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            app_report = load_report(raw)
            if raw.with_suffix(".png").is_file():
                shutil.copy2(raw.with_suffix(".png"), screenshot)
            log_files = sorted((profile / "logs").glob("*.log")) if (profile / "logs").is_dir() else []
            if log_files:
                log_text = "\n\n".join(f"=== {path.name} ===\n{path.read_text(encoding='utf-8', errors='replace')}" for path in log_files)
                result.with_name("windows-smoke-logs.log").write_text(log_text, encoding="utf-8")
            if not app_report:
                failures.append("O aplicativo não produziu um relatório de inicialização.")
            else:
                if not app_report.get("ok"):
                    failures.append(app_report.get("detail") or "O teste interno do aplicativo falhou.")
                if not app_report.get("packaged"):
                    failures.append("O processo testado não se identificou como binário empacotado.")
                if app_report.get("version") != expected_version:
                    failures.append("A versão do binário diverge de VERSION.")
                if not app_report.get("shutdown_complete"):
                    failures.append("O aplicativo não confirmou o encerramento do motor local.")
            if not screenshot.is_file() or screenshot.stat().st_size < 1000:
                failures.append("A captura da janela renderizada não foi produzida.")
            report.update(app_report)
    report.update({
        "schema_version": 2, "ok": not failures,
        "status": "passed" if not failures else "failed",
        "detail": "Binário portátil abriu, renderizou a área de trabalho e encerrou sem processos remanescentes." if not failures else " ".join(failures),
        "failures": failures, "supervisor": supervision,
        "duration_seconds": round(time.monotonic() - started, 3),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "screenshot": screenshot.name if screenshot.is_file() else None,
        "raw_report": raw.name,
    })
    result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--timeout", type=float, default=150)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("O smoke do executável exige Windows; não usa emulação nem a API de desenvolvimento.")
    result = run_smoke(args.archive.resolve(), args.result.resolve(), args.expected_version, args.timeout)
    print(json.dumps({"ok": result["ok"], "detail": result["detail"], "result": str(args.result)}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
