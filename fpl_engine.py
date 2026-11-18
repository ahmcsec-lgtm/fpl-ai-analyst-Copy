
"""AJK Bola Wawei AI — transparent FPL projection and optimisation engine.

Uses public FPL data and transparent statistical heuristics.
These are estimates, not official FPL projections or guaranteed outcomes.
"""

from __future__ import annotations

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

    bonus_total = num(player.get("bonus"))
    bonus_rate = bonus_total / max(1, starts)
    bonus = clamp(bonus_rate * 0.30 * mins_factor, 0, 1.0)

    baseline = (
        num(player.get("points_per_game")) * 0.20
        + num(player.get("form")) * 0.10
    ) * mins_factor

    attacking *= team_strength
    clean_sheet *= team_strength

    raw = (
        attacking + appearance + clean_sheet + bonus + baseline
    ) * fixture_factor

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

    selected: list[dict] = []
    selected_ids: set[int] = set()
    club_counts: dict[int, int] = {}
    remaining = budget

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


# =========================================================
# MULTI-GAMEWEEK TRANSFER OPTIMISER
# =========================================================


def _optimiser_squad_is_legal(squad: list[dict]) -> bool:
    """Check standard 15-player squad composition and the three-per-club limit."""
    if len(squad) != 15:
        return False

    counts = {pos: 0 for pos in POSITION_QUOTAS}
    clubs: dict[int, int] = {}
    ids = set()

    for player in squad:
        pid = player.get("id")
        pos = int(num(player.get("element_type")))
        team = player.get("team")

        if pid is None or pid in ids or pos not in counts or team is None:
            return False

        ids.add(pid)
        counts[pos] += 1
        clubs[team] = clubs.get(team, 0) + 1

    return counts == POSITION_QUOTAS and max(clubs.values(), default=0) <= 3


def _optimiser_lineup(
    squad: list[dict],
    gw: int,
    fx_map: dict,
    *,
    risk: str = "Balanced",
    minutes_overrides: dict[int, float] | None = None,
    team_strengths: dict[int, float] | None = None,
) -> dict:
    """Return best legal XI, captain and projected captain-adjusted points."""
    minutes_overrides = minutes_overrides or {}
    team_strengths = team_strengths or {}

    def get_xp(player: dict) -> float:
        return player_fixture_xp(
            player,
            fx_map.get((player["team"], gw), []),
            minutes_override=minutes_overrides.get(player["id"]),
            team_strength=team_strengths.get(player["team"], 1.0),
            risk=risk,
        )

    by_position = {
        pos: sorted(
            [p for p in squad if int(num(p.get("element_type"))) == pos],
            key=get_xp,
            reverse=True,
        )
        for pos in POSITION_QUOTAS
    }

    if not by_position[1]:
        return {"xi": [], "captain": None, "vice": None, "points": 0.0}

    best_xi: list[dict] = []
    best_score = -1.0

    for defenders in range(3, 6):
        for midfielders in range(2, 6):
            forwards = 10 - defenders - midfielders
            if not 1 <= forwards <= 3:
                continue
            if (
                defenders > len(by_position[2])
                or midfielders > len(by_position[3])
                or forwards > len(by_position[4])
            ):
                continue

            xi = (
                by_position[1][:1]
                + by_position[2][:defenders]
                + by_position[3][:midfielders]
                + by_position[4][:forwards]
            )
            if len(xi) != 11:
                continue

            score = sum(get_xp(p) for p in xi)
            if score > best_score:
                best_xi = xi
                best_score = score

    if not best_xi:
        return {"xi": [], "captain": None, "vice": None, "points": 0.0}

    captain_candidates = sorted(
        [p for p in best_xi if int(num(p.get("element_type"))) != 1],
        key=get_xp,
        reverse=True,
    )
    captain = captain_candidates[0] if captain_candidates else None
    vice = captain_candidates[1] if len(captain_candidates) > 1 else None
    captain_xp = get_xp(captain) if captain else 0.0

    return {
        "xi": best_xi,
        "captain": captain,
        "vice": vice,
        "xi_xp": round(best_score, 2),
        "captain_xp": round(captain_xp, 2),
        "points": round(best_score + captain_xp, 2),
    }


