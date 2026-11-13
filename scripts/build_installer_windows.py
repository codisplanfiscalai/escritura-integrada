"""Constrói o instalador Inno e valida instalação, atualização e migração portátil."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from build_windows import ROOT,sha256,source_revision,version_resource,maintenance_bundle_args


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    if sys.platform!='win32':parser.error('Construa no Windows x64.')
    version=(ROOT/'VERSION').read_text().strip();artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
    report={'ok':False,'version':version,'source_sha':source_revision(),'started_at':datetime.now(timezone.utc).isoformat()}
    try:
        payload=ROOT/'build/windows-dist/EscrituraIntegrada'
        if not (payload/'EscrituraIntegrada.exe').is_file():raise RuntimeError('Construa primeiro o aplicativo Windows.')
        helperdir=ROOT/'build/maintenance';helperdir.mkdir(parents=True,exist_ok=True)
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--noconsole',
            '--name','EscrituraMaintenance',*maintenance_bundle_args(),'--distpath',str(helperdir),
            '--workpath',str(ROOT/'build/maintenance-work'),'--specpath',str(ROOT/'build'),'app/maintenance.py'],cwd=ROOT,check=True)
        helper=helperdir/'EscrituraMaintenance.exe'
        candidates=[Path(x)/'Inno Setup 6/ISCC.exe' for x in [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')]]
        candidates.extend(Path(x)/'Inno Setup 7/ISCC.exe' for x in [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')])
        compiler=next((p for p in candidates if p.is_file()),None)
        if compiler is None:
            found=shutil.which('iscc');compiler=Path(found) if found else None
        if compiler is None:raise RuntimeError('Compilador Inno Setup ausente no runner.')
        name=f'EscrituraIntegrada-{version}-windows-x64-setup'
        values={'VERSION':version,'NUMERIC':'.'.join(map(str,version_resource(version)['numeric'])),
            'PAYLOAD':str(payload),'HELPER':str(helper),'OUTPUT':str(artifacts),'FILENAME':name,'ICON':str(ROOT/'app/assets/app.ico')}
        script=(ROOT/'packaging/windows/setup.iss').read_text(encoding='utf-8')
        for key,value in values.items():script=script.replace('@@'+key+'@@',value)
        spec=ROOT/'build/setup.iss';spec.write_text(script,encoding='utf-8-sig')
        subprocess.run([str(compiler),str(spec)],check=True,cwd=ROOT)
        installer=artifacts/(name+'.exe')
        report.update(installer=installer.name,size=installer.stat().st_size,sha256=sha256(installer),compiler_sha256=sha256(compiler),
            app_id='D596DE8F-DC39-47A6-B39C-41893D9184B5',per_user=True,requires_windows_service=False,data_preserved_on_uninstall=True,
            signing='unsigned: certificado Authenticode não configurado')
        if args.smoke:
            subprocess.run([sys.executable,str(ROOT/'scripts/smoke_installer_windows.py'),'--installer',str(installer),
                '--helper',str(helper),'--version',version,'--result',str(artifacts/'windows-installer-smoke.json')],check=True,cwd=ROOT,timeout=600)
            smoke=json.loads((artifacts/'windows-installer-smoke.json').read_text(encoding='utf-8'))
            if not smoke.get('ok'):raise RuntimeError('Smoke do instalador não aprovado.')
            report['smoke']=smoke
        report['ok']=True
        return 0
    except Exception as exc:
        report['error']=str(exc);print(str(exc),file=sys.stderr);return 1
    finally:
        (artifacts/'windows-installer-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':raise SystemExit(main())
