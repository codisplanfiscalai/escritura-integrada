"""Instala e atualiza o .pkg no runner macOS e exercita o aplicativo nativo."""
from __future__ import annotations
from contextlib import closing
import argparse,hashlib,json,os,platform,plistlib,shutil,signal,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.maintenance import integrity
from scripts.build_windows import source_revision

def database_hash(path):
    with closing(sqlite3.connect(path)) as conn:return hashlib.sha256('\n'.join(conn.iterdump()).encode()).hexdigest()

def install(package):subprocess.run(['sudo','installer','-pkg',str(package),'-target','/'],check=True,timeout=180)

def main():
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);p.add_argument('--result',type=Path,required=True);p.add_argument('--expected-version',required=True);a=p.parse_args()
    if sys.platform!='darwin':p.error('Exige macOS nativo.')
    app=Path('/Applications/Escritura Integrada.app')
    if app.exists():raise RuntimeError('Use um runner descartável sem instalação existente; não substituir uma instalação real.')
    report={'ok':False,'version':a.expected_version,'source_sha':source_revision(),'architecture':platform.machine(),'host_macos':platform.mac_ver()[0],
            'package':a.package.name,'checks':[],'forced_cleanup':False}
    a.result.parent.mkdir(parents=True,exist_ok=True);raw=a.result.with_name(a.result.stem+'-app.json')
    process=None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-macos-') as temporary:
            temp=Path(temporary);profile=temp/'Perfil isolado';profile.mkdir();data=profile/'data'
            # Banco realmente produzido pela versão anterior, antes da migração 2 -> 3.
            old=temp/'anterior';old.mkdir()
            archive=subprocess.check_output(['git','archive','51537872f8598af84d22b4544f75a4001f42f56f','app'],cwd=ROOT)
            import tarfile,io
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(old,filter='data')
            environment=dict(os.environ,PYTHONPATH=str(old),ESCRITURA_DATA_DIR=str(data))
            subprocess.run([sys.executable,'-c','from app.db import Database; from app.business import BusinessCore; import os; c=BusinessCore(Database(os.environ["ESCRITURA_DATA_DIR"]),demo=True); c.setup({"username":"teste","password":"SenhaForte12345"})'],cwd=old,env=environment,check=True)
            before=integrity(data/'escritura.sqlite3');assert before['schema_version']==2
            (profile/'config.ini').write_text('[General]\nstart_minimized=true\n[Personalizado]\npreservar=sim\n')
            original=database_hash(data/'escritura.sqlite3')
            install(a.package);report['checks'].append('Instalação nova via Installer do macOS')
            install(a.package);assert database_hash(data/'escritura.sqlite3')==original
            assert 'preservar=sim' in (profile/'config.ini').read_text()
            report['checks'].append('Reinstalação/atualização do mesmo bundle preservou base, usuários e configurações')
            with (app/'Contents/Info.plist').open('rb') as f:info=plistlib.load(f)
            assert info['EscrituraSemVer']==a.expected_version
            executable=app/'Contents/MacOS/EscrituraIntegrada'
            env=dict(os.environ)
            for key in ['PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QTWEBENGINEPROCESS_PATH','QTWEBENGINE_RESOURCES_PATH','QTWEBENGINE_LOCALES_PATH']:env.pop(key,None)
            env.update(ESCRITURA_DESKTOP_SMOKE_RESULT=str(raw.resolve()),ESCRITURA_DESKTOP_SMOKE_PROFILE=str(profile),ESCRITURA_DATA_DIR=str(data),ESCRITURA_DEMO='1',ESCRITURA_DESKTOP_SMOKE_TIMEOUT='140')
            with (a.result.with_suffix('.log')).open('w') as log:
                process=subprocess.Popen([str(executable)],cwd=temp,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:code=process.wait(timeout=165)
                except subprocess.TimeoutExpired:
                    report['forced_cleanup']=True;os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10);raise RuntimeError('Aplicativo não terminou no prazo.')
            assert code==0,f'Código de saída {code}'
            smoke=json.loads(raw.read_text());report['app']=smoke
            assert smoke.get('ok') and smoke.get('packaged') and smoke.get('shutdown_complete'),smoke.get('detail')
            assert smoke.get('tray_available'),'Barra de menus indisponível.'
            assert smoke.get('version')==a.expected_version
            after=integrity(data/'escritura.sqlite3');assert after['schema_version']==3
            for key in ['companies','users']:assert after[key]>=before[key]
            assert list((data/'backups').glob('antes-schema-3-*.sqlite3'))
            assert 'preservar=sim' in (profile/'config.ini').read_text()
            assert raw.with_suffix('.png').stat().st_size>1000
            shutil.copy2(raw.with_suffix('.png'),a.result.with_suffix('.png'))
            report['checks']+=['Bundle Mach-O nativo abriu API, autenticação e interface Vue','Ícone na barra de menus e controles gráficos disponíveis','Primeira abertura migrou schema 2 para 3 com backup e dados preservados','Encerramento completo do motor local']
            # Não há processo da aplicação nem auxiliar WebEngine remanescente deste bundle.
            running=subprocess.run(['pgrep','-f',str(app)+'/Contents/'],capture_output=True,text=True)
            assert running.returncode==1,'Processos remanescentes: '+running.stdout
            report['remaining_processes']=0
            report.update(ok=True,installed=True,updated=True,minimum_macos='15.0',quarantine_tested=False,
                upgrade_fixture='Reinstalação da nova versão e migração de base real 0.5.0-dev.6; Gatekeeper de download não validado.')
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}';print(report['error'],file=sys.stderr)
    finally:
        a.result.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return 0 if report['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
