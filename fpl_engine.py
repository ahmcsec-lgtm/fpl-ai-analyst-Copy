
"""AJK Bola Wawei AI — transparent FPL projection and optimisation engine.

Uses public FPL data and transparent statistical heuristics.
These are estimates, not official FPL projections or guaranteed outcomes.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

POSITION_QUOTAS = {1: 2, 2: 5, 3: 5, 4: 3}
POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

RISK_FACTORS = {
    "Cautious": 0.85,
    "Balanced": 1.0,
    "Aggressive": 1.15,
}


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def availability_factor(player: dict) -> float:
    status = player.get("status", "a")
    factors = {
        "a": 1.0, "d": 0.65, "i": 0.15,
        "s": 0.0, "u": 0.0, "n": 0.0,
    }
    factor = factors.get(status, 0.6)
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        factor *= clamp(num(chance) / 100.0, 0.0, 1.0)
    return factor


def projected_minutes(
    player: dict,
    minutes_override: float | None = None,
) -> float:
    """Estimate expected minutes in one fixture."""
    if minutes_override is not None:
        base = clamp(num(minutes_override), 0, 90)
    else:
        minutes = num(player.get("minutes"))
        starts = num(player.get("starts"))
        appearances = num(player.get("starts")) + num(player.get("substitute_in"))

        if minutes <= 0:
            base = 20.0
        elif starts > 0:
            minutes_per_start = clamp(minutes / starts, 0, 90)
            start_rate = clamp(starts / max(1, appearances), 0, 1)
            base = minutes_per_start * (0.75 + 0.25 * start_rate)
        else:
            base = clamp(minutes / 10, 0, 35)

    return round(clamp(base * availability_factor(player), 0, 90), 1)


def _rate_per_90(value: Any, minutes: float) -> float:
    return num(value) / max(minutes / 90.0, 1.0)


def player_projection(
    player: dict,
    difficulty: float = 3.0,
    *,
    minutes_override: float | None = None,
    team_strength: float = 1.0,
    risk: str = "Balanced",
) -> dict:
    """Return a transparent single-fixture projection breakdown."""
    position = int(num(player.get("element_type"), 3))
    minutes = projected_minutes(player, minutes_override)
    mins_factor = minutes / 90.0
    historical_minutes = num(player.get("minutes"))

    if minutes <= 0:
        return {
            "xp": 0.0, "minutes": 0.0, "start_probability": 0.0,
            "appearance": 0.0, "attacking": 0.0,
            "clean_sheet": 0.0, "bonus": 0.0,
            "availability": availability_factor(player),
        }

    xg90 = _rate_per_90(player.get("expected_goals"), historical_minutes)
    xa90 = _rate_per_90(player.get("expected_assists"), historical_minutes)
    xgi90 = _rate_per_90(
        player.get("expected_goal_involvements"), historical_minutes
    )

    goal_points = {1: 10, 2: 6, 3: 5, 4: 4}.get(position, 4)
    if xg90 + xa90 > 0:
        attacking_rate = xg90 * goal_points + xa90 * 3
    else:
        attacking_rate = xgi90 * 4.2

    attacking = attacking_rate * mins_factor
    appearance = 2.0 * mins_factor

    difficulty = clamp(num(difficulty, 3), 1, 5)
    fixture_factor = clamp(1.16 - (difficulty - 1) * 0.11, 0.72, 1.20)
    team_strength = clamp(num(team_strength, 1), 0.75, 1.25)

    starts = num(player.get("starts"))
    clean_sheets = num(player.get("clean_sheets"))
    cs_rate = clamp(clean_sheets / max(1, starts), 0, 0.9)
    cs_points = {1: 4, 2: 4, 3: 1, 4: 0}.get(position, 0)
    clean_sheet = cs_rate * 0.75 * cs_points * mins_factor

    # Use historic bonus per start as a modest baseline, not a guarantee.
    bonus_total = num(player.get("bonus"))
    bonus_rate = bonus_total / max(1, starts)
    bonus = clamp(bonus_rate * 0.30 * mins_factor, 0, 1.0)

    # Blend long-run performance and recent form conservatively.
    baseline = (
        num(player.get("points_per_game")) * 0.20
        + num(player.get("form")) * 0.10
    ) * mins_factor

    attacking *= team_strength
    clean_sheet *= team_strength

    raw = (
        attacking + appearance + clean_sheet + bonus + baseline
    ) * fixture_factor

    # Risk mode changes how much uncertain projections are discounted/boosted.
    risk_factor = RISK_FACTORS.get(risk, 1.0)
    availability = availability_factor(player)
    uncertainty_penalty = (1.0 - availability) * 0.8
    if risk == "Cautious":
        raw -= uncertainty_penalty
    elif risk == "Aggressive":
        raw += min(0.25, uncertainty_penalty * 0.25)

    return {
        "xp": round(clamp(raw, 0, 15), 2),
        "minutes": minutes,
        "start_probability": round(clamp(minutes / 90, 0, 1), 3),
        "appearance": round(appearance, 2),
        "attacking": round(attacking * fixture_factor, 2),
        "clean_sheet": round(clean_sheet * fixture_factor, 2),
        "bonus": round(bonus * fixture_factor, 2),
        "availability": round(availability, 3),
    }


def estimate_xp(
    player: dict,
    difficulty: float = 3.0,
    *,
    minutes_override: float | None = None,
    team_strength: float = 1.0,
    risk: str = "Balanced",
) -> float:
    return player_projection(
        player,
        difficulty,
        minutes_override=minutes_override,
        team_strength=team_strength,
        risk=risk,
    )["xp"]


def fixture_lookup(
    fixtures: list[dict],
    teams: list[dict],
) -> dict[tuple[int, int], list[tuple[str, int]]]:
    names = {
        team["id"]: team.get("short_name", str(team["id"]))
        for team in teams
    }
    output: dict[tuple[int, int], list[tuple[str, int]]] = {}

    for fixture in fixtures:
        gw = fixture.get("event")
        home = fixture.get("team_h")
        away = fixture.get("team_a")
        if gw is None or home is None or away is None:
            continue

        output.setdefault((home, gw), []).append(
            (f"{names.get(away, away)} (H)", int(fixture.get("team_h_difficulty") or 3))
        )
        output.setdefault((away, gw), []).append(
            (f"{names.get(home, home)} (A)", int(fixture.get("team_a_difficulty") or 3))
        )

    return output


def player_fixture_xp(
    player: dict,
    fixtures: list[tuple[str, int]],
    *,
    minutes_override: float | None = None,
    team_strength: float = 1.0,
    risk: str = "Balanced",
) -> float:
    """Calculate one Gameweek's xP. A blank Gameweek correctly returns zero."""
    if not fixtures:
        return 0.0

    return round(sum(
        estimate_xp(
            player,
            difficulty,
            minutes_override=minutes_override,
            team_strength=team_strength,
            risk=risk,
        )
        for _, difficulty in fixtures
    ), 2)


