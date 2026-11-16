#!/usr/bin/env python3
"""Disposable real Compose: five services, cold migration and bind persistence.

Uses only already loaded images. Never runs against an operator's stack.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import uuid

from deploy_storage import TARGETS
from image_tools import ROOT, read_json, write_json
from package_deploy import deployment_env, release_compose


# Runs inside the MinIO image; credentials stay in its environment, never argv/logs.
MINIO_PROBE = r'''
import datetime, hashlib, hmac, os, urllib.request
def request(method, path, data=b''):
    now=datetime.datetime.now(datetime.timezone.utc)
    stamp=now.strftime('%Y%m%dT%H%M%SZ'); day=stamp[:8]
    scope=day+'/us-east-1/s3/aws4_request'
    hashed=hashlib.sha256(data).hexdigest()
    headers='host:127.0.0.1:9000\nx-amz-content-sha256:'+hashed+'\nx-amz-date:'+stamp+'\n'
    signed='host;x-amz-content-sha256;x-amz-date'
    canonical='\n'.join([method,path,'',headers,signed,hashed])
    string='\n'.join(['AWS4-HMAC-SHA256',stamp,scope,hashlib.sha256(canonical.encode()).hexdigest()])
    key=('AWS4'+os.environ['MINIO_ROOT_PASSWORD']).encode()
    for value in (day,'us-east-1','s3','aws4_request'):
        key=hmac.new(key,value.encode(),hashlib.sha256).digest()
    auth='AWS4-HMAC-SHA256 Credential='+os.environ['MINIO_ROOT_USER']+'/'+scope+', SignedHeaders='+signed+', Signature='+hmac.new(key,string.encode(),hashlib.sha256).hexdigest()
    req=urllib.request.Request('http://127.0.0.1:9000'+path,data=None if method=='GET' else data,method=method,
        headers={'Authorization':auth,'x-amz-date':stamp,'x-amz-content-sha256':hashed})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=15) as response:
        return response.read()
payload=b'synthetic-storage-\x00\xff'
if os.environ.get('STORAGE_SEED')=='1':
    request('PUT','/storage-probe')
    request('PUT','/storage-probe/object',payload)
assert request('GET','/storage-probe/object')==payload
'''


def smoke_storage(manifest):
    project = "storage-smoke-" + uuid.uuid4().hex[:12]
    fresh = project + "-fresh"
    checks = []
    def record(value):
        checks.append(value)
        print("Storage: " + value, flush=True)
    helper = manifest["images"]["app"]["reference"]
    with tempfile.TemporaryDirectory(prefix="escritura-storage-") as temporary:
        root = Path(temporary)
        env_text = deployment_env(manifest, "develop")
        env_text = env_text.replace('COMPOSE_PROJECT_NAME=escritura-develop', 'COMPOSE_PROJECT_NAME=' + project)
        env_text = "\n".join("ESCRITURA_IMAGE=" + helper if row.startswith("ESCRITURA_IMAGE=") else row
                             for row in env_text.splitlines()) + "\n"
        credentials = {"REDIS_PASSWORD": secrets.token_hex(24), "POSTGRES_PASSWORD": secrets.token_hex(24),
                       "MYSQL_PASSWORD": secrets.token_hex(24), "MYSQL_ROOT_PASSWORD": secrets.token_hex(24),
                       "MINIO_ROOT_USER": "storage-smoke", "MINIO_ROOT_PASSWORD": secrets.token_hex(24)}
        for key, value in credentials.items():
            env_text = env_text.replace(key + "=\n", key + "=" + value + "\n")
        (root / ".env").write_text(env_text)
        os.chmod(root / ".env", 0o600)
        # Isolate .env interpolation from unrelated test-runner variables.
        variables = {row.split("=", 1)[0] for row in env_text.splitlines() if "=" in row and not row.startswith("#")}
        environment = {key: value for key, value in os.environ.items() if key not in variables}
        new = json.loads((ROOT / "deploy/develop/compose.yaml").read_text())
        new["services"]["app"]["ports"] = ["127.0.0.1::8000/tcp"]
        legacy = copy.deepcopy(new)
        legacy["volumes"] = {name + "-data": {} for name in TARGETS}
        for name, target in TARGETS.items():
            legacy["services"][name]["volumes"] = [name + "-data:" + target]
        (root / "compose.yaml").write_text(json.dumps(new))
        (root / "compose.named.yaml").write_text(json.dumps(legacy))
        (root / "compose.release.yaml").write_text(json.dumps(release_compose(manifest)))
        plan = root / "storage-plan.json"

        def run(command, expected=0, stdin=None):
            result = subprocess.run([str(arg) for arg in command], cwd=root, env=environment,
                                    input=stdin, text=True, capture_output=True, timeout=600)
            if (expected == 0 and result.returncode) or (expected != 0 and not result.returncode):
                if str(command[0]) == sys.executable and str(command[1]).endswith("deploy_storage.py"):
                    # This CLI deliberately sanitizes its errors and never emits config/secrets.
                    print(result.stderr.strip(), flush=True)
                raise RuntimeError("Storage smoke: resultado inesperado em " + str(command[0]) + " " + str(command[1]))
            return result.stdout.strip()

        def compose(legacy_mode=False, fresh_mode=False):
            command = ["docker", "compose", "-p", fresh if fresh_mode else project, "-f",
                       root / ("compose.named.yaml" if legacy_mode else "compose.yaml"),
                       "-f", root / "compose.release.yaml"]
            if not legacy_mode and not fresh_mode and plan.exists():
                command += ["-f", plan.with_suffix(".images.yaml")]
            return [*command, "--profile", "*"]

        def cli(*args, expected=0):
            return run([sys.executable, ROOT / "scripts/deploy_storage.py", *args], expected=expected)

        def fs_probe(code):
            # Host users need not have access to private UID-owned data folders.
            return run(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                        "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
                        "--tmpfs", "/data:rw,noexec,nosuid,size=1m", "--entrypoint", "python",
                        "--mount", "type=bind,src=" + str(root) + ",dst=/test", helper, "-c", code])

        def probe(old=False, seed=False, fresh_mode=False):
            base = compose(old, fresh_mode)
            sqlite = ("import sqlite3; c=sqlite3.connect('/data/escritura.sqlite3'); " +
                      ("c.execute('CREATE TABLE storage_probe(value INTEGER)'); c.execute('INSERT INTO storage_probe VALUES (42)'); c.commit(); " if seed else "") +
                      "assert c.execute('SELECT value FROM storage_probe').fetchall()==[(42,)]; c.close(); "
                      "import pathlib; assert pathlib.Path('/data/escritura.sqlite3').stat().st_uid==10001; " +
                      ("p=pathlib.Path('/data/documents'); p.mkdir(exist_ok=True); (p/'synthetic.xml').write_bytes(b'<NFe>synthetic</NFe>'); " if seed else "") +
                      "assert pathlib.Path('/data/documents/synthetic.xml').read_bytes()==b'<NFe>synthetic</NFe>'; " +
                      ("assert not pathlib.Path('/data/fresh-probe').exists()" if not fresh_mode else "pass"))
            run([*base, "exec", "-T", "app", "python", "-c", sqlite])
            health = "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health'))['status']=='ok'"
            run([*base, "exec", "-T", "app", "python", "-c", health])
            if seed:
                run([*base, "exec", "-T", "redis", "sh", "-c", 'export REDISCLI_AUTH="$REDIS_PASSWORD"; redis-cli --no-auth-warning SET storage-probe persisted; redis-cli --no-auth-warning SAVE'])
                run([*base, "exec", "-T", "postgres", "sh", "-c", 'export PGPASSWORD="$POSTGRES_PASSWORD"; psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE TABLE storage_probe(value BIGINT); INSERT INTO storage_probe VALUES (42)"'])
                run([*base, "exec", "-T", "mysql", "sh", "-c", 'export MYSQL_PWD="$MYSQL_PASSWORD"; mysql -u "$MYSQL_USER" "$MYSQL_DATABASE" -e "CREATE TABLE storage_probe(value BIGINT); INSERT INTO storage_probe VALUES (42)"'])
            assert run([*base, "exec", "-T", "redis", "sh", "-c", 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning GET storage-probe']) == "persisted"
            assert run([*base, "exec", "-T", "postgres", "sh", "-c", 'PGPASSWORD="$POSTGRES_PASSWORD" psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT value FROM storage_probe"']) == "42"
            assert run([*base, "exec", "-T", "mysql", "sh", "-c", 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -N -u "$MYSQL_USER" "$MYSQL_DATABASE" -e "SELECT value FROM storage_probe"']) == "42"
            run([*base, "exec", "-T", "-e", "STORAGE_SEED=" + ("1" if seed else "0"), "minio", "python", "-c", MINIO_PROBE])

        try:
            run([*compose(fresh_mode=True), "up", "-d", "--pull", "never", "app"], expected=1)
            fs_probe("from pathlib import Path; assert not Path('/test/data/" + fresh + "').exists()")
            run([*compose(fresh_mode=True), "down"])
            record("missing bind directories are refused without silently creating empty data")
            # Real fresh preparation, including UID/GID 10001 and refusal to overwrite.
            cli("init", "--directory", root, "--project", fresh, "--helper-image", helper)
            cli("init", "--directory", root, "--project", fresh, "--helper-image", helper, expected=1)
            run([*compose(fresh_mode=True), "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "300"])
            probe(seed=True, fresh_mode=True)
            run([*compose(fresh_mode=True), "exec", "-T", "app", "python", "-c",
                 "import pathlib; p=pathlib.Path('/data/fresh-probe'); p.write_text('ok'); assert p.stat().st_uid==10001"])
            run([*compose(fresh_mode=True), "up", "-d", "--pull", "never", "--force-recreate", "--wait", "--wait-timeout", "300"])
            probe(fresh_mode=True)
            run([*compose(fresh_mode=True), "exec", "-T", "app", "python", "-c", "from pathlib import Path; assert Path('/data/fresh-probe').read_text()=='ok'"])
            run([*compose(fresh_mode=True), "down"])
            record("five fresh services: explicit init, app UID 10001, existing destination refused, data survives recreation")
            # Separate synthetic stack after the fresh-project scenario.
            (root / '.env').write_text(env_text)
            (root / '.env').chmod(0o600)

            run([*compose(True), "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "300"])
            probe(old=True, seed=True)
            cli("init", "--directory", root, "--project", project, "--helper-image", helper, expected=1)
            cli("plan", "--directory", root, "--project", project, "--compose-file", root / "compose.named.yaml",
                "--helper-image", helper, "--output", plan)
            original_plan = plan.read_bytes()
            original_lock = plan.with_suffix(".images.yaml").read_bytes()
            cli("plan", "--directory", root, "--project", project, "--compose-file", root / "compose.named.yaml",
                "--helper-image", helper, "--output", plan, expected=1)
            assert plan.read_bytes() == original_plan
            assert plan.with_suffix(".images.yaml").read_bytes() == original_lock
            cli("migrate", "--plan", plan, expected=1)  # Active writers must block before any copying.
            fs_probe("from pathlib import Path; assert not Path('/test/data/" + project + "').exists()")
            record("five real services seeded; active writers and init on existing stack refused")
            run([*compose(True), "stop"])
            cli("migrate", "--plan", plan)
            cli("verify", "--plan", plan)
            cli("migrate", "--plan", plan, expected=1)
            cli('prepare-app', '--directory', root, '--project', project, '--helper-image', helper)
            # Verify every resolved mount, no extra anonymous/persistent volume paths.
            config = json.loads(run([*compose(), "config", "--format", "json"]))
            planned = json.loads(plan.read_text())
            for name in TARGETS:
                assert config["services"][name]["image"] == planned["images"][name]
                assert config["services"][name]["pull_policy"] == "never"
                mount = config["services"][name]["volumes"][0]
                assert mount["type"] == "bind"
                assert mount["source"] == str(root / "data" / project / name)
                assert not mount.get("bind", {}).get("create_host_path", False)
            record("cold-copy verified all files/metadata; repetition refused; installed image IDs locked; overrides preserved bind mounts")
            run([*compose(), "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "300"])
            probe()
            run([*compose(), "stop"])
            run([*compose(), "up", "-d", "--pull", "never", "--force-recreate", "--wait", "--wait-timeout", "300"])
            probe()
            record("SQLite row, Redis key, PostgreSQL/MySQL rows and S3 object survive migration and recreation")
            run([*compose(), "stop"])
            run([*compose(True), "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "300"])
            probe(old=True)
            record("original named volumes still start and retain every seeded service value")
            return {"status": "passed", "checks": checks, "fixture": "synthetic only; ephemeral local Compose projects"}
        finally:
            # Only resources of the two UUID-named test projects are deleted.
            for base in (compose(True), compose(fresh_mode=True)):
                subprocess.run([*map(str, base), "down", "-v", "--remove-orphans"], cwd=root, env=environment, capture_output=True, timeout=120)
            subprocess.run(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only", "--user", "0:0",
                            "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER", "--cap-add", "CHOWN",
                            "--no-healthcheck", "--tmpfs", "/data:rw,noexec,nosuid,size=1m",
                            "--mount", "type=bind,src=" + str(root) + ",dst=/test", "--entrypoint", "python", helper,
                            "-c", "from pathlib import Path; import shutil; p=Path('/test/data'); shutil.rmtree(p) if p.exists() else None"], capture_output=True, timeout=120, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = smoke_storage(read_json(args.images_manifest))
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
