#!/usr/bin/env python3
"""Real isolated app: keep ./data/app, with a deliberately older named backup.

No production access. Only UUID-named fixtures are created and removed.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from image_tools import ROOT, read_json, write_json


def smoke_existing_bind(manifest):
    project = "existing-bind-" + uuid.uuid4().hex[:12]
    backup = project + "_app-data"
    image = manifest["images"]["app"]["reference"]
    checks = []
    with tempfile.TemporaryDirectory(prefix="escritura-existing-bind-") as temporary:
        root = Path(temporary)
        base = json.loads((ROOT / "deploy/develop/compose.yaml").read_text())
        base["services"]["app"]["ports"] = ["127.0.0.1::8000/tcp"]
        current = copy.deepcopy(base)
        current["services"]["app"]["volumes"] = ["./data/app:/data"]  # The user's existing syntax.
        current["volumes"] = {name + "-data": {} for name in ("redis", "postgres", "mysql", "minio")}
        for name in current["volumes"]:
            service = name.removesuffix("-data")
            current["services"][service]["volumes"] = [name + ":" + base["services"][service]["volumes"][0]["target"]]
        (root / "compose.yaml").write_text(json.dumps(base))
        (root / "compose.current.yaml").write_text(json.dumps(current))
        (root / "compose.existing-bind.yaml").write_bytes((ROOT / "deploy/compose.existing-bind.yaml").read_bytes())
        environment = {**os.environ, "ESCRITURA_IMAGE": image, "COMPOSE_PROJECT_NAME": project,
                       "ESCRITURA_APP_DATA_BIND": ""}
        environment.pop('ESCRITURA_APP_DATA_BIND')
        (root / '.env').write_text('COMPOSE_PROJECT_NAME=' + project + '\nESCRITURA_APP_DATA_BIND=\n')
        (root / '.env').chmod(0o600)

        def run(command, expected=0):
            result = subprocess.run([str(x) for x in command], cwd=root, env=environment, capture_output=True, text=True, timeout=300)
            if bool(result.returncode) != bool(expected):
                if expected == 0 and command[0] == "docker" and "up" in command:
                    diagnostic = subprocess.run(["docker", "logs", "--tail", "30", project + "-app-1"], capture_output=True, text=True)
                    print(diagnostic.stderr, flush=True)  # Only this synthetic fixture, never a user's container.
                raise RuntimeError("Existing-bind smoke failed in " + str(command[0]))
            if expected and command[0] == sys.executable and 'check-app' in command and not result.stdout.strip():
                raise RuntimeError('Synthetic preflight did not produce a report: ' + result.stderr.strip())
            return result.stdout.strip()

        def compose(current_mode=False):
            command = ["docker", "compose", "-p", project, "-f", root / ("compose.current.yaml" if current_mode else "compose.yaml")]
            if not current_mode:
                command += ["-f", root / "compose.existing-bind.yaml"]
            return command

        def helper(code, backup_mode=None):
            command = ["docker", "run", "--rm", "--pull", "never", "--no-healthcheck", "--network", "none", "--read-only",
                       "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "FOWNER", "--cap-add", "DAC_OVERRIDE",
                       "--tmpfs", "/data:rw,noexec,nosuid,size=1m", "--entrypoint", "python",
                       "--mount", "type=bind,src=" + str(root) + ",dst=/test",
                       "--mount", "type=bind,src=" + str(ROOT / "scripts/deploy_storage.py") + ",dst=/tool/storage.py,readonly"]
            if backup_mode:
                command += ["--mount", "type=volume,src=" + backup + ",dst=/backup,volume-nocopy" + (",readonly" if backup_mode == "ro" else "")]
            return run([*command, image, "-B", "-c", code])

        def record(value):
            checks.append(value)
            print("Existing bind: " + value, flush=True)

        backup_snapshot = "import sys,json,hashlib; sys.path.insert(0,'/tool'); from storage import inventory; print(hashlib.sha256(json.dumps(inventory(__import__('pathlib').Path('/backup')),sort_keys=True).encode()).hexdigest())"
        snapshot = """import sqlite3,json,hashlib; from pathlib import Path
