# -*- mode: python ; coding: utf-8 -*-
"""Pacote Windows portátil com uma entrada gráfica e runtime Qt compartilhado."""
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

root = Path(SPECPATH)
frontend = root / "frontend" / "dist"
icon = root / "app" / "assets" / "app.ico"
if not (frontend / "index.html").is_file():
    raise SystemExit("Compile a interface: cd frontend && npm ci && npm run build")
if not icon.is_file():
    raise SystemExit("Ícone ausente: app/assets/app.ico")

datas = [
    (str(frontend), "frontend/dist"),
    (str(root / "app" / "assets"), "app/assets"),
    (str(root / "VERSION"), "."),
    (str(root / "docs" / "DISTRIBUICAO_WINDOWS.md"), "docs"),
]
for package in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
    try:
        datas += copy_metadata(package)
    except PackageNotFoundError:
        pass

datas += collect_data_files('reportlab', includes=['fonts/*'])
a = Analysis(
    [str(root / "app" / "desktop.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "app.api", "uvicorn.logging", "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "PySide6.QtSvg", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="EscrituraIntegrada", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(icon), version=str(root / "build" / "windows-version.txt"),
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="EscrituraIntegrada")
