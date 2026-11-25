import unittest, tempfile
from pathlib import Path
import pandas as pd
from ml_v81 import *
class Tests(unittest.TestCase):
    def test_cutoff(self):
        a=[{'gw':g,'observed_utc':f'2026-08-{g:02d}T00:00:00Z','elements':[{'id':1,'stats':{'total_points':g}}]} for g in (1,2,3,4,5)]
        self.assertEqual([r['total_points'] for r in live_history(a,1,5,stamp('2026-08-02T12:00:00Z'))],[1,2])
    def test_blend(self):
        self.assertEqual(blend(4,8,.25),5); self.assertEqual(blend(4,8,0),4)
    def test_lag_and_walk_forward(self):
        rows=[]
        for g in range(1,39):
            for p in range(1,41):
                rows.append({'element':p,'GW':g,'position':'MID','fixture':g,'kickoff_time':(pd.Timestamp('2020-08-01',tz='UTC')+pd.Timedelta(days=7*g)).isoformat(),**{s:g if s=='total_points' else 60 if s=='minutes' else 0 for s in STATS}})
        d=historical_frame(pd.DataFrame(rows),'2020-21')
        self.assertTrue((d.total_points_3<d.points).all())
        self.assertEqual(d.gw.min(),5)
        ds=pd.concat([d.assign(season=s) for s in SEASONS[:3]])
        folds=walk_forward(ds); self.assertEqual(len(folds),1); self.assertEqual(folds[0]['test'],SEASONS[2]); self.assertNotIn(folds[0]['test'],folds[0]['train'])
    def test_model_roundtrip(self):
        d=pd.DataFrame([{**features(3,[{s:float(i%5) for s in STATS}]*4),'points':i%5} for i in range(200)])
        with tempfile.TemporaryDirectory() as tmp:
            from lightgbm import Booster
            p=Path(tmp)/'m.txt'; fit(d,'points').booster_.save_model(str(p)); self.assertEqual(len(Booster(model_file=str(p)).predict(d[FEATURES],num_threads=1)),200)
if __name__=='__main__': unittest.main()
