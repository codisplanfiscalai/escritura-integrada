"""Exportação sem navegar, falhas preservadas e paginação real em volume."""
import json
import re
import time
from pathlib import Path
from playwright.sync_api import expect


def run(page, url, cid, nav, check, shot):
    main=page.locator('.main-content')
    for menu,kind in [('Livros e relatórios fiscais','fiscal-documents'),('Livros e demonstrações','diary'),('Consultas e relatórios financeiros','financial')]:
        nav(menu)
        page.get_by_label(re.compile('^Relatório')).select_option(kind)
        page.get_by_role('button',name='Gerar relatório',exact=True).click()
        expect(main.locator('.report-output')).to_be_visible()
        href=main.get_by_role('link',name='PDF',exact=True).get_attribute('href')
        original=page.url
        with page.expect_download() as info:main.get_by_role('link',name='PDF',exact=True).click()
        assert Path(info.value.path()).read_bytes().startswith(b'%PDF')
        expect(main.locator('.report-output')).to_be_visible();assert page.url==original
        with page.expect_popup() as info:main.get_by_role('link',name='Prévia / imprimir PDF',exact=True).click()
        popup=info.value;popup.wait_for_load_state('domcontentloaded');popup.close()
        expect(main.locator('.report-output')).to_be_visible();assert page.url==original
        denial=f'Exportação recusada no teste de preservação: {kind}'
        def deny(route):route.fulfill(status=403,content_type='application/json',body=json.dumps({'detail':denial}))
        page.route('**'+href,deny)
        main.get_by_role('link',name='PDF',exact=True).click()
        expect(page.get_by_text(denial,exact=True)).to_be_visible()
        expect(main.locator('.report-output')).to_be_visible();assert page.url==original
        page.unroute('**'+href,deny)
        with page.expect_download() as info:main.get_by_role('link',name='Excel',exact=True).click()
        assert Path(info.value.path()).read_bytes().startswith(b'PK')
    check('Fiscal/Contábil/Financeiro: PDF, Excel, prévia, falha 403 e nova tentativa sem sair da aplicação')
    nav('Livros e relatórios fiscais')
    expect(page.get_by_label(re.compile('^Relatório'))).to_have_value('fiscal-documents')
    report_url=url+f'/api/companies/{cid}/business-reports/fiscal-documents?start=2026-01-01&end=2026-12-31'
    payload=page.request.get(report_url).json();assert payload['rows']
    payload['rows']=[dict(payload['rows'][0],document=f'VOLUME-{n:05d}') for n in range(5000)]
    payload['totals']={'documents':5000,'total_cents':sum(r['total_cents'] for r in payload['rows'])}
    def volume(route):route.fulfill(json=payload)
    pattern='**/business-reports/fiscal-documents?*'
    page.route(pattern,volume)
    try:
        start=time.perf_counter();page.get_by_role('button',name='Gerar relatório',exact=True).click()
        expect(main.locator('.report-output tbody tr')).to_have_count(50)
        expect(main.locator('.table-footer')).to_contain_text('5000 linhas')
        main.get_by_role('button',name='Próxima',exact=True).click()
        expect(main.locator('.report-output tbody tr').first).to_contain_text('VOLUME-00050')
        elapsed=round((time.perf_counter()-start)*1000,2)
        shot('relatorio-paginado-5000.png')
        (Path(__file__).resolve().parents[1]/'artifacts/browser/report-performance.json').write_text(json.dumps({'synthetic_rows':5000,'rendered_rows':50,'query_and_next_page_ms':elapsed,'source':'Resposta sintética para medir somente a renderização; API e totais validados separadamente.'},indent=2))
    finally:page.unroute(pattern,volume)
    page.get_by_role('button',name='Gerar relatório',exact=True).click()
    expect(main.locator('.table-footer')).not_to_contain_text('5000 linhas')
    check('Relatório de 5.000 linhas mantém somente 50 linhas no DOM e troca de página com filtros preservados')
