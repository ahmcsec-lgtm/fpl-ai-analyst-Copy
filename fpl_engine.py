"""AJK Bola Wawei AI: free, transparent FPL estimators and squad tools.

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
_MODEL = {"attack": {}, "defence": {}, "league_goals": 1.42, "games": {}, "cache": {}, "calibration": {}, "calibration_n": 0, "residual_width": {}}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def configure_projection_context(teams: list[dict], fixtures_raw: list[dict]) -> None:
    """Learn shrunk home/away attacking/defensive strengths from completed fixtures.

    Strengths are descriptive and not fitted to future results; low-sample data
    is pulled toward league average. Clear cached xP when source data changes.
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
    attack, defence = {}, {}
    for t in teams:
        tid = int(t["id"])
        count = matches.get(tid, 0)
        # Eight-match equivalent prior, avoiding noisy early-season rankings.
        attack[tid] = clamp((gf.get(tid, 0) + 8 * league) / ((count + 8) * league), .67, 1.48)
        defence[tid] = clamp((ga.get(tid, 0) + 8 * league) / ((count + 8) * league), .67, 1.48)
    _MODEL.update({"attack": attack, "defence": defence, "league_goals": league,
                   "games": matches, "cache": {}})


def availability(player: dict) -> float:
    status = player.get("status", "a")
    chance = player.get("chance_of_playing_next_round")
    factor = {"a": 1.0, "d": .68, "i": .12, "s": 0.0, "u": .08, "n": 0.0}.get(status, .6)
    if chance is not None:
        factor = min(factor, clamp(num(chance) / 100, 0, 1))
    return factor


def projected_minutes(player: dict) -> float:
    """Unconditional expected minutes per fixture, including non-start risk."""
    appearances = num(player.get("appearances"))
    starts = num(player.get("starts"))
    played = num(player.get("minutes"))
    team_games = _MODEL["games"].get(int(player.get("team", 0)), 0)
    if team_games >= 3:
        # Recent-season minutes per team match, with small prior for new signings.
        prior = 16 if appearances == 0 else 48
        effective = (played + 2 * prior) / (team_games + 2)
    elif appearances:
        effective = (played / appearances) * clamp(appearances / max(3, team_games), .35, 1)
    elif starts:
        effective = played / starts
    else:
        effective = 40 if num(player.get("now_cost")) <= 45 else 57
    # Optional *completed-match* minutes evidence, fetched from the FPL public
    # element-summary endpoint. Shrink back toward the season estimate when the
    # recent window contains little evidence. No future matches are included.
    recent = player.get("_ajk_recent_minutes")
    sample = int(player.get("_ajk_recent_matches", 0) or 0)
    if recent is not None and sample > 0:
        weight = min(0.40, sample * 0.08)
        effective = (1.0 - weight) * effective + weight * clamp(num(recent), 0, 90)
    # FPL availability remains authoritative; news headlines do not change xP.
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
    relevant = [row for row in history if int(row.get("round", -1)) in weeks]
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
    expected_opp_goals = clamp(_MODEL["league_goals"] *
                              a.get(opponent, 1) * d.get(team, 1) *
                              (0.94 if home else 1.08), .45, 2.9)
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
            "cs_probability": cs_probability * chance_60, "expected_minutes": minutes}


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
    variance = 0.0
    pos = int(player.get("element_type", 3))
    for match in games:
        comp = _fixture_components(player, int(match["opponent"]), bool(match["home"]),
                                   minutes, int(match.get("difficulty", 3)))
        for k in totals:
            totals[k] += comp[k]
        cs_probs.append(comp["cs_probability"])
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
              "fixtures_count": len(games), "cs_probability": round(sum(cs_probs), 3)}
    _MODEL["cache"][key] = output
    return output


def player_fixture_xp(player: dict, gw: int, fixtures: dict,
                      minutes_overrides: dict[int, float] | None = None) -> float:
    return player_prediction(player, gw, fixtures, minutes_overrides)["xp"]


def horizon_xp(player: dict, gameweeks: list[int], fixtures: dict,
               minutes_overrides: dict[int, float] | None = None) -> float:
    return round(sum(player_fixture_xp(player, gw, fixtures, minutes_overrides)
                     for gw in gameweeks), 2)


