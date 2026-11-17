
"""Transparent statistical helpers for FPL AI Analyst.

These are heuristic estimates based on public FPL data.
They are not official FPL projections or guaranteed outcomes.
"""

from __future__ import annotations

from typing import Any


POSITION_QUOTAS = {
    1: 2,  # Goalkeepers
    2: 5,  # Defenders
    3: 5,  # Midfielders
    4: 3,  # Forwards
}

POSITION_NAMES = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}


def num(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to a number."""
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def availability_factor(player: dict) -> float:
    """Estimate the probability that a player is available."""
    status = player.get("status", "a")

    factors = {
        "a": 1.0,
        "d": 0.65,
        "i": 0.15,
        "s": 0.0,
        "u": 0.0,
        "n": 0.0,
    }

    factor = factors.get(status, 0.6)

    chance = player.get("chance_of_playing_next_round")

    if chance is not None:
        factor *= max(0.0, min(1.0, num(chance) / 100.0))

    return factor


def projected_minutes(player: dict) -> float:
    """Estimate minutes for one fixture using historical minutes and starts."""

    minutes = num(player.get("minutes"))
    starts = num(player.get("starts"))

    if minutes <= 0:
        expected = 20.0
    elif starts > 0:
        minutes_per_start = min(90.0, minutes / starts)

        appearance_rate = min(
            1.0,
            starts / max(1.0, minutes / 90.0),
        )

        expected = minutes_per_start * (
            0.75 + 0.25 * appearance_rate
        )
    else:
        expected = min(35.0, minutes / 10.0)

    expected *= availability_factor(player)

    return round(max(0.0, min(90.0, expected)), 1)


def estimate_xp(player: dict, difficulty: float = 3.0) -> float:
    """
    Estimate expected points for one fixture.

    This is a transparent heuristic, not an official FPL prediction.
    """

    position = int(num(player.get("element_type"), 3))

    minutes = projected_minutes(player)

    if minutes < 1:
        return 0.0

    minutes_per_90 = minutes / 90.0

    historical_minutes = num(player.get("minutes"))

    historical_90s = max(
        1.0,
        historical_minutes / 90.0,
    )

    xg_per_90 = (
        num(player.get("expected_goals")) / historical_90s
    )

    xa_per_90 = (
        num(player.get("expected_assists")) / historical_90s
    )

    xgi_per_90 = (
        num(player.get("expected_goal_involvements")) / historical_90s
    )

    goal_points = {
        1: 10,
        2: 6,
        3: 5,
        4: 4,
    }.get(position, 4)

    if xg_per_90 + xa_per_90 > 0:
        attacking_rate = (
            xg_per_90 * goal_points
            + xa_per_90 * 3.0
        )
    else:
        attacking_rate = xgi_per_90 * 4.2

    attacking_points = attacking_rate * minutes_per_90

    appearance_points = (
        2.0 if minutes >= 60 else 1.0
    ) * min(1.0, minutes / 60.0)

    difficulty = max(1.0, min(5.0, num(difficulty, 3.0)))

    fixture_factor = max(
        0.72,
        min(1.20, 1.16 - (difficulty - 1.0) * 0.11),
    )

    clean_sheet_rate = (
        num(player.get("clean_sheets"))
        / max(1.0, num(player.get("starts")))
    )

    clean_sheet_points = {
        1: 4,
        2: 4,
        3: 1,
        4: 0,
    }.get(position, 0)

    clean_sheet_estimate = (
        min(0.75, clean_sheet_rate * 0.75)
        * clean_sheet_points
        * minutes_per_90
    )

    baseline_points = (
        num(player.get("points_per_game")) * 0.25
        + num(player.get("form")) * 0.15
    )

    raw_xp = (
        attacking_points
        + appearance_points
        + clean_sheet_estimate
        + baseline_points
    ) * fixture_factor

    return round(max(0.0, min(15.0, raw_xp)), 2)


def fixture_lookup(
    fixtures: list[dict],
    teams: list[dict],
) -> dict[tuple[int, int], list[tuple[str, int]]]:
    """Create a team/Gameweek fixture lookup."""

    names = {
        team["id"]: team.get(
            "short_name",
            str(team["id"]),
        )
        for team in teams
    }

    output = {}

    for fixture in fixtures:
        gameweek = fixture.get("event")

        if gameweek is None:
            continue

        home_team = fixture.get("team_h")
        away_team = fixture.get("team_a")

        if home_team is None or away_team is None:
            continue

        home_difficulty = int(
            fixture.get("team_h_difficulty") or 3
        )

        away_difficulty = int(
            fixture.get("team_a_difficulty") or 3
        )

        output.setdefault(
            (home_team, gameweek),
            [],
        ).append(
            (
                f"{names.get(away_team, away_team)} (H)",
                home_difficulty,
            )
        )

        output.setdefault(
            (away_team, gameweek),
            [],
        ).append(
            (
                f"{names.get(home_team, home_team)} (A)",
                away_difficulty,
            )
        )

    return output


def player_fixture_xp(
    player: dict,
    fixtures: list[tuple[str, int]],
) -> float:
    """Calculate projected points across a Gameweek's fixtures."""

    if not fixtures:
        return estimate_xp(player, 3.0)

    # Each fixture is estimated separately.
    # Minutes and availability are based on historical player data,
    # so double-gameweek projections should be treated cautiously.
    total_xp = sum(
        estimate_xp(player, difficulty)
        for _, difficulty in fixtures
    )

    return round(total_xp, 2)


def _player_fixture_difficulty(
    player: dict,
    fx_by_team_gw: dict,
    gw: int,
) -> float:
    fixtures = fx_by_team_gw.get(
        (player["team"], gw),
        [],
    )

    if not fixtures:
        return 3.0

    return sum(
        difficulty
        for _, difficulty in fixtures
    ) / len(fixtures)


def _player_score(
    player: dict,
    fx_by_team_gw: dict,
    gw: int,
) -> float:
    """Combine expected points and price efficiency."""

    difficulty = _player_fixture_difficulty(
        player,
        fx_by_team_gw,
        gw,
    )

    xp = estimate_xp(player, difficulty)

    price = max(
        0.1,
        num(player.get("now_cost")) / 10.0,
    )

    return xp / price


def build_squad(
    players: list[dict],
    fx_by_team_gw: dict,
    gw: int,
    budget_m: float = 100.0,
) -> list[dict]:
    """
    Build an indicative 15-player squad.

    Uses FPL position quotas, a three-player club limit,
    budget-aware selection and a reserve-budget check.

    This is a greedy heuristic, not a guaranteed global optimum.
    """

    remaining_budget = int(round(budget_m * 10))

    selected = []
    selected_ids = set()
    club_counts = {}

    pools = {}

    for position in POSITION_QUOTAS:
        pools[position] = [
            player
            for player in players
            if int(num(player.get("element_type"))) == position
            and player.get("status", "a") not in ("u", "s", "n")
            and num(player.get("now_cost")) > 0
        ]

        pools[position].sort(
            key=lambda player: (
                _player_score(
                    player,
                    fx_by_team_gw,
                    gw,
                ),
                estimate_xp(
                    player,
                    _player_fixture_difficulty(
                        player,
                        fx_by_team_gw,
                        gw,
                    ),
                ),
            ),
            reverse=True,
        )

    if any(
        len(pools[position]) < quota
        for position, quota in POSITION_QUOTAS.items()
    ):
        return []

    # Minimum price reserve for every remaining position.
    for position, quota in POSITION_QUOTAS.items():

        for _ in range(quota):

            candidates = [
                player
                for player in pools[position]
                if player["id"] not in selected_ids
                and club_counts.get(player["team"], 0) < 3
            ]

            if not candidates:
                return selected

            chosen = None

            for candidate in candidates:

                cost = int(
                    num(candidate.get("now_cost"))
                )

                # Calculate the minimum cost of the other
                # unfilled squad places.
                future_costs = []

                for future_position, future_quota in POSITION_QUOTAS.items():

                    already_selected = sum(
                        1
                        for item in selected
                        if int(num(item.get("element_type")))
                        == future_position
                    )

                    outstanding = future_quota - already_selected

                    if future_position == position:
                        outstanding -= 1

                    if outstanding <= 0:
                        continue

                    future_pool = [
                        item
                        for item in pools[future_position]
                        if item["id"] not in selected_ids
                        and item["id"] != candidate["id"]
                        and item["team"] != candidate["team"]
                        or (
                            future_position == position
                            and item["id"] not in selected_ids
                            and item["id"] != candidate["id"]
                            and club_counts.get(item["team"], 0) < 3
                            and (
                                item["team"] != candidate["team"]
                                or club_counts.get(item["team"], 0) < 2
                            )
                        )
                    ]

                    future_pool.sort(
                        key=lambda item: num(item.get("now_cost"))
                    )

                    if len(future_pool) < outstanding:
                        future_costs = []
                        break

                    future_costs.extend(
                        int(num(item.get("now_cost")))
                        for item in future_pool[:outstanding]
                    )

                if not future_costs and sum(
                    POSITION_QUOTAS.values()
                ) - len(selected) > 1:
                    continue

                reserve = sum(future_costs)

                if cost + reserve <= remaining_budget:
                    chosen = candidate
                    break

            # If reserve checking is too restrictive, use the
            # best affordable candidate that respects club limits.
            if chosen is None:
                chosen = next(
                    (
                        player
                        for player in candidates
                        if int(num(player.get("now_cost")))
                        <= remaining_budget
                    ),
                    None,
                )

            if chosen is None:
                return selected

            cost = int(num(chosen.get("now_cost")))

            selected.append(chosen)
            selected_ids.add(chosen["id"])

            remaining_budget -= cost

            club_counts[chosen["team"]] = (
                club_counts.get(chosen["team"], 0) + 1
            )

    return selected


def best_starting_xi(
    squad: list[dict],
    fx_by_team_gw: dict,
    gw: int,
) -> list[dict]:
    """
    Select the highest-xP legal starting XI.

    Checks formations with 3–5 defenders, 2–5 midfielders
    and 1–3 forwards.
    """

    if len(squad) < 11:
        return []

    def player_xp(player):
        return player_fixture_xp(
            player,
            fx_by_team_gw.get(
                (player["team"], gw),
                [],
            ),
        )

    goalkeepers = sorted(
        [
            player
            for player in squad
            if int(num(player.get("element_type"))) == 1
        ],
        key=player_xp,
        reverse=True,
    )

    defenders = sorted(
        [
            player
            for player in squad
            if int(num(player.get("element_type"))) == 2
        ],
        key=player_xp,
        reverse=True,
    )

    midfielders = sorted(
        [
            player
            for player in squad
            if int(num(player.get("element_type"))) == 3
        ],
        key=player_xp,
        reverse=True,
    )

    forwards = sorted(
        [
            player
            for player in squad
            if int(num(player.get("element_type"))) == 4
        ],
        key=player_xp,
        reverse=True,
    )

    if not goalkeepers:
        return []

    goalkeeper = goalkeepers[:1]

    best_xi = None
    best_score = -1.0

    for defender_count in range(
        3,
        min(5, len(defenders)) + 1,
    ):

        for midfielder_count in range(
            2,
            min(5, len(midfielders)) + 1,
        ):

            forward_count = (
                10
                - defender_count
                - midfielder_count
            )

            if not 1 <= forward_count <= 3:
                continue

            if forward_count > len(forwards):
                continue

            xi = (
                goalkeeper
                + defenders[:defender_count]
                + midfielders[:midfielder_count]
                + forwards[:forward_count]
            )

            if len(xi) != 11:
                continue

            score = sum(
                player_xp(player)
                for player in xi
            )

            if score > best_score:
                best_score = score
                best_xi = xi

    return best_xi or []
