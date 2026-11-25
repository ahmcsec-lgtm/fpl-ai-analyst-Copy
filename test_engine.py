"""Synthetic, offline regression tests for AJK v7.15 transfer decisions."""
import importlib.util
import random
from collections import Counter
from pathlib import Path

path = Path(__file__).with_name('fpl_engine.py')
spec = importlib.util.spec_from_file_location('engine_v715', str(path))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
e.player_fixture_xp = lambda p, gw, fixtures, minutes_overrides=None: p['xp'][gw]
e.projected_minutes = lambda p, gw=None: p.get('test_minutes', 90)
GWS = [11, 12, 13]
POS = [1] * 2 + [2] * 5 + [3] * 5 + [4] * 3

def player(pid, pos, xp=None, cost=50, club=None, **extra):
    return {'id': pid, 'web_name': f'P{pid}', 'element_type': pos,
            'team': club if club else pid, 'now_cost': cost, 'selling_price': cost,
            'status': 'a', 'xp': dict(zip(GWS, xp or [2, 2, 2])), **extra}

def fixture(selling=None):
    base = [player(i, pos) for i, pos in enumerate(POS, 1)]
    if selling:
        for p in base:
            if p['id'] in selling:
                p['selling_price'] = selling[p['id']]
    return base

def evaluate(base, alternates=(), ft=1, bank=0, strategy='Balanced', gws=GWS):
    r = e.smart_transfer_plan(base, base + list(alternates), gws, {}, bank, ft, strategy)
    assert r['ranked_plans'] and len(r['ranked_plans']) <= 3
    assert sum(int(o.get('recommended', False)) for o in r['options']) == 1
    assert r['ranked_plans'][0]['recommended']
    assert r['ranked_plans'][0]['first_action'] == r['recommended_option']
    assert r['action'] == ('ROLL' if r['recommended_option'] == 'ROLL' else 'TRANSFER')
    for plan in r['ranked_plans']:
        ids = {p['id'] for p in base}
        price_by_id = {p['id']: p['now_cost'] for p in base + list(alternates)}
        sell = {p['id']: p['selling_price'] for p in base}
        clubs = {p['id']: p['team'] for p in base + list(alternates)}
        positions = {p['id']: p['element_type'] for p in base + list(alternates)}
        current_ft = ft
        money = bank
        score = 0.0
        hits_total = 0
        for wi, row in enumerate(plan['plan']):
            assert row['gw'] == gws[wi]
            assert row['free_transfers_before'] == current_ft
            cnt = len(row['moves'])
            assert cnt <= (3 if wi == 0 else 2)
            hits = 4 * max(0, cnt - current_ft)
            assert hits == row['hits']
            assert len(set(m['out'] for m in row['moves'])) == cnt
            assert len(set(m['in'] for m in row['moves'])) == cnt
            assert not set(m['out'] for m in row['moves']) & set(m['in'] for m in row['moves'])
            for move in row['moves']:
                assert move['out'] in ids
                assert move['in'] not in ids
                assert move['out_price'] == sell[move['out']]
                assert positions[move['out']] == positions[move['in']]
                money += sell.pop(move['out']) - price_by_id[move['in']]
                assert money >= 0
                ids.remove(move['out'])
                ids.add(move['in'])
                sell[move['in']] = price_by_id[move['in']]
                assert len(ids) == 15
                assert all(Counter(positions[pid] for pid in ids)[p] == e.QUOTAS[p] for p in e.QUOTAS)
                assert max(Counter(clubs[pid] for pid in ids).values()) <= 3
            current_ft = min(5, max(0, current_ft - cnt) + 1)
            assert row['free_transfers_after'] == current_ft
            assert row['bank'] == money
            score += row['projected_xp'] - hits
            hits_total += hits
        assert plan['total_hits'] == hits_total
        assert abs(plan['planned_net_xp'] - score) <= .05
        assert plan['final_free_transfers'] == current_ft
        assert plan['final_bank'] == money
    return r

base = fixture()
assert evaluate(base)['recommended_option'] == 'ROLL', 'no artificial recommendation for equal xP'
strong = player(16, 3, [11, 11, 11])
assert evaluate(base, [strong])['recommended_option'] == 'ONE', 'one strong transfer should pay'
strong2 = player(17, 2, [10, 10, 10])
assert evaluate(base, [strong, strong2])['recommended_option'] in ('TWO', 'THREE'), 'two upgrades'
late = player(18, 3, [0, 13, 13])
assert evaluate(base, [late])['recommended_option'] == 'ROLL', 'wait for future fixture swing'
zero_ft = evaluate(base, [strong], ft=0)
assert zero_ft['ranked_plans'][0]['first_hit'] == 4, 'hit cost when no FTs'
cap5 = evaluate(base, [], ft=5)
assert cap5['ranked_plans'][0]['plan'][0]['free_transfers_after'] == 5
expensive = player(19, 3, [20, 20, 20], cost=101)
assert evaluate(base, [expensive], bank=0)['recommended_option'] == 'ROLL'
assert evaluate(base, [expensive], bank=51)['recommended_option'] == 'ONE'

# Funding move: one player must be downgraded before another expensive upgrade.
# Nobody can afford the premium midfielder from a single sale plus bank.
base_budget = fixture()
base_budget[2]['now_cost'] = base_budget[2]['selling_price'] = 100
cheaper_def = player(20, 2, [1.5, 1.5, 1.5], cost=40)
premium_mid = player(21, 3, [17, 17, 17], cost=95)
r = evaluate(base_budget, [cheaper_def, premium_mid])
assert any(len(option['first_moves']) >= 2 for option in r['ranked_plans']), 'pair candidates generated'
assert any(any(m['in'] == 21 for m in opt['first_moves']) for opt in r['ranked_plans']), 'premium funded'

# Status/doubt: stress scenarios must never *increase* projected xP.
doubtful = player(22, 3, [11, 11, 11], status='d')
rs = evaluate(base, [doubtful], strategy='Safe')
for p in rs['ranked_plans']:
    assert p['downside_scenario_net_xp'] <= p['planned_net_xp'] + .01

# Benchmark realistic shortlist: synthetic players, six fixture weeks.
random.seed(42)
large_base = []
large_pool = []
for i in range(1, 301):
    pos = POS[i-1] if i <= 15 else (i % 4) + 1
    p = player(i, pos, cost=random.randint(40, 110), club=(i-1)%20+1)
    p['xp'] = {j: random.uniform(1.0, 8.0) for j in range(11, 17)}
    large_pool.append(p)
    if i <= 15: large_base.append(p)
r6 = evaluate(large_base, large_pool[15:], bank=50, ft=2, gws=list(range(11, 17)))
assert len(r6['ranked_plans']) == 3
print('PASS: baseline, roll, hits, caps, bank, funding, availability stress, 3 distinct six-GW plans')
