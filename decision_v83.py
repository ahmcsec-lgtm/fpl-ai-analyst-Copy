"""Transparent, uncalibrated decision heuristics for Auto AI (not FPL points)."""
import math
from itertools import permutations
from collections import Counter


def adaptive_margin(horizon, ft, count, immediate_gain, immediate_risk_gain=0.0):
    """Small edges need more evidence; urgent XI improvement reduces hurdle."""
    base = .65 + .15 * min(6, max(1, horizon)) + .20 * max(0, count-1)
    if ft >= 5:
        base *= .45
    # Immediate benefit already enters xP; this only reduces the hurdle.
    urgency = min(.65, max(0., immediate_gain) * .12 + max(0., immediate_risk_gain) * .08)
    return max(.15, base - urgency)


def ft_value(ft, opportunity, remaining=True):
    if not remaining:
        return 0.
    return (0., 0., .8, 1.4, 1.85, 2.2)[max(0,min(5,int(ft)))] * min(1.6,max(.6, opportunity))


def seed_moves(market, ids, sales, prices, xp, weeks, eligible, bank, max_count, allow_hits, ft):
    """Optional MILP first-week candidate discovery; never replaces beam search.
    Uses liquidation-budget identity, and validates sequential legal swaps.
    """
    from milp_v82 import formulate, solve_highs, decode
    owned=set(ids)
    candidates=owned | set(eligible)
    players=[]
    for pid in sorted(candidates):
        p=dict(market[pid]); p['now_cost']=sales[pid] if pid in owned else prices[pid]
        if pid in owned: p['status']='a'  # allow retaining injured owned players
        players.append(p)
    budget=bank+sum(sales.values())
    matrix={(pid,g):xp[pid][i] for pid in candidates for i,g in enumerate(weeks)}
    by_id,obj,rows=formulate(players,weeks,matrix,budget,bench_weight=.035)
    output=[]
    for count in range(1,min(max_count,3,ft if not allow_hits else 3)+1):
        constraints=rows+[({('s',pid):1 for pid in by_id if pid in owned},15-count,15-count)]
        try:
            values,status,gap=solve_highs(obj,constraints,time_limit=2)
            decoded=decode(by_id,obj,constraints,values,weeks,matrix,status,gap)
            # decode returns dict containing squad (see solver contract)
            target={int(p['id']) for p in decoded['squad']}
        except Exception:
            continue
        outs=owned-target; ins=target-owned
        if len(outs)!=count or len(ins)!=count: continue
        for order in permutations(outs):
            found=False
            for incoming in permutations(ins):
                cash=bank; current=set(owned); moves=[]
                for a,b in zip(order,incoming):
                    if market[a]['element_type']!=market[b]['element_type']: break
                    cash+=sales[a]-prices[b]
                    current.remove(a); current.add(b)
                    if cash<0 or max(Counter(market[p]['team'] for p in current).values())>3: break
                    moves.append((a,b))
                if len(moves)==count:
                    output.append(moves); found=True; break
            if found: break
    return output
