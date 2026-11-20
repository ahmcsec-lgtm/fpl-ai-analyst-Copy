"""AJK Bola Wawei AI v7.18: free, transparent FPL estimators and squad tools.

No paid model, no official xP claim. All monetary amounts are FPL tenths.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
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
          "attack_venue": {}, "defence_venue": {}}


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


def availability(player: dict) -> float:
    status = player.get("status", "a")
    chance = player.get("chance_of_playing_next_round")
    factor = {"a": 1.0, "d": .68, "i": .12, "s": 0.0, "u": .08, "n": 0.0}.get(status, .6)
    if chance is not None:
        factor = min(factor, clamp(num(chance) / 100, 0, 1))
    return factor


def projected_minutes(player: dict) -> float:
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
    return round(clamp(effective * availability(player), 0, 90), 1)



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


def player_prediction(player: dict, gw: int, fixtures: dict,
                      minutes_overrides: dict[int, float] | None = None) -> dict:
    """Return explainable projected FPL points and an approximate 80% range."""
    pid = int(player["id"])
    override = (minutes_overrides or {}).get(pid)
    minutes = clamp(num(override, projected_minutes(player)), 0, 90)
    key = (pid, int(gw), round(minutes, 2), id(fixtures))
    cached = _MODEL["cache"].get(key)
    if cached is not None:
        return cached
    games = fixtures.get((int(gw), int(player.get("team", 0))), [])
    totals = {k: 0.0 for k in ("appearance", "goals", "assists", "clean_sheet", "saves",
                                  "goals_conceded", "bonus", "defensive_contributions", "discipline",
                                  "goal_expectation", "assist_expectation")}
    cs_probs = []
    opponent_goals = []
    variance = 0.0
    pos = int(player.get("element_type", 3))
    for match in games:
        comp = _fixture_components(player, int(match["opponent"]), bool(match["home"]),
                                   minutes, int(match.get("difficulty", 3)))
        for k in totals:
            totals[k] += comp[k]
        cs_probs.append(comp["cs_probability"])
        opponent_goals.append(comp["expected_opponent_goals"])
        variance += ({1: 10, 2: 6, 3: 5, 4: 4}[pos] ** 2 * comp["goal_expectation"]
                     + 9 * comp["assist_expectation"]
                     + ({1: 4, 2: 4, 3: 1, 4: 0}[pos] ** 2) *
                     comp["cs_probability"] * (1 - comp["cs_probability"]) + 2.0)
    raw_xp = max(0.0, sum(totals[k] for k in totals if k not in ("goal_expectation", "assist_expectation")))
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
                      and p.get("status", "a") not in ("i", "n", "s", "u")]
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
    mins = clamp(num(minutes_overrides[pid]) if manual else projected_minutes(player), 0, 90)
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
        chance = min(chance, availability(player))
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
               else projected_minutes(p) for pid, p in by_id.items()}
    groups = {pos: sorted((p for p in squad if int(p['element_type']) == pos),
                          key=lambda p: (xp[int(p['id'])], minutes[int(p['id'])]),
                          reverse=True) for pos in QUOTAS}
    best, best_score, best_minutes = None, float('-inf'), float('-inf')
    best_bench, best_evaluation = None, None
    for defenders, midfielders, forwards in FORMATIONS:
        candidate = ([groups[1][0]] + groups[2][:defenders] +
                     groups[3][:midfielders] + groups[4][:forwards])
        xi_ids = [int(p['id']) for p in candidate]
        selected = set(xi_ids)
        bench = sorted((p for p in squad if int(p['id']) not in selected),
                       key=lambda p: (int(p['element_type']) == 1, -xp[int(p['id'])]))
        bench_ids = [int(p['id']) for p in bench]
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
            "model_version": "v4", "raw_xp": forecast["raw_xp"],
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
                        beam_width: int = 12, candidate_count: int = 9) -> dict:
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

    strategy = strategy if strategy in ("Safe", "Balanced", "Aggressive") else "Balanced"
    # Ranking factors are deliberately small, and never added to reported xP.
    downside_weight = {"Safe": .30, "Balanced": .14, "Aggressive": .04}[strategy]
    cover_weight = {"Safe": .06, "Balanced": .035, "Aggressive": .012}[strategy]
    action_friction = {"Safe": .10, "Balanced": .055, "Aggressive": .018}[strategy]
    min_transfer_edge = {"Safe": .90, "Balanced": .55, "Aggressive": .22}[strategy]
    if free_transfers == 5:
        min_transfer_edge *= .5   # rolling cannot increase the FT balance at the cap
    terminal_ft_tiebreak = .025    # << one projected FPL point, never presented as xP

    market = {int(p["id"]): p for p in player_pool}
    market.update({int(p["id"]): p for p in squad})
    ids0 = tuple(sorted(int(p["id"]) for p in squad))
    selling0 = {int(p["id"]): int(p.get("selling_price", p.get("now_cost", 0)))
                for p in squad}
    positions = {pid: int(p["element_type"]) for pid, p in market.items()}
    clubs = {pid: int(p["team"]) for pid, p in market.items()}
    prices = {pid: int(p.get("now_cost", 0)) for pid, p in market.items()}
    n_weeks = len(gameweeks)

    xp: dict[int, tuple[float, ...]] = {}
    downside_xp: dict[int, tuple[float, ...]] = {}
    for pid, player in market.items():
        series = tuple(max(0.0, player_fixture_xp(player, gw, fixtures, minutes_overrides))
                       for gw in gameweeks)
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
                              for wi, gw in enumerate(gameweeks))
                   for pid in market}

    horizon = {pid: sum(values) for pid, values in xp.items()}
    shortlist: dict[int, list[int]] = {}
    for pos in QUOTAS:
        eligible = [pid for pid in market if positions[pid] == pos and prices[pid] > 0 and
                    market[pid].get("status", "a") not in ("u", "n", "s", "i")]
        # Diversify: whole-horizon prospects, future GW specialists, cheaper
        # budget enablers, and players with high points/price. The old shortlist
        # sometimes missed the first leg of a useful two-player combination.
        by_horizon = sorted(eligible, key=lambda pid: horizon[pid], reverse=True)[:candidate_count]
        by_week = [pid for wi in range(n_weeks)
                   for pid in sorted(eligible, key=lambda p: xp[p][wi], reverse=True)[:3]]
        by_value = sorted(eligible, key=lambda pid: horizon[pid] / max(35, prices[pid]),
                          reverse=True)[:4]
        by_price = sorted(eligible, key=lambda pid: (prices[pid], -horizon[pid]))[:5]
        shortlist[pos] = list(dict.fromkeys(by_horizon + by_week + by_value + by_price))

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

    def next_ft_balance(ft: int, count: int) -> int:
        return min(5, max(0, ft - count) + 1)

    # A cheap per-player bound limits expensive full-XI recomputations.
    # Exact points are still used before any transfer is put in a plan.
    suffix_xp = {pid: tuple(sum(values[wi:]) for wi in range(n_weeks))
                 for pid, values in xp.items()}
    swap_cache: dict[tuple[tuple[int, ...], int, tuple[tuple[int, int], ...], int], list[tuple]] = {}

    def swaps_for(ids: tuple[int, ...], bank: int, sales: dict[int, int], wi: int,
                  max_options: int = 12) -> list[tuple[float, int, int, int]]:
        key = (ids, bank, tuple(sorted(sales.items())), wi)
        raw = swap_cache.get(key)
        if raw is None:
            owned = set(ids)
            counts = Counter(clubs[pid] for pid in ids)
            rough = []
            for old in ids:
                sale = sales.get(old, prices[old])
                budget = bank + sale
                for incoming in shortlist[positions[old]]:
                    if incoming in owned or prices[incoming] > budget:
                        continue
                    if counts[clubs[incoming]] >= 3 and clubs[incoming] != clubs[old]:
                        continue
                    new_bank = budget - prices[incoming]
                    released = new_bank - bank
                    rough_gain = suffix_xp[incoming][wi] - suffix_xp[old][wi]
                    immediate = xp[incoming][wi] - xp[old][wi]
                    rough.append((rough_gain, immediate, released, old, incoming, new_bank))
            if not rough:
                swap_cache[key] = []
            else:
                # Compare exactly only a diversified candidate group. A large
                # league-wide shortlist otherwise creates thousands of costly
                # formation evaluations for each beam state.
                by_rough = sorted(rough, key=lambda r: (r[0], r[2]), reverse=True)
                by_release = sorted((r for r in rough if r[2] >= 10),
                                    key=lambda r: (r[2], r[0]), reverse=True)
                by_immediate = sorted(rough, key=lambda r: (r[1], r[0]), reverse=True)
                sample = []
                seen = set()
                for bucket in (by_rough[:30], by_release[:10], by_immediate[:9]):
                    for r in bucket:
                        if (r[3], r[4]) not in seen:
                            sample.append(r)
                            seen.add((r[3], r[4]))
                baseline_future = sum(lineup_metrics(ids, j)[0] for j in range(wi, n_weeks))
                raw = []
                for _, _, released, old, incoming, new_bank in sample:
                    next_ids = tuple(sorted((owned - {old}) | {incoming}))
                    gain = sum(lineup_metrics(next_ids, j)[0]
                               for j in range(wi, n_weeks)) - baseline_future
                    if gain < -3.5 and released < 10:
                        continue
                    raw.append((gain, old, incoming, new_bank, released))
                swap_cache[key] = raw
        if not raw:
            return []
        by_gain = sorted(raw, key=lambda r: (r[0], r[4]), reverse=True)
        by_release = sorted((r for r in raw if r[4] >= 10),
                            key=lambda r: (r[4], r[0]), reverse=True)
        by_now = sorted(raw, key=lambda r: (xp[r[2]][wi] - xp[r[1]][wi], r[0]), reverse=True)
        chosen: list[tuple] = []
        seen = set()
        for bucket in (by_gain[:max(1, max_options - 3)], by_release[:3], by_now[:3], by_gain):
            for row in bucket:
                signature = (row[1], row[2])
                if signature not in seen:
                    chosen.append(row)
                    seen.add(signature)
                    if len(chosen) == max_options:
                        break
            if len(chosen) == max_options:
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
        first_moves = swaps_for(ids, bank, sales, wi)
        for _, old, incoming, bank1 in first_moves:
            ids1 = tuple(sorted((set(ids) - {old}) | {incoming}))
            sales1 = dict(sales)
            sold = sales1.pop(old, prices[old])
            sales1[incoming] = prices[incoming]
            move1 = move_data(old, incoming, sold)
            yield ids1, bank1, sales1, [move1], 1

        seen_pairs: set[tuple[tuple[int, int], ...]] = set()
        pair_states = []
        # Bring at least one cash-releasing first step into pair search.
        for _, old, incoming, bank1 in first_moves[:6]:
            ids1 = tuple(sorted((set(ids) - {old}) | {incoming}))
            sales1 = dict(sales)
            sold = sales1.pop(old, prices[old])
            sales1[incoming] = prices[incoming]
            move1 = move_data(old, incoming, sold)
            for _, old2, incoming2, bank2 in swaps_for(ids1, bank1, sales1, wi, max_options=6):
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

        if wi == 0:  # only first GW offers three transfers; cap computational work
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
               "cover": 0.0, "transfers": 0, "plan": [], "first_action": None}]

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
                future = sum(lineup_metrics(ids, j)[0] for j in range(wi + 1, n_weeks))
                future_down = sum(lineup_metrics(ids, j)[1] for j in range(wi + 1, n_weeks))
                # Accumulate risk penalty relative to the base forecast.
                rank = (net + future
                        - downside_weight * ((net + future) - (down + future_down))
                        + cover_weight * cover - action_friction * transfers
                        + terminal_ft_tiebreak * ft_after)
                first_action = state["first_action"]
                if first_action is None:
                    first_action = ("ROLL" if count == 0 else
                                    "ONE" if count == 1 else "TWO" if count == 2 else "THREE")
                week = {"gw": gw, "moves": moves, "hits": hits, "bank": new_bank,
                        "free_transfers_before": state["ft"],
                        "free_transfers_after": ft_after,
                        "projected_xp": round(normal, 2),
                        "net_xp": round(normal - hits, 2)}
                expanded.append({"ids": ids, "sales": sales, "bank": new_bank,
                                 "ft": ft_after, "net": net, "down": down,
                                 "cover": cover, "transfers": transfers, "rank": rank,
                                 "first_action": first_action,
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
    def contingency_lineup(ids: tuple[int, ...], wi: int) -> tuple[float, float]:
        key = (ids, wi)
        cached = contingency_cache.get(key)
        if cached is not None:
            return cached
        groups = {pos: sorted((pid for pid in ids if positions[pid] == pos),
                              key=lambda pid: xp[pid][wi], reverse=True)
                  for pos in QUOTAS}
        normal_points = {pid: xp[pid][wi] for pid in ids}
        downside_points = {pid: downside_xp[pid][wi] for pid in ids}
        chance = {pid: appearances[pid][wi] for pid in ids}
        best_normal, best_down = float('-inf'), 0.0
        for defenders, midfielders, forwards in FORMATIONS:
            xi = (groups[1][:1] + groups[2][:defenders] +
                  groups[3][:midfielders] + groups[4][:forwards])
            if len(xi) != 11:
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
                - action_friction * s["transfers"]
                + terminal_ft_tiebreak * s["ft"])

    def decision_score(s: dict) -> float:
        return utility(s) - (min_transfer_edge if s["first_action"] != "ROLL" else 0.0)

    preference = {"ROLL": 3, "ONE": 2, "TWO": 1, "THREE": 0}
    kinds = ("ROLL", "ONE", "TWO", "THREE")
    best_by_kind = {kind: max((s for s in states if s["first_action"] == kind),
                              key=utility, default=None) for kind in kinds}
    available = {k: s for k, s in best_by_kind.items() if s is not None}
    if not available:
        raise ValueError("No valid transfer strategies were found.")
    best_kind = max(available, key=lambda k: (decision_score(available[k]), preference[k]))
    best = available[best_kind]
    best_roll = best_by_kind["ROLL"]
    best_transfer = max((available[k] for k in ("ONE", "TWO", "THREE") if k in available),
                        key=utility, default=None)

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
            "downside_scenario_net_xp": round(s["down"], 2),
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
            "downside_scenario_net_xp": round(s["down"], 2),
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
        "decision_margin": min_transfer_edge,
        "method": ("Bounded opportunity-aware beam search: 0–3 moves in the first GW; 0–2 later, "
                   "legal 15-player squads, 5-FT rollover, 4-point hits, manager selling prices. "
                   "Rank by XI+captain+vice and legal auto-sub expected points (post-search), with heuristic "
                   "appearance/downside and small transfer-friction tie-breakers. "
                   "Current prices held fixed; no chips or adaptive future scenario tree."),
    }
