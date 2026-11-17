"""Required Docker rehearsal for CI. Never attaches to an existing installation.

Only UUID-scoped volumes/images created here are removed; no prune, host chmod,
real certificates, fiscal hosts, published ports or Docker socket in containers.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]


def docker(*args, env=None):
    result = subprocess.run(['docker', *map(str, args)], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        sys.stderr.write(result.stderr[-6000:])  # Build/fixture diagnostics; never dump certificate material.
        result.check_returncode()
    return result.stdout


def main():
    # CI's local daemon only; never follow a developer's remote Docker context.
    endpoint = os.environ.get('DOCKER_HOST')
    if not endpoint:
        context = os.environ.get('DOCKER_CONTEXT') or docker('context', 'show').strip()
        endpoint = json.loads(docker('context', 'inspect', context))[0]['Endpoints']['docker']['Host']
    if not endpoint.startswith('unix://'):
        raise RuntimeError('A prova exige daemon Docker Linux local; contexto remoto recusado.')
    docker('info', '--format', '{{.ServerVersion}}')  # Required, not silently skipped.
    catalog = json.loads((ROOT / 'docker/images.lock.json').read_text())
    prefix = 'escritura-a1-fixture-' + uuid.uuid4().hex
    base, runtime = prefix + ':base', prefix + ':runtime'
    created = []
    images = []
    try:
        config = json.loads(docker('compose', '--project-name', prefix, '-f', 'compose.yaml',
                                  '-f', 'deploy/compose.reception-vault.yaml', 'config', '--format', 'json',
                                  env=dict(os.environ, ESCRITURA_IMAGE=runtime,
                                           ESCRITURA_APP_DATA_BIND='/tmp/' + prefix + '/configuration-only')))
        app = config['services']['app']
        mounts = {mount['target']: mount for mount in app['volumes']}
        # Compose's normalized JSON omits false fields (omitempty).
        assert mounts['/data']['type'] == 'bind' and not mounts['/data'].get('bind', {}).get('create_host_path', False)
        assert mounts['/run/escritura/reception-vault']['type'] == 'volume'
        assert app['read_only'] and app['cap_drop'] == ['ALL']
        assert config['volumes']['reception_vault']['name'] == prefix + '_reception_vault'
        docker('build', '-f', 'docker/base.Dockerfile', '--build-arg',
               'PYTHON_IMAGE=' + catalog['upstreams']['python']['reference'], '-t', base, '.')
        images.append(base)
        docker('build', '--target', 'reception-runtime', '--build-arg', 'RUNTIME_IMAGE=' + base,
               '--build-arg', 'NODE_IMAGE=' + catalog['upstreams']['node']['reference'], '-t', runtime, '.')
        images.append(runtime)
        for name in ('data', 'vault', 'empty-vault', 'wrong-vault', 'backup', 'key-backup', 'restored-data', 'restored-vault'):
            volume = prefix + '-' + name
            docker('volume', 'create', '--label', 'escritura.fixture=' + prefix, volume)
            created.append(volume)

        def mount(name, target, readonly=False):
            assert prefix + '-' + name in created
            return ['--mount', 'type=volume,source=' + prefix + '-' + name + ',target=' + target + (',readonly' if readonly else '')]

        def run(action, data, vault, extra=()):
            args = ['run', '--rm', '--name', prefix + '-' + action, '--read-only', '--network', 'none',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                    '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '--workdir', '/app',
                    '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'ESCRITURA_DATA_DIR=/data/store',
                    '-e', 'ESCRITURA_RECEPTION_VAULT_DIR=/run/escritura/reception-vault',
                    '--mount', 'type=bind,source=' + str(ROOT / 'app') + ',target=/app/app,readonly',
                    '--mount', 'type=bind,source=' + str(ROOT / 'scripts/probes/reception_vault_fixture.py') + ',target=/app/probe.py,readonly']
            args += mount(data, '/data') + mount(vault, '/run/escritura/reception-vault') + list(extra)
            result = json.loads(docker(*args, runtime, 'python', '/app/probe.py', action))
            assert result['ok'] is True
            print(json.dumps(result), flush=True)  # Booleans/counts only.

        run('seed', 'data', 'vault')
        run('check', 'data', 'vault')  # Different container after creation/removal of seed.
        run('missing', 'data', 'empty-vault')
        run('wrong', 'data', 'wrong-vault')
        run('backup', 'backup', 'key-backup', mount('data', '/source-data', True) + mount('vault', '/source-vault', True))
        run('restore', 'restored-data', 'restored-vault', mount('backup', '/source-backup', True) + mount('key-backup', '/source-vault', True))
        run('check', 'restored-data', 'restored-vault')
    finally:
        # Explicit names generated in this invocation only. Never delete other volumes.
        for volume in reversed(created):
            subprocess.run(['docker', 'volume', 'rm', volume], stdout=subprocess.DEVNULL, check=False)
        if images:
            subprocess.run(['docker', 'image', 'rm', *reversed(images)], stdout=subprocess.DEVNULL, check=False)


if __name__ == '__main__':
    main()
