"""Opt-in local Docker + Chromium preparation smoke, synthetic disposable stack only.

Does not install an executor/service or update an existing deployment.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from docker_update_executor import Docker, REPOSITORY

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'docker-updates'


def run(*args):
    env = {k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
    return subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args], env=env, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    from playwright.sync_api import sync_playwright, expect
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'cutover_tested': False, 'application_updated': False, 'checks': []}
    processes = []
    name = 'synthetic-updater-' + uuid.uuid4().hex[:10]
    created = False
    with tempfile.TemporaryDirectory(prefix='escritura-updater-smoke-') as temporary:
        folder = Path(temporary)
        data = folder / 'data' / 'app'
        data.mkdir(parents=True)
        data.chmod(0o777)  # Disposable fixture only; no chown/migration of existing data.
        marker = data / 'synthetic-marker.txt'
        marker.write_text('Synthetic fixture only. Preserve this bind.\n')
        marker_before = marker.read_bytes()
        reference = None
        try:
            target = Docker(name, data).resolve('develop')
            reference = REPOSITORY + '@' + target['digest']
            run('pull', '--platform', 'linux/amd64', reference)
            # The fixture is explicitly configured to the existing mobile alias.
            # Verify it did not move after the immutable manifest was resolved.
            configured_reference=REPOSITORY+':develop'
            run('pull','--platform','linux/amd64',configured_reference)
            run('run', '-d', '--name', name,
                '--label', 'com.docker.compose.project=' + name,
                '--label', 'com.docker.compose.service=app', '-p', '127.0.0.1::8000',
                '--mount', f'type=bind,source={data},target=/data', configured_reference)
            created = True
            installed = Docker(name, data).installed()
            assert installed['image_id']==target['image_id'], 'Fixture alias moved; do not guess another target'
            container_url = 'http://' + run('port', name, '8000/tcp')
            for _ in range(100):
                health = run('inspect', '--format', '{{.State.Health.Status}}', name)
                if health == 'healthy': break
                time.sleep(.5)
            else: raise RuntimeError('Synthetic container did not become healthy')
            with urllib.request.urlopen(container_url + '/api/health', timeout=5) as response:
                assert json.load(response)['status'] == 'ok'
            state = folder / '.docker-updater'
            state.mkdir(mode=0o700)
            (state / 'run').mkdir()
            control_socket = state / 'run' / 'control.sock'
            executor = subprocess.Popen([sys.executable, 'scripts/docker_update_executor.py', '--project-directory', str(folder),
                                         '--project-name', name, '--allowed-uid', str(os.getuid())], cwd=ROOT,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(executor)
            for _ in range(100):
                if control_socket.is_socket(): break
                if executor.poll() is not None: raise RuntimeError('Synthetic executor did not start')
                time.sleep(.1)
            else: raise RuntimeError('Synthetic executor socket absent')
            local_port = port()
            url = f'http://127.0.0.1:{local_port}'
            env = dict(os.environ, ESCRITURA_DATA_DIR=str(folder / 'web-data'), ESCRITURA_DEMO='0',
                       ESCRITURA_UPDATE_SOCKET=str(control_socket))
            web = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', str(local_port)],
                                   cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(web)
            for _ in range(100):
                try:
                    with urllib.request.urlopen(url + '/api/health', timeout=1): break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('Synthetic web app absent')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, **({'executable_path': os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel': 'chromium'}))
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                page.get_by_label('Usuário', exact=True).fill('synthetic-admin')
                page.locator('input[type=password]').fill('Synthetic-only-fixture-12345!')
                page.get_by_role('button', name='Criar acesso e continuar').click()
                navigation = page.get_by_role('navigation', name='Navegação principal')
                button = navigation.get_by_role('button', name='Atualização da aplicação', exact=True, include_hidden=True)
                expect(button).to_be_attached(timeout=20000)
                parent = button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None: parent.locator('summary').click()
                button.click()
                expect(page.get_by_role('heading', name='Atualização da aplicação', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Buscar versão disponível', exact=True)).to_be_enabled(timeout=60000)
                with page.expect_response(lambda response: response.url.endswith('/api/docker-updates/check') and response.request.method=='POST', timeout=120000) as checked:
                    page.get_by_role('button', name='Buscar versão disponível', exact=True).click()
                assert checked.value.status==200, checked.value.text()
                expect(page.get_by_role('button', name='Baixar versão', exact=True)).to_be_enabled(timeout=120000)
                assert page.locator('.update-diagnostics').get_attribute('open') is None
                page.get_by_role('button', name='Baixar versão', exact=True).click()
                expect(page.get_by_role('dialog')).to_be_visible()
                page.get_by_role('dialog').get_by_role('button', name='Confirmar download', exact=True).click()
                expect(page.get_by_text('Download concluído. A versão em uso ainda não foi alterada.', exact=True).first).to_be_visible(timeout=180000)
                page.screenshot(path=str(OUT/'prepared-1440.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                for _ in range(60):
                    sidebar_box = page.locator('.sidebar').bounding_box()
                    if sidebar_box and sidebar_box['x'] + sidebar_box['width'] <= 1: break
                    time.sleep(.05)
                else: raise RuntimeError('Sidebar did not settle outside mobile viewport')
                page.screenshot(path=str(OUT/'prepared-390.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Horizontal overflow'
                response = page.request.get(url+'/api/docker-updates')
                assert response.ok
                result = response.json()
                assert result['jobs'][0]['state'] == 'prepared'
                assert result['jobs'][0]['application_updated'] is False
                assert result['installed'] == installed
                page.reload()
                page.get_by_role('button', name='Abrir navegação', exact=True).click()
                expect(navigation).to_be_visible()
                button = navigation.get_by_role('button', name='Atualização da aplicação', exact=True, include_hidden=True)
                parent = button.locator('xpath=ancestor::details')
                if parent.count() and parent.get_attribute('open') is None: parent.locator('summary').click()
                button.click()
                expect(page.get_by_text('Download concluído. A versão em uso ainda não foi alterada.', exact=True).first).to_be_visible(timeout=60000)
                assert not errors, errors
                report['browser_version'] = browser.version
                browser.close()
            after = Docker(name, data).installed()
            assert after == installed
            assert marker.read_bytes() == marker_before
            assert run('inspect', '--format', '{{.State.Health.Status}}', name) == 'healthy'
            with urllib.request.urlopen(container_url+'/api/health', timeout=5) as response:
                assert json.load(response)['status'] == 'ok'
            report.update(ok=True, target_digest=target['digest'], target_version=target['version'], uid_gid=after['uid_gid'],
                          checks=['real pinned pull and image identity', 'real Unix socket and peer UID', 'admin UI without company',
                                  'explicit confirmation and persistent job after reload', 'same container/config/bind/marker',
                                  'existing app healthcheck and HTTP health before/after preparation', 'Chromium desktop and mobile'])
        except Exception as exc:
            report['error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            for process in reversed(processes):
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            if created: run('rm', '-f', name)
            if reference:
                # Fixture files created as UID 10001 are removed by that same UID.
                run('run', '--rm', '--network', 'none', '--mount', f'type=bind,source={data},target=/data',
                    '--entrypoint', 'python', reference, '-c',
                    "from pathlib import Path; import shutil; [(shutil.rmtree(p) if p.is_dir() else p.unlink()) for p in Path('/data').iterdir()]")
            (OUT/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