def optimise_multi_gw_transfers(
    squad: list[dict],
    players: list[dict],
    gameweeks: list[int],
    fx_map: dict,
    *,
    bank_tenths: int = 0,
    free_transfers: int = 1,
    risk: str = "Balanced",
    minutes_overrides: dict[int, float] | None = None,
    team_strengths: dict[int, float] | None = None,
    max_transfers_per_gw: int = 2,
    candidates_per_position: int = 8,
    beam_width: int = 20,
) -> dict:
    """Find a bounded-search multi-GW transfer plan.

    Current owned-player selling prices are taken from squad selling_price values.
    Newly bought players are assigned their purchase price as their estimated
    selling price. Future price changes, bench points, autosubs and chips are
    not modelled. The objective is starting-XI xP plus captain xP, less hits.
    """
    gameweeks = list(gameweeks)
    if not gameweeks:
        return {"error": "Please provide at least one Gameweek."}
    if not _optimiser_squad_is_legal(squad):
        return {
            "error": (
                "Your current squad is not a legal 15-player FPL squad. "
                "Check the squad picks before running the optimiser."
            )
        }
    if max_transfers_per_gw < 0:
        return {"error": "Maximum transfers per Gameweek cannot be negative."}
    if candidates_per_position < 1 or beam_width < 1:
        return {"error": "Candidate count and beam width must be at least one."}

    minutes_overrides = minutes_overrides or {}
    team_strengths = team_strengths or {}
    max_transfers_per_gw = min(int(max_transfers_per_gw), 5)
    candidates_per_position = int(candidates_per_position)
    beam_width = int(beam_width)

    initial_squad = []
    for player in squad:
        item = dict(player)
        item["selling_price"] = int(num(
            player.get("selling_price"), num(player.get("now_cost"))
        ))
        initial_squad.append(item)

    # Shortlist the highest projected non-unavailable players by position.
    candidate_pools: dict[int, list[dict]] = {}
    for pos in POSITION_QUOTAS:
        scored = []
        for player in players:
            if int(num(player.get("element_type"))) != pos:
                continue
            if player.get("status", "a") in ("i", "s", "u", "n"):
                continue
            if int(num(player.get("now_cost"))) <= 0:
                continue

            horizon_score = sum(
                player_fixture_xp(
                    player,
                    fx_map.get((player["team"], gw), []),
                    minutes_override=minutes_overrides.get(player["id"]),
                    team_strength=team_strengths.get(player["team"], 1.0),
                    risk=risk,
                )
                for gw in gameweeks
            )
            scored.append((horizon_score, player))

        scored.sort(key=lambda item: item[0], reverse=True)
        candidate_pools[pos] = [
            player for _, player in scored[:candidates_per_position]
        ]

    # State is the squad and bank immediately before the next planned GW.
    states = [{
        "squad": initial_squad,
        "bank": max(0, int(bank_tenths)),
        "free_transfers": max(0, min(5, int(free_transfers))),
        "total_net_xp": 0.0,
        "plan": [],
    }]

    for gw in gameweeks:
        completed_states = []

        for base_state in states:
            frontier = [{
                "squad": [dict(p) for p in base_state["squad"]],
                "bank": base_state["bank"],
                "actions": [],
            }]

            for transfer_depth in range(max_transfers_per_gw + 1):
                next_frontier = []

                for state in frontier:
                    current_squad = state["squad"]
                    actions = state["actions"]
                    transfers_made = len(actions)

                    if not _optimiser_squad_is_legal(current_squad):
                        continue

                    lineup = _optimiser_lineup(
                        current_squad,
                        gw,
                        fx_map,
                        risk=risk,
                        minutes_overrides=minutes_overrides,
                        team_strengths=team_strengths,
                    )
                    if not lineup["xi"]:
                        continue

                    ft_before = base_state["free_transfers"]
                    hit_points = max(0, transfers_made - ft_before) * 4
                    weekly_net = round(lineup["points"] - hit_points, 2)
                    ft_after = min(5, max(0, ft_before - transfers_made) + 1)

                    weekly_row = {
                        "gameweek": gw,
                        "transfers": [dict(a) for a in actions],
                        "transfer_count": transfers_made,
                        "free_transfers_before": ft_before,
                        "free_transfers_after": ft_after,
                        "hit_points": hit_points,
                        "bank_after": state["bank"],
                        "xi_xp": lineup["xi_xp"],
                        "captain": lineup["captain"].get("web_name", "") if lineup["captain"] else "",
                        "captain_xp": lineup["captain_xp"],
                        "vice_captain": lineup["vice"].get("web_name", "") if lineup["vice"] else "",
                        "net_xp": weekly_net,
                        "squad_ids": [p["id"] for p in current_squad],
                    }

                    completed_states.append({
                        "squad": [dict(p) for p in current_squad],
                        "bank": state["bank"],
                        "free_transfers": ft_after,
                        "total_net_xp": round(base_state["total_net_xp"] + weekly_net, 2),
                        "plan": base_state["plan"] + [weekly_row],
                    })

                    if transfer_depth >= max_transfers_per_gw:
                        continue

                    owned_ids = {p["id"] for p in current_squad}
                    moved_ids = {
                        player_id
                        for action in actions
                        for player_id in (action["out_id"], action["in_id"])
                    }
                    club_counts: dict[int, int] = {}
                    for player in current_squad:
                        club_counts[player["team"]] = club_counts.get(player["team"], 0) + 1

                    for outgoing in current_squad:
                        if outgoing["id"] in moved_ids:
                            continue

                        pos = int(num(outgoing.get("element_type")))
                        sell_price = int(num(
                            outgoing.get("selling_price"), num(outgoing.get("now_cost"))
                        ))

                        for incoming in candidate_pools.get(pos, []):
                            if incoming["id"] in owned_ids or incoming["id"] in moved_ids:
                                continue

                            buy_price = int(num(incoming.get("now_cost")))
                            new_bank = state["bank"] + sell_price - buy_price
                            if new_bank < 0:
                                continue

                            if (
                                incoming["team"] != outgoing["team"]
                                and club_counts.get(incoming["team"], 0) >= 3
                            ):
                                continue

                            new_squad = [
                                dict(p) for p in current_squad
                                if p["id"] != outgoing["id"]
                            ]
                            new_player = dict(incoming)
                            new_player["selling_price"] = buy_price
                            new_squad.append(new_player)

                            if not _optimiser_squad_is_legal(new_squad):
                                continue

                            action = {
                                "out_id": outgoing["id"],
                                "in_id": incoming["id"],
                                "out": outgoing.get("web_name", ""),
                                "in": incoming.get("web_name", ""),
                                "position": POSITION_NAMES.get(pos, "?"),
                                "sell_price": sell_price,
                                "buy_price": buy_price,
                                "bank_after": new_bank,
                            }
                            next_frontier.append({
                                "squad": new_squad,
                                "bank": new_bank,
                                "actions": actions + [action],
                            })

                if not next_frontier:
                    break

                # Keep the strongest partial transfer paths at this depth.
                next_frontier.sort(
                    key=lambda item: (
                        _optimiser_lineup(
                            item["squad"], gw, fx_map,
                            risk=risk,
                            minutes_overrides=minutes_overrides,
                            team_strengths=team_strengths,
                        )["points"]
                        - max(
                            0,
                            len(item["actions"]) - base_state["free_transfers"],
                        ) * 4
                    ),
                    reverse=True,
                )
                frontier = next_frontier[:beam_width]

        if not completed_states:
            return {"error": f"The optimiser could not find a legal squad plan for GW{gw}."}

        completed_states.sort(key=lambda item: item["total_net_xp"], reverse=True)
        unique_states = []
        seen = set()

        for state in completed_states:
            signature = (
                tuple(sorted(p["id"] for p in state["squad"])),
                state["bank"],
                state["free_transfers"],
            )
            if signature in seen:
                continue
            seen.add(signature)
            unique_states.append(state)
            if len(unique_states) >= beam_width:
                break

        states = unique_states

    if not states:
        return {"error": "No complete transfer plan could be generated."}

    best = max(states, key=lambda item: item["total_net_xp"])
    return {
        "gameweeks": gameweeks,
        "total_net_xp": best["total_net_xp"],
        "final_bank": best["bank"],
        "final_free_transfers": best["free_transfers"],
        "final_squad": best["squad"],
        "plan": best["plan"],
        "search_settings": {
            "max_transfers_per_gw": max_transfers_per_gw,
            "candidates_per_position": candidates_per_position,
            "beam_width": beam_width,
        },
        "assumptions": [
            "Newly purchased players retain their purchase price as their estimated selling price.",
            "Future player price changes are not predicted.",
            "Projected points include the starting XI and one additional captain copy.",
            "Bench points, automatic substitutions and chip effects are excluded.",
            "The bounded search returns the best plan found, not a guaranteed global optimum.",
        ],
    }
