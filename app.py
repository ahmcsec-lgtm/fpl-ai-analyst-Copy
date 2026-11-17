
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

MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")
BASE_URL = "https://fantasy.premierleague.com/api"
REPORTS_DIR = Path(__file__).parent / "reports"

st.set_page_config(
    page_title="FPL AI Analyst",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CUSTOM DESIGN
# ============================================================

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

    :root {
        --bg: #07111f;
        --panel: #101e30;
        --panel2: #14263b;
        --line: rgba(148, 163, 184, .16);
        --muted: #91a4ba;
        --text: #f2f7fc;
        --green: #32e6a1;
        --blue: #69b7ff;
        --red: #ff6b78;
        --gold: #f7c969;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    .stApp {
        background: radial-gradient(
            circle at 15% 0%,
            #132b43 0,
            #07111f 42%,
            #060d18 100%
        );
        color: var(--text);
    }

    [data-testid="stHeader"] {
        background: rgba(7,17,31,.75);
    }

    [data-testid="stSidebar"] {
        background: #0b1727;
        border-right: 1px solid var(--line);
    }

    [data-testid="stSidebar"] * {
        color: var(--text);
    }

    h1, h2, h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        color: var(--text);
    }

    h1 {
        letter-spacing: -1.4px;
    }

    .hero {
        background: linear-gradient(
            115deg,
            rgba(31,70,91,.96),
            rgba(15,35,55,.98) 55%,
            rgba(18,63,55,.92)
        );
        border: 1px solid rgba(91, 230, 177, .25);
        border-radius: 22px;
        padding: 26px 28px;
        margin: 4px 0 22px 0;
        box-shadow: 0 16px 50px rgba(0,0,0,.22);
    }

    .eyebrow {
        color: var(--green);
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 2px;
        text-transform: uppercase;
    }

    .hero-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: clamp(28px, 4vw, 42px);
        line-height: 1.08;
        font-weight: 700;
        margin: 8px 0;
        color: #fff;
    }

    .hero-sub {
        color: #c2d1df;
        font-size: 14px;
    }

    .metric {
        background: linear-gradient(
            145deg,
            rgba(20,38,59,.98),
            rgba(12,27,44,.98)
        );
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 17px 18px;
        min-height: 108px;
    }

    .metric-label {
        color: var(--muted);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.1px;
        text-transform: uppercase;
    }

    .metric-value {
        color: #fff;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 27px;
        font-weight: 700;
        margin-top: 6px;
    }

    .metric-note {
        color: var(--green);
        font-size: 11px;
        margin-top: 2px;
    }

    .panel {
        background: rgba(16,30,48,.88);
        border: 1px solid var(--line);
        border-radius: 17px;
        padding: 18px 20px;
        margin-bottom: 14px;
    }

    .section-kicker {
        color: var(--green);
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }

    .big-number {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 32px;
        font-weight: 700;
        color: white;
    }

    .muted {
        color: var(--muted);
    }

    .pill {
        display: inline-block;
        padding: 4px 9px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 700;
        background: rgba(50,230,161,.12);
        color: var(--green);
        border: 1px solid rgba(50,230,161,.22);
    }

    .captain-card {
        background: linear-gradient(
            135deg,
            rgba(24,67,62,.96),
            rgba(16,37,53,.98)
        );
        border: 1px solid rgba(50,230,161,.32);
        border-radius: 20px;
        padding: 22px;
    }

    .captain-label {
        color: var(--green);
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 1.5px;
    }

    .captain-name {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 30px;
        font-weight: 700;
        color: white;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 7px;
        background: transparent;
        flex-wrap: wrap;
    }

    .stTabs [data-baseweb="tab"] {
        background: #102035;
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 9px 14px;
        color: #b7c6d6;
    }

    .stTabs [aria-selected="true"] {
        background: rgba(50,230,161,.13) !important;
        color: var(--green) !important;
        border-color: rgba(50,230,161,.38) !important;
    }

    .stButton button,
    .stDownloadButton button {
        border-radius: 10px;
        border: 1px solid rgba(50,230,161,.35);
        background: rgba(50,230,161,.12);
        color: #baffdf;
        font-weight: 700;
    }

    .stButton button:hover,
    .stDownloadButton button:hover {
        border-color: var(--green);
        color: white;
    }

    [data-testid="stDataFrame"],
    [data-testid="stTable"] {
        border: 1px solid var(--line);
        border-radius: 12px;
        overflow: hidden;
    }

    div[data-testid="stAlert"] {
        border-radius: 12px;
    }

    footer {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

@st.cache_data(ttl=900, show_spinner=False)
def get_json(endpoint):
    response = requests.get(
        f"{BASE_URL}/{endpoint}",
        timeout=20
    )
    response.raise_for_status()
    return response.json()


def safe_get(endpoint, default=None):
    try:
        return get_json(endpoint)
    except requests.RequestException as exc:
        st.warning(
            f"Could not load FPL data from {endpoint}. "
            f"Please refresh later. Details: {exc}"
        )
        return default


def metric_card(label, value, note=""):
    st.markdown(
        f"""
        <div class="metric">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(kicker, title, subtitle=None):
    st.markdown(
        f'<div class="section-kicker">{kicker}</div>',
        unsafe_allow_html=True
    )
    st.subheader(title)

    if subtitle:
        st.caption(subtitle)


def money(value):
    return f"£{float(value):.1f}m"


def player_name(player):
    return player.get("web_name", "Unknown")


def team_name(player, teams):
    return teams.get(player.get("team"), "—")


def position_name(player):
    return {
        1: "GK",
        2: "DEF",
        3: "MID",
        4: "FWD"
    }.get(player.get("element_type"), "—")


def player_xp(player, fixtures, teams_by_id):
    try:
        return float(
            player_fixture_xp(
                player,
                fixtures,
                teams_by_id
            )
        )
    except Exception:
        try:
            return float(estimate_xp(player))
        except Exception:
            return 0.0


def make_player_frame(players, teams, fixtures, teams_by_id):
    rows = []

    for player in players:
        rows.append({
            "Player": player_name(player),
            "Club": team_name(player, teams),
            "Pos": position_name(player),
            "Price": float(player.get("now_cost", 0)) / 10,
            "xP": round(
                player_xp(player, fixtures, teams_by_id),
                2
            ),
            "Form": round(num(player.get("form")), 1),
            "Minutes": int(player.get("minutes", 0)),
            "Selected %": round(
                num(player.get("selected_by_percent")),
                1
            ),
            "Status": player.get("status", "a"),
        })

    return pd.DataFrame(rows)


def get_current_gameweek(events):
    current = next(
        (event for event in events if event.get("is_current")),
        None
    )

    if current:
        return current

    next_event = next(
        (event for event in events if event.get("is_next")),
        None
    )

    if next_event:
        return next_event

    finished = [
        event for event in events
        if event.get("finished")
    ]

    if finished:
        return finished[-1]

    return {
        "id": 1,
        "name": "Gameweek 1"
    }


def get_entry_data(team_id, gw):
    profile = safe_get(f"entry/{team_id}/")

    if not profile:
        return None, None, None

    picks_data = safe_get(
        f"entry/{team_id}/event/{gw}/picks/"
    )

    history = safe_get(
        f"entry/{team_id}/history/"
    )

    return profile, picks_data, history


def fixture_label(fixture, teams_by_id, team_id):
    is_home = fixture.get("team_h") == team_id

    opponent_id = (
        fixture.get("team_a")
        if is_home
        else fixture.get("team_h")
    )

    opponent = teams_by_id.get(
        opponent_id,
        {}
    ).get("short_name", "TBC")

    return f"{opponent} ({'H' if is_home else 'A'})"


def player_fixture_rows(
    player,
    fixtures,
    teams_by_id,
    count=5
):
    team_id = player.get("team")

    upcoming = [
        fixture for fixture in fixtures
        if not fixture.get("finished")
        and (
            fixture.get("team_h") == team_id
            or fixture.get("team_a") == team_id
        )
    ]

    upcoming.sort(
        key=lambda fixture: (
            fixture.get("event") or 99,
            fixture.get("kickoff_time") or ""
        )
    )

    return [
        fixture_label(fixture, teams_by_id, team_id)
        for fixture in upcoming[:count]
    ]


def fdr_colour(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""

    colours = {
        1: "background-color: #155e48; color: white",
        2: "background-color: #287b5d; color: white",
        3: "background-color: #8b7835; color: white",
        4: "background-color: #9b523c; color: white",
        5: "background-color: #873b4a; color: white",
    }

    return colours.get(value, "")


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## ⚽ FPL AI Analyst")
    st.caption(
        "Your weekly Fantasy Premier League command centre"
    )

    team_id_input = st.text_input(
        "Your FPL Team ID",
        value="",
        placeholder="Enter your FPL Team ID"
    )

    if st.button(
        "↻ Refresh FPL data",
        use_container_width=True
    ):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    st.caption(
        "Data source: Official Fantasy Premier League API"
    )

    st.caption(
        "All times shown in Malaysia time (MYT)."
    )


if not team_id_input.strip():
    st.title("⚽ FPL AI Analyst")
    st.info(
        "Enter your FPL Team ID in the sidebar to access "
        "your personal dashboard."
    )
    st.stop()

try:
    team_id = int(team_id_input.strip())

    if team_id <= 0:
        raise ValueError

except ValueError:
    st.error("Please enter a valid numeric FPL Team ID.")
    st.stop()


# ============================================================
# LOAD FPL DATA
# ============================================================

with st.spinner("Loading the latest Fantasy Premier League data..."):
    bootstrap = safe_get("bootstrap-static/")
    fixtures = safe_get("fixtures/", [])

if not bootstrap:
    st.error(
        "The FPL API is temporarily unavailable. "
        "Please refresh the page in a few minutes."
    )
    st.stop()


elements = bootstrap.get("elements", [])
teams_list = bootstrap.get("teams", [])
events = bootstrap.get("events", [])

elements_by_id = {
    player["id"]: player
    for player in elements
}

teams_by_id = {
    team["id"]: team
    for team in teams_list
}

teams = {
    team["id"]: team.get(
        "name",
        team.get("short_name", "—")
    )
    for team in teams_list
}

gw_info = get_current_gameweek(events)
gw = int(gw_info.get("id", 1))

profile, picks_data, history = get_entry_data(
    team_id,
    gw
)

if not profile:
    st.error(
        "Could not find this FPL team. "
        "Check that your Team ID is correct."
    )
    st.stop()


if not picks_data or not picks_data.get("picks"):
    st.warning(
        f"Your Gameweek {gw} squad data is not available yet. "
        "You can still use the league-wide analysis."
    )
    picks = []
else:
    picks = picks_data["picks"]


picked_players = [
    elements_by_id[pick["element"]]
    for pick in picks
    if pick.get("element") in elements_by_id
]

squad_ids = {
    player["id"]
    for player in picked_players
}

squad_df = make_player_frame(
    picked_players,
    teams,
    fixtures,
    teams_by_id
)

all_df = make_player_frame(
    elements,
    teams,
    fixtures,
    teams_by_id
)


# ============================================================
# MANAGER INFORMATION
# ============================================================

manager_name = (
    profile.get("player_first_name", "")
    + " "
    + profile.get("player_last_name", "")
).strip()

team_name_text = profile.get("name", "FPL Team")

overall_rank = profile.get("summary_overall_rank")

bank = (
    float(profile.get("last_deadline_bank", 0))
    / 10
)

team_value = (
    float(profile.get("last_deadline_value", 0))
    / 10
)

points = profile.get(
    "summary_overall_points",
    0
)

deadline = gw_info.get("deadline_time")
deadline_text = "Not announced"

if deadline:
    try:
        deadline_dt = datetime.fromisoformat(
            deadline.replace("Z", "+00:00")
        ).astimezone(MY_TZ)

        deadline_text = deadline_dt.strftime(
            "%d %b %Y, %I:%M %p MYT"
        )

    except ValueError:
        deadline_text = str(deadline)


current_year = datetime.now(MY_TZ).year


# ============================================================
# HERO HEADER
# ============================================================

st.markdown(
    f"""
    <div class="hero">
        <div class="eyebrow">
            FPL MANAGER DASHBOARD
        </div>

        <div class="hero-title">
            {team_name_text}
        </div>

        <div class="hero-sub">
            {manager_name}
            &nbsp;·&nbsp;
            Team ID {team_id}
            &nbsp;·&nbsp;
            {gw_info.get('name', f'Gameweek {gw}')}
        </div>

        <div style="margin-top:16px">
            <span class="pill">
                NEXT DEADLINE: {deadline_text}
            </span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DASHBOARD METRICS
# ============================================================

m1, m2, m3, m4 = st.columns(4)

with m1:
    metric_card(
        "Overall rank",
        f"{overall_rank:,}" if overall_rank else "—",
        "Current season rank"
    )

with m2:
    metric_card(
        "Team value",
        money(team_value),
        "Latest reported value"
    )

with m3:
    metric_card(
        "Money in bank",
        money(bank),
        "Available transfer budget"
    )

with m4:
    metric_card(
        "Overall points",
        f"{points:,}",
        "Season total"
    )


# ============================================================
# APPLICATION TABS
# ============================================================

tabs = st.tabs([
    "Overview",
    "Captain & xP",
    "Transfers",
    "Wildcard / Free Hit",
    "Differentials",
    "Fixtures & Rotation",
    "Weekly Reports",
])


# ============================================================
# TAB 1 — OVERVIEW
# ============================================================

with tabs[0]:

    section_title(
        "YOUR TEAM",
        "Squad overview",
        "A quick view of your current squad, player availability "
        "and upcoming points potential."
    )

    if not picks:

        st.info(
            "Your squad picks are not currently available "
            "from the FPL API."
        )

    else:

        starters = [
            pick for pick in picks
            if pick.get("position", 99) <= 11
        ]

        captain_id = next(
            (
                pick.get("element")
                for pick in picks
                if pick.get("is_captain")
            ),
            None
        )

        vice_id = next(
            (
                pick.get("element")
                for pick in picks
                if pick.get("is_vice_captain")
            ),
            None
        )

        flagged_players = [
            player for player in picked_players
            if player.get("status") not in ("a", "")
        ]

        squad_xp = sum(
            player_xp(player, fixtures, teams_by_id)
            for player in picked_players
        )

        c1, c2, c3 = st.columns(3)

        with c1:
            metric_card(
                "Starting XI",
                str(len(starters)),
                "Selected for this Gameweek"
            )

        with c2:
            metric_card(
                "Squad xP",
                f"{squad_xp:.1f}",
                "Model estimate"
            )

        with c3:
            metric_card(
                "Availability flags",
                str(len(flagged_players)),
                "Players with non-available status"
            )

        rows = []

        for pick in picks:

            player = elements_by_id.get(
                pick.get("element")
            )

            if not player:
                continue

            role = ""

            if player["id"] == captain_id:
                role = "C"

            elif player["id"] == vice_id:
                role = "VC"

            rows.append({
                "Slot": pick.get("position"),
                "Player": player_name(player),
                "Club": team_name(player, teams),
                "Pos": position_name(player),
                "Price": money(
                    player.get("now_cost", 0) / 10
                ),
                "xP": round(
                    player_xp(
                        player,
                        fixtures,
                        teams_by_id
                    ),
                    2
                ),
                "Role": role,
                "Availability": player.get(
                    "status",
                    "a"
                ).upper(),
            })

        st.markdown("#### Your current squad")

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True
        )

        if flagged_players:
            st.warning(
                "Availability check: "
                + ", ".join(
                    player_name(player)
                    for player in flagged_players
                )
            )

        if history and history.get("current"):

            current_history = history["current"]

            if current_history:

                latest = current_history[-1]

                st.markdown(
                    "#### Recent Gameweek performance"
                )

                a, b, c = st.columns(3)

                with a:
                    metric_card(
                        "Last GW points",
                        str(latest.get("points", "—")),
                        "Points scored"
                    )

                with b:
                    metric_card(
                        "Transfers",
                        str(
                            latest.get(
                                "event_transfers",
                                0
                            )
                        ),
                        "Made that Gameweek"
                    )

                with c:
                    metric_card(
                        "Transfer cost",
                        str(
                            latest.get(
                                "event_transfers_cost",
                                0
                            )
                        ),
                        "Points hit"
                    )


# ============================================================
# TAB 2 — CAPTAIN & EXPECTED POINTS
# ============================================================

with tabs[1]:

    section_title(
        "DECISION SUPPORT",
        "Captain & expected points",
        "Captaincy recommendations prioritise your own squad."
    )

    if not picked_players:

        st.info(
            "Your current squad picks are not available."
        )

    else:

        squad_ranked = sorted(
            picked_players,
            key=lambda player: player_xp(
                player,
                fixtures,
                teams_by_id
            ),
            reverse=True
        )

        captain = squad_ranked[0]

        vice = (
            squad_ranked[1]
            if len(squad_ranked) > 1
            else captain
        )

        current_captain = next(
            (
                elements_by_id.get(pick["element"])
                for pick in picks
                if pick.get("is_captain")
            ),
            None
        )

        left, right = st.columns([1.25, 1])

        with left:

            captain_xp = player_xp(
                captain,
                fixtures,
                teams_by_id
            )

            st.markdown(
                f"""
                <div class="captain-card">
                    <div class="captain-label">
                        ★ AI CAPTAIN PICK
                    </div>

                    <div class="captain-name">
                        {player_name(captain)}
                    </div>

                    <div style="color:#c7e8dc">
                        {team_name(captain, teams)}
                        · {position_name(captain)}
                        · {money(captain.get('now_cost', 0) / 10)}
                    </div>

                    <div style="
                        font-size:38px;
                        font-weight:800;
                        color:#fff;
                        margin-top:14px
                    ">
                        {captain_xp:.2f}

                        <span style="
                            font-size:14px;
                            color:#a8c9bc
                        ">
                            projected xP
                        </span>
                    </div>

                    <div style="
                        color:#b9d7ce;
                        font-size:12px;
                        margin-top:5px
                    ">
                        Current captain:
                        {player_name(current_captain)
                        if current_captain else 'Not set'}

                        · Suggested vice:
                        {player_name(vice)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with right:

            st.markdown(
                '<div class="panel">',
                unsafe_allow_html=True
            )

            st.markdown("**Captaincy shortlist**")

            for index, player in enumerate(
                squad_ranked[:5],
                1
            ):

                xp = player_xp(
                    player,
                    fixtures,
                    teams_by_id
                )

                st.write(
                    f"**{index}. {player_name(player)}** "
                    f"— {xp:.2f} xP · "
                    f"{team_name(player, teams)}"
                )

            st.caption(
                "This is a model estimate, not a guarantee. "
                "Check injuries, press conferences and "
                "likely minutes before the deadline."
            )

            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("#### Your squad — xP ranking")

        captain_df = make_player_frame(
            squad_ranked,
            teams,
            fixtures,
            teams_by_id
        )

        captain_display = captain_df[
            [
                "Player",
                "Club",
                "Pos",
                "xP",
                "Form",
                "Minutes"
            ]
        ]

        st.bar_chart(
            captain_display.set_index("Player")[["xP"]],
            horizontal=True,
            height=320
        )

        st.dataframe(
            captain_display,
            use_container_width=True,
            hide_index=True
        )

    st.markdown(
        "#### Best projected players across the game"
    )

    global_top = (
        all_df[
            all_df["Minutes"] >= 180
        ]
        .sort_values("xP", ascending=False)
        .head(15)
    )

    st.dataframe(
        global_top,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# TAB 3 — TRANSFER PLANNER
# ============================================================

with tabs[2]:

    section_title(
        "TRANSFER MARKET",
        "Transfer planner",
        "Compare an outgoing player with same-position replacements."
    )

    if not picked_players:

        st.info(
            "Your squad is required to use the transfer planner."
        )

    else:

        player_options = {
            (
                f"{player_name(player)} · "
                f"{team_name(player, teams)} · "
                f"{money(player.get('now_cost', 0) / 10)}"
            ): player["id"]

            for player in picked_players
        }

        selected_label = st.selectbox(
            "Select a player to replace",
            list(player_options.keys())
        )

        outgoing = elements_by_id[
            player_options[selected_label]
        ]

        position = outgoing.get("element_type")

        outgoing_cost = (
            float(outgoing.get("now_cost", 0)) / 10
        )

        budget_for_replacement = (
            outgoing_cost + bank
        )

        incoming_pool = [
            player
            for player in elements

            if player.get("element_type") == position

            and player.get("id") != outgoing.get("id")

            and player.get("team") != outgoing.get("team")

            and (
                float(player.get("now_cost", 0)) / 10
                <= budget_for_replacement
            )

            and player.get("status") not in ("u", "s")

            and int(player.get("minutes", 0)) >= 90
        ]

        incoming_pool.sort(
            key=lambda player: player_xp(
                player,
                fixtures,
                teams_by_id
            ),
            reverse=True
        )

        st.markdown(
            f"""
            <div class="panel">
                <span class="section-kicker">
                    OUTGOING PLAYER
                </span>

                <div class="big-number">
                    {player_name(outgoing)}
                </div>

                <span class="muted">
                    {team_name(outgoing, teams)}
                    · {position_name(outgoing)}
                    · Current price {money(outgoing_cost)}
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

        if not incoming_pool:

            st.warning(
                "No suitable same-position replacements "
                "were found within the estimated budget."
            )

        else:

            comparison = []

            outgoing_xp = player_xp(
                outgoing,
                fixtures,
                teams_by_id
            )

            for player in incoming_pool[:12]:

                xp = player_xp(
                    player,
                    fixtures,
                    teams_by_id
                )

                price = (
                    float(player.get("now_cost", 0)) / 10
                )

                comparison.append({
                    "Player": player_name(player),
                    "Club": team_name(player, teams),
                    "Price": money(price),
                    "Budget change": money(
                        outgoing_cost - price
                    ),
                    "xP": round(xp, 2),
                    "xP gain": round(
                        xp - outgoing_xp,
                        2
                    ),
                    "Form": round(
                        num(player.get("form")),
                        1
                    ),
                    "Selected %": round(
                        num(
                            player.get(
                                "selected_by_percent"
                            )
                        ),
                        1
                    ),
                })

            transfer_df = pd.DataFrame(comparison)

            st.markdown(
                "#### Recommended replacements"
            )

            st.dataframe(
                transfer_df,
                use_container_width=True,
                hide_index=True
            )

            best = comparison[0]

            st.success(
                f"Top projected replacement: "
                f"{best['Player']} ({best['Club']}) "
                f"— xP gain {best['xP gain']:+.2f}."
            )

        st.caption(
            "Budget estimate uses the outgoing player's current "
            "listed price. Your actual selling price may differ "
            "because of price changes and purchase price."
        )


# ============================================================
# TAB 4 — WILDCARD / FREE HIT
# ============================================================

with tabs[3]:

    section_title(
        "SQUAD BUILDER",
        "Wildcard / Free Hit planner",
        "Build a balanced 15-player squad using your selected budget."
    )

    mode = st.radio(
        "Planning mode",
        ["Wildcard", "Free Hit"],
        horizontal=True
    )

    available_budget = st.number_input(
        "Total squad budget (£m)",
        min_value=80.0,
        max_value=120.0,
        value=100.0,
        step=0.5
    )

    if st.button(
        "Build recommended squad",
        type="primary"
    ):

        try:

            generated = build_squad(
                elements,
                available_budget
            )

            if not generated:

                st.warning(
                    "The squad builder could not find "
                    "a squad with the available data and budget."
                )

            else:

                st.session_state["generated_squad"] = generated

                st.session_state["generated_mode"] = mode

                st.session_state["generated_budget"] = (
                    available_budget
                )

        except Exception as exc:

            st.error(
                f"Squad builder encountered an issue: {exc}"
            )

    generated = st.session_state.get(
        "generated_squad"
    )

    if generated:

        generated_players = []

        for item in generated:

            if isinstance(item, dict):

                generated_players.append(item)

            elif isinstance(item, int):

                if item in elements_by_id:

                    generated_players.append(
                        elements_by_id[item]
                    )

        if generated_players:

            total_cost = sum(
                float(player.get("now_cost", 0)) / 10
                for player in generated_players
            )

            total_xp = sum(
                player_xp(
                    player,
                    fixtures,
                    teams_by_id
                )
                for player in generated_players
            )

            x1, x2, x3 = st.columns(3)

            with x1:

                metric_card(
                    "Players found",
                    f"{len(generated_players)}/15",
                    "Squad completeness"
                )

            with x2:

                metric_card(
                    "Squad cost",
                    money(total_cost),
                    f"Budget £{st.session_state.get('generated_budget', available_budget):.1f}m"
                )

            with x3:

                metric_card(
                    "Combined xP",
                    f"{total_xp:.1f}",
                    "Sum of player projections"
                )

            if len(generated_players) < 15:

                st.warning(
                    "The squad builder returned fewer than "
                    "15 players. Treat this as a shortlist, "
                    "not a valid final squad."
                )

            try:

                xi = best_starting_xi(
                    generated_players
                )

                if xi:

                    st.markdown(
                        "#### Suggested starting XI"
                    )

                    xi_df = make_player_frame(
                        xi,
                        teams,
                        fixtures,
                        teams_by_id
                    )

                    st.dataframe(
                        xi_df,
                        use_container_width=True,
                        hide_index=True
                    )

            except Exception as exc:

                st.caption(
                    f"Starting XI optimisation unavailable: {exc}"
                )

            st.markdown("#### Full squad")

            full_df = make_player_frame(
                generated_players,
                teams,
                fixtures,
                teams_by_id
            )

            st.dataframe(
                full_df,
                use_container_width=True,
                hide_index=True
            )

            st.caption(
                f"{st.session_state.get('generated_mode', mode)} "
                "planning model. Verify formation, club limits, "
                "prices and player availability before confirming."
            )


# ============================================================
# TAB 5 — DIFFERENTIALS
# ============================================================

with tabs[4]:

    section_title(
        "LOW-OWNERSHIP PICKS",
        "Differential watchlist",
        "Find lower-owned players with useful projected returns."
    )

    ownership_limit = st.slider(
        "Maximum ownership (%)",
        min_value=1,
        max_value=30,
        value=10
    )

    min_minutes = st.slider(
        "Minimum minutes played",
        min_value=0,
        max_value=2000,
        value=360,
        step=90
    )

    differential_df = all_df[
        (all_df["Selected %"] <= ownership_limit)
        & (all_df["Minutes"] >= min_minutes)
        & (all_df["Status"] == "a")
    ].sort_values(
        "xP",
        ascending=False
    ).head(25)

    if differential_df.empty:

        st.info(
            "No players match these filters. "
            "Try increasing the ownership limit or "
            "lowering minimum minutes."
        )

    else:

        st.dataframe(
            differential_df,
            use_container_width=True,
            hide_index=True
        )

        st.markdown(
            "#### Top differential projections"
        )

        st.bar_chart(
            differential_df.head(10).set_index("Player")[["xP"]],
            horizontal=True,
            height=300
        )


# ============================================================
# TAB 6 — FIXTURES & ROTATION
# ============================================================

with tabs[5]:

    section_title(
        "FIXTURE INTELLIGENCE",
        "Fixtures & rotation",
        "Compare upcoming fixture difficulty and identify "
        "teams with favourable short-term runs."
    )

    upcoming_fixtures = [
        fixture
        for fixture in fixtures
        if not fixture.get("finished")
        and fixture.get("event") is not None
    ]

    upcoming_fixtures.sort(
        key=lambda fixture: (
            fixture.get("event") or 99,
            fixture.get("kickoff_time") or ""
        )
    )

    next_events = sorted({
        fixture["event"]
        for fixture in upcoming_fixtures
    })[:5]

    team_rows = []
    fdr_rows = []

    for team in teams_list:

        row = {
            "Team": team.get(
                "name",
                team.get("short_name", "")
            )
        }

        fdr_row = {
            "Team": team.get(
                "name",
                team.get("short_name", "")
            )
        }

        for event_id in next_events:

            game = next(
                (
                    fixture
                    for fixture in upcoming_fixtures
                    if fixture.get("event") == event_id
                    and (
                        fixture.get("team_h") == team["id"]
                        or fixture.get("team_a") == team["id"]
                    )
                ),
                None
            )

            column = f"GW{event_id}"

            if not game:

                row[column] = "—"
                fdr_row[column] = None
                continue

            is_home = game.get("team_h") == team["id"]

            opponent_id = (
                game.get("team_a")
                if is_home
                else game.get("team_h")
            )

            opponent = teams_by_id.get(
                opponent_id,
                {}
            ).get("short_name", "TBC")

            fdr = (
                game.get("team_h_difficulty")
                if is_home
                else game.get("team_a_difficulty")
            )

            row[column] = (
                f"{opponent} {'H' if is_home else 'A'}"
            )

            fdr_row[column] = int(fdr or 3)

        team_rows.append(row)
        fdr_rows.append(fdr_row)

    if team_rows and next_events:

        fixture_df = pd.DataFrame(team_rows)

        fdr_df = pd.DataFrame(fdr_rows)

        visible_columns = (
            ["Team"]
            + [f"GW{event_id}" for event_id in next_events]
        )

        display_df = fixture_df[visible_columns]

        # Build a matching style matrix so each fixture cell
        # receives the correct official FDR colour.
        style_matrix = pd.DataFrame(
            "",
            index=display_df.index,
            columns=display_df.columns
        )

        for row_index in display_df.index:

            for event_id in next_events:

                column = f"GW{event_id}"

                style_matrix.loc[
                    row_index,
                    column
                ] = fdr_colour(
                    fdr_df.loc[row_index, column]
                )

        styled_fixture_df = display_df.style.apply(
            lambda _: style_matrix,
            axis=None
        )

        st.markdown(
            "#### Next five Gameweeks"
        )

        st.dataframe(
            styled_fixture_df,
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            "Fixture labels show opponent and home/away. "
            "Green = easier fixture; red = harder fixture."
        )

    else:

        st.info(
            "Upcoming fixtures are not currently available."
        )

    # --------------------------------------------------------
    # BEST FIXTURE RUNS
    # --------------------------------------------------------

    st.markdown(
        "#### Best short-term fixture runs"
    )

    run_rows = []

    for team in teams_list:

        fdr_values = []
        labels = []

        for event_id in next_events[:3]:

            game = next(
                (
                    fixture
                    for fixture in upcoming_fixtures
                    if fixture.get("event") == event_id
                    and (
                        fixture.get("team_h") == team["id"]
                        or fixture.get("team_a") == team["id"]
                    )
                ),
                None
            )

            if not game:
                continue

            is_home = game.get("team_h") == team["id"]

            fdr = (
                game.get("team_h_difficulty")
                if is_home
                else game.get("team_a_difficulty")
            )

            opponent_id = (
                game.get("team_a")
                if is_home
                else game.get("team_h")
            )

            opponent = teams_by_id.get(
                opponent_id,
                {}
            ).get("short_name", "TBC")

            labels.append(
                f"{opponent} {'H' if is_home else 'A'}"
            )

            fdr_values.append(
                int(fdr or 3)
            )

        if fdr_values:

            run_rows.append({
                "Team": team.get("name"),
                "Avg FDR": round(
                    sum(fdr_values) / len(fdr_values),
                    2
                ),
                "Fixtures": " · ".join(labels)
            })

    if run_rows:

        run_df = (
            pd.DataFrame(run_rows)
            .sort_values("Avg FDR")
            .head(10)
        )

        st.dataframe(
            run_df,
            use_container_width=True,
            hide_index=True
        )

    # --------------------------------------------------------
    # YOUR SQUAD FIXTURES
    # --------------------------------------------------------

    if picked_players:

        st.markdown(
            "#### Your squad's next fixtures"
        )

        rotation_rows = []

        for player in picked_players:

            rotation_rows.append({
                "Player": player_name(player),
                "Club": team_name(player, teams),
                "Pos": position_name(player),
                "Next fixtures": " · ".join(
                    player_fixture_rows(
                        player,
                        fixtures,
                        teams_by_id,
                        3
                    )
                ) or "No fixture found",
                "xP": round(
                    player_xp(
                        player,
                        fixtures,
                        teams_by_id
                    ),
                    2
                )
            })

        rotation_df = (
            pd.DataFrame(rotation_rows)
            .sort_values("xP", ascending=False)
        )

        st.dataframe(
            rotation_df,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# TAB 7 — WEEKLY REPORTS
# ============================================================

with tabs[6]:

    section_title(
        "WEEKLY INTELLIGENCE",
        "Weekly reports",
        "Read the latest automatically generated FPL reports."
    )

    report_files = (
        sorted(
            REPORTS_DIR.glob("GW*_report.md"),
            reverse=True
        )
        if REPORTS_DIR.exists()
        else []
    )

    if not report_files:

        st.info(
            "No weekly reports found yet. "
            "Once your GitHub Actions workflow generates "
            "a report and commits it to the reports folder, "
            "it will appear here."
        )

    else:

        selected_report = st.selectbox(
            "Choose a report",
            report_files,
            format_func=lambda path: (
                path.stem.replace("_", " ")
            )
        )

        try:

            report_text = selected_report.read_text(
                encoding="utf-8"
            )

            st.markdown(report_text)

            st.download_button(
                "Download this report",
                data=report_text,
                file_name=selected_report.name,
                mime="text/markdown"
            )

        except OSError as exc:

            st.error(
                f"Could not read the selected report: {exc}"
            )


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    """
    <div style="
        text-align:center;
        color:#71869c;
        font-size:11px;
        padding:22px 0 8px
    ">
        FPL AI Analyst · Unofficial fan-made tool
        · Always verify decisions in the official FPL game
    </div>
    """,
    unsafe_allow_html=True
)
