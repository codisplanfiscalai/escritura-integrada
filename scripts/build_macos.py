"""Constrói app/pkg nativos, verifica arquitetura e testa instalação + interface no Mac."""
from __future__ import annotations
import argparse,json,os,platform,plistlib,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from build_windows import ROOT,run,source_revision,sha256,frontend_assets,collect_notices,version_resource

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    if sys.platform!='darwin':parser.error('Execute no macOS nativo. Não há emulação nem cross-build.')
    arch=platform.machine();label={'arm64':'arm64','x86_64':'x64'}.get(arch)
    if not label:parser.error('Arquitetura não suportada.')
    artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
    version=(ROOT/'VERSION').read_text().strip()
    report={'ok':False,'version':version,'source_sha':source_revision(),'architecture':arch,'minimum_macos':'15.0',
      'host_macos':platform.mac_ver()[0],'python':platform.python_version(),'signature':'ad-hoc','notarized':False,
      'built_at_utc':datetime.now(timezone.utc).isoformat()}
    try:
        frontend_assets(ROOT/'frontend/dist');build=ROOT/'build';build.mkdir(exist_ok=True)
        iconset=build/'app.iconset';iconset.mkdir(exist_ok=True)
        for size in [16,32,128,256,512]:
            for multiplier in [1,2]:
                name=f'icon_{size}x{size}'+('@2x' if multiplier==2 else '')+'.png'
                run(['sips','-z',size*multiplier,size*multiplier,ROOT/'app/assets/app.png','--out',iconset/name])
        run(['iconutil','-c','icns',iconset,'-o',build/'app.icns'])
        run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',build/'macos-dist','--workpath',build/'macos-work',ROOT/'escritura-integrada-macos.spec'])
        app=build/'macos-dist/Escritura Integrada.app';executable=app/'Contents/MacOS/EscrituraIntegrada'
        architectures=subprocess.check_output(['lipo','-archs',executable],text=True).split()
        if architectures!=[arch]:raise RuntimeError('Arquitetura Mach-O não corresponde à construção nativa: '+str(architectures))
        with (app/'Contents/Info.plist').open('rb') as f:info=plistlib.load(f)
        if info['EscrituraSemVer']!=version:raise RuntimeError('Versão do bundle divergente.')
        resources=app/'Contents/Resources'
        frontend_assets(resources/'frontend/dist')
        notice=build/'macos-notices';shutil.rmtree(notice,ignore_errors=True)
        shutil.copytree(ROOT/'frontend/dist/third-party',notice/'_internal/frontend/dist/third-party')
        report['notices']=collect_notices(notice)
        shutil.copytree(notice/'licenses',resources/'licenses',dirs_exist_ok=True)
        shutil.copy2(notice/'THIRD_PARTY_NOTICES.txt',resources/'THIRD_PARTY_NOTICES.txt')
        shutil.copy2(ROOT/'docs/DISTRIBUICAO_DESKTOP.md',resources/'LEIA-ME.md')
        run(['codesign','--force','--deep','--sign','-',app])
        run(['codesign','--verify','--deep','--strict','--verbose=2',app])
        payload=build/'macos-payload';shutil.rmtree(payload,ignore_errors=True);payload.mkdir()
        shutil.copytree(app,payload/app.name,symlinks=True)
        scripts=build/'macos-installer-scripts';shutil.rmtree(scripts,ignore_errors=True);scripts.mkdir()
        run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--name','EscrituraMaintenance',
            '--distpath',scripts,'--workpath',build/'macos-maintenance-work','--specpath',build,ROOT/'app/maintenance.py'])
        run(['codesign','--force','--sign','-',scripts/'EscrituraMaintenance'])
        pre=(ROOT/'packaging/macos/preinstall').read_text().replace('@@ARCH@@',arch).replace('@@VERSION@@',version)
        (scripts/'preinstall').write_text(pre);(scripts/'preinstall').chmod(0o755)
        component=build/'macos-components.plist'
        run(['pkgbuild','--analyze','--root',payload,component])
        with component.open('rb') as f:components=plistlib.load(f)
        for c in components:c.update(BundleIsRelocatable=False,BundleIsVersionChecked=False,BundleOverwriteAction='upgrade')
        with component.open('wb') as f:plistlib.dump(components,f)
        package=artifacts/f'EscrituraIntegrada-{version}-macos-{label}.pkg'
        numeric='.'.join(map(str,version_resource(version)['numeric']))
        run(['pkgbuild','--root',payload,'--install-location','/Applications','--identifier','br.com.codisplan.escritura-integrada',
             '--version',numeric,'--component-plist',component,'--scripts',scripts,package])
        report.update(package=package.name,sha256=sha256(package),bytes=package.stat().st_size,bundle_architectures=architectures)
        package.with_suffix('.pkg.sha256').write_text(f"{report['sha256']}  {package.name}\n")
        if args.smoke:
            result=artifacts/f'macos-{label}-smoke.json'
            run([sys.executable,ROOT/'scripts/smoke_macos.py','--package',package,'--result',result,'--expected-version',version],timeout=600)
            smoke=json.loads(result.read_text());report['smoke_ok']=smoke.get('ok')
            if not report['smoke_ok']:raise RuntimeError('O pacote não aprovou instalação e abertura gráfica.')
        report['ok']=True;return 0
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}';print(report['error'],file=sys.stderr);return 1
    finally:(artifacts/f'macos-{label}-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':raise SystemExit(main())
