"""AJK Bola Wawei AI v7.21: Gameweek-specific, source-aware availability + transfer engine.

No paid model, no official xP claim. All monetary amounts are FPL tenths.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import re
from statistics import mean
from itertools import combinations
from typing import Any

POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
QUOTAS = {1: 2, 2: 5, 3: 5, 4: 3}
FORMATIONS = [(d, m, 10 - d - m) for d in range(3, 6) for m in range(2, 6)
              if 1 <= 10 - d - m <= 3]


def num(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return default


def fixture_lookup(fixtures: list[dict]) -> dict[tuple[int, int], list[dict]]:
    result: dict[tuple[int, int], list[dict]] = {}
    for fixture in fixtures:
        gw = fixture.get("event")
        if gw is None or fixture.get("finished"):
            continue
        for team_id, opponent_id, home in (
            (fixture.get("team_h"), fixture.get("team_a"), True),
            (fixture.get("team_a"), fixture.get("team_h"), False),
        ):
            if team_id is None or opponent_id is None:
                continue
            result.setdefault((int(gw), int(team_id)), []).append({
                "opponent": int(opponent_id), "home": home,
                "difficulty": int(fixture.get("team_h_difficulty" if home else "team_a_difficulty") or 3),
            })
    return result


# Match-derived team strength and per-GW projections are cached for fast optimiser runs.
# Streamlit configures this once per rerun using current FPL public data.
_MODEL = {"attack": {}, "defence": {}, "league_goals": 1.42, "games": {}, "cache": {}, "calibration": {}, "calibration_n": 0, "residual_width": {},
          "attack_venue": {}, "defence_venue": {}, "next_gw": None, "gw_deadlines": {}}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _official_team_priors(teams: list[dict]) -> tuple[dict, dict, dict, dict]:
    """Bounded FPL rating priors, normalised within the current season's clubs.

    FPL's attack ratings are stronger when HIGHER; its defence ratings are
    stronger when HIGHER, meaning the *goals-conceded multiplier* is inverted.
    Missing/malformed ratings have a neutral multiplier of 1.0. Venue effects
    are centred around each club's average, preventing home/away prior from
    being counted twice alongside the explicit league home advantage.
    """
    fields = ("strength_attack_home", "strength_attack_away",
              "strength_defence_home", "strength_defence_away")
    averages = {}
    for field in fields:
        values = [num(t.get(field)) for t in teams if num(t.get(field)) > 0]
        averages[field] = mean(values) if len(values) >= 10 else 0.0

    attack_prior, conceded_prior, attack_venue, defence_venue = {}, {}, {}, {}
    for club in teams:
        tid = int(club["id"])
        relative = {}
        for field in fields:
            rating, avg = num(club.get(field)), averages[field]
            relative[field] = clamp(rating / avg, .65, 1.55) if rating > 0 and avg else 1.0
        ah, aa = relative["strength_attack_home"], relative["strength_attack_away"]
        dh, da = relative["strength_defence_home"], relative["strength_defence_away"]
        attack_prior[tid] = clamp((ah * aa) ** .30, .78, 1.25)
        conceded_prior[tid] = clamp((dh * da) ** (-.30), .78, 1.25)
        attack_venue[tid] = {
            True: clamp((ah / max((ah * aa) ** .5, .01)) ** .35, .93, 1.07),
            False: clamp((aa / max((ah * aa) ** .5, .01)) ** .35, .93, 1.07),
        }
        defence_venue[tid] = {
            True: clamp((max((dh * da) ** .5, .01) / dh) ** .35, .93, 1.07),
            False: clamp((max((dh * da) ** .5, .01) / da) ** .35, .93, 1.07),
        }
    return attack_prior, conceded_prior, attack_venue, defence_venue


def configure_projection_context(teams: list[dict], fixtures_raw: list[dict]) -> None:
    """Estimate team goals-for and goals-against multipliers without leakage.

    Mix previous *completed* league results with a bounded 8-match equivalent
    prior from official FPL home/away team strength. Early in a season this
    gives promoted teams and strong opponents a reasonable initial estimate;
    completed matches gradually displace the prior. Venue ratings have only a
    small additional effect. No future scores are used.
    """
    gf: dict[int, float] = {}
    ga: dict[int, float] = {}
    matches: dict[int, int] = {}
    total_goals, finished = 0, 0
    for match in fixtures_raw:
        if not match.get("finished"):
            continue
        hs, aws = match.get("team_h_score"), match.get("team_a_score")
        home, away = match.get("team_h"), match.get("team_a")
        if None in (hs, aws, home, away):
            continue
        home, away = int(home), int(away)
        for t, goals_for, goals_against in ((home, hs, aws), (away, aws, hs)):
            gf[t] = gf.get(t, 0) + float(goals_for)
            ga[t] = ga.get(t, 0) + float(goals_against)
            matches[t] = matches.get(t, 0) + 1
        total_goals += int(hs) + int(aws)
        finished += 1
    league = clamp(total_goals / (2 * finished), 1.1, 1.9) if finished else 1.42
    priors_a, priors_d, venue_a, venue_d = _official_team_priors(teams)
    attack, defence = {}, {}
    for t in teams:
        tid = int(t["id"])
        count = matches.get(tid, 0)
        # FPL strength is a *prior*, never a guarantee and never a direct xP.
        attack[tid] = clamp((gf.get(tid, 0) + 8 * league * priors_a[tid]) /
                            ((count + 8) * league), .67, 1.48)
        defence[tid] = clamp((ga.get(tid, 0) + 8 * league * priors_d[tid]) /
                             ((count + 8) * league), .67, 1.48)
    _MODEL.update({"attack": attack, "defence": defence, "league_goals": league,
                   "games": matches, "attack_venue": venue_a,
                   "defence_venue": venue_d, "cache": {}})


def _utc_time(value):
    """Strict, timezone-aware ISO date; missing/invalid dates cannot verify news."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else (dt.replace(tzinfo=timezone.utc) if len(value)==10 else None)
    except ValueError:
        return None


def configure_availability_context(events: list[dict], next_gw: int | None = None) -> None:
    """Connect injury status to real GW dates; avoids carrying next-GW odds indefinitely."""
    active = [int(ev['id']) for ev in events if not ev.get('finished') and ev.get('id') is not None]
    _MODEL['next_gw'] = int(next_gw) if next_gw is not None else (min(active) if active else None)
    _MODEL['gw_deadlines'] = {int(ev['id']): _utc_time(ev.get('deadline_time'))
                              for ev in events if ev.get('id') is not None}
    _MODEL['cache'] = {}


def attach_verified_availability_reports(players: list[dict], teams: list[dict],
                                         records: list[dict], now: datetime | None = None) -> dict:
    """Attach *curated, source-linked* reports, without scraping or guessing news.

    Records require a player+team match, explicit GW, valid dates, HTTPS article
    and a recognised evidence label. Nothing is inferred from article headlines.
    No record means the engine uses FPL data and playing-time evidence only.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError('now must contain a timezone')
    current = current.astimezone(timezone.utc)
    for player in players:
        player.pop('_ajk_reports', None)
    codes = {int(t['id']): str(t.get('short_name', '')).upper() for t in teams}
    by_id = {int(p['id']):p for p in players}
    by_name = {}
    for p in players:
        full = (' '.join((str(p.get('first_name') or '').strip(), str(p.get('second_name') or '').strip()))).strip().casefold()
        if full:
            by_name.setdefault((full, codes.get(int(p.get('team', 0)), '')), []).append(p)
    accepted, rejected, why = 0, 0, []
    if not isinstance(records, list):
        records = []
    valid_signals = {'ruled_out', 'confirmed_fit', 'training', 'doubtful',
                     'expected_start', 'minutes_limited'}
    kinds = {'club', 'manager', 'league', 'journalist', 'predicted_lineup'}
    for row in records[:350]:
        reason = None
        if not isinstance(row, dict):
            rejected += 1; continue
        try:
            pid = row.get('player_id')
            if pid is not None:
                p = by_id.get(int(pid))
                if p and str(row.get('team_code', '')).upper() not in ('',codes.get(int(p['team']), '')):
                    p = None
            else:
                team_code = str(row.get('team_code','')).upper()
                matches = by_name.get((str(row.get('player_name','')).strip().casefold(), team_code), [])
                # Some official FPL first names differ from a player's usual
                # name. A separately supplied *unique* web_name + club is an
                # explicit fallback, never a fuzzy surname match.
                if not matches and str(row.get('web_name','')).strip():
                    web_name = str(row['web_name']).strip().casefold()
                    matches = [candidate for candidate in players
                               if codes.get(int(candidate.get('team',0)), '') == team_code
                               and str(candidate.get('web_name','')).strip().casefold() == web_name]
                p = matches[0] if len(matches)==1 else None
            gw = int(row.get('gameweek', 0))
            published = _utc_time(row.get('published_at'))
            expires = _utc_time(row.get('expires_at'))
            source = str(row.get('url','')).strip()
            host = urlparse(source).hostname or ''
            source_kind = str(row.get('source_kind','')).strip().lower()
            signal = str(row.get('signal','')).strip().lower()
            if not p: reason = 'player or team does not match current season'
            elif not 1 <= gw <= 38: reason = 'invalid Gameweek'
            elif not published or not expires: reason = 'missing publication or expiry date'
            elif not published <= current <= expires or (current-published)>timedelta(days=10):
                reason = 'stale, future-dated or expired evidence'
            elif (expires-published)>timedelta(days=15): reason = 'validity window too long'
            elif not source.startswith('https://') or not host or '.' not in host:
                reason = 'a source HTTPS article is required'
            elif source_kind not in kinds or signal not in valid_signals:
                reason = 'unknown evidence category'
            elif source_kind == 'predicted_lineup' and signal not in {'expected_start','doubtful'}:
                reason = 'predicted lineups cannot confirm fitness or injury'
            if reason:
                rejected += 1
                if len(why)<6: why.append(reason)
                continue
            # Source_kind labels describe who is being attributed, NOT independent verification.
            p.setdefault('_ajk_reports', []).append({
                'gw': gw, 'signal': signal, 'source_kind': source_kind,
                'url': source, 'published': published.isoformat(),
                'note': str(row.get('note',''))[:260],
            })
            accepted += 1
        except (TypeError, ValueError, OverflowError):
            rejected += 1
    return {'accepted': accepted, 'rejected': rejected, 'warnings': why,
            'source': 'curated dated reports, not automated web scraping'}


def _expected_return_date(player: dict):
    """Only use a date explicitly included in FPL's own injury news."""
    match = re.search(r'expected (?:to be )?back\s+(\d{1,2})\s+([A-Za-z]{3,9})',
                      str(player.get('news', '')), flags=re.IGNORECASE)
    if not match:
        return None
    reference = _utc_time(player.get('news_added')) or datetime.now(timezone.utc)
    for year in (reference.year, reference.year + 1):
        try:
            date = datetime.strptime(f'{match.group(1)} {match.group(2)[:3]} {year}', '%d %b %Y')
            result = date.replace(tzinfo=timezone.utc)
            if result >= reference - timedelta(days=40):
                return result
        except ValueError:
            continue
    return None


def _report_for_gw(player: dict, gw: int | None):
    if gw is None:
        gw = _MODEL.get('next_gw')
    if gw is None:
        return None
    reports = [r for r in player.get('_ajk_reports', []) if r['gw'] == int(gw)]
    if not reports:
        return None
    rank = {'club':4, 'manager':4, 'league':3, 'journalist':2, 'predicted_lineup':1}
    # Prefer first-hand reporting; prefer newer evidence within equal priority.
    return max(reports, key=lambda r:(rank.get(r['source_kind'],0),r['published'],
                                      r['signal']=='ruled_out'))


def availability(player: dict, gw: int | None = None) -> float:
    """Heuristic participation factor, *not* a calibrated start probability.

    FPL next-round flags affect only the immediate GW. Verified, time-bound
    human-curated evidence can modify one GW, never the whole horizon.
    """
    gw = int(gw) if gw is not None else _MODEL.get('next_gw')
    next_gw = _MODEL.get('next_gw')
    distance = max(0, gw-next_gw) if (gw is not None and next_gw is not None) else 0
    status = str(player.get('status', 'a')).lower()
    chance = player.get('chance_of_playing_next_round')
    base = {'a': 1.0, 'd': .68, 'i': .12, 's': 0.0,
            'u': .08, 'n': 0.0}.get(status, .6)
    # FPL 75% doubtful is a useful baseline; do not arbitrarily reduce to 68%.
    if distance == 0 and chance is not None:
        c = clamp(num(chance)/100,0,1)
        base = c if status == 'd' else min(base,c)
    elif distance > 0 and status == 'd':
        # One-week caution should not be cloned into all later GWs.
        base = min(.90, .75 + .05 * min(distance,3))
    if status == 'i' and gw is not None:
        returning = _expected_return_date(player)
        deadline = _MODEL.get('gw_deadlines',{}).get(gw)
        if returning and deadline:
            if deadline < returning:
                base = 0.0
            else:
                days = (deadline-returning).days
                base = max(base, .45 if days<7 else .65 if days<21 else .82)
    # Suspension and eligibility restrictions must not be overruled by news.
    if status in {'s','n'}:
        return round(base,4)
    report = _report_for_gw(player,gw)
    if report:
        signal, kind = report['signal'],report['source_kind']
        first_hand = kind in {'club','manager','league'}
        if signal == 'ruled_out':
            base = 0.0 if first_hand else min(base,.20)
        elif signal == 'confirmed_fit':
            if first_hand:
                base = max(base,.91)
        elif (signal == 'training' and status in {'d','i','u'}
              and not (distance == 0 and chance is not None and num(chance) == 0)):
            # In training != fit or confirmed to start. Tiny positive update.
            base = min(.78,max(base, .24 if status=='i' else base+.03))
        elif signal == 'doubtful':
            base = min(base,.65 if first_hand else .75)
        elif signal == 'expected_start' and status not in {'i','u'}:
            base = min(.96,max(base,base+(.04 if first_hand else .02)))
        elif signal == 'minutes_limited':
            base = min(base,.85)
    return round(clamp(base,0,1),4)


