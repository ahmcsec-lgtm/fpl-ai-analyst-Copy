"""AJK Bola Wawei AI — free FPL My Team, AI-style rating and squad builder.
Run: streamlit run app.py
Requires: streamlit, pandas, requests (see requirements.txt).
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from fpl_engine import (
    POSITION_NAMES, QUOTAS, best_lineup, configure_projection_context, fixture_lookup, horizon_xp,
    num, optimise_chip_squad, player_fixture_xp, projected_minutes,
    suggest_transfers, team_rating, valid_squad, player_prediction,
    SNAPSHOT_FIELDS, make_snapshot, validate_snapshots, join_actuals,
    configure_calibration, backtest_report,
)

API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "AJK-Bola-Wawei-AI/4.0 (public FPL data)"}
MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")

st.set_page_config(page_title="AJK Bola Wawei AI", page_icon="⚽", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1.4rem;max-width:1400px}
[data-testid="stMetric"]{border:1px solid rgba(130,130,130,.22);border-radius:14px;padding:14px}
.pitch{background:linear-gradient(180deg,#0d6b48,#07553b);border:2px solid #4da47b;
  border-radius:16px;padding:16px 8px;margin:8px 0;color:white}
.pitch-row{display:flex;justify-content:space-evenly;gap:5px;margin:16px 0}
.pitch-player{background:rgba(0,0,0,.27);border:1px solid rgba(255,255,255,.24);
  border-radius:9px;padding:8px 3px;width:19%;text-align:center;font-size:12px;line-height:1.35}
.pitch-player strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pitch-player small{display:block;opacity:.92}
.muted-note{color:#888;font-size:.85rem}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner=False)
def get_json(path: str) -> dict | list:
    response = requests.get(f"{API}/{path.lstrip('/')}", headers=HEADERS, timeout=22)
    response.raise_for_status()
    return response.json()


def pounds(tenths: int | float) -> str:
    return f"£{num(tenths) / 10:.1f}m"


def short_name(p: dict, clubs: dict[int, str]) -> str:
    return f"{p.get('web_name', p.get('second_name', '?'))} ({clubs.get(int(p.get('team', 0)), '—')})"


def player_options(players: list[dict], clubs: dict[int, str]) -> dict[int, str]:
    return {int(p["id"]): f"{short_name(p, clubs)} · {POSITION_NAMES.get(int(p['element_type']), '?')} · {pounds(p.get('now_cost', 0))}" for p in players}


def get_manager(team_id: int, events: list[dict]) -> tuple[dict, dict, int]:
    profile = get_json(f"entry/{team_id}/")
    playable = sorted([int(e["id"]) for e in events if e.get("finished") or e.get("is_current")], reverse=True)
    if not playable:
        raise ValueError("No completed/current Gameweek picks available for this team yet.")
    for gw in playable[:8]:
        try:
            picks = get_json(f"entry/{team_id}/event/{gw}/picks/")
            if len(picks.get("picks", [])) == 15:
                return profile, picks, gw
        except (requests.RequestException, ValueError):
            continue
    raise ValueError("Could not load 15 public squad picks for this FPL Team ID.")


def render_pitch(xi: list[dict], captain_id: int, vice_id: int,
                 gw: int, fixture_map: dict, clubs: dict[int, str],
                 minutes_overrides: dict[int, float] | None = None) -> None:
    """Static squad pitch; player controls are below the pitch."""
    import html
    lines = []
    for pos in [4, 3, 2, 1]:
        players = [p for p in xi if int(p["element_type"]) == pos]
        cards = []
        for p in players:
            pid = int(p["id"])
            captain = " (C)" if pid == captain_id else " (VC)" if pid == vice_id else ""
            name = html.escape(str(p.get("web_name", "Player")) + captain)
            club = html.escape(clubs.get(int(p.get("team", 0)), ""))
            xp = player_fixture_xp(p, gw, fixture_map, minutes_overrides)
            cards.append(f'<div class="pitch-player"><strong>{name}</strong><small>{club} · {xp:.1f} xP</small></div>')
        lines.append('<div class="pitch-row">' + "".join(cards) + '</div>')
    st.markdown('<div class="pitch">' + "".join(lines) + '</div>', unsafe_allow_html=True)


def squad_table(squad: list[dict], gws: list[int], fixture_map: dict,
                clubs: dict[int, str], minutes_overrides: dict[int, float] | None = None) -> pd.DataFrame:
    rows = []
    for p in squad:
        rows.append({"Player": short_name(p, clubs), "Pos": POSITION_NAMES[int(p["element_type"])],
                     "Price": pounds(p.get("now_cost", 0)),
                     "Sell": pounds(p.get("selling_price", p.get("now_cost", 0))),
                     "GW xP": player_fixture_xp(p, gws[0], fixture_map, minutes_overrides),
                     "Horizon xP": horizon_xp(p, gws, fixture_map, minutes_overrides),
                     "Status": p.get("status", "?")})
    return pd.DataFrame(rows).sort_values(["Pos", "Horizon xP"], ascending=[True, False])


def squad_with_sell_prices(picks: dict, player_by_id: dict[int, dict]) -> list[dict]:
    squad = []
    for item in picks.get("picks", []):
        player = player_by_id.get(int(item["element"]))
        if player is None:
            continue
        data = dict(player)
        data["selling_price"] = int(item.get("selling_price") or player.get("now_cost", 0))
        squad.append(data)
    return squad


def xp_for_selected_xi(xi: list[dict], captain: int, gw: int,
                       fixture_map: dict, overrides: dict) -> float:
    return round(sum(player_fixture_xp(p, gw, fixture_map, overrides) for p in xi)
                 + next((player_fixture_xp(p, gw, fixture_map, overrides)
                         for p in xi if int(p["id"]) == captain), 0), 2)


def legal_starting_xi(xi: list[dict]) -> bool:
    counts = Counter(int(p["element_type"]) for p in xi)
    return len(xi) == 11 and counts[1] == 1 and 3 <= counts[2] <= 5 and 2 <= counts[3] <= 5 and 1 <= counts[4] <= 3


st.title("⚽ AJK Bola Wawei AI")
st.caption("My Team • AI Transfers • Wildcard / Free Hit • Accuracy Lab | Free open-data forecasts")

try:
    bootstrap = get_json("bootstrap-static/")
    fixtures_raw = get_json("fixtures/")
except (requests.RequestException, ValueError) as exc:
    st.error(f"FPL public API could not be loaded: {exc}")
    st.stop()

players = bootstrap.get("elements", [])
clubs = {int(t["id"]): t.get("short_name", t.get("name", "?")) for t in bootstrap.get("teams", [])}
player_by_id = {int(p["id"]): p for p in players}
labels = player_options(players, clubs)
fixture_map = fixture_lookup(fixtures_raw)
configure_projection_context(bootstrap.get("teams", []), fixtures_raw)
events = bootstrap.get("events", [])
next_event = next((e for e in events if e.get("is_next")), None)
if next_event is None:
    next_event = next((e for e in events if not e.get("finished") and not e.get("is_current")), None)
if next_event is None:
    next_event = next((e for e in events if e.get("is_current")), None)
if next_event is None:
    st.warning("There is currently no upcoming FPL gameweek in the public API.")
    st.stop()
next_gw = int(next_event["id"])
upcoming_gws = [int(e["id"]) for e in events if int(e["id"]) >= next_gw][:5]

with st.sidebar:
    st.header("Your Team")
    fpl_id = st.number_input("FPL Team ID", min_value=1, value=1645144, step=1)
    import_team = st.button("🔄 Import / Reset My Team", type="primary", use_container_width=True)
    st.divider()
    selected_gw = st.selectbox("Gameweek to analyse", upcoming_gws, format_func=lambda v: f"GW {v}")
    start_index = upcoming_gws.index(selected_gw)
    horizon_max = min(5, len(upcoming_gws) - start_index)
    horizon = st.slider("Planning horizon (GWs)", 1, horizon_max, min(3, horizon_max))
    gws = upcoming_gws[start_index:start_index + horizon]
    st.divider()
    st.subheader("Accuracy data")
    snapshot_files = st.file_uploader(
        "Restore saved pre-deadline forecast CSVs", type="csv",
        accept_multiple_files=True, key="accuracy_snapshot_upload",
        help="Upload your previously downloaded AJK prediction snapshots. Streamlit Cloud storage is temporary.")
    free_transfers = st.number_input("Available free transfers", min_value=0, max_value=5, value=1)
    st.caption("FPL manager imports are read-only. Changes here are planning drafts and are never submitted to FPL.")

# Train only on previously captured forecasts from finalized earlier GWs.
# No historical reconstruction is performed using present-day season aggregates.
first_deadline = next((e.get("deadline_time") for e in events if int(e.get("id", 0)) == 1), None)
season_start = int(str(first_deadline)[:4]) if first_deadline else datetime.now(timezone.utc).year
season_id = f"{season_start}-{str(season_start + 1)[-2:]}"

uploaded_rows = []
for uploaded in snapshot_files or []:
    try:
        frame = pd.read_csv(BytesIO(uploaded.getvalue()))
        if len(frame) > 4000 or not set(SNAPSHOT_FIELDS).issubset(frame.columns):
            st.sidebar.warning(f"Skipped {uploaded.name}: missing fields or too many rows")
            continue
        uploaded_rows.extend(frame.to_dict("records"))
    except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        st.sidebar.warning(f"Skipped {uploaded.name}: {exc}")

all_saved = uploaded_rows + st.session_state.get("saved_snapshots", [])
validated_snapshots = validate_snapshots(all_saved, season_id)
finalized_gws = {int(e["id"]) for e in events
                 if e.get("finished") and e.get("data_checked")}
actuals_by_gw = st.session_state.get("accuracy_actuals", {})
completed_rows = join_actuals(validated_snapshots, actuals_by_gw, finalized_gws)
calibration_state = configure_calibration(completed_rows, selected_gw)

# Load the imported manager exactly once per selected ID, unless reset is requested.
if import_team or st.session_state.get("loaded_id") != int(fpl_id):
    try:
        profile, picks, picks_gw = get_manager(int(fpl_id), events)
        imported_squad = squad_with_sell_prices(picks, player_by_id)
        if not valid_squad(imported_squad):
            raise ValueError("Imported picks are incomplete or violate the 15-player squad limits.")
        st.session_state.loaded_id = int(fpl_id)
        st.session_state.profile = profile
        st.session_state.picks_gw = picks_gw
        st.session_state.draft = imported_squad
        st.session_state.bank = int(picks.get("entry_history", {}).get(
            "bank", profile.get("last_deadline_bank", 0)) or 0)
        st.session_state.manual_xi = []
        st.session_state.manual_captain = None
        st.session_state.moves = []
        st.session_state.chip_result = None
    except (requests.RequestException, ValueError, KeyError) as exc:
        st.error(f"Unable to import team {fpl_id}: {exc}")
        st.info("Check the Team ID on your public FPL Points page and retry.")
        st.stop()

squad: list[dict] = st.session_state.draft
bank: int = st.session_state.bank
profile = st.session_state.profile
if not valid_squad(squad):
    st.error("Draft squad is invalid. Click 'Import / Reset My Team' to restore your actual FPL squad.")
    st.stop()

# Optional personal minute assumptions (never mutate public API data).
with st.sidebar.expander("Advanced: minutes assumptions", expanded=False):
    minutes_overrides = {}
    for p in squad:
        pid = int(p["id"])
        estimate = int(round(projected_minutes(p) / 5) * 5)
        updated = st.slider(short_name(p, clubs), min_value=0, max_value=90,
                            value=estimate, step=5, key=f"mins_{st.session_state.loaded_id}_{pid}")
        minutes_overrides[pid] = updated

assessment = team_rating(squad, gws, fixture_map, minutes_overrides)
lineup = best_lineup(squad, selected_gw, fixture_map, minutes_overrides)

st.subheader(profile.get("name", "My FPL Team"))
st.caption(f"Manager: {profile.get('player_first_name', '')} {profile.get('player_last_name', '')} · Imported from GW {st.session_state.picks_gw} · Selected GW {selected_gw}")

metric_cols = st.columns(5)
metric_cols[0].metric("Team Rating", f"{assessment['rating']}/100")
metric_cols[1].metric("GW Rating", f"{assessment['gw_rating']}/100")
metric_cols[2].metric(f"GW {selected_gw} xP", f"{lineup['total_xp']:.1f}")
metric_cols[3].metric(f"{horizon}-GW xP", f"{assessment['total_xp']:.1f}")
metric_cols[4].metric("In the Bank", pounds(bank))
st.caption("Model v4: xG/xA, minutes, team goals, clean sheets, saves, defensive contributions and bonus. "
           f"Calibration examples from earlier finalized GWs: {calibration_state['count']}. "
           "Ratings remain heuristic; no paid-model equivalence is claimed.")
with st.expander("📊 How the upgraded prediction model works", expanded=False):
    st.markdown("""**Model v4 — open-data expected points with walk-forward evaluation.**
    - Goals and assists: season xG/xA rates, shrunk toward positional priors for small samples.
    - Fixtures: offensive/defensive strength estimated from completed league matches, combined with FPL fixture difficulty and home advantage.
    - Minutes: regular-start history, injury availability and optional manager overrides.
    - Other points: appearance, clean sheets, goalkeeper saves, bonus, defensive contributions and expected conceded-goal/card deductions.
    - Double GWs are added; blank GWs return zero.

    **Calibration:** Position-level bias adjustments learned only from your saved, pre-deadline predictions in earlier finalized GWs. At least 80 historical observations per position are needed before using an empirical uncertainty width.

    **Limits:** Uncertainty ranges are only empirical when enough historical data exists, and even then are approximate, not guaranteed coverage. No private team news or paid bookmaker odds. The 0–100 rating is a heuristic, not a percentile or Hub score. CSV records are user-supplied and cannot be independently verified as pre-deadline exports.""")

my_team_tab, transfers_tab, chip_tab, accuracy_tab = st.tabs(["🏟️ My Team", "🔁 AI Transfers", "✨ Wildcard / Free Hit", "📈 Accuracy Lab"])

with my_team_tab:
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        st.markdown("### Starting XI")
        natural_xi = lineup["xi"]
        manual_ids = set(st.session_state.get("manual_xi") or [])
        if len(manual_ids) == 11:
            proposed_xi = [p for p in squad if int(p["id"]) in manual_ids]
            if legal_starting_xi(proposed_xi):
                natural_xi = proposed_xi
        xi_ids = {int(p["id"]) for p in natural_xi}
        selected_captain = st.session_state.get("manual_captain")
        if selected_captain not in xi_ids:
            selected_captain = int(max(natural_xi, key=lambda p: player_fixture_xp(p, selected_gw, fixture_map, minutes_overrides))["id"])
        vice_id = int(max((p for p in natural_xi if int(p["id"]) != selected_captain),
                          key=lambda p: player_fixture_xp(p, selected_gw, fixture_map, minutes_overrides))["id"])
        render_pitch(natural_xi, selected_captain, vice_id, selected_gw, fixture_map, clubs, minutes_overrides)
        actual_xp = xp_for_selected_xi(natural_xi, selected_captain, selected_gw, fixture_map, minutes_overrides)
        st.metric("Selected XI + captain projected points", f"{actual_xp:.1f} xP")
        bench = [p for p in squad if int(p["id"]) not in xi_ids]
        st.markdown("**Bench**")
        for p in bench:
            st.write(f"{short_name(p, clubs)} — {player_fixture_xp(p, selected_gw, fixture_map, minutes_overrides):.1f} xP")
    with right:
        st.markdown("### Edit Starting XI & Captain")
        cap = st.selectbox("Captain", sorted(xi_ids), index=sorted(xi_ids).index(selected_captain),
                           format_func=lambda pid: labels[pid], key=f"cap_{selected_gw}_{len(st.session_state.moves)}")
        if cap != selected_captain:
            st.session_state.manual_captain = cap
            st.rerun()
        start_id = st.selectbox("Starting player to bench", sorted(xi_ids), format_func=lambda pid: labels[pid])
        bench_ids = [int(p["id"]) for p in bench]
        bench_id = st.selectbox("Bench player to start", bench_ids, format_func=lambda pid: labels[pid])
        if st.button("Swap XI / bench", use_container_width=True):
            revised = [p for p in squad if (int(p["id"]) in xi_ids and int(p["id"]) != start_id)
                       or int(p["id"]) == bench_id]
            if legal_starting_xi(revised):
                st.session_state.manual_xi = [int(p["id"]) for p in revised]
                st.session_state.manual_captain = cap if cap != start_id else None
                st.rerun()
            else:
                st.warning("This swap would create an invalid formation (need 1 GKP, 3–5 DEF, 2–5 MID and 1–3 FWD).")
        if st.button("Auto-pick best XI and captain", use_container_width=True):
            st.session_state.manual_xi = []
            st.session_state.manual_captain = None
            st.rerun()
        st.divider()
        st.markdown("### Next Gameweeks")
        for gw, weekly in zip(gws, assessment["weekly"]):
            st.write(f"**GW {gw}:** {weekly['total_xp']:.1f} xP · Captain {weekly['captain'].get('web_name')} ({weekly['captain_xp']:.1f} xP)")
        st.markdown("### Squad Health")
        risk_players = [p for p in squad if p.get("status", "a") != "a"]
        if not risk_players:
            st.success("All squad players are currently marked available in FPL data.")
        for p in risk_players:
            st.warning(f"{short_name(p, clubs)} · FPL status {p.get('status')} · {p.get('news') or 'Check latest news'}")

    st.markdown("### Projection Confidence & Components")
    focus_id = st.selectbox("Inspect player projection", [int(p["id"]) for p in squad],
                            format_func=lambda pid: labels[pid], key="projection_inspect")
    focus = next(p for p in squad if int(p["id"]) == focus_id)
    detail = player_prediction(focus, selected_gw, fixture_map, minutes_overrides)
    a, b, c = st.columns(3)
    a.metric("Predicted xP", f"{detail['xp']:.1f}")
    b.metric("Approx. 80% range", f"{detail['lower']:.1f}–{detail['upper']:.1f}")
    c.metric("Expected minutes", f"{detail['minutes']:.0f}")
    components = [(key.replace("_", " ").title(), detail[key]) for key in
                  ("appearance", "goals", "assists", "clean_sheet", "saves", "bonus",
                   "defensive_contributions", "goals_conceded", "discipline")]
    st.dataframe(pd.DataFrame(components, columns=["xP component", "Expected points"]),
                 use_container_width=True, hide_index=True)
    st.caption("The 80% interval is an indicative uncertainty band, not a validated coverage guarantee.")
    st.markdown("### Your Full Squad")
    st.dataframe(squad_table(squad, gws, fixture_map, clubs, minutes_overrides),
                 hide_index=True, use_container_width=True)

with transfers_tab:
    st.markdown("### AI-style Transfer Recommendations")
    st.caption("Ranked by estimated improvement in best XI + captain points over the selected horizon. Club, positional, selling-price and bank restrictions apply.")
    suggestions = suggest_transfers(squad, players, gws, fixture_map, bank,
                                    free_transfers=int(free_transfers),
                                    minutes_overrides=minutes_overrides, limit=12)
    if suggestions:
        table_rows = []
        for move in suggestions:
            table_rows.append({"Sell": short_name(move["out"], clubs),
                               "Buy": short_name(move["in"], clubs),
                               "Horizon gain": move["gain"], "Hit": -move["hit"],
                               "Net gain": move["net_gain"], "Bank after": pounds(move["bank_after"])})
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
        best_move = suggestions[0]
        st.info(f"Top model suggestion: **{short_name(best_move['out'], clubs)} → {short_name(best_move['in'], clubs)}** · {best_move['net_gain']:+.1f} net xP across {len(gws)} GW(s).")
    else:
        st.info("No legal transfer improvements found for these settings.")
    st.divider()
    st.markdown("### Manual Transfer Builder")
    col_sell, col_buy = st.columns(2)
    with col_sell:
        sell_id = st.selectbox("Transfer out", sorted(int(p["id"]) for p in squad), format_func=lambda pid: labels[pid])
    outgoing = next(p for p in squad if int(p["id"]) == sell_id)
    eligible = [p for p in players if int(p["element_type"]) == int(outgoing["element_type"])
                and int(p["id"]) not in {int(s["id"]) for s in squad}
                and int(p["now_cost"]) <= bank + int(outgoing.get("selling_price", outgoing["now_cost"]))]
    eligible.sort(key=lambda p: horizon_xp(p, gws, fixture_map, minutes_overrides), reverse=True)
    with col_buy:
        buy_id = st.selectbox("Transfer in (affordable)", [int(p["id"]) for p in eligible],
                              format_func=lambda pid: labels[pid], placeholder="Select a player") if eligible else None
    if buy_id is not None:
        incoming = player_by_id[buy_id]
        proposed = [p for p in squad if int(p["id"]) != sell_id] + [incoming]
        if valid_squad(proposed):
            before = assessment["total_xp"]
            after = team_rating(proposed, gws, fixture_map, minutes_overrides)
            gain = round(after["total_xp"] - before, 2)
            post_bank = bank + int(outgoing.get("selling_price", outgoing["now_cost"])) - int(incoming["now_cost"])
            c1, c2, c3 = st.columns(3)
            c1.metric("Before", f"{before:.1f} xP")
            c2.metric("After", f"{after['total_xp']:.1f} xP", delta=f"{gain:+.1f}")
            c3.metric("Bank after", pounds(post_bank))
            if st.button("Apply transfer to draft", type="primary"):
                st.session_state.draft = proposed
                st.session_state.bank = post_bank
                st.session_state.moves.append((sell_id, buy_id))
                st.session_state.manual_xi = []
                st.session_state.manual_captain = None
                st.session_state.chip_result = None
                st.rerun()
        else:
            st.warning("This player would violate the three-per-club rule. Choose a different replacement.")
    if st.session_state.moves:
        st.caption(f"Draft transfers applied: {len(st.session_state.moves)}. These are NOT submitted to your FPL account.")
        if st.button("Discard transfers / Restore imported squad"):
            st.session_state.loaded_id = None
            st.rerun()

with chip_tab:
    st.markdown("### Wildcard / Free Hit Squad Optimiser")
    st.caption("Build a legal 15-player squad of 2 GKP, 5 DEF, 5 MID and 3 FWD, with a maximum of three players per club.")
    chip_mode = st.radio("Chip simulation", ["Wildcard", "Free Hit"], horizontal=True)
    if chip_mode == "Free Hit":
        chip_gws = [selected_gw]
        st.info("Free Hit is optimised for one selected Gameweek only. Your imported FPL squad is not changed.")
    else:
        chip_gws = gws
        st.info(f"Wildcard optimises across {len(chip_gws)} selected Gameweek(s). This is a draft, not a chip activation.")
    # Whole-squad liquidation budget is a conservative approximation; carried
    # players may be cheaper to retain than rebuying them at current prices.
    liquidation = sum(int(p.get("selling_price", p.get("now_cost", 0))) for p in squad) + bank
    manual_budget = st.number_input("Total budget (£m)", min_value=70.0, max_value=130.0,
                                     value=float(round(liquidation / 10, 1)), step=0.1)
    budget_tenths = round(manual_budget * 10)
    st.caption("Budget defaults to squad selling value + cash. Suggested players are purchased at current FPL prices; future price changes are not forecast.")
    if st.button(f"✨ Generate {chip_mode} Squad", type="primary"):
        try:
            with st.spinner("Evaluating legal teams using free FPL statistics..."):
                result = optimise_chip_squad(players, chip_gws, fixture_map, budget_tenths,
                                             minutes_overrides=minutes_overrides, shortlist=24)
            st.session_state.chip_result = {"mode": chip_mode, "gws": chip_gws[:],
                                            "budget": budget_tenths, "result": result}
        except (ValueError, KeyError) as exc:
            st.session_state.chip_result = None
            st.error(str(exc))
    saved = st.session_state.get("chip_result")
    if saved and (saved["mode"] != chip_mode or saved["gws"] != chip_gws or saved["budget"] != budget_tenths):
        saved = None
        st.caption("Settings changed; generate again to see an updated team.")
    if saved:
        result = saved["result"]
        proposed = result["squad"]
        chip_lineup = best_lineup(proposed, selected_gw, fixture_map, minutes_overrides)
        c1, c2, c3 = st.columns(3)
        c1.metric("Projected Rating", f"{result['rating']['rating']}/100")
        c2.metric("Total predicted xP", f"{result['rating']['total_xp']:.1f}")
        c3.metric("Unspent budget", pounds(result["bank"]))
        st.markdown("**Recommended Starting XI**")
        render_pitch(chip_lineup["xi"], int(chip_lineup["captain"]["id"]),
                     int(chip_lineup["vice"]["id"]), selected_gw, fixture_map, clubs, minutes_overrides)
        st.dataframe(squad_table(proposed, chip_gws, fixture_map, clubs, minutes_overrides),
                     use_container_width=True, hide_index=True)
        st.warning("Greedy optimisation is approximate, not globally optimal. It does not model chips other than the selected simulation, auto-subs, changing prices or future injury reports.")
        if st.button("Use this squad as an editable draft", use_container_width=True):
            # Simulated chip squads may be explored in Transfers/My Team, but
            # remain separate from actual account changes.
            st.session_state.draft = [dict(p, selling_price=int(p["now_cost"])) for p in proposed]
            st.session_state.bank = int(result["bank"])
            st.session_state.manual_xi = []
            st.session_state.manual_captain = None
            st.session_state.moves = []
            st.session_state.chip_result = None
            st.rerun()

with accuracy_tab:
    st.markdown("### Forecast History & Honest Backtesting")
    st.info("Save predictions **before each FPL deadline**, then upload the saved CSV after the GW is finalized. "
            "The dashboard compares those predictions against actual FPL points. "
            "Recreating old predictions from today's player statistics would leak future data.")
    col1, col2 = st.columns([1.1, 1])
    current_event = next((e for e in events if int(e["id"]) == selected_gw), {})
    deadline_string = current_event.get("deadline_time", "")
    can_capture = False
    try:
        capture_deadline = datetime.fromisoformat(deadline_string.replace("Z", "+00:00"))
        can_capture = datetime.now(timezone.utc) < capture_deadline
    except (ValueError, AttributeError):
        pass
    with col1:
        st.markdown("**1. Capture a pre-deadline prediction**")
        st.write(f"Selected GW: **{selected_gw}** · Deadline: **{deadline_string or 'unknown'}**")
        st.caption("Captures projections for all players scheduled to play, not only your own squad. "
                   "The generated CSV is your forecast audit trail.")
        if st.button("Capture predictions for this GW", disabled=not can_capture, type="primary"):
            try:
                new_rows = make_snapshot(players, selected_gw, fixture_map,
                                         deadline_string, season_id, minutes_overrides)
                st.session_state.saved_snapshots = [r for r in st.session_state.get("saved_snapshots", [])
                                                    if int(r["gw"]) != selected_gw] + new_rows
                st.success(f"Captured {len(new_rows)} predictions. Download the CSV below.")
            except ValueError as exc:
                st.error(str(exc))
        if not can_capture:
            st.warning("This GW deadline has passed (or is unknown). New snapshots are disabled.")
        saved = [r for r in st.session_state.get("saved_snapshots", [])
                 if int(r["gw"]) == selected_gw]
        if saved:
            data = pd.DataFrame(saved, columns=list(SNAPSHOT_FIELDS))
            st.download_button("⬇ Download forecast CSV — keep this file", data.to_csv(index=False).encode("utf-8"),
                               file_name=f"ajk_forecast_{season_id}_gw{selected_gw}.csv",
                               mime="text/csv")
    with col2:
        st.markdown("**2. Load final GW points**")
        st.caption("Upload past forecast CSV files in the sidebar. Click below to obtain official final scores "
                   "for their gameweeks. No API score is considered final until FPL marks the event data checked.")
        to_load = sorted({r["gw"] for r in validated_snapshots if r["gw"] in finalized_gws})
        st.write(f"Valid archived forecasts: **{len(validated_snapshots)}** player-GW rows, "
                 f"across **{len(set(r['gw'] for r in validated_snapshots))}** GWs")
        if st.button("Load finalized FPL actual points", disabled=not to_load):
            fetched = dict(st.session_state.get("accuracy_actuals", {}))
            errors = []
            for gw in to_load:
                try:
                    live = get_json(f"event/{gw}/live/")
                    fetched[gw] = {int(e["id"]): int(e.get("stats", {}).get("total_points", 0))
                                   for e in live.get("elements", [])}
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    errors.append(f"GW {gw}: {exc}")
            st.session_state.accuracy_actuals = fetched
            if errors:
                st.warning("Unable to fetch: " + "; ".join(errors[:4]))
            else:
                st.success("Final gameweek points loaded. The calibration will update on rerun.")
            st.rerun()
        st.metric("Finalized, matched predictions", len(completed_rows))
        st.metric("Earlier-GW training examples", calibration_state["count"])
    st.divider()
    if completed_rows:
        overall, by_position, by_gw = backtest_report(completed_rows)
        st.markdown("### Accuracy results")
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("Captured forecast MAE", f"{overall['captured_mae']:.2f} pts")
        x2.metric("Uncalibrated MAE", f"{overall['raw_mae']:.2f} pts")
        x3.metric("Walk-forward MAE", f"{overall['walk_forward_mae']:.2f} pts")
        x4.metric("Forecast bias", f"{overall['bias']:+.2f} pts")
        st.caption("MAE = mean absolute error, lower is better. Bias = predicted − actual; "
                   "positive means overprediction. Walk-forward estimates each GW using *only earlier* finalized GWs. "
                   "Captured MAE reflects the actual saved model predictions; walk-forward MAE is a retrospective calibration simulation.")
        st.markdown("**By position**")
        st.dataframe(pd.DataFrame(by_position), hide_index=True, use_container_width=True)
        st.markdown("**By gameweek**")
        chart_df = pd.DataFrame(by_gw).set_index("GW")
        st.line_chart(chart_df[["captured_mae", "raw_mae", "walk_forward_mae"]])
        st.dataframe(pd.DataFrame(by_gw), hide_index=True, use_container_width=True)
        st.caption("A single GW is too little to establish predictive superiority. "
                   "At least several finalized GWs are needed for meaningful comparisons. "
                   "Current forecasts may include minutes overrides; saved values are evaluated as originally captured.")
    else:
        st.info("No saved pre-deadline forecasts with finalized scores yet. "
                "Capture the next GW, download the CSV, then return after FPL has finalized it.")

st.divider()
st.caption("Data: official Fantasy Premier League public API. Player projections, ratings, transfer scores and optimisation are independent AJK estimates; no affiliation with Fantasy Football Hub or the Premier League. Use the official FPL site to make actual transfers or activate chips.")
