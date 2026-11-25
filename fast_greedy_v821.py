"""Bounded chip optimiser; no cross-session projection cache or ML changes."""
from collections import Counter
from itertools import permutations
from time import perf_counter
import math
import logging
from milp_v82 import QUOTAS, BENCH_WEIGHT, solve_squad

FORMATIONS = [(1,d,m,10-d-m) for d in range(3,6) for m in range(2,6) if 1<=10-d-m<=3]


def validate(squad,budget):
    if (len(squad)!=15 or len({int(p['id']) for p in squad})!=15
        or Counter(int(p['element_type']) for p in squad)!=QUOTAS
        or max(Counter(int(p['team']) for p in squad).values(),default=0)>3
        or any(int(p['now_cost'])<=0 or p.get('status') in ('u','n') for p in squad)
        or sum(int(p['now_cost']) for p in squad)>budget):
        raise ValueError('No valid squad within budget and club limits.')


def projection_cache(players,weeks,project):
    cache={}
    for p in players:
        for g in weeks:
            key=int(p['id']),g
            if key in cache: raise ValueError('Duplicate player or gameweek.')
            v=float(project(p,g))
            if not math.isfinite(v): raise ValueError('Non-finite projection.')
            cache[key]=v
    return cache


def weekly_plan(squad,weeks,xp):
    plans={}; objective=0.0
    for g in weeks:
        groups={pos:sorted((p for p in squad if int(p['element_type'])==pos),key=lambda p:(-xp[int(p['id']),g],int(p['id']))) for pos in QUOTAS}
        score=lambda p:xp[int(p['id']),g]
        def value(xi): return (1-BENCH_WEIGHT)*sum(map(score,xi))+max(map(score,xi))
        xi=max(([p for pos,n in zip(QUOTAS,f) for p in groups[pos][:n]] for f in FORMATIONS),key=value)
        ranked=sorted(xi,key=lambda p:(-score(p),int(p['id'])))
        captain,vice=ranked[:2]
        bench=sorted((p for p in squad if p not in xi),key=lambda p:(int(p['element_type'])==1,-score(p),int(p['id'])))
        base=sum(map(score,xi))+score(captain)
        objective+=base+BENCH_WEIGHT*sum(map(score,bench))
        plans[g]=dict(xi=xi,captain=captain,vice=vice,bench=bench,base_xp=round(base,2))
    return objective,plans


