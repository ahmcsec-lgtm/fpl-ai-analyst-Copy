"""V8.6 chip timing: bounded, paired comparison against a V8.5 ordinary-transfer path.
No authenticated FPL writes. Scores and reserve thresholds are experimental.
"""
from collections import Counter
from time import monotonic
from functools import partial
import numpy as np
import fpl_engine as e
from monte_carlo_v84 import RiskSimulation, paired_risk
from fast_greedy_v821 import fast_greedy, validate
from milp_v82 import solve_squad, solve_highs

CHIPS = ('Wildcard','Free Hit','Bench Boost','Triple Captain')
ALIASES = {'wildcard':CHIPS[0], 'freehit':CHIPS[1], 'bboost':CHIPS[2], '3xc':CHIPS[3]}
RESERVE = dict(zip(CHIPS,(8.,8.,8.,5.)))

def half_end(gw):
    if not 1 <= gw <= 38: raise ValueError('Invalid GW')
    return 19 if gw <= 19 else 38

def history_inventory(history, gw):
    """Return unused chips and last FH GW; invalid data is not an empty history."""
    if not isinstance(history,dict) or not isinstance(history.get('chips'),list):
        raise ValueError('Chip history unavailable')
    start = 1 if gw <= 19 else 20
    used=set(); last_fh=None
    for row in history['chips']:
        name=ALIASES.get(row['name']); event=int(row['event'])
        if not 1<=event<=38: raise ValueError('Invalid chip history')
        if name and start<=event<=half_end(gw): used.add(name)
        if name=='Free Hit' and event<gw: last_fh=max(last_fh or 0,event)
    return [c for c in CHIPS if c not in used],last_fh

def eligible(chip,gw,last_fh):
    return chip in CHIPS and 1<=gw<=38 and not (gw==1 and chip in CHIPS[:2]) and not (chip=='Free Hit' and last_fh==gw-1)

def fixture_context(squad,gw,fixtures):
    counts=[len(fixtures.get((gw,int(p['team'])),[])) for p in squad]
    return {'blank_players':sum(n==0 for n in counts),'double_players':sum(n>=2 for n in counts)}

def score_chip(sim,wi,line,chip=None):
    ids=lambda xs: [int(p['id']) for p in xs]
    xi,bench=ids(line['xi']),ids(line['bench']); c,v=int(line['captain']['id']),int(line['vice']['id'])
    normal=sim.lineup(wi,xi,bench,c,v)
    if chip=='Triple Captain':
        played,pts=sim.player(c,wi)
        return normal+pts+(~played)*sim.player(v,wi)[1]
    if chip=='Bench Boost':
        played,pts=sim.player(c,wi)
        return sum((sim.player(p,wi)[1] for p in xi+bench),np.zeros(sim.n))+pts+(~played)*sim.player(v,wi)[1]
    return normal

def replay(squad,players,plan,bank,ft):
    """Track actual selling-price estimates and legal ordinary-transfer baseline."""
    market={int(p['id']):p for p in players}; current={int(p['id']):dict(p) for p in squad}; rows=[]
    for w in plan:
        before=list(current.values()); before_bank=bank
        for m in w['moves']:
            out=current.pop(int(m['out'])); incoming=dict(market[int(m['in'])]); incoming['selling_price']=int(incoming['now_cost'])
            bank+=int(out.get('selling_price',out['now_cost']))-int(incoming['now_cost']); current[int(incoming['id'])]=incoming
        if bank<0 or not e.valid_squad(list(current.values())): raise ValueError('Invalid baseline path')
        rows.append(dict(gw=int(w['gw']),before=before,bank_before=before_bank,after=list(current.values()),hits=int(w['hits']),moves=w['moves'],ft_before=ft))
        ft=int(w['free_transfers_after'])
    return rows