def _difficulty(player: dict, fx_map: dict, gw: int) -> float:
    fixtures = fx_map.get((player["team"], gw), [])
    if not fixtures:
        return 3.0
    return sum(d for _, d in fixtures) / len(fixtures)


def player_horizon_xp(
    player: dict,
    gameweeks: list[int],
    fx_map: dict,
    *,
    risk: str = "Balanced",
    minutes_overrides: dict[int, float] | None = None,
    team_strengths: dict[int, float] | None = None,
) -> float:
    total = 0.0
    minutes_overrides = minutes_overrides or {}
    team_strengths = team_strengths or {}

    for gw in gameweeks:
        total += player_fixture_xp(
            player,
            fx_map.get((player["team"], gw), []),
            minutes_override=minutes_overrides.get(player["id"]),
            team_strength=team_strengths.get(player["team"], 1.0),
            risk=risk,
        )
    return round(total, 2)


def best_starting_xi(
    squad: list[dict],
    fx_by_team_gw: dict,
    gw: int,
    *,
    risk: str = "Balanced",
) -> list[dict]:
    """Find the highest-xP legal XI across available FPL formations."""
    if len(squad) < 11:
        return []

    def xp(p):
        return player_fixture_xp(
            p, fx_by_team_gw.get((p["team"], gw), []), risk=risk
        )

    keepers = sorted([p for p in squad if int(num(p.get("element_type"))) == 1],
                     key=xp, reverse=True)
    defs = sorted([p for p in squad if int(num(p.get("element_type"))) == 2],
                  key=xp, reverse=True)
    mids = sorted([p for p in squad if int(num(p.get("element_type"))) == 3],
                  key=xp, reverse=True)
    fwds = sorted([p for p in squad if int(num(p.get("element_type"))) == 4],
                  key=xp, reverse=True)

    if not keepers:
        return []

    best, best_score = [], -1.0
    for dc in range(3, min(5, len(defs)) + 1):
        for mc in range(2, min(5, len(mids)) + 1):
            fc = 10 - dc - mc
            if not 1 <= fc <= 3 or fc > len(fwds):
                continue

            # Top players per position are sufficient because each position
            # contributes independently to the total score.
            xi = [keepers[0]] + defs[:dc] + mids[:mc] + fwds[:fc]
            score = sum(xp(p) for p in xi)
            if len(xi) == 11 and score > best_score:
                best, best_score = xi, score

    return best


def bench_order(
    squad: list[dict],
    xi: list[dict],
    fx_map: dict,
    gw: int,
) -> list[dict]:
    xi_ids = {p["id"] for p in xi}
    bench = [p for p in squad if p["id"] not in xi_ids]
    return sorted(
        bench,
        key=lambda p: (
            player_fixture_xp(p, fx_map.get((p["team"], gw), [])),
            p.get("element_type") == 1,
        ),
        reverse=True,
    )


def _player_score(player: dict, fx_map: dict, gw: int) -> float:
    xp = player_fixture_xp(player, fx_map.get((player["team"], gw), []))
    price = max(0.1, num(player.get("now_cost")) / 10)
    return xp / price


