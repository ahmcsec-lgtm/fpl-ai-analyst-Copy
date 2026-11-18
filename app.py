
import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from fpl_engine import (
    num,
    player_projection,
    player_fixture_xp,
    player_horizon_xp,
    fixture_lookup,
    build_squad,
    best_starting_xi,
    bench_order,
    suggest_transfers,
    optimise_multi_gw_transfers,
    POSITION_NAMES,
)

# =========================================================
# CONFIGURATION
# =========================================================

API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "AJK-Bola-Wawei-AI/2.0"}
MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")

st.set_page_config(
    page_title="AJK Bola Wawei AI",
    page_icon="⚽",
    layout="wide",
)

# =========================================================
# STYLE
# =========================================================

st.markdown(
    """
    <style>
    .block-container {padding-top:1.2rem;max-width:1600px;}
    [data-testid="stMetric"] {
        background:rgba(120,130,145,.09);
        padding:12px 14px;border-radius:12px;
    }
    .small-note {color:#8b93a1;font-size:.84rem;}
    .section-note {
        padding:11px 14px;border-radius:10px;
        background:rgba(120,130,145,.08);margin-bottom:12px;
    }
    .pitch {
        background:repeating-linear-gradient(
            0deg,#176b42,#176b42 70px,
            #1b7549 70px,#1b7549 140px
        );
        border:3px solid rgba(255,255,255,.75);
        border-radius:15px;padding:15px 8px;color:white;
        width:100%;box-sizing:border-box;
    }
    .pitch-row {
        display:flex;justify-content:space-evenly;
        align-items:center;flex-wrap:wrap;gap:9px;margin:14px 0;
    }
    .pitch-player {
        background:rgba(0,0,0,.30);
        border:1px solid rgba(255,255,255,.30);
        border-radius:10px;min-width:85px;max-width:125px;
        padding:8px 6px;text-align:center;font-size:12px;
        line-height:1.35;box-sizing:border-box;
    }
    .pitch-player strong {display:block;color:white;font-size:12px;}
    .pitch-player small {display:block;color:#e1f5e8;font-size:10px;}
    .captain {
        background:#e9bd35;color:#222;border-radius:5px;
        padding:1px 5px;font-weight:bold;margin-left:3px;
    }
    .vice {
        background:#d9e4ef;color:#222;border-radius:5px;
        padding:1px 5px;font-weight:bold;margin-left:3px;
    }
    .bench-card {
        background:rgba(120,130,145,.10);
        border:1px solid rgba(120,130,145,.25);
        border-radius:9px;padding:10px;text-align:center;font-size:12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# HELPERS
# =========================================================

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


def malaysia_time(value, fmt="%d %b %Y, %H:%M"):
    if not value:
        return "TBC"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(MY_TZ).strftime(fmt)
    except Exception:
        return "TBC"


def status_label(player):
    labels = {
        "a": "Available", "d": "Doubtful", "i": "Injured",
        "s": "Suspended", "u": "Unavailable", "n": "Not available",
    }
    label = labels.get(player.get("status"), "Unknown")
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        label += f" · {chance}% chance"
    return label


def fx_text(fixtures_for_player):
    return ", ".join(x[0] for x in fixtures_for_player) if fixtures_for_player else "Blank"


def report_files():
    folder = Path("reports")
    return sorted(folder.glob("GW*_report.md"), reverse=True) if folder.exists() else []


def gw_xp(player, gw, fx_map, risk="Balanced", minute_overrides=None):
    return player_fixture_xp(
        player,
        fx_map.get((player["team"], gw), []),
        risk=risk,
        minutes_override=(minute_overrides or {}).get(player["id"]),
    )


def horizon_xp(player, gameweeks, fx_map, risk="Balanced", minute_overrides=None):
    return player_horizon_xp(
        player,
        gameweeks,
        fx_map,
        risk=risk,
        minutes_overrides=minute_overrides or {},
    )


def render_pitch(xi, gw, fx_map, captain_id=None, vice_id=None, bench=None, risk="Balanced"):
    if not xi:
        st.info("No starting XI is available.")
        return

    groups = {4: [], 3: [], 2: [], 1: []}
    for player in xi:
        groups.setdefault(player.get("element_type"), []).append(player)

    rows = []
    for pos in (4, 3, 2, 1):
        cards = []
        for player in groups.get(pos, []):
            pid = player["id"]
            name = html.escape(str(player.get("web_name", "Player")))
            club = html.escape(str(player.get("team_name", "")))
            fixture = html.escape(fx_text(fx_map.get((player["team"], gw), [])))
            xp = gw_xp(player, gw, fx_map, risk)

            badge = ""
            if pid == captain_id:
                badge = '<span class="captain">C</span>'
            elif pid == vice_id:
                badge = '<span class="vice">VC</span>'

            cards.append(
                f'<div class="pitch-player">'
                f'<strong>{name} {badge}</strong>'
                f'<small>{club} · {fixture}</small>'
                f'<small>xP: {xp:.2f}</small></div>'
            )

        if cards:
            rows.append('<div class="pitch-row">' + "".join(cards) + "</div>")

    st.markdown(
        '<div class="pitch">' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )

    if bench:
        st.markdown("**Substitutes — recommended order**")
        cols = st.columns(len(bench))
        for index, player in enumerate(bench):
            xp = gw_xp(player, gw, fx_map, risk)
            fixture = html.escape(fx_text(fx_map.get((player["team"], gw), [])))
            name = html.escape(str(player.get("web_name", "Player")))
            pos = POSITION_NAMES.get(player.get("element_type"), "?")
            card = (
                f'<div class="bench-card"><strong>{index + 1}. {name}</strong><br>'
                f'{pos}<br>{fixture}<br>xP: {xp:.2f}</div>'
            )
            with cols[index]:
                st.markdown(card, unsafe_allow_html=True)


def make_projection_table(players, gameweeks, fx_map, risk, minute_overrides):
    rows = []
    for p in players:
        row = {
            "Player": p.get("web_name", ""),
            "Position": POSITION_NAMES.get(p.get("element_type"), "?"),
            "Club": p.get("team_name", ""),
            "Price": money(p.get("now_cost")),
            "Status": status_label(p),
        }
        total = 0.0
        for gw in gameweeks:
            value = gw_xp(p, gw, fx_map, risk, minute_overrides)
            row[f"GW{gw}"] = value
            total += value
        row["Total xP"] = round(total, 2)
        rows.append(row)
    return pd.DataFrame(rows)


def best_xi(squad, gw, fx_map, risk):
    return best_starting_xi(squad, fx_map, gw, risk=risk)


def choose_captains(xi, gw, fx_map, risk):
    candidates = sorted(
        [p for p in xi if p.get("element_type") != 1],
        key=lambda p: gw_xp(p, gw, fx_map, risk),
        reverse=True,
    )
    captain = candidates[0] if candidates else None
    vice = candidates[1] if len(candidates) > 1 else None
    return captain, vice


def legal_squad_summary(squad, budget):
    cost = sum(int(num(p.get("now_cost"))) for p in squad)
    club_counts = {}
    for p in squad:
        club_counts[p["team"]] = club_counts.get(p["team"], 0) + 1
    positions = {
        pos: sum(p.get("element_type") == pos for p in squad)
        for pos in (1, 2, 3, 4)
    }
    legal = (
        len(squad) == 15
        and positions == {1: 2, 2: 5, 3: 5, 4: 3}
        and max(club_counts.values(), default=0) <= 3
        and cost <= int(round(budget * 10))
    )
    return cost, legal


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.title("⚽ AJK Bola Wawei AI")
    st.caption("Your personal Fantasy Premier League analyst")

    team_id_input = st.text_input(
        "FPL Team ID",
        value="",
        placeholder="Enter your FPL Team ID",
        key="ajk_fpl_team_id",
    )

    risk = st.selectbox(
        "Planning style",
        ["Cautious", "Balanced", "Aggressive"],
        index=1,
        help="Cautious discounts uncertain players. Aggressive is less risk-averse.",
    )

    if st.button("↻ Refresh data", use_container_width=True):
        get_json.clear()
        st.rerun()

    st.divider()
    st.caption("Free public FPL data. No FPL password or paid AI API required.")


if not team_id_input.strip():
    st.title("⚽ AJK Bola Wawei AI")
    st.info("Enter your FPL Team ID in the sidebar to load your personalised analysis.")
    st.markdown(
        """
        **How to find your FPL Team ID**

        1. Open the official Fantasy Premier League website.
        2. Open your team or Points page.
        3. Check the URL.

        Example: `https://fantasy.premierleague.com/entry/1234567/event/1`

        The Team ID in this example is `1234567`.
        """
    )
    st.stop()

if not team_id_input.strip().isdigit() or int(team_id_input) < 1:
    st.error("Please enter a valid numeric FPL Team ID.")
    st.stop()

team_id = int(team_id_input)

# =========================================================
# LOAD DATA
# =========================================================

try:
    with st.spinner("Loading live FPL data..."):
        boot = get_json("bootstrap-static/")
        fixtures = get_json("fixtures/")
        profile = get_json(f"entry/{team_id}/")
except requests.HTTPError as exc:
    st.error("Unable to load this FPL Team ID. Check that the ID is correct and the team profile is public.")
    st.caption(str(exc))
    st.stop()
except requests.RequestException as exc:
    st.error("Unable to connect to the FPL API.")
    st.caption(str(exc))
    st.stop()
except Exception as exc:
    st.error(f"Unable to load FPL data: {exc}")
    st.stop()

players = boot.get("elements", [])
teams = boot.get("teams", [])
events = boot.get("events", [])

player_by_id = {p["id"]: p for p in players}
team_short = {
    t["id"]: t.get("short_name", t.get("name", ""))
    for t in teams
}
team_names = {t["id"]: t.get("name", "") for t in teams}

for player in players:
    player["team_name"] = team_short.get(player.get("team"), "")

fx_map = fixture_lookup(fixtures, teams)

current_event = next((e for e in events if e.get("is_current")), None)
next_event = next((e for e in events if e.get("is_next")), None)

if next_event:
    target_event = next_event
elif current_event and not current_event.get("finished"):
    target_event = current_event
else:
    target_event = next(
        (e for e in events if not e.get("finished") and e.get("deadline_time")),
        None,
    )

if not target_event:
    st.warning("No upcoming Gameweek is currently available.")
    st.stop()

target_gw = int(target_event["id"])
upcoming_events = sorted(
    [
        e for e in events
        if int(e["id"]) >= target_gw
        and not e.get("finished")
        and e.get("deadline_time")
    ],
    key=lambda e: int(e["id"]),
)
available_gws = [int(e["id"]) for e in upcoming_events] or [target_gw]

# Load picks, falling back to the most recent finished GW.
picks_data = None
snapshot_gw = target_gw
try:
    picks_data = get_json(f"entry/{team_id}/event/{target_gw}/picks/")
except Exception:
    finished = [e for e in events if e.get("finished")]
    if finished:
        snapshot_gw = int(finished[-1]["id"])
        try:
            picks_data = get_json(f"entry/{team_id}/event/{snapshot_gw}/picks/")
        except Exception:
            picks_data = None

try:
    history = get_json(f"entry/{team_id}/history/").get("current", [])
except Exception:
    history = []

latest = history[-1] if history else {}
picks = picks_data.get("picks", []) if picks_data else []
squad = [
    player_by_id[pick["element"]]
    for pick in picks
    if pick.get("element") in player_by_id
]
owned_ids = {p["id"] for p in squad}

manager = (
    f"{profile.get('player_first_name', '')} "
    f"{profile.get('player_last_name', '')}"
).strip()
deadline_text = malaysia_time(target_event.get("deadline_time"))

# =========================================================
# SCENARIO CONTROLS
# =========================================================

with st.sidebar:
    st.divider()
    st.subheader("Scenario assumptions")
    st.caption("Optional adjustments for your own planning scenario.")

    default_strength = st.slider(
        "Overall team-strength adjustment",
        min_value=0.85,
        max_value=1.15,
        value=1.0,
        step=0.05,
        help="This adjusts attacking and clean-sheet estimates equally for all clubs.",
    )

    edit_minutes = st.checkbox("Enable player-minute overrides", value=False)

minute_overrides = {}
if edit_minutes and players:
    with st.sidebar:
        st.caption("Choose a player and set their expected minutes.")
        player_options = {
            f"{p['web_name']} ({team_short.get(p['team'], '')})": p
            for p in sorted(players, key=lambda x: x.get("web_name", ""))
        }
        selected_override_name = st.selectbox(
            "Player to adjust",
            ["No adjustment"] + list(player_options.keys()),
        )
        if selected_override_name != "No adjustment":
            selected_override = player_options[selected_override_name]
            default_minutes = min(
                90,
                int(num(selected_override.get("minutes")) /
                    max(1, num(selected_override.get("starts"), 1))),
            )
            override_value = st.slider(
                "Expected minutes",
                0, 90, max(0, default_minutes), 5,
            )
            minute_overrides[selected_override["id"]] = float(override_value)

# The global team-strength adjustment is applied to all players.
# The engine accepts team-specific strengths; this maps the chosen global factor.
team_strengths = {t["id"]: default_strength for t in teams}


def xp(player, gw):
    return player_fixture_xp(
        player,
        fx_map.get((player["team"], gw), []),
        risk=risk,
        minutes_override=minute_overrides.get(player["id"]),
        team_strength=team_strengths.get(player["team"], 1.0),
    )


def total_xp(player, gws):
    return sum(xp(player, gw) for gw in gws)


# =========================================================
# HEADER
# =========================================================

st.title("⚽ AJK Bola Wawei AI")
st.caption(
    f"{profile.get('name', 'FPL Manager')} · {manager} · "
    f"Team ID {team_id} · Target GW{target_gw} · "
    f"Deadline: {deadline_text} Malaysia time"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Overall points", f"{profile.get('summary_overall_points', 0):,}")
c2.metric("Overall rank", f"{profile.get('summary_overall_rank', 0):,}")
c3.metric("Target Gameweek", str(target_gw))
c4.metric(
    "Team value",
    money(latest.get("value", profile.get("last_deadline_value", 0))),
)

# =========================================================
# TABS
# =========================================================

tabs = st.tabs([
    "Overview",
    "Captain & xP",
    "Transfers",
    "Multi-GW Planner",
    "Wildcard / Free Hit",
    "Differentials",
    "Fixtures & Rotation",
    "Weekly Reports",
])

# =========================================================
# TAB 1 — OVERVIEW
# =========================================================

with tabs[0]:
    left, right = st.columns([1.5, 1])

    with left:
        st.subheader("Your squad — pitch view")
        if picks and squad:
            xi = [
                player_by_id[p["element"]]
                for p in picks
                if p.get("position", 99) <= 11
                and p.get("element") in player_by_id
            ]
            bench = [
                player_by_id[p["element"]]
                for p in picks
                if p.get("position", 99) > 11
                and p.get("element") in player_by_id
            ]
            captain_id = next(
                (p["element"] for p in picks if p.get("is_captain")), None
            )
            vice_id = next(
                (p["element"] for p in picks if p.get("is_vice_captain")), None
            )
            render_pitch(
                xi, target_gw, fx_map,
                captain_id, vice_id, bench, risk,
            )
            st.caption(
                f"Squad snapshot: GW{snapshot_gw}. "
                "If target-GW picks are not published, the latest available picks are shown."
            )
        else:
            st.info("Your public squad picks are not available.")

    with right:
        st.subheader("Squad health")
        if squad:
            flagged = [
                p for p in squad
                if p.get("status") != "a"
                or p.get("chance_of_playing_next_round") not in (None, 100)
            ]
            st.metric("Availability concerns", len(flagged))
            for p in flagged:
                st.warning(
                    f"**{p['web_name']}** — {status_label(p)}\n\n"
                    f"{p.get('news') or 'No additional FPL news supplied.'}"
                )
            if not flagged:
                st.success("No major availability concerns detected.")

        st.subheader("Upcoming deadlines")
        for event in upcoming_events[:6]:
            st.write(
                f"**GW{event['id']}** · "
                f"{malaysia_time(event.get('deadline_time'), '%d %b %H:%M')} Malaysia"
            )

# =========================================================
# TAB 2 — CAPTAIN & xP
# =========================================================

with tabs[1]:
    st.subheader("Captain and vice-captain recommendations")
    st.caption(
        "Ranked using estimated xP, expected minutes and availability. "
        "Actual captain points are doubled by FPL."
    )

    captain_rows = []
    for p in players:
        if p.get("element_type") == 1 or p.get("status") in ("i", "s", "u", "n"):
            continue
        projection = player_projection(
            p,
            3,
            minutes_override=minute_overrides.get(p["id"]),
            team_strength=default_strength,
            risk=risk,
        )
        p_xp = xp(p, target_gw)
        captain_rows.append({
            "Player": p["web_name"],
            "Club": team_short.get(p["team"], ""),
            "Fixture": fx_text(fx_map.get((p["team"], target_gw), [])),
            "xP": p_xp,
            "Expected minutes": projection["minutes"],
            "Start estimate": f"{projection['start_probability']:.0%}",
            "Availability": status_label(p),
            "_id": p["id"],
        })

    captain_df = pd.DataFrame(captain_rows).sort_values("xP", ascending=False)
    if not captain_df.empty:
        captain_df.insert(
            0, "Role",
            ["Captain" if i == 0 else "Vice-captain" if i == 1 else "Alternative"
             for i in range(len(captain_df))],
        )
        st.dataframe(
            captain_df.drop(columns="_id").head(15),
            use_container_width=True,
            hide_index=True,
        )
        a, b = st.columns(2)
        a.metric("Top captain xP", f"{captain_df.iloc[0]['xP']:.2f}")
        b.metric(
            "Captain's doubled xP estimate",
            f"{captain_df.iloc[0]['xP'] * 2:.2f}",
        )

    st.divider()
    st.subheader("Player projection explorer")
    position_filter = st.selectbox(
        "Position",
        ["All", "GKP", "DEF", "MID", "FWD"],
        key="xp_position_filter",
    )
    projection_rows = []
    for p in players:
        pos = POSITION_NAMES.get(p.get("element_type"), "?")
        if position_filter != "All" and pos != position_filter:
            continue
        breakdown = player_projection(
            p, 3,
            minutes_override=minute_overrides.get(p["id"]),
            team_strength=default_strength,
            risk=risk,
        )
        projection_rows.append({
            "Player": p["web_name"],
            "Position": pos,
            "Club": team_short.get(p["team"], ""),
            "Price": money(p.get("now_cost")),
            "Fixture": fx_text(fx_map.get((p["team"], target_gw), [])),
            "xP": xp(p, target_gw),
            "Minutes": breakdown["minutes"],
            "Attacking": breakdown["attacking"],
            "Clean sheet": breakdown["clean_sheet"],
            "Bonus estimate": breakdown["bonus"],
            "Status": status_label(p),
        })
    st.dataframe(
        pd.DataFrame(projection_rows).sort_values("xP", ascending=False).head(50),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Projection components are heuristic estimates derived from public FPL statistics. "
        "They are not official FPL or Solio projections."
    )

# =========================================================
# TAB 3 — TRANSFERS
# =========================================================

with tabs[2]:
    st.subheader("Transfer planner")
    st.markdown(
        '<div class="section-note">Compare one-for-one transfer options over a selected '
        '1–6 Gameweek horizon. The recommendations respect position, available budget '
        'and the three-player club limit.</div>',
        unsafe_allow_html=True,
    )

    if not squad or not picks:
        st.info("Transfer planning requires your public squad picks.")
    else:
        horizon = st.slider(
            "Transfer evaluation horizon",
            1, min(6, len(available_gws)),
            min(3, len(available_gws)),
            key="transfer_horizon",
        )
        transfer_gws = available_gws[:horizon]
        bank = int(num(
            latest.get("bank", profile.get("last_deadline_bank", 0))
        ))
        free_transfers = st.number_input(
            "Free transfers available",
            min_value=0, max_value=5, value=1,
            help="Enter your current free-transfer count from FPL.",
        )
        st.metric("Reported bank", money(bank))
        st.caption("Selling prices are read from your latest available picks when provided.")

        squad_for_transfer = []
        for pick in picks:
            p = player_by_id.get(pick.get("element"))
            if p:
                item = dict(p)
                item["selling_price"] = pick.get("selling_price", p.get("now_cost"))
                squad_for_transfer.append(item)

        suggestions = suggest_transfers(
            squad_for_transfer,
            players,
            transfer_gws,
            fx_map,
            bank_tenths=bank,
            free_transfers=int(free_transfers),
            risk=risk,
        )

        if suggestions:
            transfer_rows = []
            for s in suggestions:
                incoming = player_by_id.get(s["in_id"], {})
                outgoing = player_by_id.get(s["out_id"], {})
                transfer_rows.append({
                    "Sell": s["out"],
                    "Buy": s["in"],
                    "Position": s["position"],
                    "Sell price": money(s["sell_price"]),
                    "Buy price": money(s["buy_price"]),
                    "Outgoing xP": s["out_xp"],
                    "Incoming xP": s["in_xp"],
                    "Gross gain": s["gain"],
                    "Net gain after estimated hit": s["net_gain_after_hit"],
                    "Incoming fixtures": " | ".join(
                        f"GW{gw}: {fx_text(fx_map.get((incoming['team'], gw), []))}"
                        for gw in transfer_gws
                    ),
                })
            st.dataframe(
                pd.DataFrame(transfer_rows),
                use_container_width=True,
                hide_index=True,
            )
            best = suggestions[0]
            st.success(
                f"Top one-for-one option: **{best['out']} → {best['in']}** "
                f"({best['gain']:+.2f} gross projected points over {horizon} GWs)."
            )
        else:
            st.info("No legal affordable one-for-one transfer options were found.")

        st.info(
            "This table ranks individual one-for-one transfers. For a multi-transfer "
            "plan with free-transfer rollover and hit calculations, use the "
            "Multi-GW Transfer Optimiser in the Multi-GW Planner tab."
        )

# =========================================================
# TAB 4 — MULTI-GW PLANNER
# =========================================================

with tabs[3]:
    st.subheader("Multi-Gameweek Planner")
    st.markdown(
        '<div class="section-note">Review projected squad points, legal starting XIs, '
        'bench order and captaincy across up to six upcoming Gameweeks.</div>',
        unsafe_allow_html=True,
    )

    max_horizon = min(6, len(available_gws))
    horizon = st.slider(
        "Planning horizon (Gameweeks)",
        1, max_horizon, max_horizon,
        key="multi_gw_horizon",
    )
    planner_gws = available_gws[:horizon]
    st.write("**Selected:** " + ", ".join(f"GW{g}" for g in planner_gws))

    # -----------------------------------------------------
    # MULTI-GW TRANSFER OPTIMISER
    # -----------------------------------------------------
    st.divider()
    st.subheader("Multi-GW Transfer Optimiser")
    st.caption(
        "Searches for a sequence of transfers across your selected Gameweeks. "
        "It accounts for transfer hits, free-transfer rollover, budget and squad legality."
    )

    if not squad or not picks:
        st.info("Your public squad picks are required to run the transfer optimiser.")
    else:
        optimiser_bank = int(num(
            latest.get("bank", profile.get("last_deadline_bank", 0))
        ))

        optimiser_free_transfers = st.number_input(
            "Current free transfers",
            min_value=0,
            max_value=5,
            value=1,
            key="optimiser_free_transfers",
            help="Enter the free transfers currently shown in your FPL account.",
        )

        max_transfers_per_gw = st.slider(
            "Maximum transfers in one Gameweek",
            min_value=0,
            max_value=4,
            value=2,
            key="optimiser_max_transfers",
        )

        beam_width = st.slider(
            "Search width",
            min_value=5,
            max_value=40,
            value=20,
            step=5,
            help="Higher values examine more possible plans but take longer.",
            key="optimiser_beam_width",
        )

        st.metric("Available bank", money(optimiser_bank))

        optimiser_squad = []
        for pick in picks:
            player = player_by_id.get(pick.get("element"))
            if player:
                item = dict(player)
                item["selling_price"] = pick.get(
                    "selling_price",
                    player.get("now_cost"),
                )
                optimiser_squad.append(item)

        optimiser_signature = (
            tuple(planner_gws),
            optimiser_bank,
            int(optimiser_free_transfers),
            risk,
            max_transfers_per_gw,
            beam_width,
            tuple(
                (p["id"], int(num(p.get("selling_price"))))
                for p in optimiser_squad
            ),
            tuple(sorted(minute_overrides.items())),
            tuple(sorted(team_strengths.items())),
        )

        if st.button(
            "Run Multi-GW Transfer Optimiser",
            type="primary",
            use_container_width=True,
            key="run_multi_gw_optimiser",
        ):
            with st.spinner(
                "Searching transfer combinations and evaluating future Gameweeks..."
            ):
                result = optimise_multi_gw_transfers(
                    optimiser_squad,
                    players,
                    planner_gws,
                    fx_map,
                    bank_tenths=optimiser_bank,
                    free_transfers=int(optimiser_free_transfers),
                    risk=risk,
                    minutes_overrides=minute_overrides,
                    team_strengths=team_strengths,
                    max_transfers_per_gw=max_transfers_per_gw,
                    candidates_per_position=8,
                    beam_width=beam_width,
                )

            st.session_state["ajk_multi_gw_optimiser"] = {
                "signature": optimiser_signature,
                "result": result,
            }

        saved_result = st.session_state.get("ajk_multi_gw_optimiser")

        if saved_result and saved_result.get("signature") == optimiser_signature:
            result = saved_result["result"]

            if result.get("error"):
                st.error(result["error"])
            else:
                st.success("Multi-Gameweek transfer plan generated.")

                r1, r2, r3 = st.columns(3)
                r1.metric(
                    "Projected net points",
                    f"{result['total_net_xp']:.2f}",
                )
                r2.metric(
                    "Estimated remaining bank",
                    money(result["final_bank"]),
                )
                r3.metric(
                    "Free transfers after final GW",
                    str(result["final_free_transfers"]),
                )

                st.markdown("**Recommended Gameweek-by-Gameweek plan**")
                plan_rows = []
                transfer_rows = []

                for week in result["plan"]:
                    actions = week["transfers"]
                    transfer_text = (
                        " · ".join(
                            f"{action['out']} → {action['in']}"
                            for action in actions
                        )
                        if actions else "No transfer"
                    )

                    plan_rows.append({
                        "Gameweek": f"GW{week['gameweek']}",
                        "Recommended transfers": transfer_text,
                        "Transfers made": week["transfer_count"],
                        "Free transfers before": week["free_transfers_before"],
                        "Free transfers after": week["free_transfers_after"],
                        "Hit points": week["hit_points"],
                        "Starting XI xP": week["xi_xp"],
                        "Captain": week["captain"],
                        "Captain xP": week["captain_xp"],
                        "Net projected points": week["net_xp"],
                        "Bank after transfers": money(week["bank_after"]),
                    })

                    for action in actions:
                        transfer_rows.append({
                            "Gameweek": f"GW{week['gameweek']}",
                            "Sell": action["out"],
                            "Buy": action["in"],
                            "Position": action["position"],
                            "Sell price": money(action["sell_price"]),
                            "Buy price": money(action["buy_price"]),
                            "Bank after transfer": money(action["bank_after"]),
                        })

                st.dataframe(
                    pd.DataFrame(plan_rows),
                    use_container_width=True,
                    hide_index=True,
                )

                if transfer_rows:
                    st.markdown("**Transfer details**")
                    st.dataframe(
                        pd.DataFrame(transfer_rows),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info(
                        "The optimiser found that keeping your current squad "
                        "was the best plan within the search settings."
                    )

                st.markdown("**Final projected 15-player squad**")
                final_squad_rows = []
                for player in result["final_squad"]:
                    final_squad_rows.append({
                        "Player": player.get("web_name", ""),
                        "Position": POSITION_NAMES.get(
                            player.get("element_type"), "?"
                        ),
                        "Club": team_short.get(player.get("team"), ""),
                        "Price": money(player.get("now_cost")),
                        "Status": status_label(player),
                    })

                st.dataframe(
                    pd.DataFrame(final_squad_rows).sort_values(
                        ["Position", "Player"]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                with st.expander("Search settings and assumptions"):
                    st.write(result["search_settings"])
                    for assumption in result["assumptions"]:
                        st.write(f"- {assumption}")

        elif saved_result:
            st.caption(
                "The previous result was generated with different planning settings. "
                "Run the optimiser again to refresh it."
            )

    if squad:
        squad_table = make_projection_table(
            squad, planner_gws, fx_map, risk, minute_overrides
        )
        st.subheader("Current squad projection")
        st.dataframe(
            squad_table.sort_values("Total xP", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
        st.metric(
            f"Squad projected points across {horizon} GWs",
            f"{squad_table['Total xP'].sum():.2f}",
        )

        st.divider()
        st.subheader("Gameweek lineup planner")
        selected_gw = st.selectbox(
            "Select Gameweek",
            planner_gws,
            format_func=lambda g: f"Gameweek {g}",
            key="planner_selected_gw",
        )
        xi = best_xi(squad, selected_gw, fx_map, risk)
        if xi:
            bench = bench_order(squad, xi, fx_map, selected_gw)
            captain, vice = choose_captains(xi, selected_gw, fx_map, risk)
            st.metric(
                "Starting XI xP",
                f"{sum(gw_xp(p, selected_gw, fx_map, risk, minute_overrides) for p in xi):.2f}",
            )
            render_pitch(
                xi, selected_gw, fx_map,
                captain["id"] if captain else None,
                vice["id"] if vice else None,
                bench, risk,
            )
            if captain:
                st.info(
                    f"Captain: **{captain['web_name']}** · "
                    f"Vice-captain: **{vice['web_name']}**"
                )
        else:
            st.warning("Unable to generate a legal XI from this squad.")

        st.divider()
        st.subheader("Captain plan by Gameweek")
        captain_plan = []
        for gw in planner_gws:
            gw_xi = best_xi(squad, gw, fx_map, risk)
            cap, vice = choose_captains(gw_xi, gw, fx_map, risk)
            captain_plan.append({
                "Gameweek": gw,
                "Captain": cap["web_name"] if cap else "—",
                "Captain xP": gw_xp(cap, gw, fx_map, risk) if cap else 0,
                "Vice-captain": vice["web_name"] if vice else "—",
                "Vice xP": gw_xp(vice, gw, fx_map, risk) if vice else 0,
                "XI xP": round(sum(gw_xp(p, gw, fx_map, risk) for p in gw_xi), 2),
            })
        st.dataframe(pd.DataFrame(captain_plan), use_container_width=True, hide_index=True)
    else:
        st.info("Your squad picks are not available. The player projection table is still available.")

    st.divider()
    st.subheader("Best projected players over the selected horizon")
    all_projection = make_projection_table(
        players, planner_gws, fx_map, risk, minute_overrides
    )
    st.dataframe(
        all_projection.sort_values("Total xP", ascending=False).head(30),
        use_container_width=True,
        hide_index=True,
    )

# =========================================================
# TAB 5 — WILDCARD / FREE HIT / CHIP COMPARISON
# =========================================================

with tabs[4]:
    st.subheader("Squad optimiser and chip planner")
    st.caption(
        "Build an indicative legal 15-player squad. Chip comparisons use projected "
        "points only and do not predict future player prices or every future transfer."
    )

    budget = st.number_input(
        "Squad budget (£m)",
        min_value=80.0, max_value=120.0,
        value=100.0, step=0.5,
    )
    chip_mode = st.radio(
        "Squad-building scenario",
        ["Wildcard — longer-term squad", "Free Hit — one Gameweek"],
        horizontal=True,
    )
    build_gw = st.selectbox(
        "Optimise for Gameweek",
        available_gws[:6],
        format_func=lambda g: f"GW{g}",
    )

    if st.button("Optimise 15-player squad", type="primary"):
        optimised = build_squad(players, fx_map, build_gw, budget)
        cost, legal = legal_squad_summary(optimised, budget)

        if not legal:
            st.error(
                "The optimiser could not create a complete legal 15-player squad "
                "within the selected budget. Try a higher budget."
            )
        else:
            xi = best_xi(optimised, build_gw, fx_map, risk)
            bench = bench_order(optimised, xi, fx_map, build_gw)
            captain, vice = choose_captains(xi, build_gw, fx_map, risk)

            st.success(f"{chip_mode} draft generated for GW{build_gw}.")
            m1, m2, m3 = st.columns(3)
            m1.metric("Squad cost", money(cost))
            m2.metric("Budget remaining", money(int(round(budget * 10)) - cost))
            m3.metric("Starting XI xP", f"{sum(gw_xp(p, build_gw, fx_map, risk) for p in xi):.2f}")

            render_pitch(
                xi, build_gw, fx_map,
                captain["id"] if captain else None,
                vice["id"] if vice else None,
                bench, risk,
            )

            squad_rows = []
            xi_ids = {p["id"] for p in xi}
            for p in optimised:
                squad_rows.append({
                    "Role": "Starting XI" if p["id"] in xi_ids else "Bench",
                    "Player": p["web_name"],
                    "Position": POSITION_NAMES.get(p["element_type"]),
                    "Club": team_short.get(p["team"], ""),
                    "Price": money(p["now_cost"]),
                    "Fixture": fx_text(fx_map.get((p["team"], build_gw), [])),
                    "xP": gw_xp(p, build_gw, fx_map, risk),
                })
            st.dataframe(
                pd.DataFrame(squad_rows).sort_values(
                    ["Role", "Position", "xP"],
                    ascending=[True, True, False],
                ),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.subheader("Chip impact comparison — your current squad")
    if squad:
        chip_gw = st.selectbox(
            "Chip comparison Gameweek",
            available_gws[:6],
            key="chip_gw",
            format_func=lambda g: f"GW{g}",
        )
        xi = best_xi(squad, chip_gw, fx_map, risk)
        bench = bench_order(squad, xi, fx_map, chip_gw)
        captain, vice = choose_captains(xi, chip_gw, fx_map, risk)

        xi_xp = sum(gw_xp(p, chip_gw, fx_map, risk) for p in xi)
        bench_xp = sum(gw_xp(p, chip_gw, fx_map, risk) for p in bench)
        cap_xp = gw_xp(captain, chip_gw, fx_map, risk) if captain else 0

        chip_df = pd.DataFrame([
            {"Scenario": "No chip", "Estimated XI / squad points": round(xi_xp, 2),
             "Estimated uplift vs no chip": 0.0},
            {"Scenario": "Triple Captain", "Estimated XI / squad points": round(xi_xp + cap_xp * 2, 2),
             "Estimated uplift vs no chip": round(cap_xp, 2)},
            {"Scenario": "Bench Boost", "Estimated XI / squad points": round(xi_xp + bench_xp, 2),
             "Estimated uplift vs no chip": round(bench_xp, 2)},
        ])
        st.dataframe(chip_df, use_container_width=True, hide_index=True)
        st.caption(
            "The Triple Captain row shows the normal XI estimate plus two additional "
            "captain copies, so its uplift is one extra captain xP. Bench Boost adds "
            "the four substitute projections. These are simplified estimates and "
            "do not account for autosubs, captain replacement or chip-specific rules."
        )
    else:
        st.info("Load your squad to compare Bench Boost and Triple Captain scenarios.")

    st.info(
        "Wildcard and Free Hit use the same squad-building algorithm here. "
        "The app does not yet simulate chip availability, chip deadlines, "
        "Free Hit squad restoration or a season-long chip schedule."
    )

# =========================================================
# TAB 6 — DIFFERENTIALS
# =========================================================

with tabs[5]:
    st.subheader("Differential and hidden-gem finder")
    a, b, c = st.columns(3)
    with a:
        max_ownership = st.slider("Maximum ownership %", 1, 50, 10)
    with b:
        max_price = st.slider("Maximum price (£m)", 4.0, 15.0, 9.0, 0.5)
    with c:
        min_minutes = st.slider("Minimum minutes", 0, 2000, 300, 50)

    differential_rows = []
    for p in players:
        price = num(p.get("now_cost")) / 10
        ownership = num(p.get("selected_by_percent"))
        minutes = num(p.get("minutes"))
        if (
            ownership <= max_ownership
            and price <= max_price
            and minutes >= min_minutes
            and p["id"] not in owned_ids
            and p.get("status") in ("a", "d")
        ):
            p_xp = xp(p, target_gw)
            differential_rows.append({
                "Player": p["web_name"],
                "Position": POSITION_NAMES.get(p["element_type"]),
                "Club": team_short.get(p["team"], ""),
                "Price": f"£{price:.1f}m",
                "Ownership %": ownership,
                "Fixture": fx_text(fx_map.get((p["team"], target_gw), [])),
                "xP": p_xp,
                "xP / £m": round(p_xp / max(price, 0.1), 2),
                "Status": status_label(p),
            })

    if differential_rows:
        st.dataframe(
            pd.DataFrame(differential_rows).sort_values(
                ["xP", "xP / £m"], ascending=False
            ).head(40),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No players match the selected differential filters.")

# =========================================================
# TAB 7 — FIXTURES & ROTATION
# =========================================================

with tabs[6]:
    st.subheader("Fixture difficulty and rotation planner")
    fixture_horizon = st.slider(
        "Upcoming Gameweeks",
        1, min(6, len(available_gws)),
        min(5, len(available_gws)),
        key="fixture_horizon",
    )
    fixture_gws = available_gws[:fixture_horizon]

    fixture_rows = []
    for team in teams:
        row = {"Club": team.get("name")}
        difficulties = []
        for gw in fixture_gws:
            team_fx = fx_map.get((team["id"], gw), [])
            row[f"GW{gw}"] = fx_text(team_fx)
            difficulties.extend(d for _, d in team_fx)
        row["Average FDR"] = (
            round(sum(difficulties) / len(difficulties), 2)
            if difficulties else None
        )
        fixture_rows.append(row)

    fixture_df = pd.DataFrame(fixture_rows).sort_values(
        "Average FDR", ascending=True, na_position="last"
    )
    st.dataframe(fixture_df, use_container_width=True, hide_index=True)

    st.subheader("Your squad's fixture run")
    if squad:
        rotation_rows = []
        for p in squad:
            upcoming = []
            diffs = []
            for gw in fixture_gws:
                team_fx = fx_map.get((p["team"], gw), [])
                upcoming.append(f"GW{gw}: {fx_text(team_fx)}")
                diffs.extend(d for _, d in team_fx)
            rotation_rows.append({
                "Player": p["web_name"],
                "Club": team_short.get(p["team"], ""),
                "Position": POSITION_NAMES.get(p["element_type"]),
                "Minutes": p.get("minutes"),
                "Status": status_label(p),
                "Average FDR": round(sum(diffs) / len(diffs), 2) if diffs else None,
                "Fixtures": " | ".join(upcoming),
                "Horizon xP": horizon_xp(p, fixture_gws, fx_map, risk, minute_overrides),
            })
        st.dataframe(
            pd.DataFrame(rotation_rows).sort_values(
                ["Average FDR", "Horizon xP"],
                ascending=[True, False],
                na_position="last",
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Load public squad picks to see your squad's fixture run.")

# =========================================================
# TAB 8 — WEEKLY REPORTS
# =========================================================

with tabs[7]:
    st.subheader("Automatic weekly FPL reports")
    st.write(
        "The GitHub Actions workflow can generate a Markdown report every "
        "Monday at 09:00 Malaysia time (01:00 UTC). Reports appear here after "
        "they are saved to the repository."
    )

    files = report_files()
    if files:
        for report_path in files[:12]:
            with st.expander(report_path.stem.replace("_", " ")):
                content = report_path.read_text(encoding="utf-8")
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
            "You can also start the workflow manually from GitHub Actions."
        )

    st.caption("Scheduled reports depend on GitHub Actions and the public FPL API.")

# =========================================================
# FOOTER
# =========================================================

st.divider()
st.caption(
    "AJK Bola Wawei AI · Independent fan-made FPL analytics tool. "
    "Not affiliated with or endorsed by the Premier League. "
    "All projections and recommendations are estimates based on public data "
    "and transparent statistical heuristics. Always verify decisions on the "
    "official FPL website."
)