def build_candidate(players,owned,bank,weeks,xp,*,use_milp=True):
    sales={int(p['id']):int(p.get('selling_price',p['now_cost'])) for p in owned}
    budget=bank+sum(sales.values())
    # Keeping an owned player consumes their liquidation value, not buy-back price.
    pool=[dict(p,now_cost=sales.get(int(p['id']),int(p['now_cost']))) for p in players]
    if use_milp:
        try: result=solve_squad(pool,weeks,xp,budget,backend=partial(solve_highs,time_limit=1.5))
        except Exception: result=fast_greedy(pool,weeks,xp,budget,time_limit=.7)
    else: result=fast_greedy(pool,weeks,xp,budget,time_limit=.7)
    validate(result['squad'],budget)
    original={int(p['id']):p for p in players}
    return [original[int(p['id'])] for p in result['squad']]

def choose(rows,available,gw,end,*,complete=True):
    """Compare current chip incremental utility against same-chip future opportunities.
    A reserve floor represents unobserved weeks, not a forecast. Urgent expiry lowers it.
    """
    if not complete: return {'action':'UNAVAILABLE','reason':'Incomplete candidate evaluation; use manual planning or retry.'}
    if not available: return {'action':'SAVE','reason':'No confirmed unused chips in this half.'}
    current=[]; future=[]
    for c in available:
        options=[r for r in rows if r['chip']==c]
        if not options: continue
        later=[r for r in options if r['gw']>gw]
        reserve=RESERVE[c] if end>max(r['gw'] for r in options) else 0.
        opportunity=max([0.,reserve]+[r['utility']*.95**(r['gw']-gw) for r in later])
        for r in options:
            if r['gw']==gw:
                current.append(dict(r,opportunity=opportunity,edge=r['utility']-opportunity))
        if later: future.append(max(later,key=lambda r:r['utility']))
    # If several chips are about to expire, do not insist on waiting for the same final GW.
    remaining=end-gw+1
    margin=.35 if remaining<=len(available) else 1.
    best=max(current,key=lambda r:r['edge'],default=None)
    if best and best['edge']>margin and best['utility']>0:
        return {'action':best['chip'],'candidate':best,'reason':f"{best['chip']} now: +{best['gain']:.1f} simulated net points; risk-adjusted advantage over waiting {best['edge']:.1f}."}
    target=max(future,key=lambda r:r['utility'],default=None)
    return {'action':'SAVE','candidate':best,'future':target,'reason':'No current chip clears its risk-adjusted opportunity cost.'}