c=sqlite3.connect('/data/escritura.sqlite3')
assert c.execute('pragma quick_check').fetchone()[0]=='ok'
out={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('users','companies','documents','audit')}
out['probe']=c.execute('SELECT value FROM storage_probe').fetchone()[0]
assert out['users']==1 and out['companies']==1 and out['documents']==1 and out['probe']==84
assert c.execute('SELECT name FROM companies').fetchone()[0]=='Empresa Bind Ficticia'
assert c.execute('SELECT number,total_cents FROM documents').fetchall()==[('123',12345)]
c.close()
p=Path('/data/documents/current.xml'); out['xml']=hashlib.sha256(p.read_bytes()).hexdigest()
out['uid']=p.stat().st_uid; out['mode']=p.stat().st_mode&511
assert out['uid']==10001
assert out['mode']==0o640
print(json.dumps(out,sort_keys=True))
"""
        try:
            run(["docker", "volume", "create", "--label", "com.docker.compose.project=" + project,
                 "--label", "com.docker.compose.volume=app-data", backup])
            helper("""from pathlib import Path; import sqlite3,os
from app.db import Database
Database('/backup')
p=Path('/backup/escritura.sqlite3'); c=sqlite3.connect(p)
c.execute('CREATE TABLE storage_probe(value INTEGER)'); c.execute('INSERT INTO storage_probe VALUES(42)'); c.commit(); c.close()
for item in [Path('/backup'),*Path('/backup').rglob('*')]: os.chown(item,10001,10001)
os.chmod('/backup',0o700)
""", "rw")
            original_backup = helper(backup_snapshot, "ro")
            # Reproduce the copy the user has ALREADY made, only in this fixture.
            helper("""import sys; from pathlib import Path
sys.path.insert(0,'/tool'); from storage import copy_tree
Path('/test/data').mkdir(mode=0o700)
copy_tree(Path('/backup'),Path('/test/data/app'))
""", "ro")
            run([*compose(True), "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "180", "app"])
            run([*compose(True), "exec", "-T", "app", "python", "-c", """import json,secrets,sqlite3,urllib.request; from pathlib import Path
