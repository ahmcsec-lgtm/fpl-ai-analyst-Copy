"""AJK Bola Wawei AI v5 — minimal My Team + Smart Transfer Advisor.

Install: pip install streamlit requests pandas
Run: streamlit run app.py
Read-only access to public Fantasy Premier League APIs. No FPL account login.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
import html

import pandas as pd
import requests
import streamlit as st

from fpl_engine import (
    POSITION_NAMES, SNAPSHOT_FIELDS, backtest_report, best_lineup,
    configure_calibration, configure_projection_context, fixture_lookup,
    horizon_xp, join_actuals, make_snapshot, num, optimise_chip_squad,
    player_fixture_xp, player_prediction, projected_minutes,
    smart_transfer_plan, team_rating, valid_squad, validate_snapshots,
)

API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "AJK-Bola-Wawei-AI/5.0 (public FPL data)"}

st.set_page_config(page_title="AJK Bola Wawei AI", page_icon="⚽", layout="wide")
st.markdown("""
<style>
.block-container{max-width:1150px;padding-top:1.5rem;padding-bottom:4rem}
[data-testid="stMetric"]{padding:14px;border-radius:14px;border:1px solid rgba(120,120,120,.22)}
.pitch{background:linear-gradient(180deg,#08754d,#084f3c);color:white;border-radius:16px;
  border:1px solid #54a982;padding:13px 5px;margin:12px 0}
.pitch-row{display:flex;justify-content:space-evenly;gap:5px;margin:15px 0}
.pitch-player{min-width:0;width:19%;max-width:160px;border-radius:10px;text-align:center;
  background:rgba(0,0,0,.28);padding:9px 3px;font-size:12px}
.pitch-player strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pitch-player small{display:block;opacity:.85}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner=False)
def get_json(path: str) -> dict | list:
    response = requests.get(f"{API}/{path.lstrip('/')}", headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.json()


def money(tenths: int | float) -> str:
    return f"£{num(tenths)/10:.1f}m"


def label(player: dict, clubs: dict[int, str]) -> str:
    return f"{player.get('web_name', '?')} · {clubs.get(int(player.get('team', 0)), '?')} · {money(player.get('now_cost', 0))}"


def load_manager(team_id: int, events: list[dict], player_by_id: dict) -> tuple[dict, list[dict], int, int]:
    profile = get_json(f"entry/{team_id}/")
    eligible = sorted((int(e["id"]) for e in events if e.get("finished") or e.get("is_current")), reverse=True)
    for gw in eligible[:10]:
        try:
            picks = get_json(f"entry/{team_id}/event/{gw}/picks/")
        except (ValueError, requests.RequestException):
            continue
        if len(picks.get("picks", [])) != 15:
            continue
        squad = []
        for item in picks["picks"]:
            player = player_by_id.get(int(item["element"]))
            if player:
                squad.append({**player, "selling_price": int(item.get("selling_price") or player.get("now_cost", 0))})
        if valid_squad(squad):
            bank = int(picks.get("entry_history", {}).get("bank") or 0)
            return profile, squad, bank, gw
    raise ValueError("Unable to find a complete public 15-player team. Check your Team ID.")


def pitch(xi: list[dict], captain_id: int, vice_id: int, gw: int,
          fixture_map: dict, clubs: dict, overrides: dict) -> None:
    lines = []
    for pos in (4, 3, 2, 1):
        cards = []
        for player in xi:
            if int(player["element_type"]) != pos:
                continue
            pid = int(player["id"])
            suffix = " (C)" if pid == captain_id else " (VC)" if pid == vice_id else ""
            name = html.escape(str(player.get("web_name", "?")) + suffix)
            club = html.escape(clubs.get(int(player["team"]), "?"))
            xp = player_fixture_xp(player, gw, fixture_map, overrides)
            cards.append(f'<div class="pitch-player"><strong>{name}</strong><small>{club} · {xp:.1f} xP</small></div>')
        lines.append('<div class="pitch-row">' + "".join(cards) + '</div>')
    st.markdown('<div class="pitch">' + "".join(lines) + '</div>', unsafe_allow_html=True)


def squad_frame(squad: list[dict], gws: list[int], fixture_map: dict,
                clubs: dict, overrides: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Player": label(p, clubs), "Position": POSITION_NAMES[int(p["element_type"])],
        "GW xP": round(player_fixture_xp(p, gws[0], fixture_map, overrides), 2),
        "Horizon xP": round(horizon_xp(p, gws, fixture_map, overrides), 2),
        "Sell price": money(p.get("selling_price", p.get("now_cost", 0))),
        "Status": p.get("status", "?"),
    } for p in squad])