def valid_squad(squad: list[dict]) -> bool:
    if len(squad) != 15 or len({int(p["id"]) for p in squad}) != 15:
        return False
    positions = Counter(int(p["element_type"]) for p in squad)
    teams = Counter(int(p["team"]) for p in squad)
    return all(positions[k] == v for k, v in QUOTAS.items()) and max(teams.values(), default=0) <= 3


def best_lineup(squad: list[dict], gw: int, fixtures: dict,
                minutes_overrides: dict[int, float] | None = None,
                captain_id: int | None = None) -> dict:
    """Optimal legal formation and bench, based on estimated xP."""
    if not valid_squad(squad):
        raise ValueError("A squad requires 2 GKP, 5 DEF, 5 MID, 3 FWD and at most 3 from each club.")
    groups = {pos: sorted((p for p in squad if int(p["element_type"]) == pos),
                           key=lambda p: player_fixture_xp(p, gw, fixtures, minutes_overrides),
                           reverse=True) for pos in QUOTAS}
    chosen = [groups[1][0]]
    score = player_fixture_xp(chosen[0], gw, fixtures, minutes_overrides)
    best = None
    for defenders, midfielders, forwards in FORMATIONS:
        xi = chosen + groups[2][:defenders] + groups[3][:midfielders] + groups[4][:forwards]
        xi_score = sum(player_fixture_xp(p, gw, fixtures, minutes_overrides) for p in xi)
        if best is None or xi_score > score:
            best, score = xi, xi_score
    xi = best or (chosen + groups[2][:3] + groups[3][:5] + groups[4][:2])
    ids = {int(p["id"]) for p in xi}
    bench = sorted([p for p in squad if int(p["id"]) not in ids],
                   key=lambda p: (int(p["element_type"]) == 1,
                                  -player_fixture_xp(p, gw, fixtures, minutes_overrides)))
    captain = next((p for p in xi if int(p["id"]) == captain_id), None)
    if captain is None:
        captain = max(xi, key=lambda p: player_fixture_xp(p, gw, fixtures, minutes_overrides))
    vice = max((p for p in xi if p["id"] != captain["id"]),
               key=lambda p: player_fixture_xp(p, gw, fixtures, minutes_overrides))
    captain_xp = player_fixture_xp(captain, gw, fixtures, minutes_overrides)
    return {"xi": xi, "bench": bench, "captain": captain, "vice": vice,
            "xi_xp": round(score, 2), "captain_xp": captain_xp,
            "total_xp": round(score + captain_xp, 2)}


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

# --- v5: budget-aware, multi-GW transfer advisor ---
# Deliberately bounded beam search: not a proven global optimum.

