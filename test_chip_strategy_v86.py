import unittest
from unittest.mock import patch
import numpy as np
from chip_strategy_v86 import *
from test_decision_v83 import base, player

class ChipTests(unittest.TestCase):
    def test_inventory(self):
        h={'chips':[{'name':'freehit','event':19},{'name':'wildcard','event':5}]}
        self.assertEqual(history_inventory(h,20),(list(CHIPS),19))
        self.assertFalse(eligible('Free Hit',20,19)); self.assertTrue(eligible('Free Hit',21,19))
        self.assertFalse(eligible('Wildcard',1,None)); self.assertEqual(half_end(19),19)
        self.assertNotIn('Wildcard',history_inventory(h,12)[0]); self.assertRaises(ValueError,history_inventory,{},12)
    def test_fixtures(self):
        s=base(); f={(12,1):[{},{}],(12,2):[{}]}
        self.assertEqual(fixture_context(s,12,f),{'blank_players':13,'double_players':1})
    def test_scoring(self):
        s=base(); ids=[p['id'] for p in s]; pos={p['id']:p['element_type'] for p in s}; clubs={p['id']:p['team'] for p in s}
        sim=RiskSimulation({i:(3.,) for i in ids},{i:(1.,) for i in ids},pos,clubs,lambda *_:90)
        xi=[s[0]]+s[2:5]+s[7:11]+s[12:15]; bench=[p for p in s if p not in xi]; line=dict(xi=xi,bench=bench,captain=xi[-1],vice=xi[-2])
        normal=score_chip(sim,0,line)
        np.testing.assert_allclose(score_chip(sim,0,line,'Triple Captain')-normal,sim.player(xi[-1]['id'],0)[1],atol=2e-5)
        np.testing.assert_allclose(score_chip(sim,0,line,'Bench Boost')-normal,sum(sim.player(p['id'],0)[1] for p in bench),atol=2e-5)
    def test_timing(self):
        rows=[dict(chip='Triple Captain',gw=12,gain=5,utility=5),dict(chip='Triple Captain',gw=13,gain=10,utility=10)]
        self.assertEqual(choose(rows,['Triple Captain'],12,19)['action'],'SAVE')
        self.assertEqual(choose([dict(chip='Triple Captain',gw=19,gain=5,utility=5)],['Triple Captain'],19,19)['action'],'Triple Captain')
        self.assertEqual(choose(rows,['Triple Captain'],12,19,complete=False)['action'],'UNAVAILABLE')
    def test_all_chips(self):
        s=base(); pool=s+[player(16,3,(10,10,10))]; weeks=[11,12]; fixtures={(g,p['team']):[{}] for g in weeks for p in pool}
        plan=[dict(gw=g,moves=[],hits=0,free_transfers_after=2) for g in weeks]
        with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]),patch.object(e,'projected_minutes',return_value=90):
            r=analyse(s,pool,weeks,fixtures,0,1,'Auto AI',list(CHIPS),baseline=plan,use_milp=False)
        self.assertEqual(len(r['rows']),8); self.assertEqual(r['samples'],10000); self.assertIn(r['action'],('SAVE',*CHIPS))
    def test_fh_replay_with_moves(self):
        s=base(); pool=s+[player(16,3,(10,10,10))]; weeks=[11,12]; fixtures={(g,p['team']):[{}] for g in weeks for p in pool}
        plan=[dict(gw=11,moves=[{'out':8,'in':16}],hits=0,free_transfers_after=1),dict(gw=12,moves=[],hits=0,free_transfers_after=2)]
        with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]),patch.object(e,'projected_minutes',return_value=90):
            r=analyse(s,pool,weeks,fixtures,0,1,'Auto AI',['Free Hit'],baseline=plan,use_milp=False)
        self.assertEqual(len(r['rows']),2); self.assertEqual(s[7]['id'],8)
    def test_half_cutoff(self):
        self.assertEqual(analyse(base(),base(),[19,20],{},0,1,'Auto AI',[])['action'],'SAVE')
    def test_timeout(self):
        with self.assertRaises(TimeoutError): analyse(base(),base(),[11],{},0,1,'Auto AI',['Bench Boost'],baseline=[dict(gw=11,moves=[],hits=0,free_transfers_after=2)],timeout=-1)
if __name__=='__main__': unittest.main()
