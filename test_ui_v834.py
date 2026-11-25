"""Offline layout contracts. No live FPL or Streamlit required."""
import ast
import unittest
from pathlib import Path
from test_ui_v833 import sorted_digest
SOURCE=Path(__file__).with_name('app.py').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
class LayoutTests(unittest.TestCase):
    def test_overview_order(self):
        self.assertIn('grid-template-columns:repeat(5,minmax(0,1fr))',SOURCE)
        self.assertLess(SOURCE.index('with overview_col:'),SOURCE.index('with upcoming_col:'))
        self.assertLess(SOURCE.index('with upcoming_col:'),SOURCE.index('with pitch_col:'))
        self.assertNotIn('st.columns([1, 3.3, 1]',SOURCE)
    def test_portrait_callbacks(self):
        nodes={n.name:n for n in ast.walk(TREE) if isinstance(n,ast.FunctionDef)}
        for name in ['clickable_pitch','pitch','pitch_player_card','player_photo_url','on_pitch_player_click']:
            self.assertIn(name,nodes)
        node=nodes['player_button']
        self.assertIn('player_photo_url(player)',ast.unparse(node))
        self.assertIn('on_click=on_click',ast.unparse(node))
        self.assertIn('args=(pid,)',ast.unparse(node))
        self.assertIn('fixture_badge',ast.unparse(node))
        self.assertIn('player_fixture_xp',ast.unparse(node))
    def test_pitch_compact_css(self):
        self.assertIn('height:55px!important;max-height:55px!important',SOURCE)
        self.assertIn('.squad-view .squad-player .player-portrait',SOURCE)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',SOURCE)
    def test_news_and_preview_retained(self):
        self.assertIn('projected_minutes(p, preview_gw)',SOURCE)
        self.assertIn('player_status_label(p, preview_gw)',SOURCE)
        self.assertIn('preview_scheduled_plan(',SOURCE)
        self.assertIn('Preview FT</span>',SOURCE)
if __name__=='__main__': unittest.main()