def fast_greedy(players,weeks,xp,budget,*,time_limit=5.0,max_iterations=8,shortlist=12,clock=perf_counter):
    """Cooperative search deadline; returns best legal incumbent, never an illegal squad."""
    if not 1<=len(weeks)<=6 or len(set(weeks))!=len(weeks) or budget<0 or time_limit<=0 or max_iterations<0 or shortlist<1:
        raise ValueError('Invalid optimiser settings.')
    start=clock(); deadline=start+time_limit
    eligible=[p for p in players if int(p['element_type']) in QUOTAS and 0<int(p['now_cost'])<=budget and p.get('status') not in ('u','n')]
    if len({int(p['id']) for p in eligible})!=len(eligible): raise ValueError('Duplicate player ID.')
    cost=lambda p:int(p['now_cost']); pid=lambda p:int(p['id']); club=lambda p:int(p['team']); pos=lambda p:int(p['element_type'])
    total={pid(p):sum(xp[pid(p),g] for g in weeks) for p in eligible}
    cheap={k:sorted((p for p in eligible if pos(p)==k),key=lambda p:(cost(p),-total[pid(p)],pid(p))) for k in QUOTAS}
    if any(len(cheap[k])<q for k,q in QUOTAS.items()): raise ValueError('Not enough eligible players.')
    candidates={k:list({pid(p):p for p in sorted(cheap[k],key=lambda p:(-total[pid(p)],cost(p),pid(p)))[:shortlist]+cheap[k][:shortlist]}.values()) for k in QUOTAS}
    best=None; best_value=-math.inf; plans=None; evaluations=0; iterations=0
    # Try all 24 positional orders for low-cost seeds. Not a feasibility proof.
    for order in permutations((1,4,2,3)):
        if clock()>=deadline: break
        seed=[]; counts=Counter()
        for k in order:
            selected=0
            for p in cheap[k]:
                if counts[club(p)]<3:
                    seed.append(p); counts[club(p)]+=1; selected+=1
                    if selected==QUOTAS[k]: break
        if len(seed)!=15 or sum(map(cost,seed))>budget: continue
        validate(seed,budget)
        v,pp=weekly_plan(seed,weeks,xp); evaluations+=1
        if v>best_value: best,best_value,plans=seed,v,pp
    if best is None: raise ValueError('Fast Greedy found no legal seed within its search limits. Try MILP or a larger budget.')
    for _ in range(max_iterations):
        if clock()>=deadline: break
        iterations+=1; improved=None; gain=best_value; next_plans=None
        owned={pid(p) for p in best}; counts=Counter(map(club,best)); spent=sum(map(cost,best))
        for j,out in enumerate(best):
            if clock()>=deadline: break
            for incoming in candidates[pos(out)]:
                if clock()>=deadline: break
                if pid(incoming) in owned or spent-cost(out)+cost(incoming)>budget: continue
                if counts[club(incoming)]-(club(out)==club(incoming))>=3: continue
                trial=best[:j]+[incoming]+best[j+1:]
                v,pp=weekly_plan(trial,weeks,xp); evaluations+=1
                if v>gain+1e-8: improved,gain,next_plans=trial,v,pp
        if improved is None: break
        best,best_value,plans=improved,gain,next_plans
    validate(best,budget)
    elapsed=clock()-start
    return dict(squad=best,milp_weekly=plans,milp_objective=round(best_value,3),solver_method='Fast Greedy',solver_status='Time limit' if clock()>=deadline else 'Bounded heuristic',solver_gap=None,search_seconds=elapsed,greedy_iterations=iterations,greedy_evaluations=evaluations)


def optimise_chip_v821(player_pool,gameweeks,fixtures,budget_tenths,minutes_overrides=None,shortlist=24,method='MILP'):
    import fpl_engine as engine
    started=perf_counter(); weeks=list(gameweeks); players=list(player_pool)
    if not 1<=len(weeks)<=6 or len(set(weeks))!=len(weeks): raise ValueError('Choose 1–6 distinct gameweeks.')
    xp=projection_cache(players,weeks,lambda p,g:engine.player_fixture_xp(p,g,fixtures,minutes_overrides))
    projection_seconds=perf_counter()-started
    search_started=perf_counter(); fallback_reason=None
    if method=='MILP':
        try:
            result=solve_squad(players,weeks,xp,budget_tenths)
            validate(result['squad'],budget_tenths)
            if not engine.valid_squad(result['squad']): raise ValueError('Engine legality check failed')
        except Exception as exc:
            logging.getLogger(__name__).exception('MILP failed; using bounded Fast Greedy')
            fallback_reason=type(exc).__name__
            result=fast_greedy(players,weeks,xp,budget_tenths)
    else:
        result=fast_greedy(players,weeks,xp,budget_tenths)
    search_seconds=perf_counter()-search_started
    squad=result['squad']; validate(squad,budget_tenths)
    if not engine.valid_squad(squad): raise ValueError('Engine legality check failed')
    spent=sum(int(p['now_cost']) for p in squad)
    rating_start=perf_counter()
    rating=engine.team_rating(squad,weeks,fixtures,minutes_overrides)
    result.update(spent=spent,bank=int(budget_tenths)-spent,rating=rating,projection_seconds=projection_seconds,optimisation_seconds=search_seconds,rating_seconds=perf_counter()-rating_start,execution_seconds=perf_counter()-started,fallback_reason=fallback_reason)
    return result