def build_squad(
    players: list[dict],
    fx_by_team_gw: dict,
    gw: int,
    budget_m: float = 100.0,
) -> list[dict]:
    """Build a legal 15-player squad using a budget-aware greedy optimiser."""
    budget = int(round(budget_m * 10))
    pools = {}

    for pos, quota in POSITION_QUOTAS.items():
        pools[pos] = sorted(
            [
                p for p in players
                if int(num(p.get("element_type"))) == pos
                and p.get("status", "a") not in ("u", "s", "n")
                and num(p.get("now_cost")) > 0
            ],
            key=lambda p: (
                _player_score(p, fx_by_team_gw, gw),
                player_fixture_xp(p, fx_by_team_gw.get((p["team"], gw), [])),
            ),
            reverse=True,
        )
        if len(pools[pos]) < quota:
            return []

    # A minimum-cost reserve prevents the early picks consuming the budget.
    selected: list[dict] = []
    selected_ids: set[int] = set()
    club_counts: dict[int, int] = {}
    remaining = budget

    # Fill positions in order of scarce/expensive positions.
    for pos, quota in POSITION_QUOTAS.items():
        for _ in range(quota):
            candidates = [
                p for p in pools[pos]
                if p["id"] not in selected_ids
                and club_counts.get(p["team"], 0) < 3
            ]

            chosen = None
            for candidate in candidates:
                cost = int(num(candidate.get("now_cost")))
                if cost > remaining:
                    continue

                future_min = 0
                possible = True

                for future_pos, future_quota in POSITION_QUOTAS.items():
                    already = sum(
                        int(num(x.get("element_type"))) == future_pos
                        for x in selected
                    )
                    outstanding = future_quota - already
                    if future_pos == pos:
                        outstanding -= 1
                    if outstanding <= 0:
                        continue

                    future_pool = [
                        p for p in pools[future_pos]
                        if p["id"] not in selected_ids
                        and p["id"] != candidate["id"]
                        and (
                            p["team"] != candidate["team"]
                            or club_counts.get(p["team"], 0) + 1 < 3
                        )
                    ]
                    future_pool.sort(key=lambda p: num(p.get("now_cost")))
                    if len(future_pool) < outstanding:
                        possible = False
                        break
                    future_min += sum(
                        int(num(p.get("now_cost")))
                        for p in future_pool[:outstanding]
                    )

                if possible and cost + future_min <= remaining:
                    chosen = candidate
                    break

            if chosen is None:
                chosen = next(
                    (p for p in candidates if int(num(p.get("now_cost"))) <= remaining),
                    None,
                )

            if chosen is None:
                return []

            cost = int(num(chosen.get("now_cost")))
            selected.append(chosen)
            selected_ids.add(chosen["id"])
            club_counts[chosen["team"]] = club_counts.get(chosen["team"], 0) + 1
            remaining -= cost

    if len(selected) != 15:
        return []

    return selected


def suggest_transfers(
    squad: list[dict],
    players: list[dict],
    gameweeks: list[int],
    fx_map: dict,
    bank_tenths: int = 0,
    free_transfers: int = 1,
    risk: str = "Balanced",
    max_suggestions: int = 10,
) -> list[dict]:
    """Rank legal one-for-one transfer options using horizon xP and budget."""
    owned = {p["id"] for p in squad}
    suggestions = []

    for outgoing in squad:
        sell_price = int(num(outgoing.get("selling_price"), num(outgoing.get("now_cost"))))
        old_xp = player_horizon_xp(outgoing, gameweeks, fx_map, risk=risk)

        for incoming in players:
            if incoming["id"] in owned:
                continue
            if incoming.get("element_type") != outgoing.get("element_type"):
                continue
            if incoming.get("status", "a") in ("i", "s", "u", "n"):
                continue

            # Maintain three-per-club rule after the swap.
            club_count = sum(p.get("team") == incoming.get("team") for p in squad)
            if incoming.get("team") != outgoing.get("team") and club_count >= 3:
                continue

            price = int(num(incoming.get("now_cost")))
            if price > sell_price + bank_tenths:
                continue

            new_xp = player_horizon_xp(incoming, gameweeks, fx_map, risk=risk)
            gain = round(new_xp - old_xp, 2)

            suggestions.append({
                "out_id": outgoing["id"],
                "in_id": incoming["id"],
                "out": outgoing.get("web_name", ""),
                "in": incoming.get("web_name", ""),
                "position": POSITION_NAMES.get(outgoing.get("element_type"), "?"),
                "sell_price": sell_price,
                "buy_price": price,
                "out_xp": old_xp,
                "in_xp": new_xp,
                "gain": gain,
            })

    hit_cost = max(0, 4 * max(0, 1 - free_transfers))
    suggestions.sort(key=lambda x: x["gain"], reverse=True)

    for item in suggestions:
        item["net_gain_after_hit"] = round(item["gain"] - hit_cost, 2)

    return suggestions[:max_suggestions]
