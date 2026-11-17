
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from fpl_engine import (
    num,
    estimate_xp,
    fixture_lookup,
    player_fixture_xp,
    build_squad,
    best_starting_xi,
)

# ============================================================
# CONFIGURATION
# ============================================================

API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "FPL-AI-Analyst/1.0"}
MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")

POS_NAMES = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}

st.set_page_config(
    page_title="FPL AI Analyst",
    page_icon="⚽",
    layout="wide",
)

# Native Streamlit styling only. No custom HTML in the header.
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        max-width: 1600px;
    }

    [data-testid="stMetric"] {
        background: rgba(120, 130, 145, 0.09);
        padding: 12px 14px;
        border-radius: 12px;
    }

    div[data-testid="stTabs"] button {
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_json(path):
    response = requests.get(
        f"{API}/{path.lstrip('/')}",
        headers=HEADERS,
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def money(tenths):
    return f"£{num(tenths) / 10:.1f}m"


def status_label(player):
    labels = {
        "a": "Available",
        "d": "Doubtful",
        "i": "Injured",
        "s": "Suspended",
        "u": "Unavailable",
        "n": "Not available",
    }

    status = labels.get(
        player.get("status"),
        str(player.get("status", "Unknown")),
    )

    chance = player.get("chance_of_playing_next_round")

    if chance is not None:
        status += f" · {chance}% chance"

    return status


def malaysia_time(iso_datetime, fmt="%d %b %Y, %I:%M %p MYT"):
    if not iso_datetime:
        return "TBC"

    return (
        datetime.fromisoformat(
            iso_datetime.replace("Z", "+00:00")
        )
        .astimezone(MY_TZ)
        .strftime(fmt)
    )


def fx_text(fixtures_for_player):
    if not fixtures_for_player:
        return "—"

    return ", ".join(
        item[0] for item in fixtures_for_player
    )


def report_files():
    folder = Path("reports")

    if not folder.exists():
        return []

    return sorted(
        folder.glob("GW*_report.md"),
        reverse=True,
    )


def get_target_gameweek(events):
    """
    Select the earliest unfinished Gameweek with a deadline
    that has not passed in Malaysia time.

    If no future deadline exists, fall back to the earliest
    unfinished Gameweek.
    """
    now = datetime.now(MY_TZ)

    unfinished = [
        event
        for event in events
        if not event.get("finished")
        and event.get("deadline_time")
    ]

    future_events = []

    for event in unfinished:
        deadline = datetime.fromisoformat(
            event["deadline_time"].replace("Z", "+00:00")
        )

        if deadline.astimezone(MY_TZ) >= now:
            future_events.append(event)

    if future_events:
        return min(
            future_events,
            key=lambda event: event["deadline_time"],
        )

    if unfinished:
        return min(
            unfinished,
            key=lambda event: event["deadline_time"],
        )

    return None


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("⚽ FPL Manager")

    st.caption(
        "Enter your public Fantasy Premier League Team ID."
    )

    team_id_input = st.text_input(
        "Your FPL Team ID",
        value="",
        placeholder="e.g. 1645144",
        help="No FPL password is required.",
    )

    if st.button(
        "↻ Refresh data",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()

    st.caption("Free public FPL data. No password required.")

if not team_id_input.strip():
    st.info(
        "👈 Enter your FPL Team ID in the sidebar "
        "to start analysing your team."
    )
    st.stop()

if not team_id_input.strip().isdigit():
    st.error("Please enter a valid numeric FPL Team ID.")
    st.stop()

team_id = int(team_id_input.strip())


# ============================================================
# LOAD FPL DATA
# ============================================================

try:
    with st.spinner("Loading current FPL data..."):
        boot = get_json("bootstrap-static/")
        fixtures = get_json("fixtures/")
        profile = get_json(f"entry/{team_id}/")

except requests.HTTPError as error:
    status_code = (
        error.response.status_code
        if error.response is not None
        else None
    )

    if status_code == 404:
        st.error(
            "That FPL Team ID was not found. "
            "Please check the number."
        )
    else:
        st.error(f"Unable to load FPL data: {error}")

    st.stop()

except requests.RequestException as error:
    st.error(f"Unable to connect to the FPL API: {error}")
    st.stop()

except Exception as error:
    st.error(f"Unexpected error while loading data: {error}")
    st.stop()


players = boot.get("elements", [])
teams = boot.get("teams", [])
events = boot.get("events", [])

player_by_id = {
    player["id"]: player
    for player in players
}

team_names = {
    team["id"]: team["name"]
    for team in teams
}

team_short = {
    team["id"]: team.get("short_name", team["name"])
    for team in teams
}

fx_map = fixture_lookup(fixtures, teams)

target_gw = get_target_gameweek(events)

if not target_gw:
    st.warning(
        "No upcoming Gameweek is currently available "
        "from the FPL API."
    )
    st.stop()

gw = int(target_gw["id"])


# ============================================================
# LOAD TEAM PICKS AND HISTORY
# ============================================================

picks_data = None
snapshot_gw = gw

try:
    picks_data = get_json(
        f"entry/{team_id}/event/{gw}/picks/"
    )

except Exception:
    completed = [
        event
        for event in events
        if event.get("finished")
    ]

    if completed:
        snapshot_gw = int(completed[-1]["id"])

        try:
            picks_data = get_json(
                f"entry/{team_id}/event/{snapshot_gw}/picks/"
            )
        except Exception:
            picks_data = None


try:
    history = get_json(
        f"entry/{team_id}/history/"
    ).get("current", [])

except Exception:
    history = []


latest = history[-1] if history else {}

manager = (
    f"{profile.get('player_first_name', '')} "
    f"{profile.get('player_last_name', '')}"
).strip()

deadline_text = malaysia_time(
    target_gw.get("deadline_time"),
    "%d %b %Y, %I:%M %p MYT",
)


# ============================================================
# DASHBOARD HEADER
# ============================================================

# IMPORTANT:
# This header deliberately uses native Streamlit components.
# Do not wrap the HTML below in st.write() or st.code().

st.title("⚽ FPL AI Analyst")

st.subheader(
    profile.get("name", "FPL Manager")
)

st.caption(
    f"{manager}  ·  Team ID {team_id}  ·  "
    f"Gameweek {gw}"
)

st.info(
    f"🗓️ NEXT DEADLINE: {deadline_text}"
)

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Overall points",
    f"{profile.get('summary_overall_points', 0):,}",
)

c2.metric(
    "Overall rank",
    f"{profile.get('summary_overall_rank', 0):,}",
)

c3.metric(
    "Target Gameweek",
    str(gw),
)

c4.metric(
    "Team value",
    money(
        latest.get(
            "value",
            profile.get("last_deadline_value", 0),
        )
    ),
)


# ============================================================
# BUILD PLAYER PROJECTIONS
# ============================================================

projection_rows = []

for player in players:
    player_fixtures = fx_map.get(
        (player["team"], gw),
        [],
    )

    xp = player_fixture_xp(
        player,
        player_fixtures,
    )

    projection_rows.append(
        {
            "id": player["id"],
            "Player": player.get("web_name", ""),
            "Position": POS_NAMES.get(
                player.get("element_type"),
                "?",
            ),
            "Club": team_short.get(
                player["team"],
                "",
            ),
            "Price": num(player.get("now_cost")) / 10,
            "Price label": money(
                player.get("now_cost")
            ),
            "Fixture": fx_text(player_fixtures),
            "xP": xp,
            "Form": num(player.get("form")),
            "xGI": num(
                player.get("expected_goal_involvements")
            ),
            "Minutes": num(player.get("minutes")),
            "Ownership %": num(
                player.get("selected_by_percent")
            ),
            "Status": status_label(player),
            "status_code": player.get("status", "a"),
            "team": player["team"],
            "element_type": player["element_type"],
        }
    )


proj = pd.DataFrame(projection_rows)

picks = []
squad = []

if picks_data:
    picks = picks_data.get("picks", [])

    squad = [
        player_by_id[pick["element"]]
        for pick in picks
        if pick.get("element") in player_by_id
    ]

owned_ids = {
    player["id"]
    for player in squad
}


# ============================================================
# MAIN NAVIGATION
# ============================================================

tabs = st.tabs(
    [
        "Overview",
        "Captain & xP",
        "Transfers",
        "Wildcard / Free Hit",
        "Differentials",
        "Fixtures & Rotation",
        "Weekly Reports",
    ]
)


# ============================================================
# TAB 1 — OVERVIEW
# ============================================================

with tabs[0]:

    left, right = st.columns([1.3, 1])

    with left:
        st.subheader("Your squad")

        if picks:
            pick_rows = []

            for pick in picks:
                player = player_by_id.get(
                    pick.get("element")
                )

                if not player:
                    continue

                player_fixtures = fx_map.get(
                    (player["team"], gw),
                    [],
                )

                pick_rows.append(
                    {
                        "Slot": (
                            "XI"
                            if pick.get("position", 99) <= 11
                            else "Bench"
                        ),
                        "Player": player["web_name"],
                        "Pos": POS_NAMES.get(
                            player["element_type"],
                            "?",
                        ),
                        "Club": team_short.get(
                            player["team"],
                            "",
                        ),
                        "Fixture": fx_text(player_fixtures),
                        "xP": player_fixture_xp(
                            player,
                            player_fixtures,
                        ),
                        "Status": status_label(player),
                        "Captain": (
                            "C"
                            if pick.get("is_captain")
                            else "VC"
                            if pick.get("is_vice_captain")
                            else ""
                        ),
                    }
                )

            st.dataframe(
                pd.DataFrame(pick_rows),
                use_container_width=True,
                hide_index=True,
            )

            st.caption(
                f"Squad snapshot: GW{snapshot_gw}. "
                "If target Gameweek picks are not published, "
                "the latest available public picks are shown."
            )

        else:
            st.info(
                "Public picks are not available for this manager. "
                "Other player analysis remains available."
            )

    with right:
        st.subheader("Squad health")

        if squad:
            flagged = [
                player
                for player in squad
                if (
                    player.get("status") != "a"
                    or player.get(
                        "chance_of_playing_next_round"
                    ) not in (None, 100)
                )
            ]

            st.metric(
                "Availability concerns",
                len(flagged),
            )

            for player in flagged:
                st.warning(
                    f"**{player['web_name']}** — "
                    f"{status_label(player)}\n\n"
                    f"{player.get('news') or 'No additional FPL news.'}"
                )

        st.subheader("Next deadlines")

        upcoming_events = [
            event
            for event in events
            if (
                not event.get("finished")
                and event.get("deadline_time")
            )
        ]

        for event in upcoming_events[:5]:
            event_time = malaysia_time(
                event["deadline_time"],
                "%d %b %Y, %I:%M %p",
            )

            st.write(
                f"**GW{event['id']}** · "
                f"{event_time} Malaysia time"
            )


# ============================================================
# TAB 2 — CAPTAIN & EXPECTED POINTS
# ============================================================

with tabs[1]:

    st.subheader(
        "Captain and vice-captain recommendations"
    )

    st.caption(
        "Ranked using the free xP estimate. "
        "Captaincy doubles the selected player's FPL points. "
        "The xP column is per player and is not doubled."
    )

    pool = proj[
        (proj["Position"] != "GKP")
        & (proj["status_code"].isin(["a", "d"]))
    ].sort_values(
        "xP",
        ascending=False,
    ).head(12).copy()

    if not pool.empty:

        pool.insert(
            0,
            "Recommendation",
            [
                "Captain candidate"
                if index == 0
                else "Vice-captain candidate"
                if index == 1
                else "Alternative"
                for index in range(len(pool))
            ],
        )

        st.dataframe(
            pool[
                [
                    "Recommendation",
                    "Player",
                    "Position",
                    "Club",
                    "Fixture",
                    "xP",
                    "Ownership %",
                    "Status",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

        st.metric(
            "Top captain projected points",
            f"{pool.iloc[0]['xP']:.2f}",
        )

    st.divider()

    st.subheader("Expected points — player explorer")

    position_filter = st.selectbox(
        "Position filter",
        ["All", "GKP", "DEF", "MID", "FWD"],
        key="xp_pos",
    )

    view = (
        proj
        if position_filter == "All"
        else proj[
            proj["Position"] == position_filter
        ]
    )

    st.dataframe(
        view.sort_values(
            "xP",
            ascending=False,
        ).head(35)[
            [
                "Player",
                "Position",
                "Club",
                "Price label",
                "Fixture",
                "xP",
                "Form",
                "xGI",
                "Status",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "xP is a transparent statistical estimate based on "
        "available player data, minutes, form and fixture difficulty. "
        "It is not official FPL data or a guarantee."
    )


# ============================================================
# TAB 3 — TRANSFER PLANNER
# ============================================================

with tabs[2]:

    st.subheader("Transfer planner")

    if not squad:
        st.info(
            "Transfer planner needs a public squad snapshot."
        )

    else:
        bank_tenths = num(
            latest.get(
                "bank",
                profile.get("last_deadline_bank", 0),
            )
        )

        st.write(
            f"Latest public bank estimate: **{money(bank_tenths)}**"
        )

        st.caption(
            "Selling prices use public picks data where available. "
            "Current market price is used as a fallback."
        )

        transfer_rows = []

        for pick in picks:
            old_player = player_by_id.get(
                pick.get("element")
            )

            if not old_player:
                continue

            sell_price = num(
                pick.get("selling_price"),
                old_player.get("now_cost", 0),
            )

            position_id = old_player.get("element_type")

            candidates = proj[
                (proj["element_type"] == position_id)
                & (~proj["id"].isin(owned_ids))
                & (proj["status_code"].isin(["a", "d"]))
            ].copy()

            candidates["cost_tenths"] = candidates["id"].map(
                {
                    player["id"]: num(
                        player.get("now_cost")
                    )
                    for player in players
                }
            )

            candidates = candidates[
                candidates["cost_tenths"]
                <= sell_price + bank_tenths
            ]

            if candidates.empty:
                continue

            best = candidates.sort_values(
                "xP",
                ascending=False,
            ).iloc[0]

            old_xp = player_fixture_xp(
                old_player,
                fx_map.get(
                    (old_player["team"], gw),
                    [],
                ),
            )

            delta = best["xP"] - old_xp

            transfer_rows.append(
                {
                    "Sell candidate": old_player["web_name"],
                    "Buy candidate": best["Player"],
                    "Position": POS_NAMES.get(position_id),
                    "Sell price": money(sell_price),
                    "Buy price": best["Price label"],
                    "Next GW xP gain": round(delta, 2),
                    "New fixture": best["Fixture"],
                    "New status": best["Status"],
                }
            )

        if transfer_rows:
            transfer_df = pd.DataFrame(
                transfer_rows
            ).sort_values(
                "Next GW xP gain",
                ascending=False,
            )

            st.dataframe(
                transfer_df.head(20),
                use_container_width=True,
                hide_index=True,
            )

        else:
            st.info(
                "No affordable same-position transfer candidates "
                "were found using the available public data."
            )

        st.warning(
            "These are one-transfer comparisons, not automatic "
            "transfer instructions. Check your actual bank, selling "
            "prices, free transfers, squad limits and hit cost "
            "before confirming transfers on the official FPL site."
        )


# ============================================================
# TAB 4 — WILDCARD / FREE HIT
# ============================================================

with tabs[3]:

    st.subheader(
        "Wildcard / Free Hit squad optimiser"
    )

    st.caption(
        "Builds an indicative 15-player squad using FPL position "
        "quotas and a maximum of three players per club. "
        "This is an estimate, not a guaranteed global optimum."
    )

    budget = st.number_input(
        "Squad budget (£m)",
        min_value=80.0,
        max_value=120.0,
        value=100.0,
        step=0.5,
    )

    chip_mode = st.radio(
        "Planning mode",
        [
            "Wildcard (longer-term squad)",
            "Free Hit (one Gameweek)",
        ],
        horizontal=True,
    )

    if st.button(
        "Optimise 15-player squad",
        type="primary",
    ):

        optimised_squad = build_squad(
            players,
            fx_map,
            gw,
            budget,
        )

        if len(optimised_squad) < 15:
            st.error(
                f"Only {len(optimised_squad)} eligible players "
                "were found within the constraints. "
                "Try increasing the budget."
            )

        else:
            starting_xi = best_starting_xi(
                optimised_squad,
                fx_map,
                gw,
            )

            rows = []

            for player in optimised_squad:
                player_fixtures = fx_map.get(
                    (player["team"], gw),
                    [],
                )

                rows.append(
                    {
                        "Line-up": (
                            "Starting XI"
                            if player in starting_xi
                            else "Bench"
                        ),
                        "Player": player["web_name"],
                        "Position": POS_NAMES.get(
                            player["element_type"]
                        ),
                        "Club": team_short.get(
                            player["team"]
                        ),
                        "Price": money(
                            player.get("now_cost")
                        ),
                        "Fixture": fx_text(player_fixtures),
                        "xP": player_fixture_xp(
                            player,
                            player_fixtures,
                        ),
                    }
                )

            result_df = pd.DataFrame(rows)

            st.dataframe(
                result_df.sort_values(
                    ["Line-up", "Position", "xP"],
                    ascending=[True, True, False],
                ),
                use_container_width=True,
                hide_index=True,
            )

            total_cost = sum(
                num(player.get("now_cost"))
                for player in optimised_squad
            ) / 10

            st.metric(
                "Estimated squad cost",
                f"£{total_cost:.1f}m",
            )

            st.success(
                f"{chip_mode} draft generated. "
                "Review player availability and club limits "
                "before using it."
            )


# ============================================================
# TAB 5 — DIFFERENTIALS
# ============================================================

with tabs[4]:

    st.subheader(
        "Differential and hidden-gem finder"
    )

    max_ownership = st.slider(
        "Maximum ownership %",
        1,
        30,
        10,
    )

    max_price = st.slider(
        "Maximum price (£m)",
        4.0,
        15.0,
        9.0,
        0.5,
    )

    min_minutes = st.slider(
        "Minimum minutes played",
        0,
        1500,
        300,
        50,
    )

    gems = proj[
        (proj["Ownership %"] <= max_ownership)
        & (proj["Price"] <= max_price)
        & (proj["Minutes"] >= min_minutes)
        & (~proj["id"].isin(owned_ids))
        & (proj["status_code"].isin(["a", "d"]))
    ].copy()

    gems["Value (xP/£m)"] = (
        gems["xP"]
        / gems["Price"].clip(lower=0.1)
    )

    st.dataframe(
        gems.sort_values(
            ["xP", "Value (xP/£m)"],
            ascending=False,
        ).head(30)[
            [
                "Player",
                "Position",
                "Club",
                "Price label",
                "Ownership %",
                "Fixture",
                "xP",
                "Value (xP/£m)",
                "Status",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Differentials are filtered by your selected ownership, "
        "price and minutes thresholds. They are not guaranteed "
        "breakout picks."
    )


# ============================================================
# TAB 6 — FIXTURES & ROTATION
# ============================================================

with tabs[5]:

    st.subheader(
        "📊 Fixture Radar & Rotation Planner"
    )

    st.caption(
        "Visualise upcoming fixture difficulty. "
        "Green = easier, red = harder."
    )

    horizon = st.slider(
        "Upcoming Gameweeks",
        2,
        8,
        5,
        key="fixture_horizon",
    )

    upcoming_gws = [
        event["id"]
        for event in events
        if (
            not event.get("finished")
            and event.get("deadline_time")
        )
    ][:horizon]

    if not upcoming_gws:
        st.warning("No upcoming fixtures available.")

    else:
        fixture_names = []
        fixture_difficulty = []

        for team in teams:
            name_row = {
                "Club": team.get("name")
            }

            difficulty_row = {
                "Club": team.get("name")
            }

            all_difficulties = []

            for event_id in upcoming_gws:
                team_fixtures = fx_map.get(
                    (team["id"], event_id),
                    [],
                )

                if team_fixtures:
                    name_row[f"GW{event_id}"] = " / ".join(
                        opponent
                        for opponent, difficulty
                        in team_fixtures
                    )

                    average_difficulty = sum(
                        difficulty
                        for _, difficulty in team_fixtures
                    ) / len(team_fixtures)

                    difficulty_row[f"GW{event_id}"] = round(
                        average_difficulty,
                        1,
                    )

                    all_difficulties.extend(
                        difficulty
                        for _, difficulty in team_fixtures
                    )

                else:
                    name_row[f"GW{event_id}"] = "Blank"
                    difficulty_row[f"GW{event_id}"] = None

            difficulty_row["Avg FDR"] = (
                round(
                    sum(all_difficulties)
                    / len(all_difficulties),
                    2,
                )
                if all_difficulties
                else None
            )

            fixture_names.append(name_row)
            fixture_difficulty.append(difficulty_row)

        names_df = pd.DataFrame(fixture_names)

        difficulty_df = pd.DataFrame(
            fixture_difficulty
        ).sort_values(
            "Avg FDR",
            ascending=True,
            na_position="last",
        )

        gameweek_columns = [
            f"GW{gameweek}"
            for gameweek in upcoming_gws
        ]

        heatmap = difficulty_df.set_index(
            "Club"
        )[gameweek_columns]

        st.markdown(
            "### 🟢 Fixture Difficulty Heatmap"
        )

        st.caption(
            "FDR scale: 1 = easiest, 5 = hardest."
        )

        st.dataframe(
            heatmap.style.background_gradient(
                cmap="RdYlGn_r",
                axis=None,
                vmin=1,
                vmax=5,
            ).format(
                "{:.1f}",
                na_rep="—",
            ),
            use_container_width=True,
            height=650,
        )

        st.markdown(
            "### 🏆 Best Upcoming Fixture Runs"
        )

        best_teams = difficulty_df.dropna(
            subset=["Avg FDR"]
        ).head(5)

        if best_teams.empty:
            st.info(
                "No fixture difficulty data is available."
            )

        else:
            metric_columns = st.columns(
                len(best_teams)
            )

            for index, (_, team_row) in enumerate(
                best_teams.iterrows()
            ):
                with metric_columns[index]:
                    st.metric(
                        label=team_row["Club"],
                        value=f'{team_row["Avg FDR"]:.2f}',
                        help=(
                            "Average fixture difficulty. "
                            "Lower is easier."
                        ),
                    )

        st.markdown(
            "### 🗓️ Opponent Fixture Timeline"
        )

        st.dataframe(
            names_df,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.markdown(
            "### 🔄 Your Squad Rotation Planner"
        )

        if squad:
            rotation_rows = []

            for player in squad:
                player_fixtures_by_gw = [
                    fx_map.get(
                        (player["team"], gameweek),
                        [],
                    )
                    for gameweek in upcoming_gws
                ]

                difficulties = [
                    difficulty
                    for fixture_group in player_fixtures_by_gw
                    for _, difficulty in fixture_group
                ]

                rotation_rows.append(
                    {
                        "Player": player["web_name"],
                        "Club": team_short.get(
                            player["team"]
                        ),
                        "Position": POS_NAMES.get(
                            player["element_type"]
                        ),
                        "Minutes": player.get("minutes"),
                        "Status": status_label(player),
                        "Avg FDR": (
                            round(
                                sum(difficulties)
                                / len(difficulties),
                                2,
                            )
                            if difficulties
                            else None
                        ),
                        "Upcoming fixtures": " | ".join(
                            f"GW{gameweek}: "
                            f"{fx_text(fx_map.get((player['team'], gameweek), []))}"
                            for gameweek in upcoming_gws
                        ),
                    }
                )

            rotation_df = pd.DataFrame(
                rotation_rows
            )

            st.dataframe(
                rotation_df.sort_values(
                    ["Avg FDR", "Minutes"],
                    ascending=[True, False],
                    na_position="last",
                ),
                use_container_width=True,
                hide_index=True,
            )

        else:
            st.info(
                "Public squad picks are not available "
                "for rotation analysis."
            )


# ============================================================
# TAB 7 — WEEKLY REPORTS
# ============================================================

with tabs[6]:

    st.subheader(
        "Automatic weekly FPL reports"
    )

    st.write(
        "The GitHub Actions workflow can generate a Markdown "
        "report every Monday at 09:00 Malaysia time (01:00 UTC) "
        "and save it in this repository. Reports appear here "
        "after the repository syncs."
    )

    available_reports = report_files()

    if available_reports:

        for report_path in available_reports[:12]:

            with st.expander(
                report_path.stem.replace("_", " ")
            ):

                content = report_path.read_text(
                    encoding="utf-8"
                )

                st.markdown(content)

                st.download_button(
                    "Download report",
                    content,
                    file_name=report_path.name,
                    mime="text/markdown",
                    key=report_path.name,
                )

    else:
        st.info(
            "No scheduled reports have been generated yet. "
            "The workflow runs on its next schedule or can be "
            "started manually from GitHub Actions."
        )

    st.caption(
        "Scheduled reports depend on GitHub Actions being enabled "
        "and the public FPL API being available. GitHub may delay "
        "scheduled runs."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Independent fan-made tool; not affiliated with the "
    "Premier League. All xP, captain, transfer and optimisation "
    "outputs are estimates from statistical heuristics, not "
    "official FPL projections or guaranteed outcomes."
)
