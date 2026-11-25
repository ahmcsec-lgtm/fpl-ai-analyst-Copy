import unittest
from unittest.mock import patch
import sys
import types
from milp_v82 import solve_squad, solve_highs, formulate, decode, SolverUnavailable, optimise_chip_v82, QUOTAS
from install_v82 import patch as patch_app


def scipy_backend(obj, rows):
    import numpy as np
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_matrix
    keys=list(obj); ix={k:i for i,k in enumerate(keys)}
    rr=[]; cc=[]; vv=[]
    for r,(coefs,lo,hi) in enumerate(rows):
        for k,v in coefs.items(): rr.append(r); cc.append(ix[k]); vv.append(v)
    A=coo_matrix((vv,(rr,cc)),shape=(len(rows),len(keys))).tocsc()
    res=milp(-np.array(list(obj.values())),integrality=np.ones(len(keys)),bounds=Bounds(0,1),constraints=LinearConstraint(A,[r[1] for r in rows],[r[2] for r in rows]),options={'time_limit':15})
    return dict(zip(keys,res.x)) if res.x is not None else {},str(res.message),getattr(res,'mip_gap',None)


def pool():
    players=[]; xp={}
    for pos,q in QUOTAS.items():
        for j in range(q+2):
            i=len(players)+1
            players.append(dict(id=i,element_type=pos,team=(i%9)+1,now_cost=40+5*j,status='a',web_name=str(i)))
            xp[i,12]=float(j+1); xp[i,13]=float(q+2-j)
    return players,xp


class Tests(unittest.TestCase):
    def verify(self,backend):
        p,x=pool(); r=solve_squad(p,[12,13],x,760,backend)
        from collections import Counter
        self.assertEqual(Counter(t['element_type'] for t in r['squad']),QUOTAS)
        self.assertLessEqual(sum(t['now_cost'] for t in r['squad']),760)
        self.assertLessEqual(max(Counter(t['team'] for t in r['squad']).values()),3)
        for g,l in r['milp_weekly'].items():
            self.assertEqual(len(l['xi']),11); self.assertEqual(len(l['bench']),4)
            self.assertIn(l['captain'],l['xi']); self.assertIn(l['vice'],l['xi']); self.assertNotEqual(l['captain'],l['vice'])
            self.assertEqual(sum(t['element_type']==1 for t in l['xi']),1)
            self.assertGreaterEqual(sum(t['element_type']==2 for t in l['xi']),3)
            self.assertGreaterEqual(sum(t['element_type']==3 for t in l['xi']),2)
            self.assertGreaterEqual(sum(t['element_type']==4 for t in l['xi']),1)
            self.assertEqual({t['id'] for t in l['xi']+l['bench']},{t['id'] for t in r['squad']})
            self.assertAlmostEqual(l['base_xp'],sum(x[t['id'],g] for t in l['xi'])+x[l['captain']['id'],g])
        self.assertNotEqual({t['id'] for t in r['milp_weekly'][12]['xi']},{t['id'] for t in r['milp_weekly'][13]['xi']})
        self.assertAlmostEqual(r['milp_objective'],sum(l['base_xp']+.1*sum(x[t['id'],g] for t in l['bench']) for g,l in r['milp_weekly'].items()),places=3)
    def test_scipy_formulation(self): self.verify(scipy_backend)
    def test_highs_production(self):
        import os
        try: import pulp, highspy
        except ImportError:
            if os.environ.get('AJK_REQUIRE_HIGHS')=='1': raise
            self.skipTest('PuLP/highspy absent locally')
        self.verify(solve_highs)
    def test_infeasible_budget(self):
        p,x=pool()
        with self.assertRaises(SolverUnavailable): solve_squad(p,[12],x,500,scipy_backend)
    def test_fractional_rejected(self):
        p,x=pool(); b,o,r=formulate(p,[12],x,760)
        with self.assertRaises(SolverUnavailable): decode(b,o,r,{k:.5 for k in o},[12],x,'timeout',None)
    def test_free_hit_one_week(self):
        p,x=pool(); r=solve_squad(p,[12],x,760,scipy_backend)
        self.assertEqual(list(r['milp_weekly']),[12])
    def test_fallback(self):
        p,x=pool(); fake=types.SimpleNamespace(player_fixture_xp=lambda p,g,f,m:x[p['id'],g],optimise_chip_squad=lambda *a:{'squad':[],'spent':0,'bank':760,'rating':{}})
        with patch.dict(sys.modules,{'fpl_engine':fake}),patch('milp_v82.solve_squad',side_effect=SolverUnavailable('test')):
            r=optimise_chip_v82(p,[12],{},760)
            self.assertEqual(r['solver_method'],'Original greedy')
    def test_six_weeks(self):
        p,x=pool()
        for g in range(14,18):
            for t in p: x[t['id'],g]=x[t['id'],12 if g%2==0 else 13]
        r=solve_squad(p,list(range(12,18)),x,760,scipy_backend)
        self.assertEqual(len(r['milp_weekly']),6)
    def test_patch_existing_app(self):
        from pathlib import Path
        f=Path(__file__).with_name('app.py')
        if not f.exists(): self.skipTest('Full repository not available locally')
        source=f.read_text(encoding='utf-8'); result=patch_app(source)
        self.assertIn('V8.2 MILP integration',result)
        self.assertEqual(patch_app(result),result)
        self.assertEqual(source.split('with tab_chips:',1)[0],result.split('with tab_chips:',1)[0])
    def test_patch_guard(self):
        with self.assertRaises(ValueError): patch_app('pass')

if __name__=='__main__': unittest.main()