req=urllib.request.Request('http://127.0.0.1:8000/api/setup',data=json.dumps({'username':'synthetic-bind-user','password':secrets.token_urlsafe(32)}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as response: assert json.load(response)['authenticated']
c=sqlite3.connect('/data/escritura.sqlite3')
company=c.execute("INSERT INTO companies(code,name,tax_id,regime,created_at,updated_at) VALUES('FIXTURE','Empresa Bind Ficticia','00000000000191','normal','2026-01-01','2026-01-01')").lastrowid
c.execute("INSERT INTO documents(company_id,direction,number,series,model,issue_date,posting_date,period,partner_name,partner_tax_id,key,cfop,total_cents,taxes_json,items_json,source_json,source_hash,business_key,payload_hash,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(company,'incoming','123','1','55','2026-11-01','2026-11-01','2026-11','Fornecedor Ficticio','00000000000191','synthetic-bind-document','1102',12345,'{}','[]','{}','a'*64,'synthetic-bind','b'*64,'pending','2026-11-01'))
c.execute("INSERT INTO audit(company_id,actor,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?)",(company,'synthetic-bind-user','fixture','document','1','{}','2026-11-01'))
c.execute('UPDATE storage_probe SET value=84'); c.commit(); c.close()
p=Path('/data/documents'); p.mkdir(); (p/'current.xml').write_bytes(b'<NFe>synthetic current bind</NFe>'); (p/'current.xml').chmod(0o640)
"""])
            before = json.loads(run([*compose(True), "exec", "-T", "app", "python", "-c", snapshot]))
            actual_id = run([*compose(True), "ps", "-q", "app"])
            installed_image = run(["docker", "inspect", "--format", "{{.Image}}", actual_id])
            actual_mounts = json.loads(run(["docker", "inspect", "--format", "{{json .Mounts}}", actual_id]))
            before_mount = next(m for m in actual_mounts if m["Destination"] == "/data")
            assert before_mount["Type"] == "bind" and before_mount["Source"] == str(root / "data/app")
            environment["ESCRITURA_IMAGE"] = installed_image  # Freeze the actual running image for this check only.
            record("current ./data/app contains user/company and newer value 84; retained named backup is older (42)")
            run([*compose(True), "stop", "app"])
            tree_snapshot = "import sys,json,hashlib; from pathlib import Path; sys.path.insert(0,'/tool'); from storage import inventory; print(hashlib.sha256(json.dumps(inventory(Path('/test/data/app')),sort_keys=True).encode()).hexdigest())"
            original_bind = helper(tree_snapshot)
            for action in ("init", "plan"):
                command = [sys.executable, ROOT / "scripts/deploy_storage.py", action, "--directory", root, "--project", project, "--helper-image", image]
                if action == "plan":
                    command += ["--compose-file", root / "compose.current.yaml", "--output", root / "storage-plan.json"]
                run(command, expected=1)
            assert not (root / "storage-plan.json").exists()
            assert helper(tree_snapshot) == original_bind
            assert helper(backup_snapshot, "ro") == original_backup
            record("init/named-volume plan refuse existing bind without changing either copy or producing a migration plan")
            # Reproduce an upgraded Compose + blank delivered .env. Plain Compose refuses to guess.
            run(['docker','compose','-p',project,'-f',root/'compose.yaml','config','--format','json'],expected=1)
            prepare = [sys.executable, ROOT/'scripts/deploy_storage.py','prepare-app','--directory',root,
                       '--project',project,'--helper-image',installed_image]
            selected = json.loads(run(prepare))
            assert selected['source']=='./data/app' and selected['configuration_recorded']
            assert not selected['data_moved'] and not selected['containers_started']
            default = json.loads(run(["docker", "compose", "-p", project, "-f", root / "compose.yaml", "config", "--format", "json"]))
            compat = json.loads(run([*compose(), "config", "--format", "json"]))
            assert default['services']['app']['volumes'][0]['source'] == before_mount['Source']
            record('blank delivered dotenv is resolved automatically to existing ./data/app, with no new namespace, copy, image pull or start')
            assert compat['services']['app']['volumes'][0]['source'] == before_mount['Source']
            assert not compat['services']['app']['volumes'][0].get('bind',{}).get('create_host_path',False)
            assert compat['services']['app']['pull_policy'] == 'always'
            # Keep all other existing service settings: apply the override over the CURRENT Compose.
            kept = json.loads(run([*compose(True), "-f", root / "compose.existing-bind.yaml", "--profile", "*", "config", "--format", "json"]))
            current_config = json.loads(run([*compose(True), "--profile", "*", "config", "--format", "json"]))
            for name in ('redis','postgres','mysql','minio'):
                assert kept['services'][name] == current_config['services'][name]
            for unused in range(2):
                if unused:
                    environment["ESCRITURA_APP_DATA_BIND"] = "./data/app"
                    explicit_env = json.loads(run(["docker", "compose", "-p", project, "-f", root / "compose.yaml", "config", "--format", "json"]))
                    assert explicit_env['services']['app']['volumes'][0]['source'] == before_mount['Source']
                active_compose = compose() if not unused else ['docker','compose','-p',project,'-f',root/'compose.yaml']
                run([*active_compose, "up", "-d", "--pull", "never", "--force-recreate", "--wait", "--wait-timeout", "180", "app"])
                assert json.loads(run([*compose(), "exec", "-T", "app", "python", "-c", snapshot])) == before
                container = run([*compose(), "ps", "-q", "app"])
                assert run(["docker", "inspect", "--format", "{{.Image}}", container]) == installed_image
                mounts = json.loads(run(["docker", "inspect", "--format", "{{json .Mounts}}", container]))
                assert next(m for m in mounts if m['Destination']=='/data')['Source'] == before_mount['Source']
            helper("from pathlib import Path; assert not Path('/test/data/" + project + "').exists()")
            assert helper(backup_snapshot, "ro") == original_backup
            helper("import sqlite3; c=sqlite3.connect('file:/backup/escritura.sqlite3?mode=ro&immutable=1',uri=True); assert c.execute('SELECT value FROM storage_probe').fetchone()[0]==42; c.close()", "ro")
            record("explicit override preserves source, UID, user/company/audit counts and XML through two recreations; no namespace folder or fallback to backup")
            # Reproduce the confirmed permissions incident ONLY in this synthetic bind.
            run(["docker", "stop", container])
            environment.pop('ESCRITURA_APP_DATA_BIND', None)
            (root/'.env').write_text('COMPOSE_PROJECT_NAME='+project+'\nESCRITURA_APP_DATA_BIND=\n')
            helper("from pathlib import Path; p=Path('/test/data/"+project+"/app'); p.mkdir(parents=True); (p/'escritura.sqlite3').write_bytes(b'synthetic ambiguity sentinel')")
            env_ambiguous=(root/'.env').read_bytes()
            run(prepare, expected=1)
            assert (root/'.env').read_bytes()==env_ambiguous
            assert json.loads(run([*compose(True),'config','--format','json']))['services']['app']['volumes'][0]['source']==before_mount['Source']
            environment['ESCRITURA_APP_DATA_BIND']='./data/app'
            assert json.loads(run(prepare))['source']=='./data/app'
            helper("from pathlib import Path; import shutil; p=Path('/test/data/"+project+"'); assert (p/'app/escritura.sqlite3').read_bytes()==b'synthetic ambiguity sentinel'; shutil.rmtree(p)")
            record('two paths refuse without changing dotenv or either database; explicit ./data/app wins without merging or copying data')
            helper("""import os; from pathlib import Path
p=Path('/test/data/app'); os.chown(p,0,0); p.chmod(0o775)
db=p/'escritura.sqlite3'; os.chown(db,0,0); db.chmod(0o600)
b=p/'backups'; b.mkdir(exist_ok=True); os.chown(b,0,0); b.chmod(0o700)
f=b/'synthetic-backup.sqlite3'; f.write_bytes(b'synthetic retained backup'); os.chown(f,0,0); f.chmod(0o600)
for service in ('redis','postgres','mysql','minio'):
    q=Path('/test/data')/('sentinel-'+service); q.mkdir(mode=0o700); os.chown(q,20002,20002)
""")
            preflight = [sys.executable, ROOT / "scripts/deploy_storage.py", "check-app", "--project", project,
                         "--compose-file", root / "compose.current.yaml"]
            incident_tree = helper(tree_snapshot)
            blocked = json.loads(run([*preflight, "--output", root / "preflight-blocked.json"], expected=1))
            assert helper(tree_snapshot) == incident_tree
            env_before=(root/'.env').read_bytes()
            run(prepare, expected=1)
            assert (root/'.env').read_bytes()==env_before
            assert blocked['status'] == 'blocked' and blocked['identity']['uid'] == 10001 and blocked['identity']['gid'] == 10001
            assert blocked['checks']['root']['metadata'] == {'uid':0,'gid':0,'mode':'0o775'}
            assert not blocked['checks']['root']['write']
            assert blocked['checks']['database']['metadata'] == {'uid':0,'gid':0,'mode':'0o600'}
            assert not blocked['checks']['database']['read'] and not blocked['checks']['database']['write']
            assert not blocked['checks']['backups']['read'] and not blocked['recovery_complete']
            run(["docker", "start", container])  # Started alone must never count as recovery.
            until = time.monotonic() + 25
            failure_log = ''
            while time.monotonic() < until:
                result = subprocess.run(['docker','logs',container],capture_output=True,text=True)
                failure_log = result.stdout + result.stderr
                if 'sqlite3.OperationalError' in failure_log:
                    break
                time.sleep(1)
            assert 'sqlite3.OperationalError' in failure_log and 'maintenance' in failure_log
            state = json.loads(run(['docker','inspect','--format','{{json .State}}',container]))
            assert state.get('Health',{}).get('Status') != 'healthy'
            run(["docker", "stop", container])
            record("actual image USER 10001:10001 rejects root:root 0775 directory and 0600 SQLite; Started reproduces maintenance startup failure, never healthy")
            # Deliberate fixture repair: ownership ONLY under this verified app Source; no chmod.
            helper("""import os; from pathlib import Path
p=Path('/test/data/app')
for item in [p,*p.rglob('*')]: os.chown(item,10001,10001,follow_symlinks=False)
for service in ('redis','postgres','mysql','minio'):
    assert (Path('/test/data')/('sentinel-'+service)).stat().st_uid==20002
assert (p/'escritura.sqlite3').stat().st_mode&511==0o600
assert p.stat().st_mode&511==0o775
assert (p/'backups/synthetic-backup.sqlite3').read_bytes()==b'synthetic retained backup'
""")
            passed = json.loads(run(preflight))
            assert passed['status']=='permissions_passed' and not passed['health_checked'] and not passed['recovery_complete']
            stopped = json.loads(run([*preflight,'--require-health'], expected=1))
            assert stopped['status']=='runtime_not_ready' and not stopped['runtime_healthy']
            run(['docker','start',container])
            healthy = json.loads(run([*preflight,'--require-health','--wait-health-seconds','90','--output',root/'preflight-healthy.json']))
            assert healthy['status']=='runtime_healthy' and healthy['health_endpoint_ok'] and healthy['runtime_healthy']
            assert healthy['interface_validation']=='pending' and not healthy['recovery_complete']
            assert run(['docker','inspect','--format','{{.Image}}',container])==installed_image
            assert run([*compose(True),'ps','-q','app'])==container
            assert json.loads(run([*compose(True),'exec','-T','app','python','-c',snapshot]))==before
            assert helper(backup_snapshot,'ro')==original_backup
            record("app-only ownership repair preserves modes, same container/image, current data and old volume; stopped preflight stays distinct from verified healthy API; interface remains pending")
            # A missing flat bind must fail instead of creating a new empty app directory.
            missing = root / "missing"
            missing.mkdir()
            (missing / "compose.yaml").write_text(json.dumps(base))
            missing_cmd = ["docker", "compose", "-p", project + "-missing", "-f", missing / "compose.yaml", "-f", root / "compose.existing-bind.yaml"]
            run([*missing_cmd, "up", "-d", "--pull", "never", "app"], expected=1)
            assert not (missing / "data").exists()
            run([*missing_cmd, "down"])
            record("missing ./data/app is refused without creating an empty directory; backup volume remains byte/metadata identical")
            return {"status": "passed", "checks": checks, "snapshot": before, "production_access": False,
                    "permission_incident": {"blocked": blocked, "after_app_only_ownership_repair": healthy}}
        finally:
            missing_compose = root / "missing/compose.yaml"
            if missing_compose.exists():
                subprocess.run(["docker", "compose", "-p", project + "-missing", "-f", str(missing_compose), "-f", str(root / "compose.existing-bind.yaml"), "down"], cwd=root, env=environment, capture_output=True, timeout=120)
            subprocess.run([*map(str, compose(True)), "down", "-v", "--remove-orphans"], cwd=root, env=environment, capture_output=True, timeout=120)  # UUID fixture only.
            subprocess.run(["docker", "volume", "rm", backup], capture_output=True, timeout=120)  # This fixture only.
            helper("from pathlib import Path; import shutil; [(shutil.rmtree(p) if p.exists() else None) for p in (Path('/test/data'),Path('/test/missing/data'))]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = smoke_existing_bind(read_json(args.images_manifest))
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