def reset_draft(team_id: int, profile: dict, squad: list[dict], bank: int, from_gw: int) -> None:
    st.session_state.loaded_id = team_id
    st.session_state.manager_profile = profile
    st.session_state.original_squad = [dict(p) for p in squad]
    st.session_state.original_bank = bank
    st.session_state.draft = [dict(p) for p in squad]
    st.session_state.bank = bank
    st.session_state.from_gw = from_gw
    st.session_state.manual_xi = []
    st.session_state.manual_captain = None
    st.session_state.draft_moves = []
    st.session_state.chip_result = None


st.title("⚽ AJK Bola Wawei AI")
st.caption("My Team + Smart Transfer Advisor · Free, independent FPL projections")

with st.form("team_import"):
    input_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
    with input_col:
        # Intentionally blank: no personal FPL Team ID is hardcoded or preselected.
        team_text = st.text_input("FPL Team ID", value="", placeholder="Enter your FPL Team ID")
    with button_col:
        submitted = st.form_submit_button("Analyse Team", type="primary", use_container_width=True)

try:
    bootstrap = get_json("bootstrap-static/")
    fixture_rows = get_json("fixtures/")
except (requests.RequestException, ValueError, KeyError) as exc:
    st.error(f"Cannot load public FPL data: {exc}")
    st.stop()

players = bootstrap.get("elements", [])
player_by_id = {int(p["id"]): p for p in players}
clubs = {int(c["id"]): c.get("short_name", "?") for c in bootstrap.get("teams", [])}
events = bootstrap.get("events", [])
fixture_map = fixture_lookup(fixture_rows)
configure_projection_context(bootstrap.get("teams", []), fixture_rows)
upcoming = [e for e in events if e.get("is_next")]
if upcoming:
    first_gw = int(upcoming[0]["id"])
else:
    first_gw = next((int(e["id"]) for e in events if not e.get("finished")), 0)
available_gws = [int(e["id"]) for e in events if int(e["id"]) >= first_gw][:6]
if not available_gws or first_gw == 0:
    st.info("No upcoming Gameweek is currently published by FPL.")
    st.stop()

if submitted:
    value = team_text.strip()
    if not value.isdecimal() or int(value) <= 0:
        st.error("Enter a valid numeric FPL Team ID.")
    else:
        try:
            profile, imported, cash, loaded_gw = load_manager(int(value), events, player_by_id)
            reset_draft(int(value), profile, imported, cash, loaded_gw)
            st.rerun()
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            st.error(f"Team could not be imported: {exc}")

if "draft" not in st.session_state:
    st.info("Enter your FPL Team ID above to see your squad and personalised transfer advice. No ID is stored in the code.")
    st.stop()

squad = st.session_state.draft
bank = int(st.session_state.bank)
profile = st.session_state.manager_profile
if not valid_squad(squad):
    st.error("Your simulated draft is invalid. Restore your imported squad in Advanced settings.")
    st.stop()

with st.expander("⚙️ Planning settings", expanded=False):
    c1, c2, c3 = st.columns(3)
    selected_gw = c1.selectbox("Starting Gameweek", available_gws, format_func=lambda gw: f"GW {gw}")
    horizon_list = [gw for gw in available_gws if gw >= selected_gw]
    horizon = c2.select_slider("Look ahead", options=list(range(1, len(horizon_list) + 1)), value=min(5, len(horizon_list)), format_func=lambda x: f"{x} GW" if x == 1 else f"{x} GWs")
    strategy = c3.selectbox("AI Strategy", ["Balanced", "Safe", "Aggressive"])
    ft = st.number_input("Free transfers available (check your FPL account)", min_value=0, max_value=5, value=1)
    st.caption("Safe applies a modest penalty to low-minute players. Aggressive prioritises upside. The risk settings are heuristics, not calibrated probabilities.")
    minutes_overrides = {}
    with st.expander("Optional player minutes assumptions"):
        for p in squad:
            pid = int(p["id"])
            minutes_overrides[pid] = st.slider(label(p, clubs), 0, 90,
                                                value=int(round(projected_minutes(p) / 5) * 5), step=5,
                                                key=f"mins_{st.session_state.loaded_id}_{pid}")
    if st.button("Restore original imported squad", use_container_width=True):
        st.session_state.draft = [dict(p) for p in st.session_state.original_squad]
        st.session_state.bank = st.session_state.original_bank
        st.session_state.draft_moves = []
        st.session_state.manual_xi = []
        st.session_state.manual_captain = None
        st.rerun()

