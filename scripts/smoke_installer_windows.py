"""Instalador real em perfil temporário; nenhuma desinstalação do usuário é executada."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from contextlib import closing
import sqlite3
import subprocess
import sys
import tempfile
import winreg
from smoke_windows import run_smoke

ROOT=Path(__file__).resolve().parents[1]
KEY=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D596DE8F-DC39-47A6-B39C-41893D9184B5}_is1'


def db_digest(path):
    with closing(sqlite3.connect(path)) as conn:
        return hashlib.sha256('\n'.join(conn.iterdump()).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--installer',type=Path,required=True);parser.add_argument('--helper',type=Path,required=True)
    parser.add_argument('--version',required=True);parser.add_argument('--result',type=Path,required=True);args=parser.parse_args()
    sys.path.insert(0,str(ROOT))
    from app.db import Database
    from app.business import BusinessCore
    from app.maintenance import integrity
    report={'ok':False,'version':args.version,'checks':[],'upgrade_fixture':'Instalação real; versão anterior simulada no registro; migração de base portátil validada separadamente.'}
    try:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY):raise RuntimeError('Já existe instalação neste perfil. Smoke recusado para preservar o usuário.')
        except FileNotFoundError:pass
        with tempfile.TemporaryDirectory(prefix='escritura-install-',ignore_cleanup_errors=True) as tmp:
            root=Path(tmp);install=root/'Aplicativo instalado';profile=root/'Perfil instalado'
            def setup(extra=None,success=True):
                command=[str(args.installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={install}',f'/PROFILEDIR={profile}',f'/LOG={root / "setup.log"}']+(extra or [])
                p=subprocess.run(command,timeout=180)
                if success and p.returncode:raise RuntimeError(f'Instalador retornou {p.returncode}: '+(root/'setup.log').read_text(encoding='utf-8-sig',errors='replace')[-2500:])
                if not success and p.returncode==0:raise RuntimeError('Instalador aceitou atualização que deveria ser bloqueada.')
            setup();exe=install/'EscrituraIntegrada.exe'
            if not exe.is_file():raise RuntimeError('Entrada instalada ausente.')
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
                if winreg.QueryValueEx(key,'DisplayVersion')[0]!=args.version:raise RuntimeError('Versão do registro diverge do pacote.')
            report['checks'].append('Instalação nova real, registro de versão e executável no diretório escolhido')
            core=BusinessCore(Database(profile/'data'),demo=True)
            core.setup({'username':'instalador-teste','password':'Senha-sintetica-123'})
            core.save_group({'name':'Grupo preservado','company_ids':[1],'permissions':[{'company_id':1,'routine':'fiscal.*','action':'read','effect':'allow'}]},'instalador-teste')
            core.create_exercise(1,{'module':'fiscal','year':2029},'instalador-teste')
            config=profile/'config.ini';config.write_text(config.read_text(encoding='utf-8')+'\n[Smoke]\nvalor=preservado\n',encoding='utf-8')
            before=db_digest(profile/'data/escritura.sqlite3')
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_SET_VALUE) as key:winreg.SetValueEx(key,'DisplayVersion',0,winreg.REG_SZ,'0.5.0-dev.6')
            setup()
            if before!=db_digest(profile/'data/escritura.sqlite3'):raise RuntimeError('Atualização alterou dados de negócio.')
            if 'valor=preservado' not in config.read_text(encoding='utf-8'):raise RuntimeError('Configuração anterior não foi preservada.')
            if not list(profile.glob('.escritura-backup-*')):raise RuntimeError('Backup anterior ausente.')
            report['checks'].append('Atualização sobre instalação existente preservou documentos, empresas, usuários, grupos, permissões, exercícios e configurações')
            (profile/'aplicacao.lock').write_text(str(os.getpid())+'\nEscrituraIntegrada\nrunner\n')
            setup(success=False);(profile/'aplicacao.lock').unlink()
            if before!=db_digest(profile/'data/escritura.sqlite3'):raise RuntimeError('Tentativa bloqueada alterou o banco.')
            report['checks'].append('Atualização com aplicação em execução foi bloqueada sem encerrar o processo')
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_SET_VALUE) as key:winreg.SetValueEx(key,'DisplayVersion',0,winreg.REG_SZ,'999.0.0')
            setup(success=False)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_SET_VALUE) as key:winreg.SetValueEx(key,'DisplayVersion',0,winreg.REG_SZ,args.version)
            report['checks'].append('Downgrade recusado antes da alteração dos arquivos')
            # Banco anterior real, criado pelo código publicado da versão 0.5, sem depender de assets temporários.
            old=root/'origem-0.5';old.mkdir()
            import tarfile,io
            source=subprocess.check_output(['git','archive','51537872f8598af84d22b4544f75a4001f42f56f','app'],cwd=ROOT)
            with tarfile.open(fileobj=io.BytesIO(source)) as tar:tar.extractall(old,filter='data')
            portable=root/'Dados portáteis'
            code='from app.business import BusinessCore; from app.db import Database; c=BusinessCore(Database('+repr(str(portable))+'),demo=True); c.setup({"username":"legado","password":"Senha-sintetica-123"})'
            env=dict(os.environ);env['PYTHONPATH']=str(old)
            subprocess.run([sys.executable,'-c',code],cwd=old,env=env,check=True)
            old_counts=integrity(portable/'escritura.sqlite3');source_hash=db_digest(portable/'escritura.sqlite3')
            profile=root/'Perfil migrado';setup([f'/PORTABLEDATA={portable}'])
            new_counts=integrity(profile/'data/escritura.sqlite3')
            if old_counts['schema_version']!=2 or new_counts['schema_version']!=3 or old_counts['companies']!=new_counts['companies'] or old_counts['users']!=new_counts['users']:raise RuntimeError('Migração portátil inconsistente.')
            if db_digest(portable/'escritura.sqlite3')!=source_hash:raise RuntimeError('A origem portátil foi alterada.')
            report['checks'].append('Banco portátil 0.5/schema 2 migrado para schema 3 pela seleção do instalador; origem preservada')
            archive=ROOT/'artifacts'/f'EscrituraIntegrada-{args.version}-windows-x64.zip'
            gui=run_smoke(archive,args.result.with_name('windows-installed-gui.json'),args.version,installed_executable=exe,existing_profile=profile)
            if not gui.get('ok'):raise RuntimeError('Aplicativo instalado não aprovou abertura gráfica e encerramento.')
            report['checks'].append('Executável instalado abriu API, interface e tray e encerrou seus processos')
            report['gui_report']='windows-installed-gui.json'
            subprocess.run([str(install/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True,timeout=120)
            if not (profile/'data/escritura.sqlite3').is_file():raise RuntimeError('Desinstalação removeu dados.')
            report['checks'].append('Desinstalação real preservou a pasta de dados e configurações')
            report['ok']=True
    except Exception as exc:report['error']=str(exc)
    args.result.parent.mkdir(parents=True,exist_ok=True);args.result.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
