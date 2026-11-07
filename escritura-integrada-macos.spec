# -*- mode: python ; coding: utf-8 -*-
"""Bundle nativo macOS; o mesmo núcleo e interface utilizados no Windows/Docker."""
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata, collect_data_files
import platform
root=Path(SPECPATH)
version=(root/'VERSION').read_text().strip()
datas=[(str(root/'frontend/dist'),'frontend/dist'),(str(root/'app/assets'),'app/assets'),
       (str(root/'VERSION'),'.'),(str(root/'docs/DISTRIBUICAO_DESKTOP.md'),'docs')]
for package in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6'):datas+=copy_metadata(package)
datas += collect_data_files('reportlab', includes=['fonts/*'])
for package in ('BrazilFiscalReport','fpdf2','fonttools','python-barcode','phonenumbers','qrcode','lxml'):datas+=copy_metadata(package)
datas += collect_data_files('brazilfiscalreport')
datas += collect_data_files('fpdf')
a=Analysis([str(root/'app/desktop.py')],pathex=[str(root)],binaries=[],datas=datas,
    hiddenimports=['app.api','uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl',
      'uvicorn.protocols.websockets.auto','uvicorn.lifespan.on','PySide6.QtSvg','PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets'],
    excludes=['PyQt5','PyQt6','PySide2','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='EscrituraIntegrada',console=False,strip=False,upx=False,
    target_arch=platform.machine(),codesign_identity=None)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='EscrituraIntegrada')
app=BUNDLE(coll,name='Escritura Integrada.app',icon=str(root/'build/app.icns'),
    bundle_identifier='br.com.codisplan.escritura-integrada',
    info_plist={'CFBundleName':'Escritura Integrada','CFBundleDisplayName':'Escritura Integrada',
        'CFBundleShortVersionString':version.split('-')[0].split('+')[0],
        'CFBundleVersion':version.split('-')[0].split('+')[0],'EscrituraSemVer':version,'LSMinimumSystemVersion':'15.0',
        'LSUIElement':True,'NSHighResolutionCapable':True,'NSRequiresAquaSystemAppearance':False})
