import unittest
from unittest.mock import patch
from decision_v85 import flexibility_value, timing_adjustment, urgency_for, evidence
from test_decision_v83 import base, player, GWS
import fpl_engine as e

class DynamicTests(unittest.TestCase):
    def test_ft(self):
        self.assertEqual(flexibility_value(6,8),flexibility_value(5,8))
        self.assertEqual(flexibility_value(5,8,False),0)
        self.assertGreater(flexibility_value(3,8),flexibility_value(3,0))
        self.assertGreater(flexibility_value(2,8)-flexibility_value(1,8),flexibility_value(5,8)-flexibility_value(4,8))
    def test_timing(self):
        def cost(ft=1,gain=0,urgency=0,strategy='Balanced',remaining=True,opp=6):
            return timing_adjustment(1,ft,gain,opp,urgency,strategy,remaining)
        self.assertGreater(cost(),cost(gain=3))
        self.assertGreater(cost(),cost(urgency=1))
        self.assertGreater(cost(),cost(ft=5))
        self.assertGreater(cost(),cost(opp=0))
        self.assertGreater(cost(strategy='Safe'),cost(strategy='Aggressive'))
        self.assertEqual(cost(remaining=False),0)
    def test_urgency(self):
        moves=[{'out':1,'in':2}]; probs={1:(.1,),2:(.9,)}
        self.assertAlmostEqual(urgency_for(moves,probs,[1]),.8)
        self.assertEqual(urgency_for(moves,probs,[]),0)
    def evaluate(self, vals, **kw):
        sq=base(); extra=player(16,3,vals)
        with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]),patch.object(e,'projected_minutes',return_value=90):
            return e.smart_transfer_plan(sq,sq+[extra],GWS,{},0,kw.pop('ft',1),kw.pop('strategy','Auto AI'),milp_seeds=False,**kw)
    def test_wait(self):
        r=self.evaluate((0,13,13)); self.assertEqual(r['action'],'ROLL'); self.assertEqual(r['decision_version'],'8.5'); self.assertIn('P16',r['dynamic_decision']['explanation'])
    def test_now(self):
        r=self.evaluate((12,12,12)); self.assertEqual(r['action'],'TRANSFER'); self.assertEqual(r['monte_carlo']['status'],'active'); self.assertIn('P16',r['dynamic_decision']['explanation']); self.assertFalse(r['dynamic_decision']['calibrated'])
        self.assertAlmostEqual(sum(w['net_xp'] for w in r['plan']),r['planned_net_xp'],delta=.04)
    def test_no_hits(self):
        r=self.evaluate((12,12,12),ft=0,allow_hits=False); self.assertEqual(r['action'],'ROLL'); self.assertTrue(all(p['total_hits']==0 for p in r['ranked_plans']))
    def test_fallback(self):
        with patch('monte_carlo_v84.evaluate_states',side_effect=TimeoutError): r=self.evaluate((12,12,12))
        self.assertEqual(r['dynamic_decision']['confidence'],'Limited'); self.assertEqual(r['dynamic_decision']['timing_cost'],0)
    def test_evidence_without_alternative(self):
        r=self.evaluate((12,12,12),max_transfers=0); self.assertEqual(r['dynamic_decision']['confidence'],'Limited'); self.assertIsNone(r['dynamic_decision']['score_gap'])
