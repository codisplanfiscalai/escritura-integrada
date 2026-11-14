"""Keep the CI scenarios aligned with asynchronous UI startup and shared dialogs."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class RebuiltBrowserContracts(unittest.TestCase):
    def test_context_waits_for_hydrated_session_before_keyboard_shortcut(self):
        code=(ROOT/'scripts/browser_workspace_context.py').read_text(encoding='utf-8')
        start=code.index('page.reload()')
        self.assertLess(code.index("expect(page.locator('#active-company')).to_have_value(str(cid))",start),code.index("page.keyboard.press('F8')",start))
        self.assertLess(code.index("name='Fixar empresa, ano e competência (F8)'",start),code.index("page.keyboard.press('F8')",start))
    def test_series_cancel_uses_shared_confirmation_button(self):
        code=(ROOT/'scripts/browser_fiscal_series.py').read_text(encoding='utf-8')
        self.assertIn("question.get_by_role('button',name='Voltar',exact=True).click()",code)
        self.assertIn('@click="answer(false)">Voltar</button>',(ROOT/'frontend/src/App.vue').read_text(encoding='utf-8'))
        self.assertNotIn("question.get_by_role('button',name='Cancelar'",code)

    def test_journal_keyboard_waits_for_ready_button_and_visible_dialog(self):
        code=(ROOT/'scripts/browser_evolution.py').read_text(encoding='utf-8')
        start=code.index("nav('Lançamentos contábeis')")
        end=code.index("keyboard(date_field('Data do lançamento *')",start)
        block=code[start:end]
        enabled=block.index('expect(new_journal).to_be_enabled()')
        focus=block.index('new_journal.focus()')
        focused=block.index('expect(new_journal).to_be_focused()')
        enter=block.index("page.keyboard.press('Enter')")
        dialog=block.index("name='Novo lançamento contábil'")
        self.assertLess(enabled,focus);self.assertLess(focus,focused)
        self.assertLess(focused,enter);self.assertLess(enter,dialog)
        self.assertNotIn('wait_for_timeout',block)
        view=(ROOT/'frontend/src/views/JournalView.vue').read_text(encoding='utf-8')
        self.assertIn(':disabled="loading||state.contextBusy"',view)
        self.assertIn('if(!afterSave&&(loading.value||state.contextBusy))return;',view)
