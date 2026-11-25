import unittest
from unittest.mock import patch
from collections import Counter
from time import perf_counter
import os
import importlib.util
import fpl_engine as e
from decision_v83 import adaptive_margin, ft_value, seed_moves

GWS=[11,12,13]
POSITIONS=[1]*2+[2]*5+[3]*5+[4]*3

def player(i,pos,values=(3,3,3),cost=50,**kw):
    return dict(id=i,element_type=pos,team=(i-1)%20+1,now_cost=cost,selling_price=cost,status='a',web_name=f'P{i}',xp=dict(zip(GWS,values)),**kw)

def base(): return [player(i,p) for i,p in enumerate(POSITIONS,1)]

class DecisionTests(unittest.TestCase):
    def evaluate(self, extra=(), ft=1, **kwargs):
        squad=base(); start=perf_counter()
        with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]), patch.object(e,'projected_minutes',return_value=90):
            r=e.smart_transfer_plan(squad,squad+list(extra),GWS,{},0,ft,'Auto AI',milp_seeds=False,**kwargs)
        self.assertEqual(r['ranked_plans'][0]['first_action'],r['recommended_option'])
        self.assertEqual(sum(x['recommended'] for x in r['options']),1)
        for p in r['ranked_plans']:
            self.assertAlmostEqual(sum(w['net_xp'] for w in p['plan']),p['planned_net_xp'],delta=.04)
            self.assertTrue(all(w['bank']>=0 for w in p['plan']))
        print(f'Auto AI synthetic case: {perf_counter()-start:.3f}s')
        return r
    def test_equal_roll(self): self.assertEqual(self.evaluate()['action'],'ROLL')
    def test_small_edge_roll(self): self.assertEqual(self.evaluate([player(16,3,(3.1,3.1,3.1))])['action'],'ROLL')
    def test_large_gain(self): self.assertEqual(self.evaluate([player(16,3,(12,12,12))])['action'],'TRANSFER')
    def test_future_wait(self): self.assertEqual(self.evaluate([player(16,3,(0,13,13))])['action'],'ROLL')
    def test_no_hits(self):
        r=self.evaluate([player(16,3,(12,12,12))],ft=0,allow_hits=False)
        self.assertEqual(r['action'],'ROLL')
        self.assertTrue(all(p['total_hits']==0 for p in r['ranked_plans']))
    def test_max_zero(self):
        r=self.evaluate([player(16,3,(12,12,12))],max_transfers=0)
        self.assertTrue(all(not w['moves'] for p in r['ranked_plans'] for w in p['plan']))
    def test_unaffordable(self): self.assertEqual(self.evaluate([player(16,3,(20,20,20),cost=100)])['action'],'ROLL')
    def test_margin(self):
        self.assertLess(adaptive_margin(6,5,1,0),adaptive_margin(6,1,1,0))
        self.assertLess(adaptive_margin(6,1,1,8),adaptive_margin(6,1,1,0))
        self.assertGreater(adaptive_margin(6,1,3,0),adaptive_margin(6,1,1,0))
        self.assertEqual(ft_value(5,1,False),0)
        self.assertGreater(ft_value(2,1.6),ft_value(2,.6))
    def test_milp_seed(self):
        if not (importlib.util.find_spec('pulp') and importlib.util.find_spec('highspy')):
            if os.environ.get('AJK_REQUIRE_HIGHS')=='1': self.fail('Missing production solver')
            self.skipTest('PuLP/highspy unavailable locally')
        squad=base(); market={p['id']:p for p in squad+[player(16,3,(15,15,15))]}; ids=tuple(range(1,16)); sales={i:50 for i in ids}; prices={i:50 for i in market}; xp={i:tuple(p['xp'][g] for g in GWS) for i,p in market.items()}
        result=seed_moves(market,ids,sales,prices,xp,GWS,[16],0,1,False,1)
        self.assertTrue(result); self.assertEqual(result[0][0][1],16)
        self.assertEqual(market[result[0][0][0]]['element_type'],3)
    def test_seed_formulation_scipy(self):
        from test_milp_v82 import scipy_backend
        squad=base(); market={p['id']:p for p in squad+[player(16,3,(15,15,15))]}
        ids=tuple(range(1,16)); sales={i:50 for i in ids}; prices={i:50 for i in market}
        xp={i:tuple(p['xp'][g] for g in GWS) for i,p in market.items()}
        with patch('milp_v82.solve_highs',side_effect=lambda obj,rows,time_limit:scipy_backend(obj,rows)):
            result=seed_moves(market,ids,sales,prices,xp,GWS,[16],0,1,False,1)
        self.assertTrue(result); self.assertEqual(result[0][0][1],16)
        self.assertEqual(market[result[0][0][0]]['element_type'],3)
    def test_seed_fallback(self):
        squad=base(); extra=player(16,3,(12,12,12))
        with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]), patch.object(e,'projected_minutes',return_value=90), patch('decision_v83.seed_moves',side_effect=RuntimeError('solver offline')):
            r=e.smart_transfer_plan(squad,squad+[extra],GWS,{},0,1,'Auto AI')
        self.assertEqual(r['action'],'TRANSFER'); self.assertEqual(r['milp_seed_count'],0)

if __name__=='__main__': unittest.main()