def availability_explanation(player: dict, gw: int) -> dict:
    """Displayable attribution without inventing or summarising article content."""
    report = _report_for_gw(player,gw)
    return {'gw':int(gw), 'factor':availability(player,gw),
            'fpl_status':str(player.get('status','a')),
            'fpl_news':str(player.get('news') or ''),
            'report':dict(report) if report else None}


def projected_minutes(player: dict, gw: int | None = None) -> float:
    """Conservative expected minutes using season and recent completed FPL matches.

    The result is *unconditional* minutes per fixture, not a starting XI
    probability. Recent evidence is shrunk toward season usage; a single
    absence or cameo cannot overwhelm a substantial season sample.
    """
    appearances = num(player.get("appearances"))
    starts = num(player.get("starts"))
    played = num(player.get("minutes"))
    team_games = _MODEL["games"].get(int(player.get("team", 0)), 0)
    if team_games >= 3:
        # The public bootstrap payload does not always expose appearances.
        # Minutes and starts are sufficient evidence that a player is active.
        prior = 16 if played <= 0 and starts <= 0 and appearances <= 0 else 48
        effective = (played + 2 * prior) / (team_games + 2)
    elif appearances:
        effective = (played / appearances) * clamp(appearances / max(3, team_games), .35, 1)
    elif starts:
        effective = played / starts
    elif team_games > 0 and played > 0:
        effective = (played + 96) / (team_games + 2)
    else:
        effective = 40 if num(player.get("now_cost")) <= 45 else 57

    recent = player.get("_ajk_recent_minutes")
    sample = max(0, int(num(player.get("_ajk_recent_matches"))))
    if recent is not None and sample >= 2:
        # Maximum 40% recent weighting, capped at five observed fixtures.
        weight = min(.40, .08 * min(sample, 5))
        recent_avg = clamp(num(recent), 0, 90)
        effective = (1 - weight) * effective + weight * recent_avg

        # Match participation is corroborating evidence, not an independent
        # availability probability. Apply only a SMALL bounded correction for
        # persistent zero-minute matches, never for a single benching.
        played_recent = player.get("_ajk_recent_played")
        if played_recent is not None and sample >= 4:
            played_recent = int(clamp(num(played_recent), 0, sample))
            missed = sample - played_recent
            if missed >= 3 and recent_avg <= 30:
                effective *= .92

    # FPL availability flags are applied exactly once. External news headlines
    # remain informational; unverified non-EPL minutes are never inferred.
    return round(clamp(effective * availability(player, gw), 0, 90), 1)



def recent_minutes_evidence(history: list[dict], finished_gws: list[int],
                            match_counts: dict[int, int] | None = None) -> dict:
    """Estimate last-five-FPL-GW minutes using only already completed fixtures.

    Absent history rows are zero minutes when the club played; blank GWs are
    excluded. Double GWs contribute the number of fixtures rather than just 1.
    This is descriptive evidence, not a calibrated starting probability.
    """
    weeks = sorted({int(gw) for gw in finished_gws}, reverse=True)[:5]
    if not weeks:
        return {"minutes": None, "matches": 0, "played": 0, "window": []}
    counts = match_counts or {}
    games = sum(max(0, int(counts.get(gw, 1))) for gw in weeks)
    if games < 1:
        return {"minutes": None, "matches": 0, "played": 0, "window": weeks}
    relevant = [row for row in history if int(num(row.get("round"), -1)) in weeks]
    # A stale/incomplete element-summary response is not evidence that the
    # player missed the most recently completed GW. Treat uncertain coverage
    # as missing data instead of fabricating zero-minute appearances.
    if not any(int(num(row.get("round"), -1)) == weeks[0] for row in relevant):
        return {"minutes": None, "matches": 0, "played": 0, "window": weeks}
    minutes = sum(clamp(num(row.get("minutes")), 0, 130) for row in relevant)
    played = sum(1 for row in relevant if num(row.get("minutes")) > 0)
    return {"minutes": round(clamp(minutes / games, 0, 90), 1),
            "matches": games, "played": played, "window": weeks}

def _poisson_at_least(k: int, lam: float) -> float:
    if lam <= 0:
        return 0.0
    term = __import__("math").exp(-lam)
    cdf = term
    for n in range(1, k):
        term *= lam / n
        cdf += term
    return clamp(1 - cdf, 0, 1)


def _smooth_rate(player: dict, field: str, total_field: str,
                 prior: float, prior_minutes: float = 720) -> float:
    mins = num(player.get("minutes"))
    if mins < 1:
        return prior
    total = num(player.get(total_field), -1)
    if total >= 0:
        return clamp((total * 90 + prior * prior_minutes) / (mins + prior_minutes), 0, 3)
    rate = num(player.get(field), -1)
    if rate < 0:
        return prior
    return clamp((rate * mins + prior * prior_minutes) / (mins + prior_minutes), 0, 3)


def _fixture_components(player: dict, opponent: int, home: bool,
                        minutes: float, difficulty: int) -> dict[str, float]:
    from math import exp
    pos = int(player.get("element_type", 3))
    team = int(player.get("team", 0))
    a = _MODEL["attack"]
    d = _MODEL["defence"]
    # Factor opponent defence and own attack; cap and mix in FPL difficulty.
    opponent_factor = (a.get(team, 1) * d.get(opponent, 1)) ** .58
    fixture_factor = clamp(1.03 - .065 * (difficulty - 3), .80, 1.20)
    attack_factor = clamp(opponent_factor * fixture_factor * (1.08 if home else .94), .62, 1.48)
    # Critical v7.17 fix: the previous model used fixture difficulty ONLY for
    # attacking returns. Opponent strength, venue and official fixture
    # difficulty must also influence a defender/GK's clean-sheet expectation.
    # FDR is a *modest residual* correction because learned team strengths
    # already capture most of the matchup; avoid counting it at full weight.
    fdr_conceded = clamp(1.0 + .065 * (difficulty - 3), .87, 1.13)
    venue_opp_attack = _MODEL.get("attack_venue", {}).get(opponent, {}).get(not home, 1.0)
    venue_own_defence = _MODEL.get("defence_venue", {}).get(team, {}).get(home, 1.0)
    expected_opp_goals = clamp(_MODEL["league_goals"] *
                              a.get(opponent, 1) * d.get(team, 1) *
                              (0.94 if home else 1.08) * fdr_conceded *
                              venue_opp_attack * venue_own_defence, .35, 3.3)
    played_fraction = clamp(minutes / 90, 0, 1)
    # Expected share of matches in which the player reaches 60 minutes.
    chance_60 = clamp((minutes - 14) / 70, 0, 1)
    chance_any = clamp(minutes / 58, 0, 1)
    prior_goals = {1: .006, 2: .045, 3: .15, 4: .27}[pos]
    prior_assists = {1: .006, 2: .075, 3: .13, 4: .11}[pos]
    xg = _smooth_rate(player, "expected_goals_per_90", "expected_goals", prior_goals)
    xa = _smooth_rate(player, "expected_assists_per_90", "expected_assists", prior_assists)
    goal_exp = xg * played_fraction * attack_factor
    assist_exp = xa * played_fraction * attack_factor
    appearance = chance_any + chance_60
    goal_pts = {1: 10, 2: 6, 3: 5, 4: 4}[pos]
    goals = goal_pts * goal_exp
    assists = 3 * assist_exp
    cs_probability = exp(-expected_opp_goals)
    cs_pts = {1: 4, 2: 4, 3: 1, 4: 0}[pos] * cs_probability * chance_60
    # GK saves per 90 and conceded goals are season-wide public FPL values.
    saves_rate = _smooth_rate(player, "saves_per_90", "saves", 2.9, 540) if pos == 1 else 0
    saves = (saves_rate / 3) * played_fraction if pos == 1 else 0
    # Expected floor penalty from conceding two+ goals, with rough minute scaling.
    conceding = 0.0
    if pos in (1, 2):
        lam = expected_opp_goals * played_fraction
        conceding = -.60 * max(0, lam - (1 - exp(-lam)))
    bonus_rate = _smooth_rate(player, "bonus_per_90", "bonus", .32, 900)
    bonus = clamp(bonus_rate * played_fraction * (0.85 + .15 * attack_factor), 0, 1.7)
    dc = 0.0
    if pos in (2, 3, 4):
        prior_dc = {2: 6.4, 3: 5.2, 4: 2.8}[pos]
        dc_rate = _smooth_rate(player, "defensive_contribution_per_90",
                               "defensive_contribution", prior_dc, 720)
        threshold = 10 if pos == 2 else 12
        dc = 2 * _poisson_at_least(threshold, dc_rate * played_fraction)
    # Yellow-card probabilities inferred from season card rates (crude).
    yellow_rate = _smooth_rate(player, "yellow_per_90", "yellow_cards", .10, 900)
    discipline = -.9 * yellow_rate * played_fraction
    return {"appearance": appearance, "goals": goals, "assists": assists,
            "clean_sheet": cs_pts, "saves": saves, "goals_conceded": conceding,
            "bonus": bonus, "defensive_contributions": dc, "discipline": discipline,
            "goal_expectation": goal_exp, "assist_expectation": assist_exp,
            "cs_probability": cs_probability * chance_60, "expected_minutes": minutes,
            "expected_opponent_goals": expected_opp_goals}


def playing_time_scenarios(player: dict, gw: int, minutes_override: float | None = None) -> dict:
    """Small, auditable playing-time mixture, not calibrated start odds.

    Returned probabilities sum to one. The conditional-on-appearance minutes
    estimate comes from the existing FPL/recent-minutes estimator. Do NOT
    multiply the expectation by availability again inside the component model.
    Explicit overrides preserve legacy behaviour (one deterministic scenario).
    """
    if minutes_override is not None:
        minutes = clamp(num(minutes_override), 0, 90)
        return {'out': 0.0, 'cameo': 0.0, 'start': 1.0,
                'scenarios': [(1.0, minutes)], 'mean_minutes': minutes}
    medical_availability = clamp(availability(player, gw), 0, 1)
    mean_minutes = clamp(projected_minutes(player, gw), 0, 90)
    # Healthy does not mean guaranteed to feature: minutes per team fixture
    # already contain rotation/bench evidence. Keep an independent role proxy
    # so a seldom-used substitute can also have a no-appearance outcome.
    base_minutes = mean_minutes / max(medical_availability, .001)
    role_presence = clamp(.20 + .80 * (clamp(base_minutes,0,90)/90)**.65,
                          .20, .995)
    chance = min(medical_availability,
                 max(medical_availability*role_presence, mean_minutes/90))
    if chance <= 0.0001 or mean_minutes < 0.01:
        return {'out': 1.0, 'cameo': 0.0, 'start': 0.0,
                'scenarios': [(1.0, 0.0)], 'mean_minutes': 0.0}
    conditional_mean = clamp(mean_minutes / chance, 0, 90)
    # A low-usage substitute is modelled as a cameo, not an 80-minute starter.
    # For long-minute starters use an 85-minute ceiling so all mixtures stay legal.
    start_minutes = max(85.0, conditional_mean)
    cameo_minutes = min(25.0, conditional_mean)
    start_given_available = clamp((conditional_mean-cameo_minutes) /
                                  max(1.0, start_minutes-cameo_minutes), 0, 1)
    p_start = chance * start_given_available
    p_cameo = chance * (1-start_given_available)
    return {'out': round(1-chance, 5), 'cameo': round(p_cameo, 5),
            'start': round(p_start, 5),
            'scenarios': [(1-chance, 0.0), (p_cameo, cameo_minutes),
                          (p_start, start_minutes)],
            'mean_minutes': round(sum(prob * mins for prob, mins in
                                      ((p_cameo,cameo_minutes),(p_start,start_minutes))), 2)}


