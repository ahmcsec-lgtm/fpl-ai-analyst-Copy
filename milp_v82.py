"""V8.2: fixed-squad multi-GW MILP, with validated incumbent and legacy fallback."""
from collections import Counter
import math
import logging
from threading import Lock

QUOTAS = {1: 2, 2: 5, 3: 5, 4: 3}
MIN_XI = {1: 1, 2: 3, 3: 2, 4: 1}
MAX_XI = {1: 1, 2: 5, 3: 5, 4: 3}
BENCH_WEIGHT = .10
_LOCK = Lock()

class SolverUnavailable(RuntimeError):
    pass


def formulate(players, weeks, xp, budget, bench_weight=BENCH_WEIGHT):
    """Backend-independent binary linear formulation. Prices in FPL tenths."""
    if not 1 <= len(weeks) <= 6 or len(set(weeks)) != len(weeks):
        raise ValueError('Choose 1–6 distinct gameweeks.')
    if not 0 <= bench_weight <= 1 or budget < 0:
        raise ValueError('Invalid budget or bench weight.')
    by_id = {}
    for p in players:
        i = int(p['id']); pos = int(p['element_type']); cost = int(p['now_cost'])
        if pos not in QUOTAS or cost <= 0 or p.get('status') in ('u','n') or cost > budget:
            continue
        if i in by_id:
            raise ValueError('Duplicate player ID.')
        by_id[i] = p
    ids = sorted(by_id)
    groups = {pos: [i for i in ids if int(by_id[i]['element_type']) == pos] for pos in QUOTAS}
    if any(len(groups[pos]) < q for pos,q in QUOTAS.items()):
        raise ValueError('Not enough eligible players.')
    obj = {}; constraints = []
    def add(coefs, lo, hi): constraints.append((coefs, lo, hi))
    for i in ids:
        values = [float(xp[i,g]) for g in weeks]
        if not all(math.isfinite(x) for x in values):
            raise ValueError('Non-finite projection.')
        obj['s',i] = bench_weight * sum(values)
        for g,x in zip(weeks,values):
            obj['x',i,g] = (1-bench_weight)*x
            obj['c',i,g] = x
            add({('x',i,g):1,('s',i):-1}, -math.inf,0)
            add({('c',i,g):1,('x',i,g):-1}, -math.inf,0)
    for pos,q in QUOTAS.items():
        add({('s',i):1 for i in groups[pos]},q,q)
    for club in {int(p['team']) for p in by_id.values()}:
        add({('s',i):1 for i in ids if int(by_id[i]['team'])==club},0,3)
    add({('s',i):int(by_id[i]['now_cost']) for i in ids},0,budget)
    for g in weeks:
        add({('x',i,g):1 for i in ids},11,11)
        add({('c',i,g):1 for i in ids},1,1)
        for pos in QUOTAS:
            add({('x',i,g):1 for i in groups[pos]},MIN_XI[pos],MAX_XI[pos])
    return by_id,obj,constraints


def solve_highs(obj, constraints, time_limit=15):
    import pulp
    problem=pulp.LpProblem('AJK_v82',pulp.LpMaximize)
    variables={k:pulp.LpVariable('v_'+ '_'.join(map(str,k)),cat='Binary') for k in obj}
    problem += pulp.lpSum(v*variables[k] for k,v in obj.items())
    for row,lo,hi in constraints:
        expr=pulp.lpSum(v*variables[k] for k,v in row.items())
        if lo==hi: problem += expr==lo
        else:
            if math.isfinite(lo): problem += expr>=lo
            if math.isfinite(hi): problem += expr<=hi
    solver=pulp.HiGHS(msg=False,timeLimit=time_limit,gapRel=0.005,threads=1)
    if not solver.available(): raise SolverUnavailable('HiGHS not installed')
    with _LOCK:
        problem.solve(solver)
        info=problem.solverModel.getInfo()
        status=str(problem.solverModel.getModelStatus())
        gap=float(info.mip_gap)
        values={k:v.value() for k,v in variables.items()}
    return values, status, gap if math.isfinite(gap) else None


def decode(by_id,obj,rows,values,weeks,xp,status,gap):
    # Never trust solver status alone (including timeout or infeasible LP relaxation).
    binary={}
    for k in obj:
        v=values.get(k)
        if v is None or not math.isfinite(v) or min(abs(v),abs(v-1))>1e-5:
            raise SolverUnavailable('No integral incumbent')
        binary[k]=int(v>=.5)
    for row,lo,hi in rows:
        v=sum(c*binary[k] for k,c in row.items())
        if v<lo-1e-6 or v>hi+1e-6: raise SolverUnavailable('Invalid incumbent')
    squad=[p for i,p in by_id.items() if binary['s',i]]
    plans={}
    for g in weeks:
        xi=[p for p in squad if binary['x',int(p['id']),g]]
        xi.sort(key=lambda p:(int(p['element_type']),-xp[int(p['id']),g],int(p['id'])))
        captain=next(p for p in xi if binary['c',int(p['id']),g])
        vice=max((p for p in xi if p['id']!=captain['id']),key=lambda p:xp[int(p['id']),g])
        bench=sorted((p for p in squad if p not in xi),key=lambda p:(int(p['element_type'])==1,-xp[int(p['id']),g],int(p['id'])))
        score=sum(xp[int(p['id']),g] for p in xi)+xp[int(captain['id']),g]
        plans[g]={'xi':xi,'captain':captain,'vice':vice,'bench':bench,'base_xp':round(score,2)}
    return {'squad':squad,'milp_weekly':plans,'milp_objective':round(sum(obj[k]*binary[k] for k in obj),3),
            'solver_status':status,'solver_gap':gap,'solver_method':'MILP / HiGHS'}


def solve_squad(players,weeks,xp,budget,backend=solve_highs):
    by_id,obj,rows=formulate(players,weeks,xp,budget)
    values,status,gap=backend(obj,rows)
    return decode(by_id,obj,rows,values,weeks,xp,status,gap)


def optimise_chip_v82(player_pool,gameweeks,fixtures,budget_tenths,minutes_overrides=None,shortlist=36,method='MILP'):
    import fpl_engine as engine
    def fallback(reason):
        result=engine.optimise_chip_squad(player_pool,gameweeks,fixtures,budget_tenths,minutes_overrides,shortlist)
        return {**result,'solver_method':'Original greedy','solver_status':reason,'solver_gap':None}
    if method != 'MILP': return fallback('Selected by user')
    try:
        xp={(int(p['id']),g):engine.player_fixture_xp(p,g,fixtures,minutes_overrides) for p in player_pool for g in gameweeks}
        result=solve_squad(player_pool,gameweeks,xp,budget_tenths)
        squad=result['squad']; spent=sum(int(p['now_cost']) for p in squad)
        if not engine.valid_squad(squad) or spent>budget_tenths:
            raise SolverUnavailable('Failed engine legality check')
        result.update(spent=spent,bank=int(budget_tenths)-spent,
                      rating=engine.team_rating(squad,gameweeks,fixtures,minutes_overrides))
        return result
    except Exception as exc:
        logging.getLogger(__name__).exception('MILP failed; using legacy optimiser')
        return fallback('MILP unavailable: '+type(exc).__name__)
