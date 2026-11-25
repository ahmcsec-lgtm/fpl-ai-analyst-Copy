"""Experimental bounded transfer timing policy. All adjustments are score units, not FPL points."""
import math


def flexibility_value(ft, opportunities, remaining=True):
    """Diminishing marginal value; never reward exceeding the five-FT cap."""
    if not remaining:
        return 0.
    scale = min(1.5, max(.65, .8 + max(0., opportunities)/12.))
    return (0., 0., .75, 1.30, 1.70, 1.95)[max(0,min(5,int(ft)))] * scale


def timing_adjustment(count, ft, gain_now, future_opportunity, urgency, strategy, remaining):
    """Small extra hurdle for spending flexibility early; immediate need relaxes it.
    Does not charge points hits or add projected gains a second time.
    """
    if not count or not remaining:
        return 0.
    weight = {'Safe':1.25,'Balanced':1.,'Aggressive':.5}[strategy]
    scarcity = max(0., (5-min(5,ft))/5.)
    opportunity = min(1., max(0.,future_opportunity)/6.)
    benefit = min(1., max(0.,gain_now)/3.)
    urgency = min(1.,max(0.,urgency))
    return weight * min(1.2, .65 * min(count, max(0,ft)) * scarcity * (.5+.5*opportunity) * (1-benefit) * (1-urgency))


def urgency_for(moves, appearances, xi):
    """Only at-risk outgoing starters contribute, not an injured bench player."""
    return max([0.] + [max(0., appearances[m['in']][0]-appearances[m['out']][0]) for m in moves if m['out'] in xi])


def evidence(best, alternative, score, risk_active, timing, urgency):
    """Qualitative evidence strength, explicitly not a calibrated probability."""
    if alternative is None:
        return {'confidence':'Limited','score_gap':None,'explanation':'No competing immediate action is eligible under your settings.','timing_cost':0.,'urgency':0.}
    gap=max(0.,score(best)-score(alternative))
    confidence='Limited' if not risk_active else 'Strong' if gap>=3 else 'Moderate' if gap>=1 else 'Close decision'
    transfer=best if best['first_action']!='ROLL' else alternative
    first=transfer['plan'][0]; moves=first['moves']
    names='; '.join(f"{m['out_name']} → {m['in_name']}" for m in moves)
    later=[w['gw'] for w in (best if best['first_action']=='ROLL' else alternative)['plan'][1:] if any((m['out'],m['in']) in {(a['out'],a['in']) for a in moves} for m in w['moves'])]
    edge=transfer['net']-(best if best['first_action']=='ROLL' else alternative)['net']
    text=(f"{names}: transfer-first projects {edge:+.1f} net xP versus roll-first over the selected horizon. "
          f"{'Waiting preserves flexibility' if best['first_action']=='ROLL' else 'Moving now ranks higher after risk and flexibility adjustments'}. "
          f"Immediate availability improvement: {urgency.get(id(transfer),0.):.0%} (heuristic).")
    if later: text+=f" The roll-first plan schedules the same move in GW {later[0]}."
    return {'confidence':confidence,'score_gap':round(gap,3),'explanation':text,'timing_cost':round(timing.get(id(transfer),0.),3),'urgency':urgency.get(id(transfer),0.),'calibrated':False}
