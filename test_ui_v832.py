"""Offline regression checks for the native planning popover."""
import ast
import requests
import unittest
from pathlib import Path
from contextlib import nullcontext

SOURCE = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
BLOCK = SOURCE[SOURCE.index('team_loaded = bool('):SOURCE.index('# Before the first successful import')]

class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__

class FakeStreamlit:
    def __init__(self, state, submitted=False, text=''):
        self.session_state = State(state)
        self.submitted, self.text = submitted, text
        self.popovers = []
        self.captions = []
        self.errors = []
        self.keys = []
    def columns(self, spec, **kw): return [nullcontext() for _ in range(spec if isinstance(spec,int) else len(spec))]
    def container(self, **kw): return nullcontext()
    def form(self, key): return nullcontext()
    def popover(self, label, **kw):
        self.popovers.append(label)
        return nullcontext()
    def empty(self): return self
    def caption(self, text): self.captions.append(text)
    def text_input(self, *args, **kw): return self.text
    def form_submit_button(self, *args, **kw): return self.submitted
    def error(self, text): self.errors.append(text)
    def selectbox(self, label, options, key, index=0, **kw):
        self.keys.append(key)
        return self.session_state.setdefault(key, options[index])
    def number_input(self, label, key, **kw):
        self.keys.append(key)
        return self.session_state.setdefault(key, 1)
    def checkbox(self, label, value, key):
        self.keys.append(key)
        return self.session_state.setdefault(key, value)
    def rerun(self): raise Rerun()

class Rerun(Exception): pass

class PopoverTests(unittest.TestCase):
    def run_block(self, state, submitted=False, text=''):
        st = FakeStreamlit(state, submitted, text)
        env = dict(st=st, available_gws=list(range(12,18)), free_transfer_was_edited=lambda:None)
        exec(BLOCK, env)
        return st, env
    def test_landing(self):
        st, env = self.run_block({})
        self.assertFalse(st.popovers)
        self.assertFalse(st.keys)
        self.assertFalse(env['submitted'])
    def test_existing_values_survive_rerun(self):
        state = dict(loaded_id=42, v831_navigation='Smart Transfers', manager_profile={'name':'Test FC'}, ajk_start_gw=13, ajk_horizon=3, v83_saved_strategy='Safe', v83_strategy_widget='Safe', ajk_free_transfers=4, v83_hits=False, v83_max=2, ajk_ft_manual_override=True)
        st, env = self.run_block(state)
        self.assertEqual(st.popovers,['⚙️ Settings'])
        self.assertEqual(tuple(env[k] for k in ('selected_gw','horizon','strategy','ft','allow_hits','max_transfers')), (13,3,'Safe',4,False,2))
        self.assertIn('Test FC · GW 13–15 · Safe · 4 FT',st.captions)
        st2, env2 = self.run_block(st.session_state)
        self.assertEqual(st2.session_state,st.session_state)
        self.assertEqual(st2.keys,st.keys)
    def test_invalid_gw_and_horizon(self):
        st, env = self.run_block(dict(loaded_id=42,v831_navigation='Smart Transfers',ajk_start_gw=17,ajk_horizon=6))
        self.assertEqual(env['horizon'],1)
        self.assertIn('My Team · GW 17–17 · Auto AI · 1 FT',st.captions)
    def test_invalid_import(self):
        st, env = self.run_block(dict(loaded_id=42),True,'invalid')
        self.assertEqual(st.errors,['Enter a valid numeric FPL Team ID.'])
    def test_native_popover_and_stable_label(self):
        nodes=[n for n in ast.walk(TREE) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='popover']
        self.assertTrue(any(isinstance(n.args[0],ast.Constant) and n.args[0].value=='⚙️ Settings' for n in nodes))
        self.assertNotIn('expanded=expand_after_import',SOURCE)
    def test_successful_import_preserves_refresh(self):
        st=FakeStreamlit(dict(loaded_id=42),True,'123')
        calls=[]
        env=dict(st=st,requests=requests,available_gws=list(range(12,18)),free_transfer_was_edited=lambda:None,events=[],player_by_id={},load_manager=lambda *a:({'name':'New FC'},[],12,11),reset_draft=lambda *a:calls.append(a))
        with self.assertRaises(Rerun): exec(BLOCK,env)
        self.assertEqual(calls,[(123,{'name':'New FC'},[],12,11)])
        self.assertTrue(st.session_state.ajk_ft_refresh_after_import)

if __name__=='__main__': unittest.main()
