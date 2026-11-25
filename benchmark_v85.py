"""Offline end-to-end transfer-search benchmark, no FPL network calls."""
import random
from time import perf_counter
from unittest.mock import patch
import fpl_engine as e
from test_decision_v83 import player, POSITIONS

rng=random.Random(84)
weeks=list(range(11,17)); pool=[]
for i in range(1,301):
    pos=POSITIONS[i-1] if i<=15 else i%4+1
    p=player(i,pos,cost=rng.randint(40,100))
    p['xp']={g:rng.uniform(1,8) for g in weeks}; pool.append(p)
for mode in ('V8.5',):
    start=perf_counter()
    with patch.object(e,'player_fixture_xp',side_effect=lambda p,g,*a:p['xp'][g]),patch.object(e,'projected_minutes',return_value=80):
        if mode=='legacy fallback':
            with patch('monte_carlo_v84.evaluate_states',side_effect=RuntimeError('benchmark baseline')):
                result=e.smart_transfer_plan(pool[:15],pool,weeks,{},50,2,'Auto AI',milp_seeds=False,beam_width=4,candidate_count=5)
        else:
            result=e.smart_transfer_plan(pool[:15],pool,weeks,{},50,2,'Auto AI',milp_seeds=False,beam_width=4,candidate_count=5)
    elapsed=perf_counter()-start
    print(f'{mode}: {elapsed:.3f}s; action={result["action"]}; risk={result["monte_carlo"]["status"]}; plans={result["monte_carlo"]["evaluated_plans"]}')
