import tempfile, unittest
from pathlib import Path
from learning_foundation import write, paired, metrics, prior_rows, stamp, baseline, season_of

class LearningTests(unittest.TestCase):
    def test_metrics(self):
        r=[{'predicted_xp':4,'actual_points':2},{'predicted_xp':1,'actual_points':3}]
        self.assertEqual(metrics(r,'predicted_xp'),{'n':2,'mae':2,'rmse':2,'bias':0})
    def test_archive_and_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); deadline='2026-11-21T11:00:00Z'
            f={'gw':11,'captured_utc':'2026-11-20T11:00:00Z','deadline_utc':deadline,'rows':[{'player_id':1,'predicted_xp':3,'raw_xp':3,'position':3},{'player_id':2,'predicted_xp':2}]}
            a={'gw':11,'deadline_utc':deadline,'observed_utc':'2026-11-24T12:00:00Z','elements':[{'id':1,'stats':{'total_points':-1,'minutes':90}}]}
            write(p/'forecasts/gw11.json',f); self.assertEqual(paired(p),[])
            write(p/'actuals/gw11.json',a); self.assertEqual(len(paired(p)),1)
            self.assertEqual(prior_rows(p,12,stamp('2026-11-23T12:00:00Z')),[])
            self.assertEqual(len(prior_rows(p,12,stamp('2026-11-25T12:00:00Z'))),1)
            self.assertEqual(baseline([a],12,stamp('2026-11-25T12:00:00Z')),{1:-1})
            f['captured_utc']=deadline; write(p/'forecasts/gw11.json',f); self.assertEqual(paired(p),[])
    def test_season(self):
        self.assertEqual(season_of([{'id':1,'deadline_time':'2026-08-15T10:00:00Z'}]),'2026-27')
if __name__=='__main__': unittest.main()
