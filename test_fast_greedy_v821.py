import unittest
from unittest.mock import patch, Mock
from collections import Counter
from time import perf_counter
import sys, types
from fast_greedy_v821 import fast_greedy, validate, projection_cache, optimise_chip_v821
from milp_v82 import QUOTAS, SolverUnavailable
from install_v821 import patch as patch_app

def pool(n=200):
    p=[dict(id=i+1,element_type=i%4+1,team=(i//4)%20+1,now_cost=40+(i%17)*3,status='a') for i in range(n)]
    weeks=list(range(12,18)); x={(t['id'],g):float((t['id']*7+g*3)%23)/3 for t in p for g in weeks}
    return p,weeks,x

class Tests(unittest.TestCase):
    def test_large_pool(self):
        p,w,x=pool(800); start=perf_counter(); r=fast_greedy(p,w,x,1000); elapsed=perf_counter()-start
        print(f'800 players / 6 GW search: {elapsed:.3f}s, {r["greedy_evaluations"]} evaluations')
        self.assertLess(elapsed,7); self.assertLessEqual(r['greedy_iterations'],8); self.assertLessEqual(r['greedy_evaluations'],24+8*15*24)
        validate(r['squad'],1000)
        for g,l in r['milp_weekly'].items():
            self.assertEqual(len(l['xi']),11); self.assertEqual(len(l['bench']),4)
            self.assertEqual(set(t['id'] for t in l['xi']+l['bench']),set(t['id'] for t in r['squad']))
            c=Counter(t['element_type'] for t in l['xi']); self.assertEqual(c[1],1); self.assertGreaterEqual(c[2],3); self.assertGreaterEqual(c[3],2); self.assertGreaterEqual(c[4],1)
            self.assertIn(l['captain'],l['xi']); self.assertIn(l['vice'],l['xi']); self.assertNotEqual(l['captain'],l['vice'])
    def test_timeout(self):
        p,w,x=pool(); ticks=iter([0,0]+[10]*100)
        r=fast_greedy(p,w,x,1000,clock=lambda:next(ticks)); self.assertEqual(r['solver_status'],'Time limit'); validate(r['squad'],1000); self.assertEqual(r['greedy_iterations'],0)
    def test_infeasible(self):
        p,w,x=pool(); self.assertRaises(ValueError,fast_greedy,p,w,x,500)
    def test_cache(self):
        p,w,x=pool(); f=Mock(side_effect=lambda t,g:x[t['id'],g]); self.assertEqual(projection_cache(p,w,f),x); self.assertEqual(f.call_count,len(p)*len(w))
    def test_fallback(self):
        p,w,x=pool(); f=Mock(side_effect=lambda t,g,*a:x[t['id'],g]); rate=Mock(return_value={'rating':50}); fake=types.SimpleNamespace(player_fixture_xp=f,valid_squad=lambda s:True,team_rating=rate,optimise_chip_squad=Mock(side_effect=AssertionError('legacy called')))
        with patch.dict(sys.modules,{'fpl_engine':fake}),patch('fast_greedy_v821.solve_squad',side_effect=SolverUnavailable('test')):
            r=optimise_chip_v821(p,w[:1],{},1000)
        self.assertEqual(r['solver_method'],'Fast Greedy'); self.assertEqual(r['fallback_reason'],'SolverUnavailable'); self.assertEqual(f.call_count,len(p)); rate.assert_called_once(); fake.optimise_chip_squad.assert_not_called(); validate(r['squad'],1000)
    def test_guard(self): self.assertRaises(ValueError,patch_app,'pass')
    def test_installer(self):
        from pathlib import Path
        f=Path(__file__).with_name('app.py')
        if not f.exists(): self.skipTest('Full app absent')
        s=f.read_text(encoding='utf-8'); r=patch_app(s); self.assertEqual(patch_app(r),r); self.assertEqual(s.split('with tab_chips:')[0],r.split('with tab_chips:')[0]); self.assertIn('optimise_chip_v821(',r)
    def test_no_iterations(self):
        p,w,x=pool(); r=fast_greedy(p,w,x,1000,max_iterations=0); self.assertEqual(r['greedy_iterations'],0); validate(r['squad'],1000)
    def test_invalid_squad(self):
        p,w,x=pool(); self.assertRaises(ValueError,validate,[p[0]]*15,1000)
if __name__=='__main__': unittest.main()
