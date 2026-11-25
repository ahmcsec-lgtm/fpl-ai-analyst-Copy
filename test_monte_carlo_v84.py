import unittest
from unittest.mock import patch
import numpy as np
import fpl_engine as e
from monte_carlo_v84 import RiskSimulation, score_lineup, paired_risk, SIMULATIONS
from test_decision_v83 import base, player, GWS

class MonteCarloTests(unittest.TestCase):
    def eval(self, value=3.5, **kw):
        squad=base(); extra=player(16,3,(value,)*3)
        with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]), patch.object(e,'projected_minutes',return_value=90):
            return e.smart_transfer_plan(squad,squad+[extra],GWS,{},0,kw.pop('ft',1),kw.pop('strategy','Auto AI'),milp_seeds=False,**kw)
    def sim(self, probability=.7):
        return RiskSimulation({1:(4.,),2:(4.,),3:(4.,),4:(0.,)}, {1:(probability,),2:(probability,),3:(probability,),4:(0.,)}, {1:2,2:2,3:2,4:2},{1:1,2:1,3:2,4:2},lambda pid,wi: 60.)
    def test_distribution_and_common_random_numbers(self):
        sim=self.sim(); play,points=sim.player(1,0)
        self.assertEqual(len(points),SIMULATIONS)
        self.assertAlmostEqual(play.mean(),.7,delta=.02)
        self.assertAlmostEqual(points.mean(),4.,delta=.2)
        self.assertTrue(np.all(points[~play]==0))
        self.assertIs(sim.player(1,0)[1],points)
        self.assertTrue(np.array_equal(self.sim().player(1,0)[1],points))
        self.assertTrue(np.all(sim.player(4,0)[1]==0))
    def test_club_correlation(self):
        s=self.sim(1.); a=s.player(1,0)[1]; b=s.player(2,0)[1]; c=s.player(3,0)[1]
        self.assertGreater(np.corrcoef(a,b)[0,1],np.corrcoef(a,c)[0,1]+.05)
    def test_captain_and_legal_bench(self):
        positions={p['id']:p['element_type'] for p in base()}
        xi=[1,3,4,5,8,9,10,11,12,13,14]; bench=[2,15,6,7]
        vals={i:(np.array([True]),np.array([2.])) for i in range(1,16)}
        vals[1]=(np.array([False]),np.array([0.])); vals[3]=(np.array([False]),np.array([0.])); vals[8]=(np.array([False]),np.array([0.]))
        # 8 playing starters + vice bonus + GK replacement + FWD for missing MID
        # + DEF for missing DEF. First FWD cannot replace DEF in a 3-5-2.
        vals[15]=(np.array([True]),np.array([9.])); vals[6]=(np.array([True]),np.array([5.])); vals[7]=(np.array([True]),np.array([20.]))
        self.assertEqual(score_lineup(vals,xi,bench,8,9,positions)[0],34.)
        vals[8]=(np.array([True]),np.array([2.]))
        # Now FWD cannot replace absent DEF; first eligible DEF only.
        self.assertEqual(score_lineup(vals,xi,bench,8,9,positions)[0],27.)
    def test_hit_cost_once(self):
        s=self.sim(); s.lineup=lambda *a: np.full(s.n,50.)
        weeks=[{'moves':[],'hits':4},{'moves':[],'hits':0}]
        self.assertTrue(np.all(s.plan([],weeks,lambda *a:([],[],1,2))==96))
    def test_paired_margin(self):
        ref=np.array([10.,10.,10.,10.]); a=np.array([0.,5.,15.,20.])
        self.assertEqual(paired_risk(ref,ref,'Balanced')['uncertainty_margin'],0)
        self.assertGreater(paired_risk(a,ref,'Safe')['uncertainty_margin'],paired_risk(a,ref,'Aggressive')['uncertainty_margin'])
        self.assertEqual(paired_risk(a,ref,'Balanced')['win_probability'],.5)
    def test_active_changes_close_decision(self):
        current=self.eval()
        with patch('monte_carlo_v84.evaluate_states',side_effect=RuntimeError('test')): legacy=self.eval()
        self.assertEqual(legacy['action'],'TRANSFER'); self.assertEqual(current['action'],'ROLL')
        self.assertEqual(current['monte_carlo']['status'],'active')
        self.assertEqual(current['monte_carlo']['best_transfer']['samples'],SIMULATIONS)
        self.assertEqual(current['ranked_plans'][0]['first_action'],current['recommended_option'])
        self.assertAlmostEqual(current['transfer_first_net_xp'],legacy['transfer_first_net_xp'])
    def test_large_gain_and_manual_strategy(self):
        for strategy in ('Auto AI','Safe','Balanced','Aggressive'):
            r=self.eval(12.,strategy=strategy)
            self.assertEqual(r['action'],'TRANSFER'); self.assertEqual(r['monte_carlo']['status'],'active')
            self.assertEqual(r['strategy_used'],strategy)
    def test_constraints_and_fallback(self):
        r=self.eval(12.,ft=0,allow_hits=False,max_transfers=0)
        self.assertEqual(r['action'],'ROLL'); self.assertTrue(all(not w['moves'] for p in r['ranked_plans'] for w in p['plan']))
        with patch('monte_carlo_v84.evaluate_states',side_effect=TimeoutError): fallback=self.eval(12.)
        self.assertEqual(fallback['monte_carlo']['status'],'fallback'); self.assertEqual(fallback['action'],'TRANSFER')
        self.assertIsNone(fallback['monte_carlo']['recommended'])
    def test_timeout(self):
        s=self.sim(); s.deadline=0
        with self.assertRaises(TimeoutError): s.player(1,0)

if __name__=='__main__': unittest.main()