# Stable defaults on the first render, independent of the optional expander.
selected_gw = locals().get("selected_gw", available_gws[0])
horizon = locals().get("horizon", min(5, len(available_gws)))
strategy = locals().get("strategy", "Balanced")
ft = int(locals().get("ft", 1))
minutes_overrides = locals().get("minutes_overrides", {})
gws = [gw for gw in available_gws if gw >= selected_gw][:int(horizon)]

# Keep v4 honest calibration, but move its controls behind an expandable section.
season_first = next((e.get("deadline_time") for e in events if int(e["id"]) == 1), None)
season_year = str(season_first)[:4] if season_first else str(datetime.now(timezone.utc).year)
season_id = f"{season_year}-{str(int(season_year) + 1)[-2:]}"
validated = validate_snapshots(st.session_state.get("saved_snapshots", []), season_id)
finalized = {int(e["id"]) for e in events if e.get("finished") and e.get("data_checked")}
actuals = st.session_state.get("accuracy_actuals", {})
completed = join_actuals(validated, actuals, finalized)
calibration = configure_calibration(completed, selected_gw)

assessment = team_rating(squad, gws, fixture_map, minutes_overrides)
lineup = best_lineup(squad, selected_gw, fixture_map, minutes_overrides)
st.subheader(profile.get("name", "My FPL Team"))
st.caption(f"Imported from GW {st.session_state.from_gw} · Current view: GW {selected_gw} · All changes are simulations only")
metrics = st.columns(4)
metrics[0].metric("Team Rating", f"{assessment['rating']}/100")
metrics[1].metric(f"GW {selected_gw} xP", f"{lineup['total_xp']:.1f}")
metrics[2].metric(f"{len(gws)}-GW projected", f"{assessment['total_xp']:.1f}")
metrics[3].metric("Bank", money(bank))

st.divider()
st.subheader("🧠 Smart Transfer Advisor")
st.caption("Looks ahead across your selected Gameweeks. Compares rolling, one transfer and two-transfer combinations, including hits and captaincy.")
settings_key = (st.session_state.loaded_id, tuple(sorted(int(p["id"]) for p in squad)),
                bank, ft, tuple(gws), strategy, tuple(sorted(minutes_overrides.items())))
if st.session_state.get("advisor_key") != settings_key:
    st.session_state.advisor_result = None

if st.button("✨ Find my best transfer strategy", type="primary", use_container_width=True):
    try:
        with st.spinner("Comparing legal transfers and the option to roll..."):
            result = smart_transfer_plan(squad, players, gws, fixture_map, bank,
                                         free_transfers=ft, strategy=strategy,
                                         minutes_overrides=minutes_overrides)
        st.session_state.advisor_result = result
        st.session_state.advisor_key = settings_key
    except (KeyError, ValueError, TypeError) as exc:
        st.error(f"Could not optimise this squad: {exc}")

