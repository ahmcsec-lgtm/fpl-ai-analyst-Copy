"""Offline UI contract tests. Does not require Streamlit or access FPL API."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
import fpl_engine as engine
from test_decision_v83 import base, player, GWS

SOURCE = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)


def calls(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and
            ((isinstance(n.func, ast.Name) and n.func.id == name) or
             (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


class MinimalUIContract(unittest.TestCase):
    def test_navigation(self):
        nav = [n for n in calls(TREE, 'radio') if any(k.arg == 'key' and
               isinstance(k.value, ast.Constant) and k.value.value == 'v831_navigation' for k in n.keywords)]
        self.assertEqual(len(nav), 1)
        self.assertEqual(ast.literal_eval(nav[0].args[1]), ['My Team', 'Smart Transfers', 'Wildcard / Free Hit'])
        self.assertFalse(calls(TREE, 'tabs'))
        for name in ('smart_transfer_plan', 'optimise_chip_v821', 'render_learning_dashboard'):
            self.assertEqual(len(calls(TREE, name)), 1)
        self.assertNotIn('Top five eligible replacements', SOURCE)
        self.assertNotIn('PLAYER PRICE WATCH', SOURCE)
        self.assertNotIn('MILP relative gap:', SOURCE)

    def test_shared_settings(self):
        for key in ('ajk_start_gw', 'ajk_horizon', 'v83_strategy_widget', 'ajk_free_transfers', 'v83_hits', 'v83_max'):
            widgets = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and any(
                k.arg == 'key' and isinstance(k.value, ast.Constant) and k.value.value == key for k in n.keywords)]
            self.assertEqual(len(widgets), 1, key)
            self.assertLess(widgets[0].lineno, SOURCE[:SOURCE.index('if page == "My Team":')].count('\n')+1)

    def test_decision_call_contract(self):
        node, = calls(TREE, 'smart_transfer_plan')
        self.assertEqual([ast.unparse(x) for x in node.args], ['squad', 'players', 'gws', 'fixture_map', 'bank'])
        self.assertEqual({k.arg: ast.unparse(k.value) for k in node.keywords}, {
            'free_transfers':'ft', 'strategy':'strategy', 'minutes_overrides':'minutes_overrides',
            'allow_hits':'allow_hits', 'max_transfers':'max_transfers'})

    def test_recommendation_parity(self):
        # Execute the exact call expression wired into the new UI, and compare
        # against the V8.3 calling contract with identical controlled inputs.
        node, = calls(TREE, 'smart_transfer_plan')
        ui_call = compile(ast.Expression(body=node), '<UI transfer call>', 'eval')
        for xp, ft, hits, max_t in [((3.1,3.1,3.1),1,True,3), ((12,12,12),1,True,3), ((0,13,13),1,True,3), ((12,12,12),0,False,3), ((12,12,12),1,True,0)]:
            squad = base(); players = squad + [player(16,3,xp)]
            context = dict(squad=squad, players=players, gws=GWS, fixture_map={}, bank=0, ft=ft, strategy='Auto AI', minutes_overrides={}, allow_hits=hits, max_transfers=max_t, smart_transfer_plan=engine.smart_transfer_plan)
            with patch.object(engine,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]), patch.object(engine,'projected_minutes',return_value=90), patch('decision_v83.seed_moves',return_value=[]):
                before = engine.smart_transfer_plan(squad, players, GWS, {}, 0, free_transfers=ft, strategy='Auto AI', minutes_overrides={}, allow_hits=hits, max_transfers=max_t)
                after = eval(ui_call, context)
            self.assertEqual(before['action'], after['action'])
            self.assertEqual(before['ranked_plans'], after['ranked_plans'])

    def test_automatic_chip_fallback(self):
        node, = calls(TREE,'optimise_chip_v821')
        self.assertEqual(ast.unparse(next(k.value for k in node.keywords if k.arg=='method')), 'solver_choice')
        assignments = [n for n in ast.walk(TREE) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='solver_choice' for t in n.targets)]
        self.assertEqual(len(assignments),1)
        self.assertEqual(ast.literal_eval(assignments[0].value),'MILP')

if __name__ == '__main__': unittest.main()
