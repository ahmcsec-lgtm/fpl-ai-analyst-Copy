"""AJK Bola Wawei AI: free, transparent FPL estimators and squad tools.

No paid model, no official xP claim. All monetary amounts are FPL tenths.
"""
from __future__ import annotations

from collections import Counter
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
                "difficulty": int(fixture.get("team_a_difficulty" if home else "team_h_difficulty") or 3),
            })
    return result


def availability(player: dict) -> float:
    status = player.get("status", "a")
    status_factor = {"a": 1.0, "d": .78, "i": .10, "s": 0.0, "u": .1, "n": 0.0}.get(status, .65)
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        status_factor = min(status_factor, max(0.0, num(chance) / 100))
    return status_factor


def projected_minutes(player: dict) -> float:
    starts = num(player.get("starts"))
    appearances = num(player.get("appearances"))
    total_minutes = num(player.get("minutes"))
    if appearances:
        average = total_minutes / appearances
    elif starts:
        average = total_minutes / starts
    else:
        average = 60 if player.get("status", "a") == "a" else 25
    return max(0.0, min(90.0, average * availability(player)))


def player_fixture_xp(player: dict, gw: int, fixtures: dict,
                      minutes_overrides: dict[int, float] | None = None) -> float:
    """Heuristic gameweek xP. Sum fixtures for doubles; zero for blanks."""
    team_id = int(player.get("team", 0))
    games = fixtures.get((int(gw), team_id), [])
    if not games:
        return 0.0
    pid = int(player["id"])
    mins = max(0.0, min(90.0, num((minutes_overrides or {}).get(pid), projected_minutes(player))))
    pos = int(player.get("element_type", 3))
    ppg = num(player.get("points_per_game"))
    form = num(player.get("form"))
    ict = num(player.get("ict_index"))
    goals = num(player.get("expected_goals_per_90"))
    assists = num(player.get("expected_assists_per_90"))
    clean = num(player.get("expected_goals_conceded_per_90"), 1.4)
    attacking = goals * ({1: 10, 2: 6, 3: 5, 4: 4}[pos]) + assists * 3
    baseline = (max(0.0, ppg) * .45 + max(0.0, form) * .25 +
                max(0.0, attacking) * .24 + min(10, ict / 30) * .06)
    if ppg <= 0 and form <= 0:
        baseline = max(baseline, {1: 2.3, 2: 2.5, 3: 2.8, 4: 2.7}[pos])
    defensive_bonus = max(0, 1.6 - clean) * {1: 1.0, 2: 1.0, 3: .25, 4: 0.0}[pos]
    total = 0.0
    for match in games:
        difficulty = match["difficulty"]
        multiplier = max(.65, min(1.25, 1.13 - .09 * (difficulty - 2)))
        home_bonus = 1.04 if match["home"] else .97
        total += (baseline + defensive_bonus + .8) * (mins / 85) * multiplier * home_bonus
    return round(max(0.0, total), 2)


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