advice = st.session_state.get("advisor_result")
if advice and st.session_state.get("advisor_key") == settings_key:
    if advice["action"] == "ROLL":
        st.success("**Best action for this GW: ROLL your free transfer.** The model found more value in waiting across the chosen horizon.")
    else:
        moves = advice["first_moves"]
        st.success("**Recommended now:** " + " + ".join(f"{m['out_name']} → {m['in_name']}" for m in moves))
    p1, p2, p3 = st.columns(3)
    p1.metric("Net projected gain", f"{advice['expected_gain']:+.1f} pts")
    p2.metric("Hits this GW", f"-{advice['first_hit']} pts")
    p3.metric("Horizon net xP", f"{advice['planned_net_xp']:.1f}")
    st.caption("Projected difference versus making no transfers; includes future simulated moves and any predicted hit costs. Not a guaranteed gain.")
    if advice["first_moves"]:
        if st.button("Apply recommended transfers to my draft", use_container_width=True):
            proposed = [dict(p) for p in squad]
            draft_bank = bank
            try:
                for move in advice["first_moves"]:
                    out = next(p for p in proposed if int(p["id"]) == move["out"])
                    new_player = player_by_id[move["in"]]
                    draft_bank += int(out.get("selling_price", out["now_cost"])) - int(new_player["now_cost"])
                    proposed = [p for p in proposed if int(p["id"]) != move["out"]]
                    proposed.append({**new_player, "selling_price": int(new_player["now_cost"])})
                if not valid_squad(proposed) or draft_bank < 0:
                    raise ValueError("An invalid proposal was produced; no draft was changed.")
                st.session_state.draft = proposed
                st.session_state.bank = draft_bank
                st.session_state.draft_moves += advice["first_moves"]
                st.session_state.manual_xi = []
                st.session_state.manual_captain = None
                st.session_state.advisor_result = None
                st.rerun()
            except (ValueError, StopIteration, KeyError) as exc:
                st.error(str(exc))
    with st.expander("View the full Gameweek-by-Gameweek plan"):
        for row in advice["plan"]:
            desc = "Roll / no transfers" if not row["moves"] else ", ".join(
                f"{m['out_name']} → {m['in_name']}" for m in row["moves"])
            st.write(f"**GW {row['gw']}** — {desc} · {row['projected_xp']:.1f} xP · "
                     f"-{row['hits']} hit · {row['free_transfers_after']} FT next GW · Bank {money(row['bank'])}")
        st.caption("Future transfers use today's prices and availability; re-run after every deadline or price change. The bounded search may miss a better plan.")

st.divider()
with st.expander("🏟️ My Team · Pitch, captain & manual changes", expanded=True):
    auto_xi = lineup["xi"]
    manual_ids = set(st.session_state.get("manual_xi", []))
    xi = [p for p in squad if int(p["id"]) in manual_ids] if len(manual_ids) == 11 else auto_xi
    counts = Counter(int(p["element_type"]) for p in xi)
    if len(xi) != 11 or not (counts[1] == 1 and 3 <= counts[2] <= 5 and 2 <= counts[3] <= 5 and 1 <= counts[4] <= 3):
        xi = auto_xi
    cap_ids = [int(p["id"]) for p in xi]
    cap_default = st.session_state.get("manual_captain")
    cap = cap_default if cap_default in cap_ids else int(lineup["captain"]["id"])
    if cap not in cap_ids:
        cap = max(xi, key=lambda p: player_fixture_xp(p, selected_gw, fixture_map, minutes_overrides))["id"]
    vice = next(pid for pid in cap_ids if pid != cap)
    pitch(xi, cap, vice, selected_gw, fixture_map, clubs, minutes_overrides)
    c1, c2 = st.columns(2)
    with c1:
        captain = st.selectbox("Captain", cap_ids, index=cap_ids.index(cap),
                               format_func=lambda pid: label(player_by_id[pid], clubs))
        if captain != cap:
            st.session_state.manual_captain = captain
            st.rerun()
    with c2:
        st.caption("The pitch defaults to the model's best XI. Select a starter and a bench player below to make a manual swap.")
    benched = [p for p in squad if int(p["id"]) not in set(cap_ids)]
    col_out, col_in = st.columns(2)
    bench_out = col_out.selectbox("Starter to bench", cap_ids, format_func=lambda pid: label(player_by_id[pid], clubs))
    bench_in = col_in.selectbox("Bench player to start", [int(p["id"]) for p in benched],
                                format_func=lambda pid: label(player_by_id[pid], clubs))
    if st.button("Swap starting XI"):
        test_ids = (set(cap_ids) - {bench_out}) | {bench_in}
        proposed = [p for p in squad if int(p["id"]) in test_ids]
        c = Counter(int(p["element_type"]) for p in proposed)
        if len(proposed) == 11 and c[1] == 1 and 3 <= c[2] <= 5 and 2 <= c[3] <= 5 and 1 <= c[4] <= 3:
            st.session_state.manual_xi = list(test_ids)
            st.session_state.manual_captain = captain if captain in test_ids else None
            st.rerun()
        else:
            st.warning("Invalid formation. A legal XI needs 1 GKP, 3–5 DEF, 2–5 MID and 1–3 FWD.")
    if st.button("Restore best XI and captain"):
        st.session_state.manual_xi = []
        st.session_state.manual_captain = None
        st.rerun()
    st.dataframe(squad_frame(squad, gws, fixture_map, clubs, minutes_overrides),
                 hide_index=True, use_container_width=True)
    risky = [p for p in squad if p.get("status", "a") != "a"]
    if risky:
        st.warning("Check availability: " + ", ".join(p.get("web_name", "?") for p in risky))