def analyse(squad,players,weeks,fixtures,bank,ft,strategy,available,last_fh=None,*,minutes_overrides=None,allow_hits=True,max_transfers=3,baseline=None,use_milp=True,timeout=25):
    started=monotonic(); weeks=list(weeks); gw=weeks[0]; end=half_end(gw)
    if weeks!=list(range(gw,gw+len(weeks))) or not 1<=len(weeks)<=6: raise ValueError('Use 1–6 consecutive upcoming GWs')
    if any(c not in CHIPS for c in available): raise ValueError('Invalid chip inventory')
    available=list(dict.fromkeys(available)); weeks=[g for g in weeks if g<=end]
    if not available: return dict(action='SAVE',reason='No confirmed unused chips in this half.',rows=[],samples=0)
    def check():
        if monotonic()-started>timeout: raise TimeoutError('Chip strategy time budget exceeded')
    if baseline is None:
        baseline=e.smart_transfer_plan(squad,players,weeks,fixtures,bank,free_transfers=ft,strategy=strategy,minutes_overrides=minutes_overrides,allow_hits=allow_hits,max_transfers=max_transfers,beam_width=4,candidate_count=5,milp_seeds=False)['plan']
    if [w['gw'] for w in baseline]!=weeks: raise ValueError('Baseline does not cover chip horizon')
    check(); path=replay(squad,players,baseline,bank,ft)
    market={int(p['id']):p for p in players}; market.update({int(p['id']):p for p in squad})
    xp={pid:tuple(max(0.,e.player_fixture_xp(p,g,fixtures,minutes_overrides)) for g in weeks) for pid,p in market.items()}
    ap={pid:tuple(e.estimated_appearance_probability(p,g,fixtures,minutes_overrides,xp[pid][i]) for i,g in enumerate(weeks)) for pid,p in market.items()}
    # Align inconsistent zero-appearance predictions with the V8.4 simulator's contract.
    xp={pid:tuple(x if ap[pid][i]>0 else 0. for i,x in enumerate(xs)) for pid,xs in xp.items()}
    positions={pid:int(p['element_type']) for pid,p in market.items()}; clubs={pid:int(p['team']) for pid,p in market.items()}
    mins=lambda pid,i: (minutes_overrides or {}).get(pid,e.projected_minutes(market[pid],weeks[i]))
    sim=RiskSimulation(xp,ap,positions,clubs,mins,timeout=max(.01,timeout-(monotonic()-started)))
    flat={(pid,g):xs[i] for pid,xs in xp.items() for i,g in enumerate(weeks)}
    def lineup(s,i): return e.best_lineup(s,weeks[i],fixtures,minutes_overrides)
    base_lines=[lineup(r['after'],i) for i,r in enumerate(path)]
    base_scores=[score_chip(sim,i,line)-path[i]['hits'] for i,line in enumerate(base_lines)]
    rows=[]; skipped=[]; mode=strategy if strategy in ('Safe','Balanced','Aggressive') else 'Balanced'
    for i,r in enumerate(path):
        for chip in available:
            check()
            if not eligible(chip,r['gw'],last_fh): continue
            if chip in CHIPS[:2]:
                suffix=weeks[i:] if chip=='Wildcard' else [r['gw']]
                cand=build_candidate(list(market.values()),r['before'],r['bank_before'],suffix,flat,use_milp=use_milp)
                alternative=sum((score_chip(sim,j,lineup(cand,j)) for j in range(i,i+len(suffix))),np.zeros(sim.n))
                reference=sum(base_scores[i:i+len(suffix)],np.zeros(sim.n))
                if chip=='Free Hit':
                    # Restore pre-chip squad; either roll the remaining weeks or
                    # replay the ordinary path with the skipped moves deferred.
                    fixed=sum((score_chip(sim,j,lineup(r['before'],j)) for j in range(i+1,len(path))),np.zeros(sim.n))
                    deferred=None
                    try:
                        holdings={int(p['id']):dict(p) for p in r['before']}; cash=r['bank_before']; free=max(1,r['ft_before']); scores=[]
                        for j in range(i+1,len(path)):
                            moves=(r['moves'] if j==i+1 else [])+path[j]['moves']
                            if len(moves)>max_transfers or (not allow_hits and len(moves)>free): raise ValueError('Deferred transfer cap')
                            hits=4*max(0,len(moves)-free)
                            for m in moves:
                                out=holdings.pop(int(m['out'])); incoming=dict(market[int(m['in'])]); incoming['selling_price']=int(incoming['now_cost'])
                                if int(incoming['id']) in holdings: raise ValueError('Duplicate deferred player')
                                cash+=int(out.get('selling_price',out['now_cost']))-int(incoming['now_cost']); holdings[int(incoming['id'])]=incoming
                            if cash<0 or not e.valid_squad(list(holdings.values())): raise ValueError('Invalid deferred squad')
                            scores.append(score_chip(sim,j,lineup(list(holdings.values()),j))-hits)
                            free=min(5,max(0,free-len(moves))+1)
                        deferred=sum(scores,np.zeros(sim.n))
                    except (ValueError,KeyError):
                        pass
                    # Choose one fixed future path using expected score, not per-scenario hindsight.
                    continuation=deferred if deferred is not None and deferred.mean()>fixed.mean() else fixed
                    alternative=alternative+continuation
                    reference=sum(base_scores[i:],np.zeros(sim.n))
            else:
                alternative=score_chip(sim,i,base_lines[i],chip)-r['hits']; reference=base_scores[i]
            risk=paired_risk(alternative,reference,mode)
            rows.append(dict(chip=chip,gw=r['gw'],gain=risk['simulated_gain'],utility=risk['simulated_gain']-risk['uncertainty_margin'],risk=risk,**fixture_context(r['after'],r['gw'],fixtures)))
    check()
    result=choose(rows,available,gw,end)
    return dict(result,rows=rows,skipped=skipped,samples=sim.n,seconds=monotonic()-started,horizon=weeks,baseline=baseline)
