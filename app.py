
import html
import itertools
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from fpl_engine import (
    num,
    player_fixture_xp,
    fixture_lookup,
    build_squad,
)

# ---------------------------------------------------------
# AJK BOLA WAWEI AI — CONFIGURATION
# ---------------------------------------------------------

API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "AJK-Bola-Wawei-AI/1.0"}
MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")

POS_NAMES = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}

st.set_page_config(
    page_title="AJK Bola Wawei AI",
    page_icon="⚽",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.3rem;
        max-width: 1600px;
    }

    [data-testid="stMetric"] {
        background: rgba(120,130,145,.09);
        padding: 12px 14px;
        border-radius: 12px;
    }

    .small-note {
        color: #8b93a1;
        font-size: .84rem;
    }

    .pitch {
        background:
            repeating-linear-gradient(
                0deg,
                #176b42,
                #176b42 70px,
                #1b7549 70px,
                #1b7549 140px
            );
        border: 3px solid rgba(255,255,255,.75);
        border-radius: 15px;
        padding: 18px 10px;
        color: white;
        position: relative;
    }

    .pitch-row {
        display: flex;
        justify-content: space-evenly;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
        margin: 16px 0;
    }

    .pitch-player {
        background: rgba(0,0,0,.30);
        border: 1px solid rgba(255,255,255,.30);
        border-radius: 10px;
        min-width: 88px;
        max-width: 125px;
        padding: 8px 6px;
        text-align: center;
        font-size: 12px;
        line-height: 1.35;
    }

    .pitch-player strong {
        display: block;
        font-size: 12px;
        color: white;
    }

    .pitch-player small {
        display: block;
        color: #e1f5e8;
        font-size: 10px;
    }

    .captain {
        background: #e9bd35;
        color: #222;
        border-radius: 5px;
        padding: 1px 5px;
        font-weight: bold;
        margin-left: 3px;
    }

    .vice {
        background: #d9e4ef;
        color: #222;
        border-radius: 5px;
        padding: 1px 5px;
        font-weight: bold;
        margin-left: 3px;
    }

    .bench-card {
        background: rgba(120,130,145,.10);
        border: 1px solid rgba(120,130,145,.25);
        border-radius: 9px;
        padding: 10px;
        text-align: center;
        font-size: 12px;
    }

    .section-note {
        padding: 10px 13px;
        border-radius: 9px;
        background: rgba(120,130,145,.08);
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

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

    label = labels.get(
        player.get("status"),
        str(player.get("status", "Unknown")),
    )

    chance = player.get("chance_of_playing_next_round")

    if chance is not None:
        label += f" · {chance}% chance"

    return label


def malaysia_time(value, fmt="%d %b %Y, %H:%M"):
    if not value:
        return "TBC"

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(MY_TZ).strftime(fmt)
    except Exception:
        return "TBC"


def fx_text(fixtures_for_player):
    return ", ".join(x[0] for x in fixtures_for_player) if fixtures_for_player else "Blank"


def report_files():
    folder = Path("reports")
    return sorted(folder.glob("GW*_report.md"), reverse=True) if folder.exists() else []


def gw_xp(player, gameweek, fx_map):
    """
    Return zero for a confirmed blank gameweek.
    Otherwise use the existing free FPL xP heuristic.
    """
    fixtures_for_player = fx_map.get((player["team"], gameweek), [])

    if not fixtures_for_player:
        return 0.0

    return player_fixture_xp(player, fixtures_for_player)


def best_xi_for_gw(squad, gameweek, fx_map):
    """
    Find the highest-scoring legal starting XI.
    Formation rules: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD.
    """
    keepers = [p for p in squad if p.get("element_type") == 1]
    defenders = sorted(
        [p for p in squad if p.get("element_type") == 2],
        key=lambda p: gw_xp(p, gameweek, fx_map),
        reverse=True,
    )
    midfielders = sorted(
        [p for p in squad if p.get("element_type") == 3],
        key=lambda p: gw_xp(p, gameweek, fx_map),
        reverse=True,
    )
    forwards = sorted(
        [p for p in squad if p.get("element_type") == 4],
        key=lambda p: gw_xp(p, gameweek, fx_map),
        reverse=True,
    )

    if not keepers:
        return []

    keeper = max(
        keepers,
        key=lambda p: gw_xp(p, gameweek, fx_map),
    )

    best_team = []
    best_score = -1

    for def_count in range(3, min(5, len(defenders)) + 1):
        for mid_count in range(2, min(5, len(midfielders)) + 1):
            forward_count = 10 - 1 - def_count - mid_count

            if forward_count < 1 or forward_count > 3:
                continue

            if forward_count > len(forwards):
                continue

            for defs in itertools.combinations(defenders, def_count):
                for mids in itertools.combinations(midfielders, mid_count):
                    for fwds in itertools.combinations(forwards, forward_count):
                        xi = [keeper] + list(defs) + list(mids) + list(fwds)

                        score = sum(
                            gw_xp(p, gameweek, fx_map)
                            for p in xi
                        )

                        if len(xi) == 11 and score > best_score:
                            best_score = score
                            best_team = xi

    return best_team


def render_pitch(
    starting_xi,
    gameweek,
    fx_map,
    captain_id=None,
    vice_id=None,
    bench=None,
):
    """
    Draw a football-pitch style lineup using Streamlit HTML rendering.
    """
    if not starting_xi:
        st.info("No starting XI is available to display.")
        return

    groups = {
        4: [],
        3: [],
        2: [],
        1: [],
    }

    for player in starting_xi:
        groups.setdefault(player.get("element_type"), []).append(player)

    pitch_rows = []

    for position in [4, 3, 2, 1]:
        cards = []

        for player in groups.get(position, []):
            player_id = player.get("id")
            name = html.escape(str(player.get("web_name", "Player")))
            club = html.escape(str(player.get("team_name", "")))
            fixture = html.escape(
                fx_text(fx_map.get((player["team"], gameweek), []))
            )
            xp = gw_xp(player, gameweek, fx_map)

            badge = ""

            if player_id == captain_id:
                badge = '<span class="captain">C</span>'
            elif player_id == vice_id:
                badge = '<span class="vice">VC</span>'

            cards.append(
                f"""
                <div class="pitch-player">
                    <strong>{name} {badge}</strong>
                    <small>{club} · {fixture}</small>
                    <small>xP: {xp:.2f}</small>
                </div>
                """
            )

        if cards:
            pitch_rows.append(
                '<div class="pitch-row">' + "".join(cards) + "</div>"
            )

    st.markdown(
        '<div class="pitch">'
        + "".join(pitch_rows)
        + "</div>",
        unsafe_allow_html=True,
    )

    if bench:
        st.markdown("**Substitutes**")

        columns = st.columns(len(bench))

        for index, player in enumerate(bench):
            xp = gw_xp(player, gameweek, fx_map)
            fixture = fx_text(fx_map.get((player["team"], gameweek), []))

            with columns[index]:
                st.markdown(
                    f"""
                    <div class="bench-card">
                        <strong>{html.escape(str(player.get("web_name", "Player")))}</strong><br>
                        {POS_NAMES.get(player.get("element_type"), "?")}<br>
                        {html.escape(fixture)}<br>
                        xP: {xp:.2f}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def player_projection_table(players, gameweeks, fx_map):
    rows = []

    for player in players:
        row = {
            "Player": player.get("web_name", ""),
            "Position": POS_NAMES.get(player.get("element_type"), "?"),
            "Club": player.get("team_name", ""),
            "Price": money(player.get("now_cost")),
            "Status": status_label(player),
        }

        total = 0.0

        for gameweek in gameweeks:
            value = gw_xp(player, gameweek, fx_map)
            row[f"GW{gameweek}"] = value
            total += value

        row["Total xP"] = round(total, 2)
        rows.append(row)

    return pd.DataFrame(rows)


def safe_horizon_max(gameweeks):
    return max(1, min(6, len(gameweeks)))


# ---------------------------------------------------------
# SIDEBAR — MANUAL TEAM ID ONLY
# ---------------------------------------------------------

with st.sidebar:
    st.title("⚽ AJK Bola Wawei AI")
    st.caption("Your personal Fantasy Premier League analyst")

    st.subheader("Manager")

    team_id = st.number_input(
        "FPL Team ID",
        min_value=1,
        value=1645144,
        step=1,
    )

    if st.button("↻ Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    st.caption(
        "Free public FPL data. No FPL password or paid AI API is required."
    )


# ---------------------------------------------------------
# LOAD FPL DATA
# ---------------------------------------------------------

try:
    with st.spinner("Loading live FPL data..."):
        boot = get_json("bootstrap-static/")
        fixtures = get_json("fixtures/")
        profile = get_json(f"entry/{int(team_id)}/")

except Exception as error:
    st.error(f"Unable to load FPL data: {error}")
    st.stop()


players = boot.get("elements", [])
teams = boot.get("teams", [])
events = boot.get("events", [])

player_by_id = {
    player["id"]: player
    for player in players
}

team_names = {
    team["id"]: team.get("name", "")
    for team in teams
}

team_short = {
    team["id"]: team.get("short_name", team.get("name", ""))
    for team in teams
}

fx_map = fixture_lookup(fixtures, teams)

current_event = next(
    (event for event in events if event.get("is_current")),
    None,
)

next_event = next(
    (event for event in events if event.get("is_next")),
    None,
)

if next_event:
    target_event = next_event
elif current_event and not current_event.get("finished"):
    target_event = current_event
else:
    target_event = next(
        (
            event for event in events
            if not event.get("finished") and event.get("deadline_time")
        ),
        None,
    )

if not target_event:
    st.warning("No upcoming Gameweek is currently available from the FPL API.")
    st.stop()

target_gw = int(target_event["id"])

# Always plan forward from the selected target GW.
upcoming_events = [
    event
    for event in events
    if int(event["id"]) >= target_gw
    and not event.get("finished")
    and event.get("deadline_time")
]

upcoming_events = sorted(
    upcoming_events,
    key=lambda event: int(event["id"]),
)

available_gws = [
    int(event["id"])
    for event in upcoming_events
]

if not available_gws:
    available_gws = [target_gw]


# ---------------------------------------------------------
# LOAD TEAM PICKS AND HISTORY
# ---------------------------------------------------------

try:
    picks_data = get_json(
        f"entry/{int(team_id)}/event/{target_gw}/picks/"
    )
    snapshot_gw = target_gw

except Exception:
    completed_events = [
        event for event in events
        if event.get("finished")
    ]

    snapshot_gw = (
        int(completed_events[-1]["id"])
        if completed_events
        else target_gw
    )

    try:
        picks_data = get_json(
            f"entry/{int(team_id)}/event/{snapshot_gw}/picks/"
        )
    except Exception:
        picks_data = None


try:
    history = get_json(
        f"entry/{int(team_id)}/history/"
    ).get("current", [])

except Exception:
    history = []


latest = history[-1] if history else {}

manager = (
    f"{profile.get('player_first_name', '')} "
    f"{profile.get('player_last_name', '')}"
).strip()

deadline_text = malaysia_time(
    target_event.get("deadline_time")
)

squad = []
picks = []

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


# Add team names to player objects for display.
for player in players:
    player["team_name"] = team_short.get(
        player.get("team"),
        "",
    )


# ---------------------------------------------------------
# BUILD PLAYER PROJECTIONS
# ---------------------------------------------------------

projection_rows = []

for player in players:
    fixtures_for_player = fx_map.get(
        (player["team"], target_gw),
        [],
    )

    projection_rows.append(
        {
            "id": player["id"],
            "Player": player.get("web_name", ""),
            "Position": POS_NAMES.get(player.get("element_type"), "?"),
            "Club": team_short.get(player["team"], ""),
            "Price": num(player.get("now_cost")) / 10,
            "Price label": money(player.get("now_cost")),
            "Fixture": fx_text(fixtures_for_player),
            "xP": gw_xp(player, target_gw, fx_map),
            "Form": num(player.get("form")),
            "xGI": num(player.get("expected_goal_involvements")),
            "Minutes": num(player.get("minutes")),
            "Ownership %": num(player.get("selected_by_percent")),
            "Status": status_label(player),
            "status_code": player.get("status", "a"),
            "team": player["team"],
            "element_type": player["element_type"],
        }
    )

proj = pd.DataFrame(projection_rows)


# ---------------------------------------------------------
# HEADER AND MANAGER OVERVIEW
# ---------------------------------------------------------

st.title("⚽ AJK Bola Wawei AI")

st.caption(
    f"{profile.get('name', 'FPL Manager')} · "
    f"{manager} · "
    f"Team ID {int(team_id)} · "
    f"Target GW{target_gw} · "
    f"Deadline: {deadline_text} Malaysia time"
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
    str(target_gw),
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


# ---------------------------------------------------------
# NAVIGATION
# ---------------------------------------------------------

tabs = st.tabs(
    [
        "Overview",
        "Captain & xP",
        "Transfers",
        "Multi-GW Planner",
        "Wildcard / Free Hit",
        "Differentials",
        "Fixtures & Rotation",
        "Weekly Reports",
    ]
)


# =========================================================
# TAB 1 — OVERVIEW
# =========================================================

with tabs[0]:
    left, right = st.columns([1.5, 1])

    with left:
        st.subheader("Your squad — pitch view")

        if picks and squad:
            starting_players = []
            bench_players = []

            captain_id = None
            vice_id = None

            for pick in picks:
                player = player_by_id.get(pick.get("element"))

                if not player:
                    continue

                if pick.get("is_captain"):
                    captain_id = player["id"]

                if pick.get("is_vice_captain"):
                    vice_id = player["id"]

                if pick.get("position", 99) <= 11:
                    starting_players.append(player)
                else:
                    bench_players.append(player)

            render_pitch(
                starting_players,
                target_gw,
                fx_map,
                captain_id=captain_id,
                vice_id=vice_id,
                bench=bench_players,
            )

            st.caption(
                f"Squad snapshot: GW{snapshot_gw}. "
                "If the target GW picks are not published yet, "
                "the latest available public lineup is displayed."
            )

        else:
            st.info(
                "Your public squad picks are not available. "
                "Other player analysis remains available."
            )

    with right:
        st.subheader("Squad health")

        if squad:
            flagged = [
                player for player in squad
                if player.get("status") != "a"
                or player.get("chance_of_playing_next_round") not in (None, 100)
            ]

            st.metric(
                "Availability concerns",
                len(flagged),
            )

            if flagged:
                for player in flagged:
                    st.warning(
                        f"**{player['web_name']}** — "
                        f"{status_label(player)}\n\n"
                        f"{player.get('news') or 'No additional FPL news supplied.'}"
                    )
            else:
                st.success("No major availability concerns detected.")

        st.subheader("Upcoming deadlines")

        for event in upcoming_events[:6]:
            st.write(
                f"**GW{event['id']}** · "
                f"{malaysia_time(event.get('deadline_time'), '%d %b %H:%M')} Malaysia"
            )


# =========================================================
# TAB 2 — CAPTAIN AND PLAYER xP
# =========================================================

with tabs[1]:
    st.subheader("Captain and vice-captain recommendations")

    st.caption(
        "Candidates are ranked using the app's free xP estimate. "
        "Captaincy doubles the selected player's actual FPL points; "
        "the xP shown here is the player's normal projected points."
    )

    captain_pool = proj[
        (proj["Position"] != "GKP")
        & (proj["status_code"].isin(["a", "d"]))
    ].sort_values(
        "xP",
        ascending=False,
    ).head(12).copy()

    if not captain_pool.empty:
        captain_pool.insert(
            0,
            "Recommendation",
            [
                "Captain candidate" if index == 0
                else "Vice-captain candidate" if index == 1
                else "Alternative"
                for index in range(len(captain_pool))
            ],
        )

        st.dataframe(
            captain_pool[
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
            f"{captain_pool.iloc[0]['xP']:.2f}",
        )

    st.divider()

    st.subheader("Expected points — player explorer")

    position_filter = st.selectbox(
        "Position filter",
        ["All", "GKP", "DEF", "MID", "FWD"],
        key="xp_position_filter",
    )

    player_view = (
        proj
        if position_filter == "All"
        else proj[proj["Position"] == position_filter]
    )

    st.dataframe(
        player_view.sort_values(
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

    # FIXED: use triple quotes for a multiline caption.
    st.caption(
        """
        xP is a transparent statistical estimate using public FPL data
        such as expected goal involvement, minutes, form, clean-sheet history
        and fixture difficulty. It is not an official FPL projection.
        """
    )


# =========================================================
# TAB 3 — MULTI-GAMEWEEK TRANSFER COMPARISON
# =========================================================

with tabs[2]:
    st.subheader("Transfer planner")

    transfer_max = safe_horizon_max(available_gws)

    transfer_horizon = st.slider(
        "Compare transfer value over how many Gameweeks?",
        min_value=1,
        max_value=transfer_max,
        value=min(3, transfer_max),
        key="transfer_horizon",
    )

    transfer_gws = available_gws[:transfer_horizon]

    st.write(
        "The planner compares the projected points of an outgoing player "
        "against affordable players in the same position across your selected "
        "Gameweek horizon."
    )

    st.caption(
        "This is a transfer comparison tool, not an automatic transfer execution system."
    )

    if not squad or not picks:
        st.info("Transfer planning requires your public squad snapshot.")
    else:
        bank_tenths = num(
            latest.get(
                "bank",
                profile.get("last_deadline_bank", 0),
            )
        )

        st.metric(
            "Latest public bank estimate",
            money(bank_tenths),
        )

        transfer_rows = []

        for pick in picks:
            old_player = player_by_id.get(pick.get("element"))

            if not old_player:
                continue

            sell_price = num(
                pick.get("selling_price"),
                old_player.get("now_cost", 0),
            )

            position_id = old_player.get("element_type")

            old_total = sum(
                gw_xp(old_player, gameweek, fx_map)
                for gameweek in transfer_gws
            )

            candidates = []

            for candidate in players:
                if candidate["id"] in owned_ids:
                    continue

                if candidate.get("element_type") != position_id:
                    continue

                if candidate.get("status") not in ("a", "d"):
                    continue

                candidate_cost = num(candidate.get("now_cost"))

                if candidate_cost > sell_price + bank_tenths:
                    continue

                new_total = sum(
                    gw_xp(candidate, gameweek, fx_map)
                    for gameweek in transfer_gws
                )

                candidates.append(
                    {
                        "player": candidate,
                        "total_xp": new_total,
                        "gain": new_total - old_total,
                    }
                )

            if not candidates:
                continue

            best = max(
                candidates,
                key=lambda item: item["gain"],
            )

            new_player = best["player"]

            transfer_rows.append(
                {
                    "Sell": old_player.get("web_name"),
                    "Buy": new_player.get("web_name"),
                    "Position": POS_NAMES.get(position_id),
                    "Sell price": money(sell_price),
                    "Buy price": money(new_player.get("now_cost")),
                    "Outgoing xP": round(old_total, 2),
                    "Incoming xP": round(best["total_xp"], 2),
                    "Projected gain": round(best["gain"], 2),
                    "New fixture run": " | ".join(
                        f"GW{gameweek}: "
                        f"{fx_text(fx_map.get((new_player['team'], gameweek), []))}"
                        for gameweek in transfer_gws
                    ),
                    "_gain": best["gain"],
                }
            )

        if transfer_rows:
            transfer_df = pd.DataFrame(transfer_rows).sort_values(
                "_gain",
                ascending=False,
            )

            st.dataframe(
                transfer_df.drop(columns=["_gain"]).head(20),
                use_container_width=True,
                hide_index=True,
            )

            best_move = transfer_df.iloc[0]

            st.success(
                f"Best estimated move over {transfer_horizon} GW(s): "
                f"{best_move['Sell']} → {best_move['Buy']} "
                f"({best_move['Projected gain']:+.2f} projected points)"
            )

        else:
            st.info(
                "No affordable same-position transfer candidates were found."
            )

        st.warning(
            "Important: this first version evaluates one transfer at a time. "
            "It does not simulate every possible multi-transfer path, "
            "and cannot fully infer private selling-price rules, exact free "
            "transfers or hit costs. Verify your bank and transfer state "
            "on the official FPL website."
        )


# =========================================================
# TAB 4 — MULTI-GAMEWEEK PLANNER
# =========================================================

with tabs[3]:
    st.subheader("Multi-Gameweek Planner")

    st.markdown(
        """
        <div class="section-note">
        Plan ahead instead of looking only at the next deadline.
        Compare your squad's estimated points, starting XI and captain
        recommendations across up to six upcoming Gameweeks.
        </div>
        """,
        unsafe_allow_html=True,
    )

    planner_max = safe_horizon_max(available_gws)

    planner_horizon = st.slider(
        "Planning horizon",
        min_value=1,
        max_value=planner_max,
        value=planner_max,
        key="multi_gw_horizon",
    )

    planner_gws = available_gws[:planner_horizon]

    st.write(
        "**Selected Gameweeks:** "
        + ", ".join(f"GW{gameweek}" for gameweek in planner_gws)
    )

    if not squad:
        st.info(
            "Your squad data is not available. "
            "The multi-gameweek player projection table can still be used below."
        )

    else:
        st.subheader("Your squad — projected points")

        squad_projection = player_projection_table(
            squad,
            planner_gws,
            fx_map,
        )

        squad_projection = squad_projection.sort_values(
            "Total xP",
            ascending=False,
        )

        st.dataframe(
            squad_projection,
            use_container_width=True,
            hide_index=True,
        )

        total_projection = squad_projection["Total xP"].sum()

        st.metric(
            f"Squad projected points — next {planner_horizon} GW(s)",
            f"{total_projection:.2f}",
        )

        st.divider()

        st.subheader("Gameweek-by-gameweek starting XI")

        selected_plan_gw = st.selectbox(
            "View lineup for",
            planner_gws,
            format_func=lambda value: f"Gameweek {value}",
            key="selected_plan_gw",
        )

        planned_xi = best_xi_for_gw(
            squad,
            selected_plan_gw,
            fx_map,
        )

        if planned_xi:
            xi_ids = {
                player["id"]
                for player in planned_xi
            }

            bench = [
                player for player in squad
                if player["id"] not in xi_ids
            ]

            bench = sorted(
                bench,
                key=lambda player: gw_xp(player, selected_plan_gw, fx_map),
                reverse=True,
            )

            captain_candidates = sorted(
                [
                    player for player in planned_xi
                    if player.get("element_type") != 1
                ],
                key=lambda player: gw_xp(player, selected_plan_gw, fx_map),
                reverse=True,
            )

            captain = captain_candidates[0] if captain_candidates else None
            vice = captain_candidates[1] if len(captain_candidates) > 1 else None

            st.metric(
                "Starting XI projected points",
                f"{sum(gw_xp(player, selected_plan_gw, fx_map) for player in planned_xi):.2f}",
            )

            render_pitch(
                planned_xi,
                selected_plan_gw,
                fx_map,
                captain_id=captain["id"] if captain else None,
                vice_id=vice["id"] if vice else None,
                bench=bench,
            )

            if captain:
                st.info(
                    f"Captain: **{captain['web_name']}** · "
                    f"Vice-captain: **{vice['web_name']}**"
                )

        else:
            st.warning(
                "A legal starting XI could not be generated from the available squad."
            )

        st.divider()

        st.subheader("Captain plan across the selected Gameweeks")

        captain_rows = []

        for gameweek in planner_gws:
            xi = best_xi_for_gw(
                squad,
                gameweek,
                fx_map,
            )

            candidates = sorted(
                [
                    player for player in xi
                    if player.get("element_type") != 1
                ],
                key=lambda player: gw_xp(player, gameweek, fx_map),
                reverse=True,
            )

            captain = candidates[0] if candidates else None
            vice = candidates[1] if len(candidates) > 1 else None

            captain_rows.append(
                {
                    "Gameweek": gameweek,
                    "Captain": captain.get("web_name") if captain else "—",
                    "Captain xP": gw_xp(captain, gameweek, fx_map) if captain else 0,
                    "Vice-captain": vice.get("web_name") if vice else "—",
                    "Vice xP": gw_xp(vice, gameweek, fx_map) if vice else 0,
                    "Starting XI xP": round(
                        sum(
                            gw_xp(player, gameweek, fx_map)
                            for player in xi
                        ),
                        2,
                    ),
                }
            )

        st.dataframe(
            pd.DataFrame(captain_rows),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.subheader("Top projected players across the planning horizon")

    all_player_projection = player_projection_table(
        players,
        planner_gws,
        fx_map,
    )

    st.dataframe(
        all_player_projection.sort_values(
            "Total xP",
            ascending=False,
        ).head(25),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "The planner uses the current public FPL data and the app's xP heuristic. "
        "It does not yet simulate every possible transfer sequence, price change, "
        "injury event or chip strategy. Blank gameweeks are shown as zero projected points."
    )


# =========================================================
# TAB 5 — WILDCARD / FREE HIT
# =========================================================

with tabs[4]:
    st.subheader("Wildcard / Free Hit squad optimiser")

    st.caption(
        "Builds an indicative 15-player squad using FPL position quotas "
        "and a maximum of three players per club. The current engine uses "
        "a greedy squad-building heuristic, not a guaranteed global optimum."
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
            "Wildcard — longer-term squad",
            "Free Hit — one Gameweek",
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
            target_gw,
            budget,
        )

        if len(optimised_squad) < 15:
            st.error(
                f"Only {len(optimised_squad)} eligible players were found. "
                "Try increasing the budget."
            )

        else:
            st.success(f"{chip_mode} draft generated.")

            optimised_xi = best_xi_for_gw(
                optimised_squad,
                target_gw,
                fx_map,
            )

            xi_ids = {
                player["id"]
                for player in optimised_xi
            }

            optimised_bench = [
                player for player in optimised_squad
                if player["id"] not in xi_ids
            ]

            total_cost = sum(
                num(player.get("now_cost"))
                for player in optimised_squad
            ) / 10

            total_xp = sum(
                gw_xp(player, target_gw, fx_map)
                for player in optimised_xi
            )

            m1, m2, m3 = st.columns(3)

            m1.metric(
                "Estimated squad cost",
                f"£{total_cost:.1f}m",
            )

            m2.metric(
                "Remaining budget",
                f"£{budget - total_cost:.1f}m",
            )

            m3.metric(
                "Starting XI xP",
                f"{total_xp:.2f}",
            )

            render_pitch(
                optimised_xi,
                target_gw,
                fx_map,
                bench=optimised_bench,
            )

            st.subheader("Full 15-player squad")

            rows = []

            for player in optimised_squad:
                rows.append(
                    {
                        "Line-up": (
                            "Starting XI"
                            if player["id"] in xi_ids
                            else "Bench"
                        ),
                        "Player": player.get("web_name"),
                        "Position": POS_NAMES.get(player.get("element_type")),
                        "Club": team_short.get(player.get("team")),
                        "Price": money(player.get("now_cost")),
                        "Fixture": fx_text(
                            fx_map.get((player["team"], target_gw), [])
                        ),
                        "xP": gw_xp(player, target_gw, fx_map),
                    }
                )

            st.dataframe(
                pd.DataFrame(rows).sort_values(
                    ["Line-up", "Position", "xP"],
                    ascending=[True, True, False],
                ),
                use_container_width=True,
                hide_index=True,
            )

            st.warning(
                "Review the squad's availability, budget and club limits "
                "before making any changes in the official FPL website."
            )


# =========================================================
# TAB 6 — DIFFERENTIALS
# =========================================================

with tabs[5]:
    st.subheader("Differential and hidden-gem finder")

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
        gems["xP"] / gems["Price"].clip(lower=0.1)
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
        "Differentials are defined by your selected ownership, price and minutes "
        "thresholds. They are not guaranteed breakout picks."
    )


# =========================================================
# TAB 7 — FIXTURES AND ROTATION
# =========================================================

with tabs[6]:
    st.subheader("Fixture difficulty and rotation planner")

    fixture_max = safe_horizon_max(available_gws)

    fixture_horizon = st.slider(
        "Upcoming Gameweeks",
        min_value=1,
        max_value=fixture_max,
        value=min(5, fixture_max),
        key="fixture_horizon",
    )

    fixture_gws = available_gws[:fixture_horizon]

    fixture_rows = []

    for team in teams:
        row = {
            "Club": team.get("name"),
        }

        difficulties = []

        for gameweek in fixture_gws:
            team_fixtures = fx_map.get(
                (team["id"], gameweek),
                [],
            )

            row[f"GW{gameweek}"] = (
                fx_text(team_fixtures)
                if team_fixtures
                else "Blank"
            )

            difficulties.extend(
                difficulty
                for _, difficulty in team_fixtures
            )

        row["Avg FDR"] = (
            round(
                sum(difficulties) / len(difficulties),
                2,
            )
            if difficulties
            else None
        )

        fixture_rows.append(row)

    fixture_df = pd.DataFrame(fixture_rows).sort_values(
        "Avg FDR",
        ascending=True,
        na_position="last",
    )

    st.dataframe(
        fixture_df,
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Rotation notes from your squad")

    if squad:
        rotation_rows = []

        for player in squad:
            difficulties = []

            for gameweek in fixture_gws:
                team_fixtures = fx_map.get(
                    (player["team"], gameweek),
                    [],
                )

                difficulties.extend(
                    difficulty
                    for _, difficulty in team_fixtures
                )

            rotation_rows.append(
                {
                    "Player": player.get("web_name"),
                    "Club": team_short.get(player.get("team")),
                    "Position": POS_NAMES.get(player.get("element_type")),
                    "Minutes": player.get("minutes"),
                    "Status": status_label(player),
                    "Avg FDR": (
                        round(
                            sum(difficulties) / len(difficulties),
                            2,
                        )
                        if difficulties
                        else None
                    ),
                    "Upcoming": " | ".join(
                        f"GW{gameweek}: "
                        f"{fx_text(fx_map.get((player['team'], gameweek), []))}"
                        for gameweek in fixture_gws
                    ),
                }
            )

        st.dataframe(
            pd.DataFrame(rotation_rows).sort_values(
                ["Avg FDR", "Minutes"],
                ascending=[True, False],
            ),
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.info("Load public picks to see squad rotation notes.")


# =========================================================
# TAB 8 — WEEKLY REPORTS
# =========================================================

with tabs[7]:
    st.subheader("Automatic weekly FPL reports")

    st.write(
        "The GitHub Actions workflow can generate a Markdown report "
        "every Monday at 09:00 Malaysia time (01:00 UTC). "
        "Reports appear here after they are saved to the repository."
    )

    files = report_files()

    if files:
        for report_path in files[:12]:
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
            "The workflow can also be started manually from GitHub Actions."
        )

    st.caption(
        "Scheduled reports depend on GitHub Actions and the public FPL API. "
        "GitHub may delay scheduled runs."
    )


# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------

st.divider()

st.caption(
    "AJK Bola Wawei AI · Independent fan-made FPL analytics tool. "
    "Not affiliated with or endorsed by the Premier League. "
    "All xP, captain, transfer and optimisation outputs are estimates "
    "based on public data and transparent statistical heuristics. "
    "Always verify decisions on the official FPL website."
)
