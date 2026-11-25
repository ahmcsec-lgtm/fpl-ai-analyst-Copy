"""Offline UI regression contracts for V8.3.5 (no live API required)."""
import ast
import unittest
from pathlib import Path
from test_ui_v833 import sorted_digest
from test_ui_v832 import FakeStreamlit, BLOCK
SOURCE = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)

def calls(name):
    return [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and getattr(n.func, 'attr', '') == name]

class FinalLayoutTests(unittest.TestCase):
    def test_native_controls(self):
        widgets = {n.args[0].value: n for n in calls('segmented_control')}
        self.assertEqual(set(widgets), {'Page', 'Preview Gameweek', 'Simulation'})
        self.assertEqual(ast.literal_eval(widgets['Page'].args[1]), ['My Team', 'Smart Transfers', 'Wildcard / Free Hit'])
        self.assertEqual(next(k.value.value for k in widgets['Page'].keywords if k.arg=='key'), 'v831_navigation')
        self.assertEqual(next(k.value.value for k in widgets['Simulation'].keywords if k.arg=='key'), 'v831_chip_widget')
        self.assertIn('default=preview_gw', ast.unparse(widgets['Preview Gameweek']))
    def test_duplicate_overview_metrics(self):
        st = FakeStreamlit(dict(loaded_id=42, manager_profile={'name':'Test FC'}, v831_navigation='My Team', bank=26))
        exec(BLOCK, dict(st=st, available_gws=list(range(12,18)), free_transfer_was_edited=lambda:None))
        self.assertFalse(any('Bank £' in c for c in st.captions))
        self.assertFalse(any('· 1 FT' in c for c in st.captions))
        self.assertIn('Preview bank</span>', SOURCE)
        self.assertIn('Preview FT</span>', SOURCE)
    def test_transfer_card(self):
        self.assertLess(SOURCE.index('st.markdown(transfer_faces_html(recommended'), SOURCE.index('gain_col.metric("Transfer vs roll"'))
        self.assertIn('max-width:460px!important', SOURCE)
        self.assertIn('key="v83_apply"', SOURCE)
        self.assertIn('Alternative plans & weekly schedule', SOURCE)
    def test_chip_toolbar(self):
        self.assertIn('chip_budget_col.markdown', SOURCE)
        self.assertIn('chip_action_col.button', SOURCE)
        self.assertIn('solver_choice = "MILP"', SOURCE)
    def test_functions_unchanged_since_v834(self):
        nodes = [n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertEqual(sorted_digest(nodes), '0f026f4d2340d614d19be68a29840f8d24542f39a8d7f014e9e1f613dc32505a')

if __name__ == '__main__': unittest.main()
