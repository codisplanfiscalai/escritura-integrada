"""Keep the CI scenarios aligned with asynchronous UI startup and shared dialogs."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class RebuiltBrowserContracts(unittest.TestCase):
    def test_context_waits_for_hydrated_session_before_keyboard_shortcut(self):
        code=(ROOT/'scripts/browser_workspace_context.py').read_text()
        start=code.index('page.reload()')
        self.assertLess(code.index("expect(page.locator('#active-company')).to_have_value(str(cid))",start),code.index("page.keyboard.press('F8')",start))
        self.assertLess(code.index("name='Fixar empresa, ano e competência (F8)'",start),code.index("page.keyboard.press('F8')",start))
    def test_series_cancel_uses_shared_confirmation_button(self):
        code=(ROOT/'scripts/browser_fiscal_series.py').read_text()
        self.assertIn("question.get_by_role('button',name='Voltar',exact=True).click()",code)
        self.assertIn('@click="answer(false)">Voltar</button>',(ROOT/'frontend/src/App.vue').read_text())
        self.assertNotIn("question.get_by_role('button',name='Cancelar'",code)
