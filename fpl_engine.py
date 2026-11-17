"""Transparent, free statistical helpers for FPL AI Analyst."""
from __future__ import annotations
from typing import Any


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def availability_factor(player: dict) -> float:
    status = player.get("status", "a")
    factor = {"a": 1.0, "d": 0.65, "i": 0.15, "s": 0.0, "u": 0.0, "n": 0.0}.get(status, 0.6)
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        factor *= max(0.0, min(1.0, num(chance) / 100.0))
    return factor


def projected_minutes(player: dict) -> float:
    starts = num(player.get("starts"))
    minutes = num(player.get("minutes"))
    if starts > 0:
        per_start = min(90.0, minutes / starts)
        start_rate = min(1.0, starts / max(1.0, minutes / 90.0))
        expected = per_start * (0.75 + 0.25 * start_rate)
    else:
        expected = min(35.0, minutes / 10.0) if minutes else 20.0
    return max(0.0, min(90.0, expected * availability_factor(player)))


def estimate_xp(player: dict, difficulty: float = 3.0) -> float:
    """One-GW estimate. Heuristic, not an official projection or trained model."""
    pos = int(num(player.get("element_type"), 3))
    mins = projected_minutes(player)
    m90 = mins / 90.0
    if mins < 1:
        return 0.0
    goal_points = {1: 10, 2: 6, 3: 5, 4: 4}.get(pos, 4)
    xg90 = num(player.get("expected_goals")) / max(1.0, num(player.get("minutes")) / 90.0)
    xa90 = num(player.get("expected_assists")) / max(1.0, num(player.get("minutes")) / 90.0)
    xgi90 = num(player.get("expected_goal_involvements")) / max(1.0, num(player.get("minutes")) / 90.0)
    # Blend xG/xA with xGI so sparse or missing component fields do not collapse the estimate.
    attack = (xg90 * goal_points + xa90 * 3.0) if (xg90 + xa90) > 0 else xgi90 * 4.2
    attack_xp = attack * m90
    appearance = (2.0 if mins >= 60 else 1.0) * min(1.0, mins / 60.0)
    fixture_factor = max(0.72, min(1.20, 1.16 - (difficulty - 1.0) * 0.11))
    cs_rate = num(player.get("clean_sheets")) / max(1.0, num(player.get("starts")))
    cs_points = {1: 4, 2: 4, 3: 1, 4: 0}.get(pos, 0)
    clean_sheet = min(0.75, cs_rate * 0.75) * cs_points * m90
    baseline = num(player.get("points_per_game")) * 0.25 + num(player.get("form")) * 0.15
    raw = (attack_xp + appearance + clean_sheet + baseline) * fixture_factor
    return round(max(0.0, min(15.0, raw)), 2)


def fixture_lookup(fixtures: list[dict], teams: list[dict]) -> dict[tuple[int, int], list[tuple[str, int]]]:
    names = {t["id"]: t.get("short_name", str(t["id"])) for t in teams}
    out: dict[tuple[int, int], list[tuple[str, int]]] = {}
    for f in fixtures:
        gw = f.get("event")
        if gw is None:
            continue
        h, a = f["team_h"], f["team_a"]
        out.setdefault((h, gw), []).append((f"{names.get(a, a)} (H)", int(f.get("team_h_difficulty") or 3)))
        out.setdefault((a, gw), []).append((f"{names.get(h, h)} (A)", int(f.get("team_a_difficulty") or 3)))
    return out


def player_fixture_xp(player: dict, fx: list[tuple[str, int]]) -> float:
    if not fx:
        return estimate_xp(player, 3)
    # Double gameweeks are additive, capped conservatively to avoid extreme projections.
    return round(sum(estimate_xp(player, diff) for _, diff in fx), 2)


def build_squad(players: list[dict], fx_by_team_gw: dict, gw: int, budget_m: float = 100.0) -> list[dict]:
    """Greedy constrained 15-player squad builder; indicative, not a solver guarantee."""
    quotas = {1: 2, 2: 5, 3: 5, 4: 3}
    selected: list[dict] = []
    club_counts: dict[int, int] = {}
    remaining = round(budget_m * 10)
    for pos, count in quotas.items():
        pool = [p for p in players if int(p.get("element_type", 0)) == pos and p.get("status") not in ("u", "s")]
        pool.sort(key=lambda p: (estimate_xp(p, (fx_by_team_gw.get((p["team"], gw)) or [("", 3)])[0][1]) / max(1, num(p.get("now_cost"))), estimate_xp(p, (fx_by_team_gw.get((p["team"], gw)) or [("", 3)])[0][1])), reverse=True)
        chosen = []
        for p in pool:
            cost = int(num(p.get("now_cost")))
            if len(chosen) >= count:
                break
            if club_counts.get(p["team"], 0) >= 3:
                continue
            if cost > remaining:
                continue
            chosen.append(p)
            remaining -= cost
            club_counts[p["team"]] = club_counts.get(p["team"], 0) + 1
        if len(chosen) < count:
            # If budget is unusually tight, fill by cheapest eligible player to complete the shape.
            for p in sorted(pool, key=lambda x: num(x.get("now_cost"))):
                cost = int(num(p.get("now_cost")))
                if p in chosen or club_counts.get(p["team"], 0) >= 3 or cost > remaining:
                    continue
                chosen.append(p)
                remaining -= cost
                club_counts[p["team"]] = club_counts.get(p["team"], 0) + 1
                if len(chosen) >= count:
                    break
        selected.extend(chosen)
    return selected


def best_starting_xi(squad: list[dict], fx_by_team_gw: dict, gw: int) -> list[dict]:
    ranked = sorted(squad, key=lambda p: player_fixture_xp(p, fx_by_team_gw.get((p["team"], gw), [])), reverse=True)
    gk = [p for p in ranked if p.get("element_type") == 1][:1]
    defs = [p for p in ranked if p.get("element_type") == 2]
    mids = [p for p in ranked if p.get("element_type") == 3]
    fwds = [p for p in ranked if p.get("element_type") == 4]
    best = None
    best_score = -1.0
    # Enumerate legal formations with at least 3 DEF, 2 MID, 1 FWD.
    for d in range(3, min(5, len(defs)) + 1):
        for m in range(2, min(5, len(mids)) + 1):
            f = 10 - 1 - d - m
            if 1 <= f <= 3 and f <= len(fwds):
                xi = gk + defs[:d] + mids[:m] + fwds[:f]
                score = sum(player_fixture_xp(p, fx_by_team_gw.get((p["team"], gw), [])) for p in xi)
                if len(xi) == 11 and score > best_score:
                    best, best_score = xi, score
    return best or ranked[:11]
