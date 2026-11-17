import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st

API = "https://fantasy.premierleague.com/api"
DEFAULT_TEAM_ID = 1645144
HEADERS = {"User-Agent": "FPL-AI-Analyst/0.1 (personal analytics app)"}

st.set_page_config(page_title="FPL AI Analyst", page_icon="⚽", layout="wide")

# ---------- Data access ----------
@st.cache_data(ttl=600, show_spinner=False)
def get_json(path: str) -> Any:
    response = requests.get(f"{API}/{path.lstrip('/')}", headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()

def safe_float(value, default=0.0):
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default

def get_gw_context(events):
    current = next((e for e in events if e.get("is_current")), None)
    upcoming = next((e for e in events if e.get("is_next")), None)
    if upcoming:
        return upcoming, current, "next"
    if current and not current.get("finished"):
        return current, current, "current"
    future = next((e for e in events if not e.get("finished") and e.get("deadline_time")), None)
    return future, current, "future"

def fixture_map(fixtures, gw_id, teams):
    names = {t["id"]: t["short_name"] for t in teams}
    result = {}
    for f in fixtures:
        if f.get("event") != gw_id:
            continue
        h, a = f["team_h"], f["team_a"]
        result.setdefault(h, []).append((f"{names.get(h, h)} (H)", f.get("team_h_difficulty", 3)))
        result.setdefault(a, []).append((f"{names.get(a, a)} (A)", f.get("team_a_difficulty", 3)))
    return result

def player_score(p, difficulty=3):
    # Transparent heuristic, not a trained or guaranteed prediction model.
    form = safe_float(p.get("form"))
    ppg = safe_float(p.get("points_per_game"))
    xgi = safe_float(p.get("expected_goal_involvements"))
    minutes = safe_float(p.get("minutes"))
    chance = p.get("chance_of_playing_next_round")
    status = p.get("status", "a")
    availability = 1.0
    if status != "a":
        availability = 0.35 if status in ("i", "s", "u") else 0.65
    if chance is not None:
        availability *= max(0.1, min(1.0, safe_float(chance) / 100))
    mins_factor = min(1.0, minutes / 900) if minutes else 0.65
    fixture_factor = max(0.72, min(1.18, 1.12 - (difficulty - 1) * 0.10))
    base = (0.45 * form + 0.35 * ppg + 0.20 * (xgi * 2.0))
    return max(0, base * availability * (0.65 + 0.35 * mins_factor) * fixture_factor)

def status_label(p):
    labels = {"a": "Available", "d": "Doubtful", "i": "Injured", "s": "Suspended", "u": "Unavailable", "n": "Not available"}
    label = labels.get(p.get("status"), str(p.get("status", "Unknown")))
    chance = p.get("chance_of_playing_next_round")
    if chance is not None:
        label += f" · {chance}% chance"
    return label

# ---------- UI ----------
st.markdown("""
<style>
.block-container {padding-top: 1.4rem; max-width: 1500px;}
[data-testid="stMetric"] {background: rgba(120,130,145,.09); padding: 12px 14px; border-radius: 12px;}
.small-note {color: #8b93a1; font-size: .84rem;}
</style>
""", unsafe_allow_html=True)

st.title("⚽ FPL AI Analyst")
st.caption("Live FPL data • squad health • transfer ideas • player rankings")

with st.sidebar:
    st.header("Manager")
    team_id = st.number_input("FPL Team ID", min_value=1, value=DEFAULT_TEAM_ID, step=1)
    refresh = st.button("↻ Refresh data", use_container_width=True)
    if refresh:
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.caption("Data comes from the public Fantasy Premier League API. No FPL password is requested.")

try:
    with st.spinner("Loading live FPL data…"):
        boot = get_json("bootstrap-static/")
        fixtures = get_json("fixtures/")
        profile = get_json(f"entry/{int(team_id)}/")
except requests.HTTPError as e:
    st.error(f"FPL API returned an error: {e}. Try refreshing in a minute.")
    st.stop()
except Exception as e:
    st.error(f"Could not load FPL data: {e}")
    st.stop()

events = boot.get("events", [])
players = boot.get("elements", [])
teams = boot.get("teams", [])
positions = {x["id"]: x["singular_name_short"] for x in boot.get("element_types", [])}
team_names = {t["id"]: t["name"] for t in teams}
player_by_id = {p["id"]: p for p in players}
gw, current_gw, gw_mode = get_gw_context(events)
if not gw:
    st.warning("No upcoming/current Gameweek is published in the API yet.")
    st.stop()

gw_id = gw["id"]
try:
    picks_data = get_json(f"entry/{int(team_id)}/event/{gw_id}/picks/")
    picks_available = True
except requests.HTTPError:
    picks_data = None
    picks_available = False

# If upcoming picks are not published, try the latest completed gameweek as a squad snapshot.
snapshot_gw = gw_id
if not picks_available:
    completed = [e for e in events if e.get("finished")]
    if completed:
        snapshot_gw = completed[-1]["id"]
        try:
            picks_data = get_json(f"entry/{int(team_id)}/event/{snapshot_gw}/picks/")
            picks_available = True
        except requests.HTTPError:
            picks_data = None

fixture_by_team = fixture_map(fixtures, gw_id, teams)
now = datetime.now(timezone.utc)
deadline = gw.get("deadline_time")
deadline_text = "TBC"
if deadline:
    deadline_text = datetime.fromisoformat(deadline.replace("Z", "+00:00")).astimezone().strftime("%d %b %Y, %H:%M local")

# Header
manager_name = f"{profile.get('player_first_name', '')} {profile.get('player_last_name', '')}".strip()
st.subheader(profile.get("name", "FPL Manager"))
st.caption(f"{manager_name} · Team ID {int(team_id)} · {gw.get('name', f'Gameweek {gw_id}')} · Deadline: {deadline_text}")

history = []
try:
    history = get_json(f"entry/{int(team_id)}/history/").get("current", [])
except Exception:
    pass
latest_history = history[-1] if history else {}
c1, c2, c3, c4 = st.columns(4)
c1.metric("Overall points", f"{profile.get('summary_overall_points', 0):,}")
c2.metric("Overall rank", f"{profile.get('summary_overall_rank', 0):,}")
c3.metric("Gameweek", str(gw_id))
c4.metric("Team value", f"£{safe_float(latest_history.get('value', profile.get('last_deadline_value', 0))) / 10:.1f}m" if latest_history or profile.get("last_deadline_value") else "—")

tabs = st.tabs(["Overview", "Transfers", "Injury Centre", "Best Picks", "Public Team Analyzer"])

with tabs[0]:
    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("### Your squad")
        if picks_available and picks_data:
            pick_rows = []
            for pick in picks_data.get("picks", []):
                p = player_by_id.get(pick["element"])
                if not p:
                    continue
                fx = fixture_by_team.get(p["team"], [])
                opponent, diff = fx[0] if fx else ("—", 3)
                pick_rows.append({
                    "Slot": "XI" if pick.get("position", 99) <= 11 else "Bench",
                    "Player": p["web_name"],
                    "Pos": positions.get(p["element_type"], "?"),
                    "Club": team_names.get(p["team"], ""),
                    "Fixture": opponent,
                    "Status": status_label(p),
                    "Price": f"£{p['now_cost']/10:.1f}m",
                    "Est. pts": round(player_score(p, diff), 1),
                    "Captain": "C" if pick.get("is_captain") else ("VC" if pick.get("is_vice_captain") else ""),
                })
            df = pd.DataFrame(pick_rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"Squad snapshot: GW{snapshot_gw}. Picks for GW{gw_id} are shown when published; otherwise the most recent completed GW is used.")
        else:
            st.info("The public picks endpoint has not published a squad snapshot for this team/Gameweek. Team profile and player analysis are still available.")
    with right:
        st.markdown("### Squad health")
        if picks_available and picks_data:
            squad_players = [player_by_id[x["element"]] for x in picks_data.get("picks", []) if x["element"] in player_by_id]
            concerns = [p for p in squad_players if p.get("status") != "a" or p.get("chance_of_playing_next_round") not in (None, 100)]
            st.metric("Availability concerns", len(concerns))
            if concerns:
                for p in concerns:
                    st.warning(f"**{p['web_name']}** — {status_label(p)}\n\n{p.get('news') or 'No additional FPL news supplied.'}")
            else:
                st.success("No flagged availability concerns in the latest squad snapshot.")
        else:
            st.info("Squad health appears here when public picks are available.")
        st.markdown("### Upcoming fixtures")
        upcoming = [e for e in events if not e.get("finished") and e.get("deadline_time")]
        for event in upcoming[:5]:
            st.write(f"**GW{event['id']}** · {event.get('name','')} · {datetime.fromisoformat(event['deadline_time'].replace('Z','+00:00')).strftime('%d %b')}")

with tabs[1]:
    st.markdown("### Transfer intelligence")
    if not picks_available or not picks_data:
        st.info("Transfer recommendations need a public squad snapshot. Try again after the next Gameweek picks are published.")
    else:
        owned_ids = {x["element"] for x in picks_data.get("picks", [])}
        owned = [player_by_id[x] for x in owned_ids if x in player_by_id]
        owned_by_pos = {}
        for p in owned:
            owned_by_pos.setdefault(p["element_type"], []).append(p)
        bank_tenths = safe_float(latest_history.get("bank", profile.get("last_deadline_bank", 0)))
        st.caption(f"Estimated bank from latest public history: £{bank_tenths/10:.1f}m. Exact selling prices may not be exposed by the public endpoint.")
        rows = []
        for pos_id, pos_name in positions.items():
            pool = [p for p in players if p.get("element_type") == pos_id and p["id"] not in owned_ids and p.get("status") != "u"]
            pool.sort(key=lambda p: player_score(p, (fixture_by_team.get(p["team"]) or [("",3)])[0][1]), reverse=True)
            for p in pool[:8]:
                fx = fixture_by_team.get(p["team"], [("—",3)])[0]
                rows.append({"Pos": pos_name, "Player": p["web_name"], "Club": team_names.get(p["team"], ""),
                             "Price": f"£{p['now_cost']/10:.1f}m", "Form": p.get("form", "0"),
                             "Fixture": fx[0], "Est. pts": round(player_score(p, fx[1]), 1),
                             "Status": status_label(p)})
        st.write("**Top alternatives by position**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("These are shortlist candidates, not automatic buy/sell commands. Compare your outgoing player's selling price, budget, free transfers and squad structure before confirming.")

with tabs[2]:
    st.markdown("### Injury & availability centre")
    flagged = [p for p in players if p.get("status") != "a" or p.get("chance_of_playing_next_round") not in (None, 100)]
    flagged.sort(key=lambda p: (safe_float(p.get("chance_of_playing_next_round"), 50), p.get("web_name","")))
    if flagged:
        injury_rows = [{"Player": p["web_name"], "Club": team_names.get(p["team"], ""),
                        "Position": positions.get(p["element_type"], "?"), "Status": status_label(p),
                        "News": p.get("news") or "No detail supplied",
                        "News added": p.get("news_added") or "—"} for p in flagged]
        st.dataframe(pd.DataFrame(injury_rows), use_container_width=True, hide_index=True)
    else:
        st.success("No players are currently flagged by the FPL API.")
    st.caption("Availability comes from FPL player status/news fields. This is not a live medical report; verify late press-conference updates before the deadline.")

with tabs[3]:
    st.markdown("### Best picks for the incoming Gameweek")
    ranked = []
    for p in players:
        fx_list = fixture_by_team.get(p["team"], [("—", 3)])
        fx, diff = fx_list[0]
        ranked.append({"Player": p["web_name"], "Position": positions.get(p["element_type"], "?"),
                       "Club": team_names.get(p["team"], ""), "Fixture": fx,
                       "Price": f"£{p['now_cost']/10:.1f}m", "Form": p.get("form", "0"),
                       "xGI": p.get("expected_goal_involvements", "—"),
                       "Est. pts": round(player_score(p, diff), 2), "Availability": status_label(p)})
    ranked_df = pd.DataFrame(ranked).sort_values("Est. pts", ascending=False)
    position_filter = st.selectbox("Position", ["All", "GKP", "DEF", "MID", "FWD"])
    if position_filter != "All":
        ranked_df = ranked_df[ranked_df["Position"] == position_filter]
    st.dataframe(ranked_df.head(30), use_container_width=True, hide_index=True)
    st.markdown("#### Captaincy shortlist")
    captain_pool = ranked_df[ranked_df["Position"] != "GKP"].head(5)
    st.dataframe(captain_pool[["Player", "Club", "Fixture", "Est. pts", "Availability"]], use_container_width=True, hide_index=True)

with tabs[4]:
    st.markdown("### Analyze another manager")
    other_id = st.number_input("Enter another FPL Team ID", min_value=1, value=int(team_id), step=1, key="other_team")
    if st.button("Analyze public team", key="analyze_other"):
        try:
            other = get_json(f"entry/{int(other_id)}/")
            st.success(f"Found **{other.get('name','FPL team')}**")
            a, b, c = st.columns(3)
            a.metric("Overall points", f"{other.get('summary_overall_points',0):,}")
            b.metric("Overall rank", f"{other.get('summary_overall_rank',0):,}")
            c.metric("Team ID", str(other_id))
            try:
                other_hist = get_json(f"entry/{int(other_id)}/history/").get("current", [])
                if other_hist:
                    st.line_chart(pd.DataFrame(other_hist).set_index("event")[["points"]])
            except Exception:
                st.info("History is not available for this manager yet.")
            st.caption("Public team profile and history are available without a password. The private editable team endpoint is not accessed.")
        except Exception as e:
            st.error(f"Could not find/read that public team: {e}")

st.divider()
st.caption("FPL AI Analyst is an independent fan-made analytics project and is not affiliated with or endorsed by the Premier League. Expected points are transparent heuristic estimates, not official FPL projections or guaranteed outcomes.")
