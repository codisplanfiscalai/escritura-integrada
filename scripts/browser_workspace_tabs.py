"""Exercise permanent overview, overflow controls and confirmed closing in Chromium."""
from __future__ import annotations

import calendar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'browser-workspace-tabs'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        'ok': False, 'checks': [], 'screenshots': [], 'console_errors': [],
        'version': (ROOT / 'VERSION').read_text().strip(),
        'source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    }
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='escritura-tabs-') as folder:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            env = dict(os.environ, ESCRITURA_DATA_DIR=folder, ESCRITURA_DEMO='1')
            with (OUT / 'server.log').open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url + '/api/health', timeout=1):
                            break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError('Servidor de teste não iniciou.')
                with sync_playwright() as playwright:
                    options = {'executable_path': os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {'channel': 'chromium'}
                    browser = playwright.chromium.launch(headless=True, **options)
                    page = browser.new_page(viewport={'width': 1440, 'height': 900})
                    page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
                    page.set_default_timeout(15000)
                    tabs = page.get_by_role('tablist', name='Guias abertas')
                    overview = tabs.get_by_role('tab', name='Visão geral', exact=True)
                    previous = page.get_by_role('button', name='Mostrar guias anteriores')
                    following = page.get_by_role('button', name='Mostrar próximas guias')
                    viewport = page.locator('.workspace-tabs-viewport')

                    def nav(label):
                        if page.viewport_size['width'] <= 760:
                            page.get_by_role('button', name='Abrir navegação').click()
                        button = page.get_by_role('navigation', name='Navegação principal').get_by_role('button', name=label, exact=True, include_hidden=True)
                        parent = button.locator('xpath=ancestor::details')
                        if parent.count() and parent.get_attribute('open') is None:
                            parent.locator('summary').click()
                        button.click()
                        expect(tabs.get_by_role('tab', name=label, exact=True)).to_have_attribute('aria-selected', 'true')

                    def shot(name):
                        page.screenshot(path=str(OUT / name), full_page=True, animations='disabled')
                        report['screenshots'].append(name)

                    def assert_selected_visible():
                        page.wait_for_function('''() => {
                            const area = document.querySelector('.workspace-tabs-viewport').getBoundingClientRect();
                            const tab = document.querySelector('.workspace-tab.selected').getBoundingClientRect();
                            return tab.left >= area.left - 1 && tab.right <= area.right + 1;
                        }''')

                    page.goto(url)
                    page.get_by_role('button', name='Entrar na demonstração').click()
                    expect(overview).to_have_attribute('aria-selected', 'true')
                    expect(previous).to_be_disabled()
                    expect(following).to_be_disabled()
                    expect(page.get_by_role('button', name='Fechar guia Visão geral')).to_have_count(0)
                    overview.press('Delete')
                    expect(overview).to_be_visible()
                    overview.dblclick()
                    expect(page.get_by_role('dialog')).to_have_count(0)
                    report['checks'].append('Visão geral sozinha permanece aberta, sem fechar nem confirmação desnecessária')

                    labels = ['Empresas', 'Escrituração e documentos', 'Importações fiscais', 'Participantes, produtos e serviços', 'Classificações fiscais', 'CFOP e associações', 'Parametrizações fiscais', 'Competências fiscais', 'Lançamentos contábeis', 'Plano de contas', 'Contas a pagar', 'Contas a receber', 'Usuários e acessos', 'Grupos de usuários']
                    for label in labels:
                        nav(label)
                        assert_selected_visible()
                    expect(tabs.get_by_role('tab')).to_have_count(len(labels) + 1)
                    expect(page.get_by_role('button', name='Fechar guia Visão geral')).to_have_count(0)

                    for width in [1920, 1440, 1024, 768, 390, 320]:
                        page.set_viewport_size({'width': width, 'height': 900})
                        assert_selected_visible()
                        metrics = viewport.evaluate('''el => ({overflowX: getComputedStyle(el).overflowX, overflowY: getComputedStyle(el).overflowY, scrollbar: getComputedStyle(el).scrollbarWidth, webkit: getComputedStyle(el, '::-webkit-scrollbar').display, height: el.clientHeight, scrollHeight: el.scrollHeight, width: el.clientWidth, scrollWidth: el.scrollWidth})''')
                        assert metrics['overflowX'] == 'auto' and metrics['overflowY'] == 'hidden', metrics
                        assert metrics['scrollbar'] == 'none' and metrics['webkit'] == 'none', metrics
                        assert metrics['scrollHeight'] <= metrics['height'] + 1, metrics
                        assert metrics['scrollWidth'] > metrics['width'], metrics
                        for control in [previous, following]:
                            box = control.bounding_box()
                            assert box and box['width'] == 24 and box['x'] >= 0 and box['x'] + box['width'] <= width, box
                        shot(f'tabs-{width}.png')
                    report['checks'].append('Sem barras nos dois eixos, guia ativa visível e controles de 24 px em 320–1920 px')

                    for _ in range(50):
                        if previous.is_disabled():
                            break
                        previous.click()
                    expect(previous).to_be_disabled()
                    assert viewport.evaluate('el => el.scrollLeft') <= 1
                    expect(following).to_be_enabled()
                    overview.focus()
                    overview.press('End')
                    last_tab = tabs.get_by_role('tab', name=labels[-1], exact=True)
                    expect(last_tab).to_be_focused()
                    last_tab.press('Home')
                    expect(overview).to_be_focused()
                    overview.press('ArrowRight')
                    expect(tabs.get_by_role('tab', name='Empresas', exact=True)).to_be_focused()
                    page.keyboard.press('Enter')
                    expect(tabs.get_by_role('tab', name='Empresas', exact=True)).to_have_attribute('aria-selected', 'true')
                    for _ in range(50):
                        if following.is_disabled():
                            break
                        following.click()
                    expect(following).to_be_disabled()
                    assert viewport.evaluate('el => Math.abs(el.scrollWidth - el.clientWidth - el.scrollLeft)') <= 1
                    # Native horizontal input remains available without a visible scrollbar.
                    viewport.hover()
                    page.mouse.wheel(-500, 0)
                    expect(following).to_be_enabled()
                    report['checks'].append('Setas repetidas atingem os limites; roda horizontal, Home/End, setas e Enter continuam acessíveis')

                    page.set_viewport_size({'width': 1440, 'height': 900})
                    nav('Visão geral')
                    overview.press('Delete')
                    expect(tabs.get_by_role('tab')).to_have_count(len(labels) + 1)
                    overview.dblclick()
                    confirmation = page.get_by_role('dialog', name='Fechar as outras guias?')
                    expect(confirmation).to_be_visible()
                    expect(confirmation).to_contain_text('ainda não salvos')
                    expect(tabs.get_by_role('tab')).to_have_count(len(labels) + 1)
                    shot('confirm-close-others.png')
                    confirmation.get_by_role('button', name='Voltar', exact=True).click()
                    expect(tabs.get_by_role('tab')).to_have_count(len(labels) + 1)
                    overview.press('Shift+Delete')
                    expect(confirmation).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(confirmation).to_have_count(0)
                    expect(tabs.get_by_role('tab')).to_have_count(len(labels) + 1)
                    report['checks'].append('Duplo clique e atalho pedem confirmação; Voltar/Escape não fecham nenhuma guia')

                    nav('Escrituração e documentos')
                    page.get_by_role('button', name='Novo documento', exact=True).click()
                    page.get_by_label('Número *', exact=True).fill('NAO-SALVO-GUIAS')
                    # A modal normally covers the strip. Also prove the handler is safe if invoked while editing.
                    overview.dispatch_event('dblclick')
                    expect(confirmation).to_be_visible()
                    confirmation.get_by_role('button', name='Voltar', exact=True).click()
                    expect(page.get_by_label('Número *', exact=True)).to_have_value('NAO-SALVO-GUIAS')
                    expect(tabs.get_by_role('tab', name='Escrituração e documentos', exact=True)).to_have_attribute('aria-selected', 'true')
                    expect(tabs.get_by_role('tab')).to_have_count(len(labels) + 1)
                    overview.dispatch_event('dblclick')
                    confirmation.get_by_role('button', name='Fechar outras guias', exact=True).click()
                    expect(page.get_by_role('dialog')).to_have_count(0)
                    expect(tabs.get_by_role('tab')).to_have_count(1)
                    expect(overview).to_have_attribute('aria-selected', 'true')
                    expect(previous).to_be_disabled()
                    expect(following).to_be_disabled()
                    nav('Escrituração e documentos')
                    page.get_by_role('button', name='Novo documento', exact=True).click()
                    expect(page.get_by_label('Número *', exact=True)).to_have_value('')
                    page.get_by_role('button', name='Fechar janela', exact=True).click()
                    expect(page.get_by_role('dialog')).to_have_count(0)
                    report['checks'].append('Rascunho preservado ao cancelar e descartado apenas após confirmar; edição reabre limpa')

                    tab = tabs.get_by_role('tab', name='Escrituração e documentos', exact=True)
                    tab.focus()
                    tab.press('Delete')
                    expect(tabs.get_by_role('tab')).to_have_count(1)
                    expect(overview).to_be_focused()
                    nav('Empresas')
                    page.get_by_role('button', name='Fechar guia Empresas', exact=True).click()
                    expect(tabs.get_by_role('tab')).to_have_count(1)
                    expect(overview).to_have_attribute('aria-selected', 'true')
                    shot('overview-permanent.png')
                    report['checks'].append('Fechamento individual por botão/Delete funciona e devolve foco à guia permanente')

                    nav('Escrituração e documentos')
                    nav('Contas a pagar')
                    def delayed_context(route):
                        time.sleep(.25)
                        route.continue_()
                    page.route('**/api/context', delayed_context)
                    page.get_by_role('button', name='Fechar guia Contas a pagar', exact=True).click()
                    fiscal_tab = tabs.get_by_role('tab', name='Escrituração e documentos', exact=True)
                    expect(fiscal_tab).to_have_attribute('aria-selected', 'true')
                    expect(fiscal_tab).to_be_focused()
                    page.unroute('**/api/context', delayed_context)
                    fiscal_tab.press('Delete')
                    expect(overview).to_be_focused()
                    report['checks'].append('Fechar guia entre módulos restaura foco após ativação assíncrona')

                    company_id = str(page.request.get(url + '/api/session').json()['active_company_id'])
                    page.keyboard.press('F8')
                    context = page.get_by_role('dialog', name='Empresa, ano e competência')
                    expect(context).to_be_visible()
                    page.keyboard.press('F8')
                    expect(context).to_have_count(1)
                    context.get_by_label('Competência a fixar (opcional)').select_option('02')
                    context.get_by_role('button', name='Cancelar', exact=True).click()
                    page.keyboard.press('F8')
                    expect(context.get_by_label('Competência a fixar (opcional)')).to_have_value('')
                    context.get_by_label('Ano a fixar (opcional)').fill('')
                    context.get_by_label('Competência a fixar (opcional)').select_option('02')
                    context.get_by_role('button', name='Aplicar contexto', exact=True).click()
                    expect(context).to_have_count(0)
                    nav('Livros e relatórios fiscais')
                    year = int(page.get_by_label('Fiscal · EXERCÍCIO', exact=True).input_value())
                    start = page.locator('label').filter(has_text='Data inicial').locator('input.date-input-field')
                    end = page.locator('label').filter(has_text='Data final').locator('input.date-input-field')
                    expect(start).to_have_value(f'01/02/{year}')
                    expect(end).to_have_value(f'{calendar.monthrange(year, 2)[1]}/02/{year}')
                    start.fill(f'0502{year}')
                    end.fill(f'1902{year}')
                    end.press('Tab')
                    nav('Visão geral')
                    nav('Livros e relatórios fiscais')
                    expect(start).to_have_value(f'05/02/{year}')
                    expect(end).to_have_value(f'19/02/{year}')
                    shot('context-february-editable.png')
                    report['checks'].append('F8 não duplica modal; cancelar preserva preferências; fevereiro sugere datas editáveis e mantém intervalo manual ao navegar')

                    page.keyboard.press('F8')
                    context.get_by_role('button', name='Limpar empresa', exact=True).click()
                    context.get_by_role('button', name='Aplicar contexto', exact=True).click()
                    expect(context).to_have_count(0)
                    expect(page.get_by_text('Escolha a empresa de trabalho', exact=True)).to_be_visible()
                    expect(page.get_by_label('EMPRESA ATIVA', exact=True)).to_have_value('')
                    expect(overview).to_be_visible()
                    page.get_by_label('EMPRESA ATIVA', exact=True).select_option(company_id)
                    expect(page.get_by_label('EMPRESA ATIVA', exact=True)).to_have_value(company_id)
                    expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
                    report['checks'].append('Limpar empresa mantém Visão geral/EmptyState e selecionar novamente restaura o contexto')
                    assert not report['console_errors'], report['console_errors']
                    browser.close()
                    report['ok'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