def smart_transfer_plan(squad: list[dict], player_pool: list[dict], gameweeks: list[int],
                        fixtures: dict, bank_tenths: int, free_transfers: int = 1,
                        strategy: str = "Balanced", minutes_overrides: dict[int, float] | None = None,
                        beam_width: int = 12, candidate_count: int = 9) -> dict:
    """Search roll, one-transfer and two-transfer decisions across future GWs.

    Objective: starting XI plus doubled captain each GW, minus actual transfer hits.
    Buy at current market price; carried player's provided selling_price is used.
    Price changes, injury news after today, and chips are not forecast.
    """
    if not valid_squad(squad):
        raise ValueError("A complete legal 15-player squad is required.")
    if not gameweeks:
        raise ValueError("Select at least one upcoming Gameweek.")
    if bank_tenths < 0 or not 0 <= free_transfers <= 5:
        raise ValueError("Bank or free-transfer count is invalid.")

    strategy = strategy if strategy in ("Safe", "Balanced", "Aggressive") else "Balanced"
    gameweeks = list(dict.fromkeys(int(g) for g in gameweeks))[:6]
    market = {int(p["id"]): p for p in player_pool}
    for p in squad:
        market.setdefault(int(p["id"]), p)
    current_ids = tuple(sorted(int(p["id"]) for p in squad))
    sell_start = {int(p["id"]): int(p.get("selling_price", p.get("now_cost", 0))) for p in squad}
    positions = {pid: int(p["element_type"]) for pid, p in market.items()}
    team_ids = {pid: int(p["team"]) for pid, p in market.items()}
    prices = {pid: int(p.get("now_cost", 0)) for pid, p in market.items()}

    # Precompute individual GW projections once. A small safety penalty based on
    # minutes and availability moderates brittle transfers; it is not calibrated risk.
    xp = {}
    for pid, p in market.items():
        values = []
        for gw in gameweeks:
            points = max(0.0, player_fixture_xp(p, gw, fixtures, minutes_overrides))
            if strategy != "Aggressive":
                mins = projected_minutes(p) if not minutes_overrides or pid not in minutes_overrides else float(minutes_overrides[pid])
                shortfall = max(0.0, (65.0 - mins) / 65.0)
                penalty = (.17 if strategy == "Safe" else .07) * shortfall
                points *= 1 - penalty
            values.append(points)
        xp[pid] = tuple(values)
    horizon = {pid: sum(values) for pid, values in xp.items()}

    # Keep a mix of reliable high-projection targets and affordable players.
    shortlist = {}
    for pos in QUOTAS:
        eligible = [pid for pid in market if positions[pid] == pos and
                    market[pid].get("status", "a") not in ("u", "n", "s", "i")]
        best = sorted(eligible, key=lambda pid: horizon[pid], reverse=True)[:candidate_count]
        value = sorted(eligible, key=lambda pid: horizon[pid] / max(prices[pid], 35), reverse=True)[:4]
        shortlist[pos] = list(dict.fromkeys(best + value))

    lineup_cache = {}
    def lineup_points(ids: tuple[int, ...], wi: int) -> float:
        key = (ids, wi)
        if key in lineup_cache:
            return lineup_cache[key]
        groups = {pos: sorted((pid for pid in ids if positions[pid] == pos),
                              key=lambda pid: xp[pid][wi], reverse=True) for pos in QUOTAS}
        best_score = -1.0
        for d, m, f in FORMATIONS:
            chosen = groups[1][:1] + groups[2][:d] + groups[3][:m] + groups[4][:f]
            total = sum(xp[pid][wi] for pid in chosen) + max(xp[pid][wi] for pid in chosen)
            best_score = max(best_score, total)
        lineup_cache[key] = best_score
        return best_score

    base_weekly = [lineup_points(current_ids, wi) for wi in range(len(gameweeks))]
    baseline = sum(base_weekly)

    def roll_ft(ft: int, n: int) -> int:
        return min(5, max(0, ft - n) + 1)

    def swaps_for(ids: tuple[int, ...], bank: int, sales: dict[int, int], wi: int,
                  max_options: int = 12) -> list[tuple[float, int, int, int]]:
        owned = set(ids)
        baseline_week = lineup_points(ids, wi)
        strength = {pid: sum(xp[pid][j] for j in range(wi, len(gameweeks))) for pid in market}
        proposed = []
        club_counts = Counter(team_ids[pid] for pid in ids)
        for out in ids:
            affordable = bank + sales.get(out, prices[out])
            for inside in shortlist[positions[out]]:
                if inside in owned or prices[inside] > affordable:
                    continue
                if club_counts[team_ids[inside]] >= 3 and team_ids[inside] != team_ids[out]:
                    continue
                new_ids = tuple(sorted((owned - {out}) | {inside}))
                # Evaluate both the current GW and residual schedule; no pure
                # individual xP ranking, so improved captaincy can count.
                future_gain = sum(lineup_points(new_ids, j) - lineup_points(ids, j)
                                  for j in range(wi, len(gameweeks)))
                # Keep a diverse set; avoid speculative near-zero moves.
                if future_gain < -1.0:
                    continue
                new_bank = affordable - prices[inside]
                proposed.append((future_gain, out, inside, new_bank))
        proposed.sort(key=lambda x: x[0], reverse=True)
        # Prioritise high projected gain, but include lower-cost alternatives.
        return proposed[:max_options]

    # A state stores the exact carried selling-price map; no forward price forecast.
    states = [{"ids": current_ids, "sales": sell_start, "bank": int(bank_tenths),
               "ft": int(free_transfers), "score": 0.0, "plan": []}]
    for wi, gw in enumerate(gameweeks):
        expanded = []
        for state in states:
            ids, bank, ft = state["ids"], state["bank"], state["ft"]
            actions = [(ids, bank, state["sales"], [], 0)]
            one_moves = swaps_for(ids, bank, state["sales"], wi)
            for gain, out, inside, next_bank in one_moves:
                owned = set(ids)
                ids1 = tuple(sorted((owned - {out}) | {inside}))
                sales1 = dict(state["sales"])
                sales1.pop(out, None)
                sales1[inside] = prices[inside]
                move1 = {"out": out, "in": inside, "out_name": market[out].get("web_name", "?"),
                         "in_name": market[inside].get("web_name", "?"),
                         "out_price": state["sales"].get(out, prices[out]), "in_price": prices[inside]}
                actions.append((ids1, next_bank, sales1, [move1], 1))
            # Expand only the strongest first swaps to keep live Streamlit responsive.
            if ft >= 2 or strategy == "Aggressive":
                for gain, out, inside, next_bank in one_moves[:5]:
                    ids1 = tuple(sorted((set(ids) - {out}) | {inside}))
                    sales1 = dict(state["sales"])
                    sales1.pop(out, None)
                    sales1[inside] = prices[inside]
                    second_moves = swaps_for(ids1, next_bank, sales1, wi, max_options=6)
                    for _, out2, in2, bank2 in second_moves:
                        if out2 == inside or in2 == out:
                            continue
                        ids2 = tuple(sorted((set(ids1) - {out2}) | {in2}))
                        sales2 = dict(sales1)
                        sales2.pop(out2, None)
                        sales2[in2] = prices[in2]
                        moves = [
                            {"out": out, "in": inside, "out_name": market[out].get("web_name", "?"),
                             "in_name": market[inside].get("web_name", "?"),
                             "out_price": state["sales"].get(out, prices[out]), "in_price": prices[inside]},
                            {"out": out2, "in": in2, "out_name": market[out2].get("web_name", "?"),
                             "in_name": market[in2].get("web_name", "?"),
                             "out_price": sales1.get(out2, prices[out2]), "in_price": prices[in2]},
                        ]
                        actions.append((ids2, bank2, sales2, moves, 2))
            for next_ids, next_bank, next_sales, moves, count in actions:
                hit = 4 * max(0, count - ft)
                week_points = lineup_points(next_ids, wi)
                cumulative = state["score"] + week_points - hit
                next_ft = roll_ft(ft, count)
                plan_item = {"gw": gw, "moves": moves, "hits": hit, "bank": next_bank,
                             "free_transfers_before": ft, "free_transfers_after": next_ft,
                             "projected_xp": round(week_points, 2),
                             "net_xp": round(week_points - hit, 2)}
                # Beam rank includes projections of the resulting squad for future
                # weeks; free-transfer reserve receives a small optionality value.
                future = sum(lineup_points(next_ids, j) for j in range(wi + 1, len(gameweeks)))
                ranking = cumulative + future + .4 * next_ft
                expanded.append({"ids": next_ids, "sales": next_sales,
                                 "bank": next_bank, "ft": next_ft, "score": cumulative,
                                 "rank": ranking, "plan": state["plan"] + [plan_item]})
        unique = {}
        for state in sorted(expanded, key=lambda x: (x["rank"], x["score"]), reverse=True):
            key = (state["ids"], state["bank"], state["ft"])
            if key not in unique:
                unique[key] = state
            if len(unique) >= max(3, beam_width):
                break
        states = list(unique.values())
    best = max(states, key=lambda s: s["score"])
    plan = best["plan"]
    first = plan[0]
    next_action = "ROLL" if not first["moves"] else "TRANSFER"
    total_hit = sum(item["hits"] for item in plan)
    return {"action": next_action, "plan": plan,
            "first_moves": first["moves"], "first_hit": first["hits"],
            "expected_gain": round(best["score"] - baseline, 2),
            "baseline_xp": round(baseline, 2), "planned_net_xp": round(best["score"], 2),
            "total_hits": total_hit, "final_bank": best["bank"],
            "final_free_transfers": best["ft"],
            "baseline_weekly": [round(v, 2) for v in base_weekly],
            "method": "Bounded beam search; rolling and 1–2 transfers per GW; static prices; XI+captain minus hits"}