def player_prediction(player: dict, gw: int, fixtures: dict,
                      minutes_overrides: dict[int, float] | None = None) -> dict:
    """Return explainable projected FPL points and an approximate 80% range."""
    pid = int(player["id"])
    override = (minutes_overrides or {}).get(pid)
    distribution = playing_time_scenarios(player, gw, override)
    minutes = distribution['mean_minutes']
    key = (pid, int(gw), round(minutes, 2), id(fixtures),
           # Scenario distribution can change while mean stays identical.
           distribution['out'], distribution['start'])
    cached = _MODEL['cache'].get(key)
    if cached is not None:
        return cached
    games = fixtures.get((int(gw), int(player.get('team', 0))), [])
    totals = {k: 0.0 for k in ('appearance', 'goals', 'assists', 'clean_sheet', 'saves',
                                  'goals_conceded', 'bonus', 'defensive_contributions',
                                  'discipline', 'goal_expectation', 'assist_expectation')}
    cs_probs = []
    opponent_goals = []
    variance = 0.0
    pos = int(player.get('element_type', 3))
    for match in games:
        match_totals = dict.fromkeys(totals, 0.0)
        cs_prob, expected_goals = 0.0, 0.0
        for prob, scenario_minutes in distribution['scenarios']:
            if prob <= 0.0000001:
                continue
            if scenario_minutes <= 0.0:
                continue
            comp = _fixture_components(player, int(match['opponent']), bool(match['home']),
                                       scenario_minutes, int(match.get('difficulty',3)))
            # A playing-time scenario represents a real appearance, not a
            # fraction of a hypothetical average-length appearance. FPL
            # appearances are 1 point below 60 minutes, 2 at 60+.
            comp['appearance'] = 2.0 if scenario_minutes >= 60 else 1.0
            if scenario_minutes < 60:
                comp['clean_sheet'] = 0.0
                comp['cs_probability'] = 0.0
            for k in totals:
                match_totals[k] += prob * comp[k]
            cs_prob += prob * comp['cs_probability']
            expected_goals += prob * comp['expected_opponent_goals']
        for k in totals:
            totals[k] += match_totals[k]
        cs_probs.append(cs_prob)
        opponent_goals.append(expected_goals)
        variance += ({1:10,2:6,3:5,4:4}[pos] ** 2 * match_totals['goal_expectation']
                     + 9 * match_totals['assist_expectation']
                     + ({1:4,2:4,3:1,4:0}[pos] ** 2) * cs_prob * (1-cs_prob)
                     + 2.0)
    raw_xp = max(0.0, sum(totals[k] for k in totals if k not in
                           ('goal_expectation', 'assist_expectation')))
    correction = calibration_adjustment(pos, raw_xp) if games else 0.0
    xp = max(0.0, raw_xp + correction)
    # This is a Poisson/ Bernoulli approximation, NOT a calibrated forecast interval.
    std = variance ** .5
    # Empirical 80%-ish residual width from *earlier* captured forecasts only.
    empirical_width = _MODEL["residual_width"].get(pos)
    width = empirical_width if empirical_width is not None else 1.28 * std
    output = {**{k: round(v, 2) for k, v in totals.items()},
              "xp": round(xp, 2), "raw_xp": round(raw_xp, 2),
              "calibration": round(xp - raw_xp, 2),
              "lower": round(max(0, xp - width), 1),
              "upper": round(xp + width, 1), "minutes": minutes,
              "fixtures_count": len(games), "cs_probability": round(sum(cs_probs), 3),
              "playing_time_scenarios": {k:distribution[k] for k in ("out", "cameo", "start")},
              "expected_opponent_goals": round(sum(opponent_goals), 2)}
    _MODEL["cache"][key] = output
    return output


def player_fixture_xp(player: dict, gw: int, fixtures: dict,
                      minutes_overrides: dict[int, float] | None = None) -> float:
    return player_prediction(player, gw, fixtures, minutes_overrides)["xp"]


def horizon_xp(player: dict, gameweeks: list[int], fixtures: dict,
               minutes_overrides: dict[int, float] | None = None) -> float:
    return round(sum(player_fixture_xp(player, gw, fixtures, minutes_overrides)
                     for gw in gameweeks), 2)



def transfer_history_candidates(squad: list[dict], player_pool: list[dict],
                                gameweeks: list[int], fixtures: dict,
                                bank_tenths: int,
                                minutes_overrides: dict[int, float] | None = None,
                                max_candidates: int = 32) -> tuple[int, ...]:
    """Select a *bounded* set of prospective purchases for recent-minutes lookup.

    This is an optional data-preparation step, not a transfer recommendation.
    It considers premium targets, immediate xP, affordable candidates, cheap
    funding options and points per price. Network callers should fetch these
    only on request, not during every page load. Candidates outside this
    shortlist keep the conservative season-based fallback.
    """
    weeks = sorted({int(gw) for gw in gameweeks})[:6]
    if not weeks or max_candidates < 1:
        return ()
    owned = {int(p["id"]) for p in squad}
    bank = max(0, int(bank_tenths))
    max_sale = {pos: max((int(p.get("selling_price", p.get("now_cost", 0)))
                          for p in squad if int(p.get("element_type", 0)) == pos),
                         default=0) for pos in QUOTAS}
    by_position: dict[int, list[int]] = {}
    for pos in QUOTAS:
        candidates = [p for p in player_pool
                      if int(p.get("id", 0)) not in owned
                      and int(p.get("element_type", 0)) == pos
                      and int(p.get("now_cost", 0)) > 0
                      and (p.get("status", "a") not in ("i", "n", "s", "u")
                           or (p.get("status") == "i" and any(
                               availability(p, gw) >= .55 for gw in weeks)))]
        if not candidates:
            by_position[pos] = []
            continue
        projections = []
        for player in candidates:
            scores = [player_fixture_xp(player, gw, fixtures, minutes_overrides)
                      for gw in weeks]
            cost = int(player["now_cost"])
            projections.append((int(player["id"]), sum(scores), scores[0],
                                sum(scores) / max(35, cost), cost))
        affordable = [r for r in projections if r[4] <= bank + max_sale[pos]]
        # Construct interleaved buckets rather than letting all 32 requests
        # come from one position or from expensive, unaffordable players.
        buckets = (
            sorted(projections, key=lambda r: r[1], reverse=True)[:8],
            sorted(affordable, key=lambda r: r[1], reverse=True)[:8],
            sorted(projections, key=lambda r: r[2], reverse=True)[:5],
            sorted(affordable, key=lambda r: r[3], reverse=True)[:5],
            sorted(projections, key=lambda r: (r[4], -r[1]))[:4],
        )
        ordered = []
        for bucket in buckets:
            for row in bucket:
                if row[0] not in ordered:
                    ordered.append(row[0])
        by_position[pos] = ordered
    result = []
    # Round robin across positions for coverage even when cap is small.
    for i in range(max((len(rows) for rows in by_position.values()), default=0)):
        for pos in QUOTAS:
            if i < len(by_position[pos]):
                result.append(by_position[pos][i])
                if len(result) >= max_candidates:
                    return tuple(result)
    return tuple(result)


def valid_squad(squad: list[dict]) -> bool:
    if len(squad) != 15 or len({int(p["id"]) for p in squad}) != 15:
        return False
    positions = Counter(int(p["element_type"]) for p in squad)
    teams = Counter(int(p["team"]) for p in squad)
    return all(positions[k] == v for k, v in QUOTAS.items()) and max(teams.values(), default=0) <= 3




def estimated_appearance_probability(player: dict, gw: int, fixtures: dict,
                                     minutes_overrides: dict[int, float] | None = None,
                                     projected_xp: float | None = None) -> float:
    """Estimate the chance of *any* minutes in this GW, for squad contingencies.

    IMPORTANT: This is an explicit conservative heuristic, NOT a calibrated
    start probability or a simulation of how many minutes the player will get.
    Base xP remains unchanged; appearance probability is used *only* for the
    vice-captain and auto-sub contingencies. No external/proprietary data.
    """
    pid = int(player['id'])
    games = fixtures.get((int(gw), int(player.get('team', 0))), [])
    if not games and (projected_xp is None or projected_xp <= 0):
        return 0.0  # Blank GW: cannot play for FPL purposes.
    manual = minutes_overrides is not None and pid in minutes_overrides
    mins = clamp(num(minutes_overrides[pid]) if manual else projected_minutes(player, gw), 0, 90)
    if mins <= .05:
        return 0.0
    # Minutes proxy: low-minute substitutes may appear frequently, so do not
    # pretend that unconditional minutes / 90 equals appearance probability.
    proxy = clamp(.16 + .84 * (mins / 90) ** .60, .02, .985)
    samples = int(max(0, num(player.get('_ajk_recent_matches'))))
    recent_played = player.get('_ajk_recent_played')
    historical = None
    if samples >= 3 and recent_played is not None:
        played = clamp(num(recent_played), 0, samples)
        historical = (played + 3.5) / (samples + 4.0)
    else:
        games_so_far = _MODEL['games'].get(int(player.get('team', 0)), 0)
        appearances = num(player.get('appearances'))
        if games_so_far >= 4 and appearances > 0:
            historical = (min(appearances, games_so_far) + 2.5) / (games_so_far + 3.5)
    chance = (.75 * proxy + .25 * historical) if historical is not None else proxy
    if not manual:
        # The injury flag already reduces projected xP; applying a probability
        # here only changes the *fallback*, never deducts points a second time.
        chance = min(chance, availability(player, gw))
    chance = clamp(chance, 0.0, .985)
    # A player in a DGW can score FPL minutes in either match. Treat match
    # appearances as approximately independent only for this fallback proxy.
    number_of_games = len(games) if games else 1  # synthetic xP tests
    if number_of_games > 1:
        chance = 1.0 - (1.0 - chance) ** number_of_games
    return round(chance, 4)


def _scenario_lineup_evaluation(xi_ids: list[int], bench_ids: list[int],
                                xp: dict[int, float], appearance: dict[int, float],
                                positions: dict[int, int],
                                captain_id: int | None = None,
                                vice_id: int | None = None) -> dict:
    """Evaluate XI, armband contingency and legal bench replacements.

    Assumes independent play/no-play indicators as a lightweight *unvalidated*
    approximation. Enumerates the 4 positional absence counts via DP, then the
    2^3 playable outfield bench patterns. Base player xP is unconditional, so
    only the additional points earned via an auto-sub are added. This is much
    cheaper than branching over 2^15 individual outcomes for every squad.
    """
    xi_set = set(xi_ids)
    xi_total = sum(xp[pid] for pid in xi_ids)
    ordered_captains = sorted((pid for pid in xi_ids if positions[pid] != 1),
                              key=lambda pid: xp[pid], reverse=True)
    if not ordered_captains:
        ordered_captains = xi_ids[:]
    if captain_id not in xi_set:
        captain_id = max(ordered_captains, key=lambda c: (
            xp[c] + (1 - appearance[c]) * max((xp[v] for v in xi_ids if v != c), default=0)))
    if vice_id not in xi_set or vice_id == captain_id:
        vice_id = max((pid for pid in xi_ids if pid != captain_id), key=lambda v: xp[v])
    vice_fallback = (1.0 - appearance[captain_id]) * xp[vice_id]

    start_gk = next((pid for pid in xi_ids if positions[pid] == 1), None)
    bench_gk = next((pid for pid in bench_ids if positions[pid] == 1), None)
    gk_cover = ((1 - appearance[start_gk]) * xp[bench_gk]
                if start_gk is not None and bench_gk is not None else 0.0)

    field = [pid for pid in xi_ids if positions[pid] != 1]
    out_bench = [pid for pid in bench_ids if positions[pid] != 1]
    original_counts = [sum(positions[pid] == pos for pid in field) for pos in (2, 3, 4)]
    # Each outcome is the probability of a certain number of absent defenders,
    # midfielders and forwards. No need to enumerate identity-equivalent cases.
    absence_counts = {(0, 0, 0): 1.0}
    for pid in field:
        idx = positions[pid] - 2
        p_missing = clamp(1 - appearance[pid], 0, 1)
        updated = {}
        for counts, prob in absence_counts.items():
            updated[counts] = updated.get(counts, 0.0) + prob * (1 - p_missing)
            nxt = list(counts)
            nxt[idx] += 1
            nxt = tuple(nxt)
            updated[nxt] = updated.get(nxt, 0.0) + prob * p_missing
        absence_counts = updated

    # Probabilities are unconditional for bench players. Divide their xP by
    # probability of playing only inside the hypothetical 'played' branches.
    out_chance = [clamp(appearance[pid], 0, 1) for pid in out_bench]
    expected_field_cover = 0.0
    for missing_counts, probability in absence_counts.items():
        if probability < 1e-7 or not any(missing_counts):
            continue
        cover_if_absent = 0.0
        for played_mask in range(1 << len(out_bench)):
            bench_pattern_prob = 1.0
            for bi, p_play in enumerate(out_chance):
                bench_pattern_prob *= p_play if played_mask & (1 << bi) else (1 - p_play)
            if bench_pattern_prob < 1e-8:
                continue
            missing = list(missing_counts)
            formed = list(original_counts)
            bench_points = 0.0
            for bi, pid in enumerate(out_bench):
                if not played_mask & (1 << bi):
                    continue
                new_pos = positions[pid] - 2
                # Same position first, then any legal positional substitution.
                # Count placeholders for remaining non-playing starters; FPL
                # judges automatic substitutions against the starting shape.
                choices = [j for j in range(3) if missing[j] > 0]
                choices.sort(key=lambda j: (j != new_pos, j))
                for old_pos in choices:
                    next_formed = formed[:]
                    next_formed[old_pos] -= 1
                    next_formed[new_pos] += 1
                    if next_formed[0] >= 3 and next_formed[1] >= 2 and next_formed[2] >= 1:
                        missing[old_pos] -= 1
                        formed = next_formed
                        bench_points += xp[pid] / max(out_chance[bi], 1e-8)
                        break
            cover_if_absent += bench_pattern_prob * bench_points
        expected_field_cover += probability * cover_if_absent
    total_cover = gk_cover + expected_field_cover
    captain_bonus = xp[captain_id]
    # The xi_total already includes each chosen starter once. The additional
    # 'captain_bonus' and vice fallback account for doubles if/when eligible.
    return {'total': xi_total + captain_bonus + vice_fallback + total_cover,
            'xi_xp': xi_total, 'captain_xp': captain_bonus,
            'vice_fallback_xp': vice_fallback, 'autosub_xp': total_cover,
            'captain_id': captain_id, 'vice_id': vice_id}