with st.expander("🔁 Manual Transfer · Compare and edit your draft"):
    options = {int(p["id"]): label(p, clubs) for p in squad}
    sell = st.selectbox("Transfer out", list(options), format_func=lambda pid: options[pid])
    departing = next(p for p in squad if int(p["id"]) == sell)
    owned_ids = {int(p["id"]) for p in squad}
    affordability = bank + int(departing.get("selling_price", departing["now_cost"]))
    candidates = [p for p in players if int(p["element_type"]) == int(departing["element_type"])
                  and int(p["id"]) not in owned_ids and int(p["now_cost"]) <= affordability]
    candidates.sort(key=lambda p: horizon_xp(p, gws, fixture_map, minutes_overrides), reverse=True)
    new_id = st.selectbox("Transfer in", [int(p["id"]) for p in candidates],
                          format_func=lambda pid: label(player_by_id[pid], clubs)) if candidates else None
    if new_id is not None:
        incoming = player_by_id[new_id]
        proposal = [p for p in squad if int(p["id"]) != sell] + [incoming]
        if valid_squad(proposal):
            delta = team_rating(proposal, gws, fixture_map, minutes_overrides)["total_xp"] - assessment["total_xp"]
            post_bank = affordability - int(incoming["now_cost"])
            st.write(f"**Projected improvement:** {delta:+.1f} xP before transfer hits · **Bank afterward:** {money(post_bank)}")
            if st.button("Apply manual transfer to draft"):
                st.session_state.draft = [p for p in squad if int(p["id"]) != sell] + [
                    {**incoming, "selling_price": int(incoming["now_cost"])}]
                st.session_state.bank = post_bank
                st.session_state.draft_moves.append({"out": sell, "in": new_id})
                st.session_state.manual_xi = []
                st.session_state.manual_captain = None
                st.rerun()
        else:
            st.warning("That transfer exceeds the maximum three players per club.")

with st.expander("✨ Wildcard / Free Hit · Generate a full squad"):
    chip = st.radio("Simulation", ["Wildcard", "Free Hit"], horizontal=True)
    chip_gws = gws if chip == "Wildcard" else [selected_gw]
    liquidation = bank + sum(int(p.get("selling_price", p["now_cost"])) for p in squad)
    st.caption(f"Estimated available budget: {money(liquidation)} from your current selling prices + bank.")
    if st.button(f"Generate {chip} squad"):
        try:
            with st.spinner("Building a legal squad..."):
                result = optimise_chip_squad(players, chip_gws, fixture_map, liquidation,
                                             minutes_overrides=minutes_overrides, shortlist=24)
            st.session_state.chip_result = {"kind": chip, "gws": chip_gws, "result": result}
        except (ValueError, TypeError, KeyError) as exc:
            st.error(str(exc))
    proposed_chip = st.session_state.get("chip_result")
    if proposed_chip and proposed_chip["kind"] == chip and proposed_chip["gws"] == chip_gws:
        result = proposed_chip["result"]
        st.write(f"**Squad rating:** {result['rating']['rating']}/100 · "
                 f"**Projected xP:** {result['rating']['total_xp']:.1f} · **Bank:** {money(result['bank'])}")
        chip_xi = best_lineup(result["squad"], selected_gw, fixture_map, minutes_overrides)
        pitch(chip_xi["xi"], int(chip_xi["captain"]["id"]), int(chip_xi["vice"]["id"]),
              selected_gw, fixture_map, clubs, minutes_overrides)
        st.dataframe(squad_frame(result["squad"], chip_gws, fixture_map, clubs, minutes_overrides),
                     hide_index=True, use_container_width=True)
        st.caption("Approximate greedy optimiser. Free Hit is a single-GW simulation, not a chip activation.")
        if st.button("Use this team as my editable draft"):
            st.session_state.draft = [{**p, "selling_price": int(p["now_cost"])} for p in result["squad"]]
            st.session_state.bank = result["bank"]
            st.session_state.manual_xi = []
            st.session_state.manual_captain = None
            st.session_state.draft_moves = []
            st.session_state.chip_result = None
            st.rerun()

