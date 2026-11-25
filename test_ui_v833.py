"""V8.3.3 offline contracts; baseline fingerprints from V8.3.2."""
import ast, hashlib, unittest
from pathlib import Path
SOURCE = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
def canonical(n):
    if isinstance(n, ast.AST): return (type(n).__name__, tuple((k,canonical(v)) for k,v in ast.iter_fields(n) if k!='type_params'))
    if isinstance(n,list): return tuple(canonical(v) for v in n)
    return n
def sorted_digest(nodes):
    return hashlib.sha256('\n'.join(sorted(repr(canonical(n)) for n in nodes)).encode()).hexdigest()
def calls(names):
    return [n for n in ast.walk(TREE) if isinstance(n,ast.Call) and (getattr(n.func,'id',None) in names or getattr(n.func,'attr',None) in names)]

class ProfessionalDarkTests(unittest.TestCase):
    def test_functions_unchanged(self):
        nodes=[n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='stadium_background_css']
        self.assertEqual(sorted_digest(nodes), '0f026f4d2340d614d19be68a29840f8d24542f39a8d7f014e9e1f613dc32505a')
    def test_engine_calls_unchanged(self):
        self.assertEqual(sorted_digest(calls({'player_prediction', 'join_actuals', 'smart_transfer_plan', 'update_estimated_ft', 'player_fixture_xp', 'configure_projection_context', 'build_applied_plan_preview', 'selected_plan_for_preview', 'configure_availability_context', 'team_rating', 'reset_draft', 'configure_calibration', 'render_learning_dashboard', 'transfer_history_candidates', 'projected_minutes', 'valid_squad', 'clear_pitch_actions', 'refresh_draft_player_data', 'attach_recent_minutes', 'attach_verified_availability_reports', 'validate_snapshots', 'optimise_chip_v821', 'best_lineup', 'preview_scheduled_plan'})), '1c8ea60739c51d3eff503c23d471564b332284818a87ea67284d3922a0ebc5f9')
    def test_input_widgets_unchanged(self):
        self.assertEqual(sorted_digest(calls({'checkbox', 'selectbox', 'number_input', 'popover', 'toggle', 'form_submit_button', 'slider', 'multiselect', 'text_input'})), 'cc78bc8a1346831737338987f787326faf341b3c67e003aa1fa3b94678ee911f')
    def test_session_state_writes_unchanged(self):
        nodes=[n for n in ast.walk(TREE) if isinstance(n,(ast.Assign,ast.AugAssign,ast.AnnAssign)) and any('st.session_state' in ast.unparse(x) for x in (n.targets if isinstance(n,ast.Assign) else [n.target]))]
        self.assertEqual(sorted_digest(nodes), 'cb7d03661779405201f699ec45f9d7514866a42838db65a69c59bd23c141eacf')
    def test_navigation_labels_preserve_values(self):
        nav=next(n for n in calls({'radio'}) if any(k.arg=='key' and ast.literal_eval(k.value)=='v831_navigation' for k in n.keywords if isinstance(k.value,ast.Constant)))
        values=ast.literal_eval(nav.args[1])
        labels=eval(compile(ast.Expression(next(k.value for k in nav.keywords if k.arg=='format_func')), '<labels>', 'eval'))
        self.assertEqual(values,['My Team','Smart Transfers','Wildcard / Free Hit'])
        self.assertEqual([labels(x) for x in values],['Overview','Transfers','Chips'])
    def test_dark_theme_and_decision(self):
        self.assertNotIn('_stadium_css = stadium_background_css()',SOURCE)
        self.assertIn('background:#0d1117!important;background-image:none!important', SOURCE)
        self.assertIn('key="v833_decision"', SOURCE)
        self.assertIn('key="v83_apply"',SOURCE)
        self.assertIn('def clickable_pitch(',SOURCE)
        self.assertIn('Alternative plans & weekly schedule',SOURCE)

if __name__=='__main__': unittest.main()