def _confirmed_unavailable_for_xi(player: dict, projected_xp: float,
                                  appearance_probability: float) -> bool:
    """Identify *near-zero-xP* non-players for lineup selection.

    An FPL injury can have a missing `chance_of_playing_next_round`, which
    does NOT mean the player is fit. In v7.19.3 the contingency estimator
    gave such a player up to 12% appearance probability and the no-show
    guard ignored him, despite displaying 0.0 xP. This is a *selection*
    preference, not an assertion that doubtful players cannot play.

    Retain partially fit, positive-xP players as legitimate alternatives.
    """
    if projected_xp > 0.10:
        return False
    status = str(player.get('status', 'a')).lower()
    chance = player.get('chance_of_playing_next_round')
    zero_chance = chance is not None and num(chance, -1) == 0
    return bool(status in {'i', 's', 'u', 'n'}
                or zero_chance or appearance_probability <= .02)



def best_lineup(squad: list[dict], gw: int, fixtures: dict,
                minutes_overrides: dict[int, float] | None = None,
                captain_id: int | None = None) -> dict:
    """Select an XI using xP + estimated auto-sub and vice-captain cover.

    Expected minutes/appearance probabilities are heuristic, not backtested.
    Returns the same core structure expected by the existing Streamlit UI.
    """
    if not valid_squad(squad):
        raise ValueError("A squad requires 2 GKP, 5 DEF, 5 MID, 3 FWD and at most 3 from each club.")
    by_id = {int(p['id']): p for p in squad}
    xp = {pid: player_fixture_xp(p, gw, fixtures, minutes_overrides)
          for pid, p in by_id.items()}
    appearances = {pid: estimated_appearance_probability(p, gw, fixtures,
                    minutes_overrides, xp[pid]) for pid, p in by_id.items()}
    positions = {pid: int(p['element_type']) for pid, p in by_id.items()}
    overrides = minutes_overrides or {}
    minutes = {pid: clamp(num(overrides[pid]), 0, 90) if pid in overrides
               else projected_minutes(p, gw) for pid, p in by_id.items()}
    groups = {pos: sorted((p for p in squad if int(p['element_type']) == pos),
                          key=lambda p: (
                              not _confirmed_unavailable_for_xi(
                                  p, xp[int(p['id'])], appearances[int(p['id'])]),
                              xp[int(p['id'])], minutes[int(p['id'])]
                          ), reverse=True) for pos in QUOTAS}
    # Scenario-aware scoring includes automatic substitutions. A confirmed
    # non-player can otherwise be selected *on purpose* so that the projected
    # bench replacement earns points via auto-sub: sometimes this even ranks
    # above simply starting the healthy player. This is fragile and confusing
    # when a legal XI with fewer non-playing players exists. Select among the
    # formations requiring the fewest confirmed no-show starters first.
    # A 0-xP player with a meaningful chance to feature is NOT excluded.
    confirmed_no_shows = {
        pid for pid, player in by_id.items()
        if _confirmed_unavailable_for_xi(player, xp[pid], appearances[pid])
    }
    formations = []
    for defenders, midfielders, forwards in FORMATIONS:
        candidate = ([groups[1][0]] + groups[2][:defenders] +
                     groups[3][:midfielders] + groups[4][:forwards])
        xi_ids = [int(p['id']) for p in candidate]
        selected = set(xi_ids)
        bench = sorted((p for p in squad if int(p['id']) not in selected),
                       key=lambda p: (int(p['element_type']) == 1, -xp[int(p['id'])]))
        bench_ids = [int(p['id']) for p in bench]
        absent_count = len(selected & confirmed_no_shows)
        formations.append((candidate, bench, xi_ids, bench_ids, absent_count))

    fewest_no_shows = min(row[4] for row in formations)
    best, best_score, best_minutes = None, float('-inf'), float('-inf')
    best_bench, best_evaluation = None, None
    for candidate, bench, xi_ids, bench_ids, absent_count in formations:
        if absent_count > fewest_no_shows:
            continue
        evaluation = _scenario_lineup_evaluation(xi_ids, bench_ids, xp,
                                                   appearances, positions, captain_id)
        candidate_score = evaluation['total']
        candidate_minutes = sum(minutes[pid] for pid in xi_ids)
        if (candidate_score > best_score + .000001 or
            (abs(candidate_score - best_score) <= .000001 and candidate_minutes > best_minutes)):
            best = candidate
            best_bench = bench
            best_evaluation = evaluation
            best_score, best_minutes = candidate_score, candidate_minutes
    xi, bench = best, best_bench
    ids = {int(p['id']) for p in xi}
    captain = by_id[best_evaluation['captain_id']]
    vice = by_id[best_evaluation['vice_id']]
    # Each close call is a single legal XI-for-bench substitution within
    # 0.5 xP. The margin is *not* a calibrated probability/confidence bound.
    # No automatic substitution is forced for a marginal difference.
    close_calls = []
    for alternate in bench:
        aid = int(alternate["id"])
        alternatives = []
        for starter in xi:
            sid = int(starter["id"])
            swapped = Counter(int(p["element_type"]) for p in xi)
            swapped[int(starter["element_type"])] -= 1
            swapped[int(alternate["element_type"])] += 1
            if not (swapped[1] == 1 and 3 <= swapped[2] <= 5 and
                    2 <= swapped[3] <= 5 and 1 <= swapped[4] <= 3):
                continue
            gap = round(xp[sid] - xp[aid], 2)
            if -0.001 <= gap <= .50:
                sfx = fixtures.get((int(gw), int(starter.get("team", 0))), [])
                afx = fixtures.get((int(gw), int(alternate.get("team", 0))), [])
                alternatives.append({
                    "starter_id": sid, "starter": str(starter.get("web_name", sid)),
                    "alternative_id": aid, "alternative": str(alternate.get("web_name", aid)),
                    "starter_xp": round(xp[sid], 2), "alternative_xp": round(xp[aid], 2),
                    "xp_margin": gap, "position": POSITION_NAMES.get(int(alternate["element_type"])),
                    "starter_difficulty": [int(f.get("difficulty", 3)) for f in sfx],
                    "alternative_difficulty": [int(f.get("difficulty", 3)) for f in afx],
                    "note": "Close xP projections; fixture labels alone cannot determine the better start.",
                })
        # Show one most relevant swap per benched player, not six variants
        # for one midfielder while a defender close call goes unnoticed.
        if alternatives:
            alternatives.sort(key=lambda c: (c["xp_margin"],
                          int(by_id[c["starter_id"]]["element_type"] !=
                              alternate["element_type"]), c["starter_id"]))
            close_calls.append(alternatives[0])
    close_calls.sort(key=lambda item: (item["xp_margin"], item["starter_id"], item["alternative_id"]))
    return {'xi': xi, 'bench': bench, 'captain': captain, 'vice': vice,
            'xi_xp': round(best_evaluation['xi_xp'], 2),
            'captain_xp': round(best_evaluation['captain_xp'], 2),
            'total_xp': round(best_evaluation['total'], 2),
            'expected_autosub_xp': round(best_evaluation['autosub_xp'], 2),
            'expected_vice_fallback_xp': round(best_evaluation['vice_fallback_xp'], 2),
            'close_calls': close_calls[:6]}


def team_rating(squad: list[dict], gameweeks: list[int], fixtures: dict,
                minutes_overrides: dict[int, float] | None = None) -> dict:
    """Illustrative 0–100 rating, NOT Fantasy Football Hub's scoring model."""
    weeks = [best_lineup(squad, gw, fixtures, minutes_overrides) for gw in gameweeks]
    if not weeks:
        return {"rating": 0, "gw_rating": 0, "average_xp": 0, "total_xp": 0, "weekly": []}
    scores = [w["total_xp"] for w in weeks]
    average = sum(scores) / len(scores)
    # 65 xP is a heuristic high-performing single GW benchmark, not league percentile.
    return {"rating": round(max(0, min(100, average / 65 * 100))),
            "gw_rating": round(max(0, min(100, scores[0] / 65 * 100))),
            "average_xp": round(average, 1), "total_xp": round(sum(scores), 1),
            "weekly": weeks}


def _evaluate(squad: list[dict], gameweeks: list[int], fixtures: dict,
              minutes_overrides: dict[int, float] | None = None) -> float:
    return sum(best_lineup(squad, gw, fixtures, minutes_overrides)["total_xp"]
               for gw in gameweeks)


def suggest_transfers(squad: list[dict], player_pool: list[dict], gameweeks: list[int],
                      fixtures: dict, bank_tenths: int, free_transfers: int = 1,
                      minutes_overrides: dict[int, float] | None = None,
                      limit: int = 10) -> list[dict]:
    """Rank legal single transfers using team XI+captain gains, selling values and cash."""
    if not valid_squad(squad) or not gameweeks:
        return []
    base = _evaluate(squad, gameweeks, fixtures, minutes_overrides)
    owned = {int(p["id"]) for p in squad}
    scores = {int(p["id"]): horizon_xp(p, gameweeks, fixtures, minutes_overrides)
              for p in player_pool}
    output = []
    for outgoing in squad:
        selling = int(outgoing.get("selling_price", outgoing.get("now_cost", 0)))
        affordable = int(bank_tenths) + selling
        same_pos = [p for p in player_pool if int(p["element_type"]) == int(outgoing["element_type"])
                    and int(p["id"]) not in owned and int(p["now_cost"]) <= affordable]
        same_pos.sort(key=lambda p: scores[int(p["id"])], reverse=True)
        for incoming in same_pos[:18]:
            proposed = [p for p in squad if p["id"] != outgoing["id"]] + [incoming]
            if not valid_squad(proposed):
                continue
            gain = round(_evaluate(proposed, gameweeks, fixtures, minutes_overrides) - base, 2)
            hit = 4 if free_transfers < 1 else 0
            output.append({"out": outgoing, "in": incoming, "gain": gain,
                           "net_gain": round(gain - hit, 2), "hit": hit,
                           "bank_after": affordable - int(incoming["now_cost"])})
    output.sort(key=lambda x: x["net_gain"], reverse=True)
    return output[:limit]


def optimise_chip_squad(player_pool: list[dict], gameweeks: list[int], fixtures: dict,
                        budget_tenths: int, minutes_overrides: dict[int, float] | None = None,
                        shortlist: int = 36) -> dict:
    """Build legal 15-player squad under a budget with bounded greedy upgrades.

    Not a guaranteed mathematical optimum. All players are priced at current buy price.
    """
    if not gameweeks:
        raise ValueError("Select at least one upcoming gameweek.")
    scored = {int(p["id"]): horizon_xp(p, gameweeks, fixtures, minutes_overrides)
              for p in player_pool}
    buckets = {}
    for position, quota in QUOTAS.items():
        eligible = [p for p in player_pool if int(p.get("element_type", 0)) == position
                    and p.get("status") not in ("u", "n")]
        # Mix best projected and cheapest options so a constrained budget can work.
        top = sorted(eligible, key=lambda p: scored[int(p["id"])], reverse=True)[:shortlist]
        cheap = sorted(eligible, key=lambda p: int(p["now_cost"]))[:max(15, quota * 5)]
        buckets[position] = list({int(p["id"]): p for p in top + cheap}.values())
        if len(buckets[position]) < quota:
            raise ValueError("Not enough available players to build a legal squad.")
    # Initial low-cost squad, avoiding the fourth player from a club.
    chosen = []
    counts = Counter()
    for position in (1, 4, 2, 3):
        candidates = sorted(buckets[position], key=lambda p: (int(p["now_cost"]), -scored[int(p["id"])]))
        count = 0
        for p in candidates:
            if counts[int(p["team"])] >= 3:
                continue
            chosen.append(p)
            counts[int(p["team"])] += 1
            count += 1
            if count == QUOTAS[position]:
                break
        if count != QUOTAS[position]:
            raise ValueError("Unable to assemble a legal squad from candidate shortlist.")
    spent = sum(int(p["now_cost"]) for p in chosen)
    if spent > budget_tenths:
        raise ValueError(f"Your budget (£{budget_tenths / 10:.1f}m) is too low for this squad (£{spent / 10:.1f}m).")
    # Iteratively choose legal profitable single swaps; score gains against spend.
    for _ in range(35):
        baseline = _evaluate(chosen, gameweeks, fixtures, minutes_overrides)
        owned = {int(p["id"]) for p in chosen}
        best_gain = 0.03
        best_squad = None
        best_spent = spent
        for outgoing in chosen:
            budget_for = budget_tenths - spent + int(outgoing["now_cost"])
            for incoming in buckets[int(outgoing["element_type"])]:
                if int(incoming["id"]) in owned or int(incoming["now_cost"]) > budget_for:
                    continue
                # Lower-priority candidates unlikely to improve any lineup can be skipped.
                if scored[int(incoming["id"])] + 1 < scored[int(outgoing["id"])]:
                    continue
                proposal = [p for p in chosen if p["id"] != outgoing["id"]] + [incoming]
                if not valid_squad(proposal):
                    continue
                gain = _evaluate(proposal, gameweeks, fixtures, minutes_overrides) - baseline
                if gain > best_gain:
                    best_gain = gain
                    best_squad = proposal
                    best_spent = spent - int(outgoing["now_cost"]) + int(incoming["now_cost"])
        if best_squad is None:
            break
        chosen, spent = best_squad, best_spent
    return {"squad": chosen, "spent": spent, "bank": int(budget_tenths) - spent,
            "rating": team_rating(chosen, gameweeks, fixtures, minutes_overrides)}


