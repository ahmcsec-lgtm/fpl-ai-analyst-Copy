"""Synthetic 300-player six-GW chip strategy, bounded search, no API."""
import random
from time import perf_counter
from unittest.mock import patch
import fpl_engine as e
from chip_strategy_v86 import analyse, CHIPS
from test_decision_v83 import player,POSITIONS
rng=random.Random(86); weeks=list(range(11,17)); pool=[]
for i in range(1,301):
    p=player(i,POSITIONS[i-1] if i<=15 else i%4+1,cost=50 if i<=15 else rng.randint(40,100)); p['xp']={g:rng.uniform(1,8) for g in weeks}; pool.append(p)
f={(g,t):[{}] for g in weeks for t in range(1,21)}
start=perf_counter()
with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]),patch.object(e,'projected_minutes',return_value=80):
    r=analyse(pool[:15],pool,weeks,f,250,2,'Auto AI',list(CHIPS),use_milp=False,timeout=40)
print(f'V8.6: {perf_counter()-start:.3f}s; action={r["action"]}; candidates={len(r["rows"])}; samples={r["samples"]}; solver=bounded Fast Greedy')
