"""Read-only inventory against run_preview.py on loopback with synthetic demo data.

Start the preview with ESCRITURA_DATA_DIR pointing to a disposable directory.
This inventories initial screens, not every subtab, editor, or permission profile.
"""
import json
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'ux-inventory'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.goto('http://127.0.0.1:8765')
            page.get_by_role('button', name='Entrar na demonstração').click()
            expect(page.get_by_role('heading', name='Visão geral', exact=True)).to_be_visible()
            expect(page.locator('.demo-banner')).to_be_visible()
            nav = page.get_by_role('navigation', name='Navegação principal')
            labels = nav.get_by_role('button', include_hidden=True).all_text_contents()
            for index, text in enumerate(labels):
                label = text.strip()
                try:
                    button = nav.get_by_role('button', name=label, exact=True, include_hidden=True)
                    details = button.locator('xpath=ancestor::details')
                    if details.count() and details.get_attribute('open') is None:
                        details.locator('summary').click()
                    started = time.perf_counter()
                    button.click()
                    tab = page.locator('.workspace-tabs').get_by_role('tab', name=label, exact=True)
                    expect(tab).to_have_attribute('aria-selected', 'true')
                    # Allow the context switch to start its asynchronous resource requests.
                    page.wait_for_timeout(800)
                    page.wait_for_load_state('networkidle')
                    main = page.locator('main')
                    screenshot = f'{index:02d}.png'
                    page.screenshot(path=str(OUT / screenshot))
                    report.append({
                        'view': label, 'opened': True,
                        'headings': main.locator('h1,h2').all_text_contents(),
                        'ms': round((time.perf_counter() - started) * 1000),
                        'screenshot': screenshot, 'text': main.inner_text()[:1200],
                    })
                except Exception as error:
                    report.append({'view': label, 'opened': False, 'error': str(error)[:300]})
        finally:
            (OUT / 'inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            browser.close()


if __name__ == '__main__':
    main()