# --- v4: honest forecast logging, walk-forward calibration and accuracy metrics ---
# The CSV input is *pre-deadline forecasts*, not recalculations from today's season stats.
SNAPSHOT_FIELDS = (
    "season", "gw", "player_id", "name", "position", "team_id", "created_utc",
    "deadline_utc", "model_version", "raw_xp", "predicted_xp", "expected_minutes",
    "fixtures_count",
)


def make_snapshot(players: list[dict], gw: int, fixtures: dict,
                  deadline_utc: str, season: str,
                  minutes_overrides: dict[int, float] | None = None,
                  now: datetime | None = None) -> list[dict]:
    """Make a reproducible record only *before* the selected GW deadline.

    Capture one row per player with a fixture; the caller must export the CSV.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Capture time must have timezone information")
    try:
        deadline = datetime.fromisoformat(deadline_utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("No valid UTC deadline for this Gameweek") from exc
    if deadline.tzinfo is None or now >= deadline:
        raise ValueError("Forecast snapshots must be captured before the FPL deadline")
    created = now.astimezone(timezone.utc).isoformat()
    rows = []
    for p in players:
        forecast = player_prediction(p, gw, fixtures, minutes_overrides)
        if forecast["fixtures_count"] == 0:
            continue
        rows.append({
            "season": str(season), "gw": int(gw), "player_id": int(p["id"]),
            "name": str(p.get("web_name", "?")), "position": int(p["element_type"]),
            "team_id": int(p["team"]), "created_utc": created,
            "deadline_utc": deadline.astimezone(timezone.utc).isoformat(),
            "model_version": "v7.21", "raw_xp": forecast["raw_xp"],
            "predicted_xp": forecast["xp"], "expected_minutes": forecast["minutes"],
            "fixtures_count": forecast["fixtures_count"],
        })
    return rows


def validate_snapshots(rows: list[dict], expected_season: str | None = None) -> list[dict]:
    """Reject invalid, non-predeadline or duplicated forecasts, not silently trusting CSVs."""
    clean, seen = [], set()
    for row in rows:
        try:
            gw, pid, pos = int(row["gw"]), int(row["player_id"]), int(row["position"])
            created = datetime.fromisoformat(str(row["created_utc"]).replace("Z", "+00:00"))
            deadline = datetime.fromisoformat(str(row["deadline_utc"]).replace("Z", "+00:00"))
            raw, pred = float(row["raw_xp"]), float(row["predicted_xp"])
            season = str(row["season"])
            if expected_season is not None and season != expected_season:
                continue
            if not (1 <= gw <= 38 and 1 <= pos <= 4 and pid > 0 and
                    created.tzinfo and deadline.tzinfo and created < deadline and
                    0 <= raw <= 60 and 0 <= pred <= 60):
                continue
            key = (season, gw, pid)
            # For duplicates prefer the earliest valid snapshot from that GW.
            if key in seen:
                continue
            seen.add(key)
            clean.append({"season": season, "gw": gw, "player_id": pid,
                          "position": pos, "raw_xp": raw, "predicted_xp": pred,
                          "expected_minutes": max(0.0, min(180.0, num(row.get("expected_minutes")))),
                          "created_utc": created.isoformat(),
                          "deadline_utc": deadline.isoformat()})
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return sorted(clean, key=lambda r: (r["gw"], r["player_id"]))


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = (len(values) - 1) * q
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def fit_calibration(completed: list[dict]) -> dict:
    """Shrink position mean errors toward zero to reduce overfitting.

    Every input must be an already-finalized captured forecast + actual points.
    """
    groups = {k: [] for k in range(1, 5)}
    for row in completed:
        if "actual_points" in row:
            groups[int(row["position"])].append(float(row["actual_points"]) - float(row["raw_xp"]))
    corrections, widths = {}, {}
    for pos, errors in groups.items():
        if errors:
            # 120-observation regularizer; max adjustment 1 point per player.
            corrections[pos] = clamp(sum(errors) / (len(errors) + 120), -1, 1)
            if len(errors) >= 80:
                widths[pos] = clamp(_quantile([abs(e - corrections[pos]) for e in errors], .80), 1.0, 18.0)
    return {"corrections": corrections, "widths": widths,
            "count": sum(len(g) for g in groups.values())}


def calibration_adjustment(position: int, raw_xp: float) -> float:
    return float(_MODEL["calibration"].get(int(position), 0.0))


def configure_calibration(completed: list[dict], target_gw: int) -> dict:
    """Strictly train on GW < target GW; never use outcomes from target GW."""
    earlier = [r for r in completed if int(r["gw"]) < int(target_gw)]
    fitted = fit_calibration(earlier)
    _MODEL["calibration"] = fitted["corrections"]
    _MODEL["residual_width"] = fitted["widths"]
    _MODEL["calibration_n"] = fitted["count"]
    _MODEL["cache"] = {}
    return fitted


def join_actuals(snapshots: list[dict], actuals_by_gw: dict[int, dict[int, int]],
                 finalized_gws: set[int]) -> list[dict]:
    """Only join against finalized gameweeks (avoid live provisional scores)."""
    completed = []
    for row in snapshots:
        gw, pid = int(row["gw"]), int(row["player_id"])
        if gw not in finalized_gws or pid not in actuals_by_gw.get(gw, {}):
            continue
        completed.append({**row, "actual_points": int(actuals_by_gw[gw][pid])})
    return completed


def backtest_report(completed: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    """Evaluate captured forecast MAE/bias and walk-forward-calibrated predictions.

    Each historical GW's adjustment is fitted from *strictly earlier* GW records.
    """
    if not completed:
        return {}, [], []
    evaluated = []
    # Fit just once per GW, making calibration linear in the number of rows.
    past_rows: list[dict] = []
    for gw in sorted({int(r["gw"]) for r in completed}):
        model = fit_calibration(past_rows)
        current = [r for r in completed if int(r["gw"]) == gw]
        for row in current:
            correction = model["corrections"].get(int(row["position"]), 0)
            raw = float(row["raw_xp"])
            actual = float(row["actual_points"])
            captured = float(row["predicted_xp"])
            walk_forward = max(0, raw + correction)
            evaluated.append({**row, "walk_forward_xp": round(walk_forward, 2),
                              "raw_error": round(raw - actual, 2),
                              "captured_error": round(captured - actual, 2),
                              "wf_error": round(walk_forward - actual, 2)})
        past_rows.extend(current)
    def summarize(rows):
        return {"count": len(rows),
                "raw_mae": round(mean(abs(r["raw_error"]) for r in rows), 3),
                "captured_mae": round(mean(abs(r["captured_error"]) for r in rows), 3),
                "walk_forward_mae": round(mean(abs(r["wf_error"]) for r in rows), 3),
                "bias": round(mean(r["captured_error"] for r in rows), 3)}
    overall = summarize(evaluated)
    by_position = [{"Position": POSITION_NAMES[pos], **summarize([r for r in evaluated if r["position"] == pos])}
                   for pos in range(1, 5) if any(r["position"] == pos for r in evaluated)]
    by_gw = [{"GW": gw, **summarize([r for r in evaluated if r["gw"] == gw])}
             for gw in sorted({r["gw"] for r in evaluated})]
    return overall, by_position, by_gw

# --- v7.15: scenario-aware, opportunity-aware three-plan transfer search ---
# Searches feasible moves over time; free-transfer opportunity cost is represented
# by which future moves remain possible, not by a large invented terminal bonus.

def smart_transfer_plan(squad: list[dict], player_pool: list[dict], gameweeks: list[int],
                        fixtures: dict, bank_tenths: int, free_transfers: int = 1,
                        strategy: str = "Balanced", minutes_overrides: dict[int, float] | None = None,
                        beam_width: int = 12, candidate_count: int = 9,
                        allow_hits: bool = True, max_transfers: int = 3,
                        milp_seeds: bool = True) -> dict:
    """Return three distinct multi-GW transfer plans and the ROLL counterfactual.

    Expected points = legal XI + captain contingency + legal auto-subs - hits.
    Search ranking separately considers plausible *downside scenarios*, small
    bench coverage, and a minimal transfer-friction tie-breaker. These are
    uncalibrated decision heuristics, not a guarantee or an FPL scoring rule.

    Future player prices are held fixed; chips and branching future
    transfer actions are not modelled. Appearance probabilities are heuristic.
    """
    if not valid_squad(squad):
        raise ValueError("A complete legal 15-player squad is required.")
    gameweeks = sorted(set(int(g) for g in gameweeks))[:6]
    if not gameweeks:
        raise ValueError("Select at least one upcoming Gameweek.")
    if int(bank_tenths) < 0 or not 0 <= int(free_transfers) <= 5:
        raise ValueError("Bank or free-transfer count is invalid.")
    if beam_width < 1 or candidate_count < 1:
        raise ValueError("Search width and candidate count must be positive.")

    from decision_v83 import adaptive_margin, ft_value, seed_moves
    from decision_v85 import flexibility_value, timing_adjustment, urgency_for, evidence
    auto = strategy == "Auto AI"
    strategy = strategy if strategy in ("Safe", "Balanced", "Aggressive") else "Balanced"
    max_transfers = max(0, min(3, int(max_transfers)))
    # Ranking factors are deliberately small, and never added to reported xP.
    downside_weight = {"Safe": .30, "Balanced": .14, "Aggressive": .04}[strategy]
    cover_weight = {"Safe": .06, "Balanced": .035, "Aggressive": .012}[strategy]
    # No move is an actual search action every week; there is NO transfer quota.
    # Because xP is uncertain, each optional move carries a small *decision*
    # cost (not an FPL hit and never subtracted from displayed FPL points).
    action_friction = {"Safe": .65, "Balanced": .45, "Aggressive": .20}[strategy]
    min_transfer_edge = {"Safe": .90, "Balanced": .55, "Aggressive": .22}[strategy]
    if free_transfers == 5:
        min_transfer_edge *= .5   # rolling cannot increase the FT balance at the cap
    # These are deliberately modest, uncalibrated terminal option values, in
    # decision-score units rather than realised/expected FPL points.  Saving a
    # fourth FT is less valuable than saving the first extra FT; hitting the
    # 5-FT cap must not award infinite banking value.
    future_ft_values = (0.0, 0.0, .80, 1.40, 1.85, 2.20)
    churn_cost = {"Safe": 1.65, "Balanced": 1.25, "Aggressive": .80}[strategy]
    early_commit_cost = {"Safe": .35, "Balanced": .25, "Aggressive": .12}[strategy]

    def ft_option_value(ft: int) -> float:
        if auto:
            return flexibility_value(ft, opportunity_points, gameweeks[-1] < 38)
        return future_ft_values[max(0, min(5, int(ft)))]

    market = {int(p["id"]): p for p in player_pool}
    market.update({int(p["id"]): p for p in squad})
    ids0 = tuple(sorted(int(p["id"]) for p in squad))
    selling0 = {int(p["id"]): int(p.get("selling_price", p.get("now_cost", 0)))
                for p in squad}
    positions = {pid: int(p["element_type"]) for pid, p in market.items()}
    clubs = {pid: int(p["team"]) for pid, p in market.items()}
    prices = {pid: int(p.get("now_cost", 0)) for pid, p in market.items()}
    n_weeks = len(gameweeks)
    # Even with a short 1–3 GW display horizon, the last GW is not the end of
    # a real FPL season.  Look a little further for the *quality of holdings*,
    # but do not count this soft tail as reported xP or pretend to optimise
    # future transfers not shown in the UI. Skip incomplete fixture calendars.
    tail_weeks: list[int] = []
    tail_weights: list[float] = []
    for offset, weight in ((1, .35), (2, .18)):
        later = gameweeks[-1] + offset
        coverage = sum(bool(fixtures.get((later, int(p["team"])), [])) for p in squad)
        if later <= 38 and coverage >= 10:
            tail_weeks.append(later)
            tail_weights.append(weight)
    projection_weeks = gameweeks + tail_weeks

    xp: dict[int, tuple[float, ...]] = {}
    downside_xp: dict[int, tuple[float, ...]] = {}
    for pid, player in market.items():
        series = tuple(max(0.0, player_fixture_xp(player, gw, fixtures, minutes_overrides))
                       for gw in projection_weeks)
        xp[pid] = series
        # The base prediction already incorporates available FPL injury flags.
        # This is an additional conditional stress test, NOT another predicted
        # probability of missing a match. Do not label it a confidence interval.
        minutes = (num(minutes_overrides[pid]) if minutes_overrides and pid in minutes_overrides
                   else projected_minutes(player))
        status = player.get("status", "a")
        if status in ("i", "s", "u", "n"):
            stress = .60
        elif status == "d":
            stress = .70
        elif minutes < 30:
            stress = .72
        elif minutes < 55:
            stress = .81
        elif minutes < 75:
            stress = .91
        else:
            stress = .97
        downside_xp[pid] = tuple(v * stress for v in series)

    # Appearance scenarios are built from the same player data as the XI.
    # These independent appearance estimates are explicit, uncalibrated proxies;
    # there is no claim to reproduce Solio's proprietary stochastic solver.
    appearances = {pid: tuple(estimated_appearance_probability(market[pid], gw,
                         fixtures, minutes_overrides, xp[pid][wi])
                              for wi, gw in enumerate(projection_weeks))
                   for pid in market}

    # v7.19: ALL eligible market players enter the cheap first-stage search.
    # Global top-N shortlists were unsafe: a highly projected but unaffordable
    # player could occupy a slot needed by a strong, affordable alternative.
    # Every player gets full horizon / individual-week xP before filtering;
    # affordability and the three-per-club rule are checked for each sale.
    eligible_by_pos = {
        pos: tuple(pid for pid, p in market.items()
                   if positions[pid] == pos and prices[pid] > 0
                   and (p.get("status", "a") not in ("u", "n", "s", "i")
                        or (p.get("status") == "i" and any(
                            availability(p, gw) >= .55 for gw in projection_weeks))))
        for pos in QUOTAS
    }
    # Estimate terminal opportunity from affordable future upgrades, not a fixed bonus per transfer.
    potential = []
    for old in ids0 if auto else ():
        gains = [sum(xp[new][j]-xp[old][j] for j in range(1, n_weeks))
                 for new in eligible_by_pos[positions[old]] if new not in ids0
                 and prices[new] <= bank_tenths + selling0[old]
                 and sum(clubs[i] == clubs[new] for i in ids0 if i != old) < 3]
        potential.append(max([0.] + gains))
    opportunity_scale = min(1.6, max(.6, .8 + sum(sorted(potential, reverse=True)[:3]) / max(12., 6.*n_weeks)))
    opportunity_points = sum(sorted(potential, reverse=True)[:3]) / max(1, n_weeks-1)
    seed_paths = []
    if auto and milp_seeds and max_transfers:
        try:
            seed_paths = seed_moves(market, ids0, selling0, prices, xp, gameweeks,
                [i for group in eligible_by_pos.values() for i in group], bank_tenths,
                max_transfers, allow_hits, free_transfers)
        except Exception:
            seed_paths = []  # bounded heuristic remains available
    # These are discovery tie-break signals only. Public FPL 'form' includes
    # realised returns and is NOT a calibrated xG or xA forecast; it must not
    # be added to predicted points or overrule the exact squad evaluation.
    recent_form = {pid: clamp(num(p.get("form")), 0, 12) for pid, p in market.items()}
    discovery_rough_first_week: set[int] = set()
    discovery_exact_first_week: set[int] = set()
    first_week_affordable_swaps = 0
    sample_limit = min(64, max(32, int(candidate_count) * 4))

    lineup_cache: dict[tuple[tuple[int, ...], int], tuple[float, float, float]] = {}

    def lineup_metrics(ids: tuple[int, ...], wi: int) -> tuple[float, float, float]:
        """Normal XI xP, same-lineup downside xP, first-bench reliability proxy."""
        key = (ids, wi)
        if key in lineup_cache:
            return lineup_cache[key]
        groups = {pos: sorted((pid for pid in ids if positions[pid] == pos),
                              key=lambda pid: xp[pid][wi], reverse=True)
                  for pos in QUOTAS}
        best_value, best_downside, best_cover = -1.0, 0.0, 0.0
        for d, m, f in FORMATIONS:
            xi = groups[1][:1] + groups[2][:d] + groups[3][:m] + groups[4][:f]
            if len(xi) != 11:
                continue
            captain = max(xi, key=lambda pid: xp[pid][wi])
            normal = sum(xp[pid][wi] for pid in xi) + xp[captain][wi]
            if normal > best_value:
                selected = set(xi)
                bench = sorted((downside_xp[pid][wi] for pid in ids
                                if pid not in selected and positions[pid] != 1), reverse=True)
                goalkeeper = [downside_xp[pid][wi] for pid in ids
                              if pid not in selected and positions[pid] == 1]
                best_cover = (bench[0] if bench else 0.0) + .2 * (goalkeeper[0] if goalkeeper else 0.0)
                best_value = normal
                best_downside = sum(downside_xp[pid][wi] for pid in xi) + downside_xp[captain][wi]
        answer = (best_value, best_downside, best_cover)
        lineup_cache[key] = answer
        return answer

    baseline_weekly = [lineup_metrics(ids0, wi)[0] for wi in range(n_weeks)]
    baseline = sum(baseline_weekly)
    baseline_tail_weekly = [lineup_metrics(ids0, n_weeks + j)[0]
                            for j in range(len(tail_weeks))]
    tail_cache: dict[tuple[int, ...], float] = {}

    def holding_quality(ids: tuple[int, ...]) -> float:
        """Heuristic post-horizon advantage, relative to keeping this squad.

        This is used ONLY to rank choices, never added to visible projected xP.
        It is deliberately discounted: there may be future free transfers.
        """
        if ids not in tail_cache:
            tail_cache[ids] = sum(weight * (
                lineup_metrics(ids, n_weeks + j)[0] - baseline_tail_weekly[j])
                for j, weight in enumerate(tail_weights))
        return tail_cache[ids]

    def next_ft_balance(ft: int, count: int) -> int:
        return min(5, max(0, ft - count) + 1)

    # A cheap per-player bound limits expensive full-XI recomputations.
    # Exact points are still used before any transfer is put in a plan.
    # Keep the cheap discovery window aligned with the displayed plan. The
    # post-horizon tail is discounted separately; it must NOT sneak into this
    # shortlist at full xP weight.
    suffix_xp = {pid: tuple(sum(values[wi:n_weeks]) for wi in range(n_weeks))
                 for pid, values in xp.items()}
    swap_cache: dict[tuple[tuple[int, ...], int, tuple[tuple[int, int], ...], int], list[tuple]] = {}

    def swaps_for(ids: tuple[int, ...], bank: int, sales: dict[int, int], wi: int,
                  max_options: int = 12) -> list[tuple[float, int, int, int]]:
        """Screen EVERY affordable transfer cheaply, then score a diverse sample.

        Full enumeration of 15-player squads across every pair/week is not
        tractable, but no player is rejected by a GLOBAL top-xP shortlist.
        We choose detailed candidates by multiple routes (horizon, immediate,
        future swing, value, cash release, and price band) so the cheap stage
        cannot drown out budget enablers or emerging players.
        """
        nonlocal first_week_affordable_swaps
        key = (ids, bank, tuple(sorted(sales.items())), wi)
        raw = swap_cache.get(key)
        if raw is None:
            owned = set(ids)
            counts = Counter(clubs[pid] for pid in ids)
            rough = []
            for old in ids:
                sale = sales.get(old, prices[old])
                budget = bank + sale
                for incoming in eligible_by_pos[positions[old]]:
                    if incoming in owned or prices[incoming] > budget:
                        continue
                    if counts[clubs[incoming]] >= 3 and clubs[incoming] != clubs[old]:
                        continue
                    new_bank = budget - prices[incoming]
                    released = new_bank - bank
                    rough_gain = suffix_xp[incoming][wi] - suffix_xp[old][wi]
                    immediate = xp[incoming][wi] - xp[old][wi]
                    future_swing = max(xp[incoming][j] - xp[old][j]
                                       for j in range(wi, n_weeks))
                    value = suffix_xp[incoming][wi] / max(35, prices[incoming])
                    # Includes a small form-discovery signal but never changes
                    # projections, net xP or the final ranking objective.
                    momentum = rough_gain + .14 * recent_form[incoming]
                    row = (rough_gain, immediate, released, old, incoming,
                           new_bank, future_swing, value, momentum)
                    rough.append(row)
                    if wi == 0 and ids == ids0:
                        discovery_rough_first_week.add(incoming)
            if wi == 0 and ids == ids0:
                first_week_affordable_swaps = len(rough)

            if not rough:
                raw = []
            else:
                by_gain = sorted(rough, key=lambda r: (r[0], r[1]), reverse=True)
                by_now = sorted(rough, key=lambda r: (r[1], r[0]), reverse=True)
                by_future = sorted(rough, key=lambda r: (r[6], r[0]), reverse=True)
                by_value = sorted(rough, key=lambda r: (r[7], r[0]), reverse=True)
                by_momentum = sorted(rough, key=lambda r: (r[8], r[0]), reverse=True)
                by_cash = sorted((r for r in rough if r[2] >= 8),
                                 key=lambda r: (r[2], r[0]), reverse=True)
                # Balance future xP lost with cash released. An ultra-cheap
                # player with enormous lost xP must not monopolise funding.
                by_funding = sorted((r for r in rough if r[2] >= 8),
                                    key=lambda r: (r[0] + .27 * r[2], r[2]),
                                    reverse=True)
                # One candidate in each feasible 0.5m selling-price bracket.
                # This protects mid-priced options squeezed between premium
                # xP leaders and very cheap value leaders.
                price_band_best = {}
                for row in rough:
                    band = prices[row[4]] // 5
                    if band not in price_band_best or row[0] > price_band_best[band][0]:
                        price_band_best[band] = row
                by_band = sorted(price_band_best.values(),
                                 key=lambda r: (r[0], r[1]), reverse=True)
                sample = []
                seen = set()
                # CPU guard: bounded distinct moves receive expensive full
                # XI evaluation per state; candidate_count scales this bound.
                # All affordable candidates
                # have still been scored in the cheap phase above.
                for bucket in (by_gain[:min(24, max(12, 2 * candidate_count - 4))],
                               by_funding[:min(12, max(6, candidate_count - 2))],
                               by_cash[:4], by_future[:6],
                               by_now[:6], by_momentum[:5],
                               by_value[:5], by_band[:min(18, max(8, candidate_count))]):
                    for r in bucket:
                        sig = (r[3], r[4])
                        if sig not in seen:
                            seen.add(sig)
                            sample.append(r)
                            if len(sample) >= sample_limit:
                                break
                    if len(sample) >= sample_limit:
                        break
                baseline_future = sum(lineup_metrics(ids, j)[0]
                                      for j in range(wi, n_weeks))
                raw = []
                for _, _, released, old, incoming, new_bank, *_ in sample:
                    if wi == 0 and ids == ids0:
                        discovery_exact_first_week.add(incoming)
                    next_ids = tuple(sorted((owned - {old}) | {incoming}))
                    gain = sum(lineup_metrics(next_ids, j)[0]
                               for j in range(wi, n_weeks)) - baseline_future
                    if gain < -3.5 and released < 8:
                        continue
                    raw.append((gain, old, incoming, new_bank, released))
            swap_cache[key] = raw

        if not raw:
            return []
        by_gain = sorted(raw, key=lambda r: (r[0], r[4]), reverse=True)
        by_cash = sorted((r for r in raw if r[4] >= 8),
                         key=lambda r: (r[4], r[0]), reverse=True)
        by_funding = sorted((r for r in raw if r[4] >= 8),
                            key=lambda r: (r[0] + .27 * r[4], r[4]), reverse=True)
        by_now = sorted(raw, key=lambda r: (xp[r[2]][wi] - xp[r[1]][wi], r[0]),
                        reverse=True)
        # Guarantee allocation for cash-releasing moves even when there are
        # more high-xP immediate swaps than the final option limit.
        chosen: list[tuple] = []
        seen = set()
        groups = ((by_gain, max(1, max_options - 5)),
                  (by_funding, 2), (by_cash, 2), (by_now, 1),
                  (by_gain, max_options))
        for bucket, quota in groups:
            added = 0
            for row in bucket:
                signature = (row[1], row[2])
                if signature in seen:
                    continue
                chosen.append(row)
                seen.add(signature)
                added += 1
                if len(chosen) >= max_options or added >= quota:
                    break
            if len(chosen) >= max_options:
                break
        return [(r[0], r[1], r[2], r[3]) for r in chosen]

    def move_data(out_id: int, in_id: int, sale: int) -> dict:
        return {"out": out_id, "in": in_id,
                "out_name": market[out_id].get("web_name", "?"),
                "in_name": market[in_id].get("web_name", "?"),
                "out_price": sale, "in_price": prices[in_id]}

    def moves_for(state: dict, wi: int):
        ids, bank, sales = state["ids"], state["bank"], state["sales"]
        yield ids, bank, sales, [], 0
        limit = min(max_transfers, 3 if wi == 0 else 2, state["ft"] if not allow_hits else 3)
        if not limit:
            return
        if wi == 0:
            for path in seed_paths:
                new_ids = set(ids); new_sales = dict(sales); cash = bank; moves = []
                for old, incoming in path:
                    sold = new_sales.pop(old); new_sales[incoming] = prices[incoming]
                    new_ids.remove(old); new_ids.add(incoming); cash += sold - prices[incoming]
                    moves.append(move_data(old, incoming, sold))
                if len(moves) <= limit:
                    yield tuple(sorted(new_ids)), cash, new_sales, moves, len(moves)
        first_moves = swaps_for(ids, bank, sales, wi)
        for _, old, incoming, bank1 in first_moves:
            ids1 = tuple(sorted((set(ids) - {old}) | {incoming}))
            sales1 = dict(sales)
            sold = sales1.pop(old, prices[old])
            sales1[incoming] = prices[incoming]
            move1 = move_data(old, incoming, sold)
            yield ids1, bank1, sales1, [move1], 1

        if limit < 2:
            return
        seen_pairs: set[tuple[tuple[int, int], ...]] = set()
        pair_states = []
        # The single-move list is stratified (gain, funding, cash, immediate).
        # IMPORTANT: do not take only the first six gain-ranked swaps: that
        # silently excluded the downgrades required to fund premium upgrades.
        # Reserve places for budget-enabling moves regardless of gain rank.
        pair_first_moves = list(first_moves[:5])
        for move in sorted(first_moves[6:], key=lambda m: (m[3] - bank, m[0]),
                           reverse=True):
            if move not in pair_first_moves:
                pair_first_moves.append(move)
                if len(pair_first_moves) >= 8:
                    break
        for _, old, incoming, bank1 in pair_first_moves:
            ids1 = tuple(sorted((set(ids) - {old}) | {incoming}))
            sales1 = dict(sales)
            sold = sales1.pop(old, prices[old])
            sales1[incoming] = prices[incoming]
            move1 = move_data(old, incoming, sold)
            for _, old2, incoming2, bank2 in swaps_for(ids1, bank1, sales1, wi, max_options=5):
                if old2 == incoming or incoming2 == old:
                    continue
                pair_key = tuple(sorted(((old, incoming), (old2, incoming2))))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                ids2 = tuple(sorted((set(ids1) - {old2}) | {incoming2}))
                sales2 = dict(sales1)
                sold2 = sales2.pop(old2, prices[old2])
                sales2[incoming2] = prices[incoming2]
                moves2 = [move1, move_data(old2, incoming2, sold2)]
                pair_states.append((ids2, bank2, sales2, moves2))
                yield ids2, bank2, sales2, moves2, 2

        if wi == 0 and limit >= 3:  # only first GW offers three transfers; cap computational work
            seen_triples: set[tuple[tuple[int, int], ...]] = set()
            # Focus triple-step search on strong pairs and budget-enabling pairs.
            ranked_pairs = sorted(pair_states,
                                  key=lambda p: (sum(lineup_metrics(p[0], j)[0]
                                                     for j in range(wi, n_weeks)), p[1]),
                                  reverse=True)
            for ids2, bank2, sales2, moves2 in ranked_pairs[:4]:
                for _, out3, in3, bank3 in swaps_for(ids2, bank2, sales2, wi, max_options=3):
                    if out3 in {m["in"] for m in moves2} or in3 in {m["out"] for m in moves2}:
                        continue
                    triple_key = tuple(sorted([(m["out"], m["in"]) for m in moves2] + [(out3, in3)]))
                    if triple_key in seen_triples:
                        continue
                    seen_triples.add(triple_key)
                    ids3 = tuple(sorted((set(ids2) - {out3}) | {in3}))
                    sales3 = dict(sales2)
                    sold3 = sales3.pop(out3, prices[out3])
                    sales3[in3] = prices[in3]
                    yield ids3, bank3, sales3, moves2 + [move_data(out3, in3, sold3)], 3

    # State dedup includes sales and bank because manager sales prices may differ
    # even with identical 15-player squads after different paths.
    states = [{"ids": ids0, "sales": selling0, "bank": int(bank_tenths),
               "ft": int(free_transfers), "net": 0.0, "down": 0.0,
               "cover": 0.0, "transfers": 0, "plan": [], "first_action": None,
               "purchased_at": {}, "sold_at": {}, "churn_penalty": 0.0,
               "early_commit_penalty": 0.0}]

    for wi, gw in enumerate(gameweeks):
        expanded: list[dict] = []
        for state in states:
            for ids, new_bank, sales, moves, count in moves_for(state, wi):
                hits = 4 * max(0, count - state["ft"])
                normal, downside, bench = lineup_metrics(ids, wi)
                ft_after = next_ft_balance(state["ft"], count)
                net = state["net"] + normal - hits
                down = state["down"] + downside - hits
                cover = state["cover"] + bench
                transfers = state["transfers"] + count
                # Penalise unnecessary short-term rentals and buybacks, but do
                # NOT forbid them: a large xP gain or real injury can still
                # justify the extra transfer. Track by player ID, not name.
                purchased_at = dict(state["purchased_at"])
                sold_at = dict(state["sold_at"])
                extra_churn = 0.0
                for move in moves:
                    outgoing, incoming = int(move["out"]), int(move["in"])
                    if outgoing in purchased_at:
                        age = wi - purchased_at[outgoing]
                        if age == 1:
                            extra_churn += churn_cost
                        elif age == 2:
                            extra_churn += churn_cost * .40
                    if incoming in sold_at:
                        age = wi - sold_at[incoming]
                        if age == 1:
                            extra_churn += churn_cost * .70
                        elif age == 2:
                            extra_churn += churn_cost * .25
                    purchased_at.pop(outgoing, None)
                    purchased_at[incoming] = wi
                    sold_at[outgoing] = wi
                    sold_at.pop(incoming, None)
                total_churn = state["churn_penalty"] + extra_churn
                # With static future prices, an early transfer that helps the
                # XI *zero* this week can usually wait for additional news.
                # Prefer deferring it; don't penalise meaningful immediate
                # upgrades, and do not prohibit funding moves outright.
                gain_this_week = normal - lineup_metrics(state["ids"], wi)[0]
                premature_cost = (early_commit_cost * min(count, 2)
                                  if count and wi < n_weeks - 1
                                  and gain_this_week <= .10 else 0.0)
                total_early_commit = state["early_commit_penalty"] + premature_cost
                future = sum(lineup_metrics(ids, j)[0] for j in range(wi + 1, n_weeks))
                future_down = sum(lineup_metrics(ids, j)[1] for j in range(wi + 1, n_weeks))
                # Accumulate risk penalty relative to the base forecast.
                rank = (net + future
                        - downside_weight * ((net + future) - (down + future_down))
                        + cover_weight * cover - action_friction * transfers
                        - total_churn - total_early_commit
                        + ft_option_value(ft_after) + holding_quality(ids))
                first_action = state["first_action"]
                if first_action is None:
                    first_action = ("ROLL" if count == 0 else
                                    "ONE" if count == 1 else "TWO" if count == 2 else "THREE")
                week = {"gw": gw, "moves": moves, "hits": hits, "bank": new_bank,
                        "free_transfers_before": state["ft"],
                        "free_transfers_after": ft_after,
                        "projected_xp": round(normal, 2),
                        "net_xp": round(normal - hits, 2),
                        "short_term_reversal_cost": round(extra_churn, 3),
                        "premature_commitment_cost": round(premature_cost, 3)}
                expanded.append({"ids": ids, "sales": sales, "bank": new_bank,
                                 "ft": ft_after, "net": net, "down": down,
                                 "cover": cover, "transfers": transfers, "rank": rank,
                                 "first_action": first_action,
                                 "purchased_at": purchased_at, "sold_at": sold_at,
                                 "churn_penalty": total_churn,
                                 "early_commit_penalty": total_early_commit,
                                 "plan": state["plan"] + [week]})
        # Preserve four independent first-week strategies so the search can
        # evaluate ROLL even when today's transfer has tempting immediate xP.
        kept = []
        for kind in ("ROLL", "ONE", "TWO", "THREE"):
            unique = set()
            group = sorted((s for s in expanded if s["first_action"] == kind),
                           key=lambda s: (s["rank"], s["net"], s["ft"]), reverse=True)
            for s in group:
                sig = (s["ids"], s["ft"], s["bank"], tuple(sorted(s["sales"].items())))
                if sig in unique:
                    continue
                unique.add(sig)
                kept.append(s)
                if len(unique) >= beam_width:
                    break
        if not kept:
            raise ValueError("Could not find a legal transfer plan.")
        states = kept

    # SECOND PASS: model all independent play/no-play outcomes for all
    # retained beam states. Use a positional count DP plus legal bench masks,
    # rather than the very expensive 2^15 raw scenario tree *during search*.
    # Future actions remain fixed in each plan; this is NOT Solio's adaptive
    # stochastic programming or a calibrated probability model.
    risk_lineups = {}

    def contingency_lineup(ids: tuple[int, ...], wi: int) -> tuple[float, float]:
        key = (ids, wi)
        cached = contingency_cache.get(key)
        if cached is not None:
            return cached
        normal_points = {pid: xp[pid][wi] for pid in ids}
        downside_points = {pid: downside_xp[pid][wi] for pid in ids}
        chance = {pid: appearances[pid][wi] for pid in ids}
        no_shows = {pid for pid in ids if _confirmed_unavailable_for_xi(
            market[pid], normal_points[pid], chance[pid])}
        groups = {pos: sorted((pid for pid in ids if positions[pid] == pos),
                              key=lambda pid: (pid not in no_shows,
                                               normal_points[pid]), reverse=True)
                  for pos in QUOTAS}
        formation_candidates = []
        for defenders, midfielders, forwards in FORMATIONS:
            xi = (groups[1][:1] + groups[2][:defenders] +
                  groups[3][:midfielders] + groups[4][:forwards])
            if len(xi) == 11:
                formation_candidates.append((xi, len(no_shows.intersection(xi))))
        fewest_no_shows = min((count for _, count in formation_candidates), default=0)
        best_normal, best_down = float('-inf'), 0.0
        for xi, count in formation_candidates:
            if count > fewest_no_shows:
                continue
            selected = set(xi)
            bench = sorted((pid for pid in ids if pid not in selected),
                           key=lambda pid: (positions[pid] == 1, -normal_points[pid]))
            evaluation = _scenario_lineup_evaluation(xi, bench, normal_points,
                                                      chance, positions)
            if evaluation['total'] > best_normal:
                stressed = _scenario_lineup_evaluation(xi, bench, downside_points,
                                    chance, positions, captain_id=evaluation['captain_id'],
                                    vice_id=evaluation['vice_id'])
                best_normal, best_down = evaluation['total'], stressed['total']
                risk_lineups[key] = (tuple(xi), tuple(bench), evaluation['captain_id'], evaluation['vice_id'])
        contingency_cache[key] = (best_normal, best_down)
        return best_normal, best_down

    contingency_cache: dict[tuple[tuple[int, ...], int], tuple[float, float]] = {}
    for state in states:
        current_ids = set(ids0)
        net = down = 0.0
        for wi, week in enumerate(state['plan']):
            for move in week['moves']:
                current_ids.remove(int(move['out']))
                current_ids.add(int(move['in']))
            normal, downside = contingency_lineup(tuple(sorted(current_ids)), wi)
            week['projected_xp'] = round(normal, 2)
            week['net_xp'] = round(normal - week['hits'], 2)
            net += normal - week['hits']
            down += downside - week['hits']
        state['net'] = net
        state['down'] = down
        # Insurance is counted in net_xP: no separate bench bonus now.
        state['cover'] = 0.0
    baseline_weekly = [contingency_lineup(ids0, wi)[0] for wi in range(n_weeks)]
    baseline = sum(baseline_weekly)
    cover_weight = 0.0

    def utility(s: dict) -> float:
        return (s["net"] - downside_weight * (s["net"] - s["down"])
                + cover_weight * s["cover"]
                - action_friction * s["transfers"] - s["churn_penalty"]
                - s["early_commit_penalty"]
                + ft_option_value(s["ft"]) + holding_quality(s["ids"]))

    def margin_for(s: dict) -> float:
        if s["first_action"] == "ROLL":
            return 0.
        if not auto:
            return min_transfer_edge
        first = s["plan"][0]
        # Compare immediate team benefit, not individual-player gain.
        return adaptive_margin(n_weeks, free_transfers, len(first["moves"]),
                               first["projected_xp"] - baseline_weekly[0])

    def legacy_decision_score(s: dict) -> float:
        return utility(s) - margin_for(s)

    # V8.4: paired scenarios only after the legal beam search. Preserve the
    # original expected points, hits, terminal FT value and all constraints.
    risk_results = {}
    risk_status = "fallback"
    try:
        from monte_carlo_v84 import evaluate_states
        def risk_minutes(pid, wi):
            return (num(minutes_overrides[pid]) if minutes_overrides and pid in minutes_overrides
                    else projected_minutes(market[pid], gameweeks[wi]))
        risk_results = evaluate_states(states, ids0, lambda ids, wi: risk_lineups[(ids, wi)],
            xp, appearances, positions, clubs, risk_minutes, legacy_decision_score, strategy)
        risk_status = "active"
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("V8.4 risk fallback: %s", type(exc).__name__)
        # Atomic fallback: never rank some plans with risk and others without.
        risk_results = {}

    timing_costs, urgency_values = {}, {}
    initial_xi = risk_lineups.get((ids0, 0), ((), (), None, None))[0]
    for state in states:
        row = state['plan'][0]
        urgency = urgency_for(row['moves'], appearances, initial_xi)
        urgency_values[id(state)] = urgency
        timing_costs[id(state)] = timing_adjustment(len(row['moves']), free_transfers,
            row['projected_xp'] - baseline_weekly[0], opportunity_points, urgency,
            strategy, gameweeks[0] < 38) if risk_status == 'active' else 0.

    def decision_score(s: dict) -> float:
        return legacy_decision_score(s) - risk_results.get(id(s), {}).get('uncertainty_margin', 0.) - timing_costs[id(s)]

    preference = {"ROLL": 3, "ONE": 2, "TWO": 1, "THREE": 0}
    kinds = ("ROLL", "ONE", "TWO", "THREE")
    best_by_kind = {kind: max((s for s in states if s["first_action"] == kind),
                              key=decision_score, default=None) for kind in kinds}
    available = {k: s for k, s in best_by_kind.items() if s is not None}
    if not available:
        raise ValueError("No valid transfer strategies were found.")
    best_kind = max(available, key=lambda k: (decision_score(available[k]), preference[k]))
    best = available[best_kind]
    best_roll = best_by_kind["ROLL"]
    best_transfer = max((available[k] for k in ("ONE", "TWO", "THREE") if k in available),
                        key=decision_score, default=None)

    options = []
    for kind in kinds:
        s = best_by_kind[kind]
        if s is None:
            options.append({"key": kind, "label": {"ROLL": "Roll", "ONE": "1 Transfer",
                        "TWO": "2 Transfers", "THREE": "3 Transfers"}[kind],
                        "available": False, "recommended": False})
            continue
        options.append({
            "key": kind, "label": {"ROLL": "Roll", "ONE": "1 Transfer",
                        "TWO": "2 Transfers", "THREE": "3 Transfers"}[kind],
            "available": True, "recommended": kind == best_kind,
            "action": "ROLL" if kind == "ROLL" else "TRANSFER",
            "plan": s["plan"], "first_moves": s["plan"][0]["moves"],
            "first_hit": s["plan"][0]["hits"],
            "first_free_transfers_after": s["plan"][0]["free_transfers_after"],
            "expected_gain": round(s["net"] - baseline, 2),
            "planned_net_xp": round(s["net"], 2),
            "decision_utility": round(utility(s), 3),
            "decision_score": round(decision_score(s), 3),
            "monte_carlo": risk_results.get(id(s)),
            "downside_scenario_net_xp": round(s["down"], 2),
            "future_ft_option_value": round(ft_option_value(s["ft"]), 2),
            "post_horizon_holding_score": round(holding_quality(s["ids"]), 2),
            "short_term_reversal_cost": round(s["churn_penalty"], 2),
            "premature_commitment_cost": round(s["early_commit_penalty"], 2),
            "total_hits": sum(row["hits"] for row in s["plan"]),
            "final_bank": s["bank"], "final_free_transfers": s["ft"],
        })
    ranked_options = sorted([opt for opt in options if opt["available"]],
                            key=lambda opt: (opt["decision_score"],
                                             preference[opt["key"]]), reverse=True)
    for rank, opt in enumerate(ranked_options, 1):
        opt["rank"] = rank

    # Three different itineraries. First prefer distinct immediate incoming
    # targets; then allow different deferred plans when no more are available.
    ranked_states = sorted(states, key=lambda s: (decision_score(s),
                                      preference[s["first_action"]]), reverse=True)
    distinct = []
    first_signatures: set[tuple[int, ...]] = set()
    full_signatures: set[tuple[tuple[tuple[int, int], ...], ...]] = set()
    for s in ranked_states:
        first_sig = tuple(sorted(m["in"] for m in s["plan"][0]["moves"]))
        full_sig = tuple(tuple(sorted((m["out"], m["in"]) for m in row["moves"]))
                         for row in s["plan"])
        if first_sig in first_signatures or full_sig in full_signatures:
            continue
        distinct.append(s)
        first_signatures.add(first_sig)
        full_signatures.add(full_sig)
        if len(distinct) >= 3:
            break
    if len(distinct) < 3:
        for s in ranked_states:
            full_sig = tuple(tuple(sorted((m["out"], m["in"]) for m in row["moves"]))
                             for row in s["plan"])
            if full_sig in full_signatures:
                continue
            distinct.append(s)
            full_signatures.add(full_sig)
            if len(distinct) >= 3:
                break

    # The winner of the ranked-plan list MUST agree with the top recommendation
    # returned elsewhere; otherwise the UI could contradict itself.
    if distinct and distinct[0] is not best:
        distinct = [best] + [s for s in distinct if s is not best][:2]

    # Plans are alternatives, not three near-copies of the same immediate
    # spend. If waiting is competitively close to the winning transfer plan,
    # reserve one of the three slots for that first-GW ROLL counterfactual.
    # Do not show it as a top-three alternative when it is far worse.
    competitive_roll = (best_roll is not None and best is not best_roll
                        and best['first_action'] != 'ROLL'
                        and decision_score(best) - decision_score(best_roll) <= 1.5)
    if competitive_roll and not any(s['first_action'] == 'ROLL' for s in distinct):
        if len(distinct) >= 3:
            distinct[-1] = best_roll
        else:
            distinct.append(best_roll)

    ranked_plans = []
    for i, s in enumerate(distinct, 1):
        first = s["plan"][0]
        ranked_plans.append({
            "plan_number": i, "label": f"Plan {i}",
            "first_action": s["first_action"], "recommended": i == 1,
            "plan": s["plan"], "first_moves": first["moves"],
            "first_hit": first["hits"],
            "first_free_transfers_after": first["free_transfers_after"],
            "expected_gain": round(s["net"] - baseline, 2),
            "planned_net_xp": round(s["net"], 2),
            "decision_score": round(decision_score(s), 3),
            "monte_carlo": risk_results.get(id(s)),
            "downside_scenario_net_xp": round(s["down"], 2),
            "future_ft_option_value": round(ft_option_value(s["ft"]), 2),
            "post_horizon_holding_score": round(holding_quality(s["ids"]), 2),
            "short_term_reversal_cost": round(s["churn_penalty"], 2),
            "premature_commitment_cost": round(s["early_commit_penalty"], 2),
            "total_hits": sum(row["hits"] for row in s["plan"]),
            "final_bank": s["bank"], "final_free_transfers": s["ft"],
        })

    first = best["plan"][0]
    return {
        "ranked_plans": ranked_plans,
        "action": "ROLL" if best_kind == "ROLL" else "TRANSFER",
        "recommended_option": best_kind, "options": options,
        "plan": best["plan"], "first_moves": first["moves"], "first_hit": first["hits"],
        "expected_gain": round(best["net"] - baseline, 2),
        "baseline_xp": round(baseline, 2), "planned_net_xp": round(best["net"], 2),
        "total_hits": sum(row["hits"] for row in best["plan"]),
        "final_bank": best["bank"], "final_free_transfers": best["ft"],
        "baseline_weekly": [round(x, 2) for x in baseline_weekly],
        "roll_first_net_xp": round(best_roll["net"], 2) if best_roll else None,
        "transfer_first_net_xp": round(best_transfer["net"], 2) if best_transfer else None,
        "roll_first_decision_utility": round(utility(best_roll), 2) if best_roll else None,
        "transfer_first_decision_utility": round(utility(best_transfer), 2) if best_transfer else None,
        "decision_margin": round(margin_for(best_transfer) + risk_results.get(id(best_transfer), {}).get("uncertainty_margin", 0.) + timing_costs[id(best_transfer)], 3) if best_transfer else 0.,
        "decision_version": "8.5",
        "dynamic_decision": evidence(best, best_transfer if best_kind == "ROLL" else best_roll,
                                     decision_score, risk_status == "active", timing_costs, urgency_values),
        "monte_carlo": {"status": risk_status, "reference": "best V8.3 roll-first plan",
                        "recommended": risk_results.get(id(best)),
                        "best_transfer": risk_results.get(id(best_transfer)),
                        "evaluated_plans": len(risk_results),
                        "calibrated": False},
        "strategy_used": "Auto AI" if auto else strategy,
        "milp_seed_count": len(seed_paths),
        "ft_opportunity_scale": round(opportunity_scale, 3) if auto else 1.,
        "transfer_first_decision_score": round(decision_score(best_transfer), 3) if best_transfer else None,
        "roll_first_decision_score": round(decision_score(best_roll), 3) if best_roll else None,
        "long_term_audit": {
            "visible_gameweeks": list(gameweeks),
            "holding_view_gameweeks": list(tail_weeks),
            "holding_view_weights": [round(w, 2) for w in tail_weights],
            "roll_first_decision_score": round(decision_score(best_roll), 3) if best_roll else None,
            "recommended_decision_score": round(decision_score(best), 3),
            "recommended_vs_roll_decision_margin": (
                round(decision_score(best) - decision_score(best_roll), 3)
                if best_roll else None),
            "recommended_short_term_reversal_cost": round(best["churn_penalty"], 2),
            "recommended_premature_commitment_cost": round(best["early_commit_penalty"], 2),
            "recommended_saved_ft_value": round(ft_option_value(best["ft"]), 2),
            "competitive_roll_shown": bool(competitive_roll),
        },
        "discovery_audit": {
            "eligible_players": sum(len(group) for group in eligible_by_pos.values()),
            "eligible_by_position": {POSITION_NAMES[pos]: len(eligible_by_pos[pos]) for pos in QUOTAS},
            "affordable_legal_first_week_swaps": first_week_affordable_swaps,
            "first_week_rough_targets": len(discovery_rough_first_week),
            "first_week_exact_targets": len(discovery_exact_first_week),
            # Internal diagnostics; the existing UI can safely ignore them.
            "eligible_player_ids": sorted(pid for group in eligible_by_pos.values() for pid in group),
            "initial_owned_ids": list(ids0),
            "first_week_rough_target_ids": sorted(discovery_rough_first_week),
            "first_week_exact_target_ids": sorted(discovery_exact_first_week),
            "exhaustive_planning": False,
        },
        "method": ("v7.19.1 full-market per-squad-budget screening + bounded diverse search: "
                   "0–3 moves in the first GW; 0–2 later, "
                   "legal 15-player squads, 5-FT rollover, 4-point hits, manager selling prices. "
                   "Rank by XI+captain+vice and legal auto-sub expected points (post-search), with heuristic "
                   "appearance/downside, declining option value of saved free transfers, "
                   "short-term buy/sell churn, deferral of no-benefit early moves, "
                   "and a discounted post-horizon holding view "
                   "when fixtures are available. These decision heuristics never change "
                   "reported net xP. A competitive ROLL-first counterfactual "
                   "is shown as an alternative when available. Current prices fixed; "
                   "no chips or adaptive future scenario tree."),
    }


def audit_transfer_candidate(plan_result: dict, player_id: int) -> dict:
    """Explain how a particular target progressed through FIRST-GW discovery.

    This does NOT claim a complete causal explanation of why a player was
    excluded from a multi-GW plan; the beam search is deliberately bounded.
    It is a stage audit that distinguishes absence from initial screening,
    exclusion by legality/price, and inclusion in a shortlisted plan.
    """
    pid = int(player_id)
    diagnostics = plan_result.get("discovery_audit", {})
    owned = pid in diagnostics.get("initial_owned_ids", [])
    eligible = pid in diagnostics.get("eligible_player_ids", [])
    affordable = pid in diagnostics.get("first_week_rough_target_ids", [])
    exact = pid in diagnostics.get("first_week_exact_target_ids", [])
    chosen = [int(p["plan_number"]) for p in plan_result.get("ranked_plans", [])
              if any(int(m["in"]) == pid for week in p.get("plan", [])
                     for m in week.get("moves", []))]
    if owned:
        status = "already_owned"
    elif chosen:
        status = "appears_in_top_plans"
    elif not eligible:
        status = "not_eligible_for_new_transfer"
    elif exact:
        status = "first_week_full_squad_evaluated_but_not_selected"
    elif affordable:
        status = "first_week_affordable_screened_only"
    else:
        status = "not_directly_affordable_or_legal_in_first_week"
    return {
        "player_id": pid, "status": status,
        "initially_owned": owned, "eligible": eligible,
        "first_week_roughly_screened": affordable,
        "first_week_full_squad_evaluated": exact,
        "top_plan_numbers": chosen,
        "exhaustive_search": False,
        "caution": ("This is a first-week candidate-discovery audit, not a "
                    "complete attribution of forecast or strategy differences. "
                    "Later-week candidates and transfer combinations may differ."),
    }
