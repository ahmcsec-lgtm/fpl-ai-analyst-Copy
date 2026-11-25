"""Bounded, paired Monte Carlo risk proxy; not a calibrated FPL score model."""
from time import monotonic
import numpy as np

SIMULATIONS = 10_000
SEED = 8401
WEIGHTS = {'Safe': .22, 'Balanced': .12, 'Aggressive': .04}

class RiskSimulation:
    def __init__(self, xp, appearances, positions, clubs, minutes, *, samples=SIMULATIONS, seed=SEED, timeout=5.):
        self.xp, self.appearances, self.positions, self.clubs, self.minutes = xp, appearances, positions, clubs, minutes
        self.n, self.seed = samples, seed
        self.deadline = monotonic() + timeout
        self.players, self.teams, self.lineups = {}, {}, {}

    def check(self):
        if monotonic() > self.deadline:
            raise TimeoutError('Monte Carlo time budget exceeded')

    def rng(self, kind, wi, ident):
        return np.random.default_rng(np.random.SeedSequence([self.seed, kind, wi, int(ident)]))

    def player(self, pid, wi):
        key = (pid, wi)
        if key in self.players: return self.players[key]
        self.check()
        p = float(self.appearances[pid][wi]); mean = float(self.xp[pid][wi])
        if not np.isfinite([p, mean]).all() or not 0 <= p <= 1 or mean < 0:
            raise ValueError('Invalid projection')
        if p == 0 and mean > 1e-6:
            raise ValueError('Positive xP with zero appearance probability')
        rng = self.rng(1, wi, pid)
        played = rng.random(self.n) < p
        # Conditional minute uncertainty: unconditional minutes / appearance
        # probability is capped at 90. For DGWs this is a per-fixture proxy.
        m = float(self.minutes(pid, wi))
        if not np.isfinite(m): raise ValueError('Invalid minutes')
        conditional = np.clip(m / max(p, 1e-8), 1., 90.)
        concentration = 8.
        fraction = np.clip(conditional / 90., .01, .99)
        minute_factor = rng.beta(fraction*concentration, (1-fraction)*concentration, self.n) / fraction
        # Shared club return multiplier, independent individual return noise.
        tk = (self.clubs[pid], wi)
        if tk not in self.teams:
            self.teams[tk] = self.rng(2, wi, tk[0]).gamma(12., 1/12., self.n)
        individual = rng.gamma(2., .5, self.n)
        # Base xP already includes availability. Preserve its expectation;
        # never multiply unconditional xP by appearance a second time.
        points = (played * (mean/max(p, 1e-8)) * self.teams[tk] * individual * (.35+.65*minute_factor)).astype(np.float32)
        self.players[key] = played, points
        return self.players[key]

    def lineup(self, wi, xi, bench, captain, vice):
        key = (wi, tuple(xi), tuple(bench), captain, vice)
        if key in self.lineups: return self.lineups[key]
        self.check()
        vals = {pid: self.player(pid, wi) for pid in (*xi, *bench)}
        result = score_lineup(vals, xi, bench, captain, vice, self.positions)
        self.lineups[key] = result
        return result

    def plan(self, initial, weeks, choose_lineup):
        ids = set(initial); result = np.zeros(self.n, dtype=np.float64)
        for wi, week in enumerate(weeks):
            self.check()
            for move in week['moves']:
                ids.remove(int(move['out'])); ids.add(int(move['in']))
            xi, bench, c, v = choose_lineup(tuple(sorted(ids)), wi)
            result += self.lineup(wi, xi, bench, c, v) - week['hits']
        return result


def score_lineup(vals, xi, bench, captain, vice, positions):
    """Same legal substitution policy as V8.3: GK separately, outfield bench order,
    prefer same-position missing starter, then preserve minimum formation."""
    played = {p: vals[p][0] for p in vals}; pts = {p: vals[p][1] for p in vals}
    result = sum((pts[p] for p in xi), np.zeros_like(pts[xi[0]]))
    result = result + pts[captain] + (~played[captain])*pts[vice]
    gk = next(p for p in xi if positions[p] == 1)
    bg = next(p for p in bench if positions[p] == 1)
    result += (~played[gk])*pts[bg]
    field = [p for p in xi if positions[p] != 1]
    n = len(result)
    formed = np.array([[sum(positions[p] == pos for p in field)]*n for pos in (2,3,4)], dtype=np.int8)
    missing = np.zeros_like(formed)
    for p in field: missing[positions[p]-2] += ~played[p]
    minimum = (3,2,1)
    for p in bench:
        if positions[p] == 1: continue
        new = positions[p]-2
        available = played[p].copy()
        for old in [new]+[j for j in range(3) if j != new]:
            take = available & (missing[old]>0)
            if old != new: take &= formed[old]>minimum[old]
            result += take*pts[p]
            missing[old] -= take
            if old != new:
                formed[old] -= take; formed[new] += take
            available &= ~take
    return result


def paired_risk(candidate, reference, strategy):
    delta = np.asarray(candidate, dtype=np.float64)-np.asarray(reference, dtype=np.float64)
    delta[np.abs(delta) < 1e-5] = 0.
    mean = float(delta.mean())
    # Centered downside measures uncertainty, not the expected point loss
    # already included in the deterministic score. Cap the experimental margin.
    downside = float(np.maximum(mean-delta, 0).mean())
    penalty = min(2.5, WEIGHTS[strategy]*downside)
    return {'simulated_gain': mean, 'win_probability': float(np.mean(delta>0)),
            'loss_probability': float(np.mean(delta<0)), 'tie_probability': float(np.mean(delta==0)),
            'p10_gain': float(np.quantile(delta,.1)), 'p90_gain': float(np.quantile(delta,.9)),
            'uncertainty_margin': penalty, 'samples': len(delta)}


def evaluate_states(states, initial, choose_lineup, xp, appearances, positions, clubs, minutes, legacy_score, strategy, *, timeout=5.):
    """Return an atomic result for all retained beam states or raise for fallback."""
    sim = RiskSimulation(xp, appearances, positions, clubs, minutes, timeout=timeout)
    reference = max((s for s in states if s['first_action']=='ROLL'), key=legacy_score)
    roll = sim.plan(initial, reference['plan'], choose_lineup)
    result = {}
    for s in states:
        sim.check()
        points = sim.plan(initial, s['plan'], choose_lineup)
        result[id(s)] = paired_risk(points, roll, strategy)
    sim.check()
    return result