with st.expander("📈 Model Accuracy · Forecast history and calibration"):
    st.caption("Capture predictions before a deadline, save the CSV, then compare with actual points once FPL has finalized the GW. Imported CSVs are treated as user-provided records.")
    uploads = st.file_uploader("Restore forecast CSV backups", type="csv", accept_multiple_files=True)
    upload_rows = []
    for upload in uploads or []:
        try:
            frame = pd.read_csv(BytesIO(upload.getvalue()))
            if len(frame) <= 4000 and set(SNAPSHOT_FIELDS).issubset(frame.columns):
                upload_rows.extend(frame.to_dict("records"))
            else:
                st.warning(f"Skipped {upload.name}: invalid format or file too large")
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            st.warning(f"Skipped {upload.name}: {exc}")
    all_rows = validate_snapshots(upload_rows + st.session_state.get("saved_snapshots", []), season_id)
    deadline = next((e.get("deadline_time", "") for e in events if int(e["id"]) == selected_gw), "")
    try:
        before_deadline = datetime.now(timezone.utc) < datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except ValueError:
        before_deadline = False
    if st.button(f"Capture predictions for GW {selected_gw}", disabled=not before_deadline):
        rows = make_snapshot(players, selected_gw, fixture_map, deadline, season_id, minutes_overrides)
        st.session_state.saved_snapshots = [r for r in st.session_state.get("saved_snapshots", [])
                                            if int(r["gw"]) != selected_gw] + rows
        st.rerun()
    current = [r for r in st.session_state.get("saved_snapshots", []) if int(r["gw"]) == selected_gw]
    if current:
        st.download_button("Download your pre-deadline forecast CSV",
                           data=pd.DataFrame(current, columns=list(SNAPSHOT_FIELDS)).to_csv(index=False).encode("utf-8"),
                           file_name=f"ajk_forecast_{season_id}_gw{selected_gw}.csv", mime="text/csv")
    archived = sorted({int(r["gw"]) for r in all_rows if int(r["gw"]) in finalized})
    if st.button("Load finalized actual FPL points", disabled=not archived):
        fetched = dict(st.session_state.get("accuracy_actuals", {}))
        for gw in archived:
            try:
                payload = get_json(f"event/{gw}/live/")
                fetched[gw] = {int(p["id"]): int(p.get("stats", {}).get("total_points", 0))
                               for p in payload.get("elements", [])}
            except (ValueError, requests.RequestException) as exc:
                st.warning(f"GW {gw} could not be loaded: {exc}")
        st.session_state.accuracy_actuals = fetched
        st.rerun()
    matched = join_actuals(all_rows, st.session_state.get("accuracy_actuals", {}), finalized)
    if matched:
        overall, positions, weeks = backtest_report(matched)
        c1, c2, c3 = st.columns(3)
        c1.metric("Captured MAE", f"{overall['captured_mae']:.2f}")
        c2.metric("Walk-forward MAE", f"{overall['walk_forward_mae']:.2f}")
        c3.metric("Prediction bias", f"{overall['bias']:+.2f}")
        st.dataframe(pd.DataFrame(positions), hide_index=True, use_container_width=True)
        st.dataframe(pd.DataFrame(weeks), hide_index=True, use_container_width=True)
    else:
        st.info("No finalized captured forecasts yet. Export a forecast before a GW deadline and restore it later.")
    st.caption(f"Calibration training observations from earlier finalized GWs: {calibration['count']}. Forecast history may be lost when Streamlit restarts; keep your CSV backups.")
    with st.expander("How predictions are calculated"):
        st.write("Independent statistical estimates using FPL xG/xA, past minutes, availability, fixture strengths, clean sheets, saves, bonus and defensive contributions. The optimiser maximises best XI plus captain projections after hits. Calibrated accuracy is only measurable after enough real pre-deadline forecasts have been collected. No paid provider model, guaranteed confidence or live injury intelligence is included.")

st.divider()
st.caption("Independent, free FPL analysis using the public official FPL API. No affiliation with Fantasy Football Hub or the Premier League. This app cannot submit transfers or activate chips. Optimised results are estimates, not guaranteed points.")
