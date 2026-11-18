"""AJK Bola Wawei AI v5.5.1 — simplified planning settings.

Install: pip install streamlit requests pandas
Run: streamlit run app.py
Read-only access to public Fantasy Premier League APIs. No FPL account login.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
import html
import re

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
HEADERS = {"User-Agent": "AJK-Bola-Wawei-AI/5.5.1 (public FPL data)"}

st.set_page_config(page_title="AJK Bola Wawei AI", page_icon="⚽", layout="wide", initial_sidebar_state="collapsed")
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
.player-portrait{width:60px;height:68px;max-width:94%;object-fit:contain;object-position:bottom;
  display:block;margin:0 auto 5px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.25))}
.portrait-shell{width:64px;height:72px;max-width:95%;margin:0 auto 5px;display:flex;
  align-items:end;justify-content:center;border-radius:12px 12px 6px 6px;
  background:rgba(255,255,255,.11);overflow:hidden}
.portrait-fallback{position:absolute;align-self:center;font-size:22px;color:white;opacity:.8}
.portrait-shell{position:relative}
.portrait-shell img{position:relative;z-index:1}
.transfer-faces{display:flex;gap:12px;justify-content:center;align-items:center;
  padding:12px 8px;border:1px solid rgba(120,120,120,.22);border-radius:15px;margin:10px 0}
.transfer-person{flex:1;min-width:0;text-align:center}
.transfer-person img{width:85px;height:94px;max-width:100%;object-fit:contain;object-position:bottom}
.transfer-person strong{display:block;overflow-wrap:anywhere}
.transfer-person small{display:block;opacity:.75}
.transfer-arrow{font-size:25px;opacity:.8}
@media(max-width:550px){.pitch-player{padding:6px 2px;font-size:10px}
  .pitch-row{gap:3px;margin:10px 0}.portrait-shell{height:50px;width:50px}
  .player-portrait{height:48px;width:48px}.pitch-player small{font-size:9px}
  .transfer-person img{width:65px;height:75px}}

/* v5.2 premium styling; keeps native Streamlit controls usable */
:root{--ajk-green:#20d99a;--ajk-border:rgba(143,179,171,.19)}
[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 85% 0%,rgba(32,217,154,.085),transparent 34%),#0c151a;color:#eaf6f1}
[data-testid="stHeader"]{background:transparent}
.block-container{max-width:1160px;padding-top:1.15rem;padding-bottom:4rem}
h1,h2,h3{letter-spacing:-.035em}
[data-testid="stMetric"]{background:linear-gradient(135deg,rgba(26,51,53,.9),rgba(12,30,35,.95));border:1px solid var(--ajk-border)!important;border-radius:18px!important;padding:16px!important}
[data-testid="stMetricLabel"]{color:#a6c3b9}
[data-testid="stMetricValue"]{font-weight:750;letter-spacing:-.04em}
[data-testid="stExpander"]{background:rgba(18,34,39,.85);border:1px solid var(--ajk-border);border-radius:16px;margin-bottom:12px}
[data-testid="stButton"] button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"]{background:linear-gradient(100deg,#11a977,#21cb91);border:0;color:#061b17;border-radius:12px;font-weight:750}
[data-testid="stButton"] button{border-radius:12px}
.ajk-hero{background:linear-gradient(115deg,#133b36,#14232d 65%,#16242a);padding:20px 24px;border:1px solid #285c53;border-radius:22px;margin-bottom:14px;position:relative;overflow:hidden}
.ajk-hero:before{content:"";position:absolute;right:-45px;top:-75px;height:190px;width:190px;border:1px solid rgba(60,235,165,.22);border-radius:50%}
.ajk-kicker{color:#76e7bf;font-size:11px;letter-spacing:.18em;font-weight:800;margin-bottom:5px}
.ajk-hero h1{font-size:clamp(27px,4vw,41px);margin:0;color:#f3fff9;line-height:1.15}
.ajk-hero p{color:#bbd8cd;font-size:14px;margin:8px 0 0}
.ajk-rating{display:flex;align-items:center;gap:24px;justify-content:space-between;padding:17px 22px;border-radius:20px;background:linear-gradient(110deg,#12382f,#122630);border:1px solid rgba(55,190,140,.32);margin:12px 0}
.ajk-rating .main{font-size:31px;font-weight:850;letter-spacing:-1px;color:white}.ajk-rating .sub{color:#a9c9bc;font-size:12px}.ajk-rating .eyebrow{color:#77e5ba;font-size:11px;letter-spacing:1.6px;font-weight:800}
.ajk-rating .circle{width:100px;height:100px;border-radius:50%;display:grid;place-items:center;flex:none}
.ajk-rating .inner{width:77px;height:77px;background:#132d2a;border-radius:50%;display:grid;place-items:center;color:#e8fff7;font-size:23px;font-weight:850}
.ajk-verdict{background:linear-gradient(110deg,rgba(27,77,65,.72),rgba(17,40,48,.95));border-left:4px solid #27d69b;border-radius:15px;padding:16px 19px;margin:12px 0 16px;color:#e5fff4}
.ajk-verdict .eyebrow{font-size:11px;font-weight:800;color:#71e4b8;letter-spacing:1.4px;margin-bottom:6px}
.ajk-verdict .explain{color:#b7d3c8;font-size:12px;margin-top:6px}
.pitch{position:relative;background:repeating-linear-gradient(180deg,rgba(255,255,255,.035) 0,rgba(255,255,255,.035) 76px,transparent 76px,transparent 152px),linear-gradient(150deg,#0e8157,#075943)!important;border:1px solid rgba(122,233,182,.5)!important;border-radius:22px!important;padding:20px 7px!important;overflow:hidden}
.pitch:before{content:"";pointer-events:none;position:absolute;inset:11px;border:1px solid rgba(255,255,255,.27);border-radius:5px}
.pitch:after{content:"";pointer-events:none;position:absolute;top:50%;left:50%;width:85px;height:85px;border:1px solid rgba(255,255,255,.2);border-radius:50%;transform:translate(-50%,-50%)}
.pitch-row{position:relative;z-index:2;margin:17px 0!important}
.pitch-player{background:rgba(3,39,29,.55)!important;border:1px solid rgba(217,255,231,.20);box-shadow:0 7px 15px rgba(0,0,0,.12);backdrop-filter:blur(4px);padding:8px 3px!important;border-radius:13px!important}
.pitch-player strong{font-size:12px;color:#fff}.pitch-player small{color:#d4ffea;opacity:.94}
.pitch-player .portrait-shell{background:rgba(203,255,222,.15)}
.pitch-player .captain-marker{display:inline-block;background:#eaffab;color:#1e4935;font-size:9px;font-weight:900;border-radius:5px;padding:2px 4px;vertical-align:middle;margin-left:3px}
.transfer-faces{background:linear-gradient(100deg,rgba(14,47,51,.85),rgba(18,36,44,.96));border:1px solid rgba(47,200,150,.25)!important;border-radius:18px!important;margin:10px 0!important}
.transfer-person{padding:8px}.transfer-person strong{color:#f2fff8}.transfer-person small{color:#a8cbbf}.transfer-arrow{color:#33e4a5;font-size:30px!important;font-weight:800}
@media(max-width:640px){.ajk-hero{padding:17px}.ajk-rating{gap:10px;padding:12px}.ajk-rating .main{font-size:24px}.ajk-rating .circle{width:75px;height:75px}.ajk-rating .inner{width:56px;height:56px;font-size:18px}.pitch-row{margin:11px 0!important}.pitch-player strong{font-size:10px}}

/* v5.3 portrait-first squad pitch: familiar rows without replacing faces */
.squad-view{margin:14px 0 19px;color:#f8fffa}
.squad-field{position:relative;isolation:isolate;overflow:hidden;border-radius:18px 18px 4px 4px;
  background:repeating-linear-gradient(180deg,#008f57 0,#008f57 86px,#009d60 86px,#009d60 172px);
  padding:40px 9px 22px;box-shadow:inset 0 0 0 2px rgba(255,255,255,.35)}
.squad-field:before{content:"";position:absolute;inset:45px 10px 8px;border:2px solid rgba(255,255,255,.58);pointer-events:none;z-index:0}
.squad-pitch-topline{position:absolute;top:7px;left:12px;right:12px;display:flex;justify-content:space-between;
  font-size:12px;font-weight:800;z-index:3;color:#edfff5;text-shadow:0 1px 3px #06412f}
.squad-goal{position:absolute;top:45px;left:39%;width:22%;height:23px;border:2px solid rgba(255,255,255,.65);border-top:0}
.squad-penalty{position:absolute;top:45px;left:27%;width:46%;height:76px;border:2px solid rgba(255,255,255,.53);border-top:0}
.squad-centreline{position:absolute;top:52%;left:10px;right:10px;border-top:2px solid rgba(255,255,255,.45)}
.squad-centrecircle{position:absolute;top:52%;left:50%;width:110px;height:110px;transform:translate(-50%,-50%);
  border:2px solid rgba(255,255,255,.45);border-radius:50%}
.squad-formation-row{position:relative;z-index:1;display:flex;justify-content:space-evenly;align-items:start;
  gap:clamp(2px,.9vw,10px);margin:12px auto 25px;min-height:123px}
.squad-formation-row.pos-1{margin-top:0}
.squad-formation-row.pos-4{margin-bottom:0}
.squad-player{position:relative;flex:0 1 120px;min-width:0;max-width:140px;text-align:center}
.squad-photo{position:relative;display:flex;justify-content:center}
.squad-player .portrait-shell{width:70px;height:75px;margin:0 auto -4px;
  background:rgba(2,62,45,.32);border:1px solid rgba(235,255,246,.22);border-radius:10px 10px 0 0}
.squad-player .player-portrait{width:68px;height:73px;object-fit:contain}
.squad-player-label{position:relative;background:#f8fffa;color:#171e29;border-radius:5px;
  border:1px solid rgba(5,52,35,.15);box-shadow:0 3px 9px rgba(0,0,0,.18);
  padding:4px 2px;min-height:37px}
.squad-player-label strong{display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.squad-player-label small{display:block;color:#1d654b;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.squad-player .captain-marker{display:inline-block;background:#39205c;color:white;border-radius:4px;
  font-size:9px;margin-left:3px;padding:1px 3px}
.squad-warning{position:absolute;top:1px;right:18%;background:#f8a83e;color:#16201b;
  font-size:10px;font-weight:900;width:17px;height:17px;border-radius:50%;z-index:4}
.squad-bench{background:#153a32;border:1px solid #315a4b;border-top:0;border-radius:0 0 17px 17px;padding:12px 10px 14px}
.squad-bench-heading{display:flex;justify-content:space-between;gap:8px;align-items:center;margin:0 2px 12px}
.squad-bench-heading strong{font-size:12px;letter-spacing:.08em}
.squad-bench-heading span{font-size:10px;color:#acd7c3}
.squad-bench-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;justify-items:center}
.squad-bench-row .squad-player{width:100%;max-width:130px}
.bench-number{position:absolute;left:1px;top:0;background:#dcfce7;color:#123c2d;border-radius:5px;
  padding:1px 4px;font-weight:800;font-size:10px;z-index:3}
@media(max-width:640px){
 .squad-field{padding:34px 4px 14px}.squad-field:before{inset:41px 4px 7px}
 .squad-formation-row{gap:2px;margin:7px auto 15px;min-height:89px}
 .squad-player .portrait-shell{width:48px;height:52px}
 .squad-player .player-portrait{height:51px;width:47px}
 .squad-player-label{padding:3px 1px;min-height:32px}
 .squad-player-label strong{font-size:9px}.squad-player-label small{font-size:8px}
 .squad-bench{padding:10px 5px}.squad-bench-row{gap:4px}
 .squad-warning{right:7%;font-size:9px;width:15px;height:15px}
 .squad-bench-heading span{font-size:9px}
}

/* v5.4 native Streamlit clickable squad cards, with photos retained. */
.st-key-ajk_click_pitch{padding:15px 8px 12px;border:1px solid #5bc99d;border-radius:18px 18px 4px 4px;
 background:repeating-linear-gradient(180deg,rgba(255,255,255,.045) 0,rgba(255,255,255,.045) 92px,transparent 92px,transparent 184px),linear-gradient(165deg,#008b53,#006d4c)}
.st-key-ajk_click_pitch .stMarkdown p{margin-bottom:0}
.st-key-ajk_click_pitch [data-testid="stButton"] button,
.st-key-ajk_click_bench [data-testid="stButton"] button{
 width:100%;height:auto;min-height:109px;padding:6px 2px;white-space:normal;
 background:rgba(8,53,43,.7);border:1px solid rgba(226,255,240,.30);color:#fff;
 box-shadow:0 3px 10px rgba(0,0,0,.14);line-height:1.22;font-size:11px;}
.st-key-ajk_click_pitch [data-testid="stButton"] button:hover,
.st-key-ajk_click_bench [data-testid="stButton"] button:hover{border-color:#a0f7ca;background:rgba(14,92,65,.87)}
.st-key-ajk_click_pitch [data-testid="stButton"] button[kind="primary"],
.st-key-ajk_click_bench [data-testid="stButton"] button[kind="primary"]{
 border:2px solid #fdef77!important;background:#154f40!important;color:#fff!important;}
.st-key-ajk_click_pitch [data-testid="stButton"] button img,
.st-key-ajk_click_bench [data-testid="stButton"] button img{
 height:57px!important;max-height:none!important;width:auto!important;max-width:90%!important;object-fit:contain;vertical-align:middle;display:block;margin:0 auto 4px;}
.st-key-ajk_click_pitch [data-testid="stHorizontalBlock"]{gap:clamp(2px,.8vw,12px)}
.st-key-ajk_click_pitch .stColumn,
.st-key-ajk_click_bench .stColumn{min-width:0}
.st-key-ajk_click_bench{padding:12px 8px;background:#123d33;border:1px solid #315a4b;border-radius:0 0 17px 17px}
@media(max-width:640px){
 .st-key-ajk_click_pitch{padding:9px 3px}
 .st-key-ajk_click_pitch [data-testid="stButton"] button,
 .st-key-ajk_click_bench [data-testid="stButton"] button{font-size:9px;min-height:88px;padding:4px 1px}
 .st-key-ajk_click_pitch [data-testid="stButton"] button img,
 .st-key-ajk_click_bench [data-testid="stButton"] button img{height:43px!important}
}

/* v5.5 premium captain and vice-captain insignia for native clickable cards. */
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"] button,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"] button{position:relative;overflow:visible}
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_captain"] button,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_captain"] button{
  border-color:#f4cb65!important;box-shadow:0 0 0 1px rgba(255,215,114,.33),0 6px 16px rgba(0,0,0,.17)}
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_vice"] button,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_vice"] button{
  border-color:#b9d8ec!important;box-shadow:0 0 0 1px rgba(197,222,245,.22),0 6px 16px rgba(0,0,0,.14)}
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_captain"] button::after,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_captain"] button::after,
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_vice"] button::after,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_vice"] button::after{
  position:absolute;top:-9px;right:-5px;z-index:4;display:block;
  border-radius:999px;padding:3px 7px;font-size:9px;font-weight:900;letter-spacing:.03em;
  border:1px solid rgba(255,255,255,.52);white-space:nowrap;
  box-shadow:0 3px 9px rgba(0,0,0,.34)}
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_captain"] button::after,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_captain"] button::after{
  content:"👑 C";background:linear-gradient(120deg,#fff2a2,#e9b43b);color:#382600}
.st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_vice"] button::after,
.st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_vice"] button::after{
  content:"◆ VC";background:linear-gradient(120deg,#eff8ff,#a7c3df);color:#16334c}
/* Static pitch cards (used elsewhere) receive matching insignia. */
.squad-player .captain-marker{position:absolute;right:-6px;top:-8px;z-index:5;
  border-radius:999px;font-size:9px;font-weight:900;padding:3px 6px;
  border:1px solid #fff7cd;box-shadow:0 3px 8px rgba(0,0,0,.25)}
.squad-player .captain-marker--c{background:linear-gradient(120deg,#fff2a2,#e9b43b);color:#382600}
.squad-player .captain-marker--vc{background:linear-gradient(120deg,#eff8ff,#a7c3df);color:#16334c}
@media(max-width:640px){
 .st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_captain"] button::after,
 .st-key-ajk_click_pitch [class*="st-key-pitch_click_"][class*="_vice"] button::after,
 .st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_captain"] button::after,
 .st-key-ajk_click_bench [class*="st-key-pitch_click_"][class*="_vice"] button::after{
   top:-7px;right:-3px;font-size:8px;padding:2px 4px}
}

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


def player_photo_url(player: dict) -> str:
    """Build a Premier League headshot URL from FPL photo/code metadata.

    This is presentation-only; failed external images are hidden in the UI.
    """
    photo = str(player.get("photo") or "")
    filename = photo.rsplit(".", 1)[0]
    if not filename.isdecimal():
        code = player.get("code")
        filename = str(code) if str(code).isdecimal() else ""
    if not filename:
        return ""
    return f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{filename}.png"


def player_portrait_html(player: dict) -> str:
    """A photo with a graceful placeholder when missing or unavailable."""
    initials = html.escape(str(player.get("web_name", "?") or "?")[:2].upper())
    src = player_photo_url(player)
    image = (f'<img src="{html.escape(src, quote=True)}" class="player-portrait" '
             f'alt="" loading="lazy" onerror="this.style.display=\'none\'">') if src else ""
    return (f'<div class="portrait-shell"><span class="portrait-fallback">{initials}</span>'
            f'{image}</div>')


def transfer_faces_html(moves: list[dict], player_by_id: dict[int, dict]) -> str:
    cards = []
    for move in moves:
        out = player_by_id.get(int(move["out"]), {"web_name": move.get("out_name", "?")})
        incoming = player_by_id.get(int(move["in"]), {"web_name": move.get("in_name", "?")})
        cards.append(
            '<div class="transfer-faces">'
            f'<div class="transfer-person">{player_portrait_html(out)}'
            f'<strong>{html.escape(str(out.get("web_name", "?")))}</strong><small>OUT · {money(out.get("selling_price",out.get("now_cost",0)))}</small></div>'
            '<span class="transfer-arrow">→</span>'
            f'<div class="transfer-person">{player_portrait_html(incoming)}'
            f'<strong>{html.escape(str(incoming.get("web_name", "?")))}</strong><small>IN · {money(incoming.get("now_cost",0))}</small></div>'
            '</div>'
        )
    return "".join(cards)


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


def fixture_badge(player: dict, gw: int, fixture_map: dict,
                  clubs: dict[int, str]) -> str:
    """One or multiple fixtures for the selected Gameweek, or a blank GW."""
    games = fixture_map.get((int(gw), int(player.get("team", 0))), [])
    if not games:
        return "Blank GW"
    return " · ".join(
        f"{html.escape(clubs.get(int(game['opponent']), '?'))} "
        f"({'H' if game['home'] else 'A'})"
        for game in games
    )


def pitch_player_card(player: dict, captain_id: int, vice_id: int, gw: int,
                      fixture_map: dict, clubs: dict, overrides: dict,
                      display: str = "xP", bench_number: str = "") -> str:
    """A portrait card shared by the starting pitch and substitutes bench."""
    pid = int(player["id"])
    name = html.escape(str(player.get("web_name", "?")))
    marker = ('<span class="captain-marker captain-marker--c" title="Captain">👑 C</span>'
              if pid == captain_id else
              '<span class="captain-marker captain-marker--vc" title="Vice-captain">◆ VC</span>'
              if pid == vice_id else '')
    if display == "Fixture":
        detail = fixture_badge(player, gw, fixture_map, clubs)
    else:
        xp = player_fixture_xp(player, gw, fixture_map, overrides)
        detail = f"{xp:.1f} xP"
    # The available flag is from the FPL API, not a guarantee of starting.
    status = str(player.get('status', 'a'))
    flag = '<span class="squad-warning" title="Availability concern">!</span>' if status != 'a' else ''
    bench_tag = (f'<span class="bench-number">{html.escape(str(bench_number))}</span>'
                 if bench_number else '')
    return (f'<div class="squad-player">{bench_tag}<div class="squad-photo">'
            f'{player_portrait_html(player)}{flag}</div>'
            f'<div class="squad-player-label"><strong title="{name}">{name}{marker}</strong>'
            f'<small title="{html.escape(detail)}">{detail}</small></div></div>')


def pitch(xi: list[dict], captain_id: int, vice_id: int, gw: int,
          fixture_map: dict, clubs: dict, overrides: dict,
          squad: list[dict] | None = None, display: str = "xP") -> None:
    """Pitch with portraits, formation rows and a separated four-player bench.

    The lineup is passed in from the established optimiser/manual swap logic;
    this presentation function never changes selection or transfer state.
    """
    lines = []
    for pos in (1, 2, 3, 4):
        group = [p for p in xi if int(p['element_type']) == pos]
        cards = [pitch_player_card(p, captain_id, vice_id, gw,
                                   fixture_map, clubs, overrides, display)
                 for p in group]
        lines.append(f'<div class="squad-formation-row pos-{pos}">' + ''.join(cards) + '</div>')
    counts = Counter(int(p['element_type']) for p in xi)
    formation = f"{counts[2]}-{counts[3]}-{counts[4]}"
    field = (f'<div class="squad-field"><div class="squad-pitch-topline">'
             f'<span>GW {gw}</span><span>{formation} · Starting XI</span></div>'
             '<div class="squad-goal"></div><div class="squad-penalty"></div>'
             '<div class="squad-centreline"></div><div class="squad-centrecircle"></div>'
             + ''.join(lines) + '</div>')
    bench_html = ''
    if squad is not None:
        starter_ids = {int(p['id']) for p in xi}
        bench = [p for p in squad if int(p['id']) not in starter_ids]
        # Preserve the backup keeper first. Outfield bench order is the
        # model's xP-ranked preview, not the user's official FPL bench order.
        keeper = [p for p in bench if int(p['element_type']) == 1]
        outfield = sorted((p for p in bench if int(p['element_type']) != 1),
                          key=lambda p: player_fixture_xp(p, gw, fixture_map, overrides), reverse=True)
        ordered = keeper + outfield
        cards = [pitch_player_card(p, captain_id, vice_id, gw, fixture_map,
                                   clubs, overrides, display,
                                   'GK' if i == 0 and int(p['element_type']) == 1 else str(i))
                 for i, p in enumerate(ordered)]
        bench_html = ('<div class="squad-bench"><div class="squad-bench-heading">'
                      '<strong>SUBSTITUTES</strong><span>Outfield order by projected xP</span>'
                      '</div><div class="squad-bench-row">' + ''.join(cards) + '</div></div>')
    st.markdown('<div class="squad-view">' + field + bench_html + '</div>',
                unsafe_allow_html=True)


def clickable_pitch(xi: list[dict], squad: list[dict], captain_id: int,
                    vice_id: int, gw: int, fixture_map: dict,
                    clubs: dict, overrides: dict, display: str,
                    selected_id: int | None, on_click) -> None:
    """Native click-to-sub Streamlit pitch. No HTML-to-Python messaging required."""
    starters = {int(p["id"]) for p in xi}
    bench = [p for p in squad if int(p["id"]) not in starters]
    keeper = [p for p in bench if int(p["element_type"]) == 1]
    outfield = sorted(
        (p for p in bench if int(p["element_type"]) != 1),
        key=lambda p: player_fixture_xp(p, gw, fixture_map, overrides), reverse=True,
    )

    def player_button(player: dict, *, is_bench: bool, bench_no: str = "") -> None:
        pid = int(player["id"])
        name = str(player.get("web_name", "?"))
        photo = player_photo_url(player)
        portrait = f"![photo]({photo})" if photo else "👤"
        if display == "Fixture":
            detail = fixture_badge(player, gw, fixture_map, clubs)
        else:
            detail = f"{player_fixture_xp(player, gw, fixture_map, overrides):.1f} xP"
        role = "captain" if pid == captain_id else "vice" if pid == vice_id else "regular"
        warning = " ⚠️" if str(player.get("status", "a")) != "a" else ""
        prefix = f"{bench_no} · " if bench_no else ""
        card = f"{portrait}  \n{prefix}{name}{warning}  \n{detail}"
        st.button(
            card, key=f"pitch_click_{gw}_{pid}_{role}", use_container_width=True,
            type="primary" if selected_id == pid else "secondary",
            help=(f"{name} ({'Captain' if role == 'captain' else 'Vice-captain' if role == 'vice' else 'Player'}) — "
                  f"{'selected; click again to cancel' if selected_id == pid else 'click to select for substitution'}"),
            on_click=on_click, args=(pid, ),
        )

    counts = Counter(int(p["element_type"]) for p in xi)
    formation = f"{counts[2]}-{counts[3]}-{counts[4]}"
    with st.container(key="ajk_click_pitch"):
        st.markdown(f"**GW {gw} · {formation} · Starting XI**")
        for position in (1, 2, 3, 4):
            group = [p for p in xi if int(p["element_type"]) == position]
            if not group:
                continue
            # Center narrow rows (GK / forwards) using small invisible spacer columns.
            total = max(5, len(group))
            side = (total - len(group)) / 2
            widths = ([side] if side else []) + [1] * len(group) + ([side] if side else [])
            cols = st.columns(widths, gap="small", vertical_alignment="top")
            offset = 1 if side else 0
            for i, player in enumerate(group):
                with cols[i + offset]:
                    player_button(player, is_bench=False)
    with st.container(key="ajk_click_bench"):
        st.markdown("**SUBSTITUTES** · Tap a starter, then tap a substitute to swap")
        ordered = keeper + outfield
        cols = st.columns(4, gap="small")
        for i, player in enumerate(ordered):
            with cols[i]:
                bench_no = "GK" if int(player["element_type"]) == 1 else str(i)
                player_button(player, is_bench=True, bench_no=bench_no)


# Friendly availability labels for the official FPL player status codes.
STATUS_LABELS = {
    "a": "🟢 Available",
    "d": "🟠 Doubtful",
    "i": "🔴 Injured",
    "s": "🔴 Suspended",
    "u": "⚪ Unavailable",
    "n": "⚪ Not available",
}


def player_status_label(player: dict) -> str:
    code = str(player.get("status") or "").strip().lower()
    return STATUS_LABELS.get(code, f"⚪ Unknown ({code})" if code else "⚪ Unknown")


def squad_frame(squad: list[dict], gws: list[int], fixture_map: dict,
                clubs: dict, overrides: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Player": label(p, clubs), "Position": POSITION_NAMES[int(p["element_type"])],
        "GW xP": round(player_fixture_xp(p, gws[0], fixture_map, overrides), 2),
        "Horizon xP": round(horizon_xp(p, gws, fixture_map, overrides), 2),
        "Sell price": money(p.get("selling_price", p.get("now_cost", 0))),
        "Status": player_status_label(p),
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
    st.session_state.manual_xi_by_gw = {}
    st.session_state.manual_captain_by_gw = {}
    st.session_state.draft_moves = []
    st.session_state.chip_result = None


def restore_original_team() -> None:
    """Undo all draft transfers/chip simulations, retaining the imported snapshot."""
    st.session_state.draft = [dict(p) for p in st.session_state.original_squad]
    st.session_state.bank = int(st.session_state.original_bank)
    st.session_state.draft_moves = []
    st.session_state.manual_xi = []
    st.session_state.manual_captain = None
    st.session_state.manual_xi_by_gw = {}
    st.session_state.manual_captain_by_gw = {}
    st.session_state.chip_result = None
    st.session_state.advisor_result = None
    st.session_state.advisor_key = None
    for key in list(st.session_state):
        if str(key).startswith("pitch_swap_selected_"):
            st.session_state.pop(key, None)


def draft_has_changes() -> bool:
    original = st.session_state.original_squad
    draft = st.session_state.draft
    original_ids = sorted(int(p["id"]) for p in original)
    draft_ids = sorted(int(p["id"]) for p in draft)
    return (original_ids != draft_ids
            or int(st.session_state.bank) != int(st.session_state.original_bank)
            or bool(st.session_state.get("draft_moves"))
            or bool(st.session_state.get("manual_xi"))
            or st.session_state.get("manual_captain") is not None
            or bool(st.session_state.get("manual_xi_by_gw"))
            or bool(st.session_state.get("manual_captain_by_gw")))


st.markdown("""<div class="ajk-hero"><div class="ajk-kicker">SMART FPL DECISIONS · FREE</div><h1>⚽ AJK Bola Wawei AI</h1><p>Your squad. Smarter transfers. A premium-feel FPL command centre.</p></div>""", unsafe_allow_html=True)

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

# A Streamlit session can survive a code redeploy. Older app versions used
# different session-state fields, so a leftover draft may be incomplete.
required_session_keys = (
    "draft", "bank", "manager_profile", "loaded_id", "from_gw",
    "original_squad", "original_bank",
)
missing_session_keys = [
    key for key in required_session_keys if key not in st.session_state
]
if missing_session_keys:
    # Discard incompatible draft data rather than accessing partial state.
    # The manager must re-import once to rebuild a consistent v5 session.
    for key in required_session_keys + (
        "manual_xi", "manual_captain", "manual_xi_by_gw", "manual_captain_by_gw", "draft_moves", "chip_result",
        "advisor_key", "advisor_result",
    ):
        st.session_state.pop(key, None)
    st.info(
        "Enter your FPL Team ID above and click Analyse Team to load your squad. "
        "If you just upgraded the app, re-import your team once to refresh the session."
    )
    st.stop()

squad = st.session_state.draft
bank = int(st.session_state.bank)
profile = st.session_state.manager_profile
if not valid_squad(squad):
    st.error("Your simulated draft is invalid. Re-import your FPL team using Analyse Team above.")
    st.stop()

with st.expander("⚙️ Planning settings", expanded=False):
    c1, c2, c3 = st.columns(3)
    selected_gw = c1.selectbox("Starting Gameweek", available_gws, format_func=lambda gw: f"GW {gw}")
    horizon_list = [gw for gw in available_gws if gw >= selected_gw]
    horizon = c2.select_slider("Look ahead", options=list(range(1, len(horizon_list) + 1)), value=min(5, len(horizon_list)), format_func=lambda x: f"{x} GW" if x == 1 else f"{x} GWs")
    strategy = c3.selectbox("AI Strategy", ["Balanced", "Safe", "Aggressive"])
    ft = st.number_input("Free transfers available (check your FPL account)", min_value=0, max_value=5, value=1)
    st.caption("Safe applies a modest penalty to low-minute players. Aggressive prioritises upside. The risk settings are heuristics, not calibrated probabilities.")
    # Use the prediction engine's automatic expected-minutes estimates.
    # Manual per-player minutes controls are intentionally not exposed.
    minutes_overrides = {}

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

# The forecast horizon and the displayed pitch GW are deliberately independent.
# Changing preview_gw never changes optimiser input or the simulated 15-player squad.
if st.session_state.get("preview_gw") not in gws:
    st.session_state.preview_gw = gws[0]
preview_gw = int(st.session_state.preview_gw)
assessment = team_rating(squad, gws, fixture_map, minutes_overrides)
lineup = best_lineup(squad, preview_gw, fixture_map, minutes_overrides)
st.subheader(profile.get("name", "My FPL Team"))
st.caption(f"Imported from GW {st.session_state.from_gw} · Pitch preview: GW {preview_gw} · Planning: GW {gws[0]}–{gws[-1]} · All changes are simulations only")
rating_value = max(0, min(100, int(assessment["rating"])))
rating_label = "Excellent" if rating_value >= 85 else "Strong" if rating_value >= 70 else "Promising" if rating_value >= 55 else "Needs attention"
st.markdown(f"""<div class="ajk-rating"><div><div class="eyebrow">AI TEAM RATING</div><div class="main">{rating_label} squad</div><div class="sub">Projected form across {len(gws)} selected Gameweek(s) · independent heuristic rating</div></div><div class="circle" style="background:conic-gradient(#21d99b {rating_value}%,rgba(255,255,255,.10) 0)"><div class="inner">{rating_value}<span style="font-size:10px;opacity:.65">/100</span></div></div></div>""",unsafe_allow_html=True)
metrics = st.columns(3)
metrics[0].metric(f"GW {preview_gw} xP", f"{lineup['total_xp']:.1f}")
metrics[1].metric(f"{len(gws)}-GW projected", f"{assessment['total_xp']:.1f}")
metrics[2].metric("Bank", money(bank))

if draft_has_changes():
    st.info("You are viewing a simulated draft, not your original FPL squad. "
            "Reset restores the 15 imported players, bank balance, XI and captain.")
    if st.button("↩️ Reset to Original FPL Team", key="reset_team_main",
                 use_container_width=True, type="secondary"):
        restore_original_team()
        st.rerun()
else:
    st.caption("✓ Original imported FPL team — no draft transfers applied.")

st.divider()
with st.expander("🏟️ My Team · Pitch, captain & manual changes", expanded=True):
    st.markdown("**Preview your squad across the selected Gameweeks**")
    preview_gw = st.select_slider(
        "Preview Gameweek", options=gws, value=preview_gw,
        format_func=lambda gw: f"GW {gw}",
    )
    # Streamlit widgets update on rerun; changing the preview only changes this view.
    if int(preview_gw) != int(st.session_state.preview_gw):
        st.session_state.preview_gw = int(preview_gw)
        st.rerun()
    st.caption(f"GW {preview_gw} preview · {len(gws)} Gameweek(s) in your Look Ahead range. "
               "Squad transfers are not automatically applied in future weeks.")
    # The engine selects the optimal legal XI for this GW. No alternative-formation UI.
    gw_xp = {int(p["id"]): player_fixture_xp(p, preview_gw, fixture_map, minutes_overrides)
             for p in squad}
    auto_xi = lineup["xi"]
    ai_counts = Counter(int(p["element_type"]) for p in auto_xi)
    ai_formation = f"{ai_counts[2]}-{ai_counts[3]}-{ai_counts[4]}"
    st.success(f"AI best for GW {preview_gw}: **{ai_formation}** · "
               f"**{lineup['total_xp']:.2f} predicted points** (captain included)")
    if st.button("✨ Apply AI best XI for all selected GWs", key="apply_best_all_gws",
                 use_container_width=True):
        st.session_state.manual_xi_by_gw = {}
        st.session_state.manual_captain_by_gw = {}
        st.session_state.manual_xi = []
        st.session_state.manual_captain = None
        st.rerun()
    # One-time migration: the previous version saved chosen formations as manual
    # overrides. Clear them once so upgrading immediately enables auto-XI for every GW.
    if not st.session_state.get("auto_formations_v524_initialized", False):
        st.session_state.manual_xi_by_gw = {}
        st.session_state.manual_captain_by_gw = {}
        st.session_state.manual_xi = []
        st.session_state.manual_captain = None
        st.session_state.auto_formations_v524_initialized = True
    auto_xi = lineup["xi"]
    weekly_xi = st.session_state.get("manual_xi_by_gw", {})
    manual_ids = set(weekly_xi.get(preview_gw, st.session_state.get("manual_xi", []) if preview_gw == selected_gw else []))
    xi = [p for p in squad if int(p["id"]) in manual_ids] if len(manual_ids) == 11 else auto_xi
    counts = Counter(int(p["element_type"]) for p in xi)
    if len(xi) != 11 or not (counts[1] == 1 and 3 <= counts[2] <= 5 and 2 <= counts[3] <= 5 and 1 <= counts[4] <= 3):
        xi = auto_xi
    counts = Counter(int(p["element_type"]) for p in xi)
    active_formation = f"{counts[2]}-{counts[3]}-{counts[4]}"
    if {int(p["id"]) for p in xi} != {int(p["id"]) for p in auto_xi}:
        st.info(f"Viewing a manual GW {preview_gw} XI ({active_formation}). "
                f"The AI recommends {ai_formation}. Click 'Restore best XI and captain' below to switch back.")
    else:
        st.caption(f"✅ Automatically selected: **{active_formation}** · AI best XI and captain for GW {preview_gw}")
    cap_ids = [int(p["id"]) for p in xi]
    cap_default = st.session_state.get("manual_captain_by_gw", {}).get(
        preview_gw, st.session_state.get("manual_captain") if preview_gw == selected_gw else None
    )
    cap = cap_default if cap_default in cap_ids else int(lineup["captain"]["id"])
    if cap not in cap_ids:
        cap = max(xi, key=lambda p: player_fixture_xp(p, preview_gw, fixture_map, minutes_overrides))["id"]
    vice = max((pid for pid in cap_ids if pid != cap), key=lambda pid: gw_xp[pid])
    pitch_display = st.radio(
        "Show on player cards", options=["xP", "Fixture"], horizontal=True,
        key="squad_pitch_display", label_visibility="collapsed",
    )
    # Each click selects a player; a click on the opposite side makes the swap.
    click_state_key = f"pitch_swap_selected_{st.session_state.loaded_id}_{preview_gw}"
    selected_for_swap = st.session_state.get(click_state_key)
    available_ids = {int(p["id"]) for p in squad}
    if selected_for_swap not in available_ids:
        selected_for_swap = None
        st.session_state.pop(click_state_key, None)

    def on_pitch_player_click(clicked_id: int) -> None:
        chosen = st.session_state.get(click_state_key)
        if chosen is None:
            st.session_state[click_state_key] = clicked_id
            return
        if chosen == clicked_id:
            st.session_state.pop(click_state_key, None)
            return
        current_starters = {int(p["id"]) for p in xi}
        if (chosen in current_starters) == (clicked_id in current_starters):
            # Click another starter/bench player to change your selection.
            st.session_state[click_state_key] = clicked_id
            return
        outgoing_id = chosen if chosen in current_starters else clicked_id
        incoming_id = clicked_id if chosen in current_starters else chosen
        proposed_ids = (current_starters - {outgoing_id}) | {incoming_id}
        proposed = [p for p in squad if int(p["id"]) in proposed_ids]
        ct = Counter(int(p["element_type"]) for p in proposed)
        st.session_state.pop(click_state_key, None)
        if not (len(proposed) == 11 and ct[1] == 1 and
                3 <= ct[2] <= 5 and 2 <= ct[3] <= 5 and 1 <= ct[4] <= 3):
            st.session_state["pitch_swap_message"] = (
                "⚠️ That substitution would create an invalid formation. "
                "Choose a different substitute (1 GKP, 3–5 DEF, 2–5 MID, 1–3 FWD)."
            )
            return
        st.session_state.setdefault("manual_xi_by_gw", {})[preview_gw] = list(proposed_ids)
        current_captain = st.session_state.get("manual_captain_by_gw", {}).get(preview_gw, cap)
        if current_captain not in proposed_ids:
            current_captain = max(proposed_ids, key=lambda pid: gw_xp[pid])
        st.session_state.setdefault("manual_captain_by_gw", {})[preview_gw] = current_captain
        if preview_gw == selected_gw:
            st.session_state.manual_xi = list(proposed_ids)
            st.session_state.manual_captain = current_captain
        st.session_state["pitch_swap_message"] = "✅ Substitution applied to your GW preview."

    if selected_for_swap is None:
        st.caption("👆 Tap any starter or substitute, then tap a player on the opposite side to swap. "
                   "Illegal formations are blocked automatically.")
    else:
        chosen_player = player_by_id.get(int(selected_for_swap), {})
        st.info(f"Selected: **{chosen_player.get('web_name', '?')}**. "
                "Tap a player on the opposite side to complete the substitution, "
                "or tap the selected player again to cancel.")
    if st.session_state.get("pitch_swap_message"):
        st.caption(st.session_state.pop("pitch_swap_message"))
    clickable_pitch(xi, squad, cap, vice, preview_gw, fixture_map, clubs,
                    minutes_overrides, pitch_display or "xP",
                    selected_for_swap, on_pitch_player_click)
    captain = st.selectbox(
        "Captain", cap_ids, index=cap_ids.index(cap),
        format_func=lambda pid: label(player_by_id[pid], clubs),
        key=f"captain_preview_{st.session_state.loaded_id}_{preview_gw}",
    )
    if captain != cap:
        st.session_state.setdefault("manual_captain_by_gw", {})[preview_gw] = captain
        if preview_gw == selected_gw:
            st.session_state.manual_captain = captain
        st.rerun()
    if st.button(f"Restore best XI and captain for GW {preview_gw}"):
        st.session_state.setdefault("manual_xi_by_gw", {}).pop(preview_gw, None)
        st.session_state.setdefault("manual_captain_by_gw", {}).pop(preview_gw, None)
        if preview_gw == selected_gw:
            st.session_state.manual_xi = []
            st.session_state.manual_captain = None
        st.rerun()
    with st.expander("🔁 Change a player · Quick manual transfer", expanded=False):
        st.caption("Replace one squad player with an affordable player in the same position. "
                   "This updates your simulated draft for every previewed GW; it does not make an actual FPL transfer.")
        owned_ids = {int(p["id"]) for p in squad}
        out_ids = sorted(owned_ids, key=lambda pid: (
            int(player_by_id[pid]["element_type"]),
            str(player_by_id[pid].get("web_name", ""))
        ))
        sell_id = st.selectbox(
            "1 · Select a player to replace", out_ids,
            format_func=lambda pid: label(next(p for p in squad if int(p["id"]) == pid), clubs),
            key="my_team_transfer_out",
        )
        outgoing = next(p for p in squad if int(p["id"]) == sell_id)
        sell_price = int(outgoing.get("selling_price", outgoing.get("now_cost", 0)))
        budget = bank + sell_price
        # Pre-filter club quota and position before displaying candidates.
        club_counts = Counter(int(p["team"]) for p in squad if int(p["id"]) != sell_id)
        candidates = [p for p in players
                      if int(p["id"]) not in owned_ids
                      and int(p["element_type"]) == int(outgoing["element_type"])
                      and int(p["now_cost"]) <= budget
                      and club_counts[int(p["team"])] < 3]
        candidates.sort(
            key=lambda p: (horizon_xp(p, gws, fixture_map, minutes_overrides),
                           player_fixture_xp(p, preview_gw, fixture_map, minutes_overrides)),
            reverse=True,
        )
        st.caption(f"Available budget: **{money(budget)}** (selling price {money(sell_price)} + bank {money(bank)})"
                   f" · {len(candidates)} eligible replacements · Sorted by projected {len(gws)}-GW points")
        if not candidates:
            st.warning("No affordable, legal replacements for this player. Choose a different player to replace.")
        else:
            candidate_ids = [int(p["id"]) for p in candidates]
            buy_id = st.selectbox(
                "2 · Choose a replacement", candidate_ids,
                format_func=lambda pid: (
                    f"{label(player_by_id[pid], clubs)} · "
                    f"{horizon_xp(player_by_id[pid], gws, fixture_map, minutes_overrides):.1f} xP"
                ),
                key="my_team_transfer_in",
            )
            incoming = player_by_id[buy_id]
            revised = [p for p in squad if int(p["id"]) != sell_id] + [
                {**incoming, "selling_price": int(incoming["now_cost"])}
            ]
            remaining_bank = budget - int(incoming["now_cost"])
            if valid_squad(revised) and remaining_bank >= 0:
                old_gw_xp = player_fixture_xp(outgoing, preview_gw, fixture_map, minutes_overrides)
                new_gw_xp = player_fixture_xp(incoming, preview_gw, fixture_map, minutes_overrides)
                revised_rating = team_rating(revised, gws, fixture_map, minutes_overrides)
                gain = revised_rating["total_xp"] - assessment["total_xp"]
                st.markdown(transfer_faces_html([{"out": sell_id, "in": buy_id}], player_by_id),
                            unsafe_allow_html=True)
                a, b, c = st.columns(3)
                a.metric(f"GW {preview_gw} player xP change", f"{new_gw_xp - old_gw_xp:+.1f}")
                b.metric(f"{len(gws)}-GW squad xP change", f"{gain:+.1f}")
                c.metric("Bank after transfer", money(remaining_bank))
                st.caption("Squad xP includes optimised lineups and captaincy. "
                           "The gain shown is before any transfer hit; check your free transfers in Planning settings.")
                if st.button("3 · Apply player change to My Team draft", type="primary",
                             use_container_width=True, key="my_team_transfer_apply"):
                    st.session_state.draft = revised
                    st.session_state.bank = remaining_bank
                    st.session_state.setdefault("draft_moves", []).append({"out": sell_id, "in": buy_id})
                    # An incoming player may invalidate an old manually chosen XI.
                    # Reset only lineup overrides; the user's original imported squad stays intact.
                    st.session_state.manual_xi = []
                    st.session_state.manual_captain = None
                    st.session_state.manual_xi_by_gw = {}
                    st.session_state.manual_captain_by_gw = {}
                    st.session_state.advisor_result = None
                    st.session_state.advisor_key = None
                    st.rerun()
            else:
                st.warning("This player change would create an invalid squad. Try another replacement.")

    st.dataframe(squad_frame(squad, [preview_gw] + [gw for gw in gws if gw != preview_gw], fixture_map, clubs, minutes_overrides),
                 hide_index=True, use_container_width=True)
    risky = [p for p in squad if p.get("status", "a") != "a"]
    if risky:
        st.warning("Check availability: " + ", ".join(p.get("web_name", "?") for p in risky))
    with st.expander("🔎 Player insights · Fixtures, xP & minutes", expanded=False):
        insight_ids = sorted((int(p["id"]) for p in squad),
                             key=lambda pid: horizon_xp(player_by_id[pid], gws, fixture_map, minutes_overrides),
                             reverse=True)
        selected_player_id = st.selectbox("Select a player", insight_ids,
            format_func=lambda pid: label(next(p for p in squad if int(p["id"]) == pid), clubs),
            key="v52_insight_player")
        selected_player = next(p for p in squad if int(p["id"]) == selected_player_id)
        breakdown = player_prediction(selected_player, preview_gw, fixture_map, minutes_overrides)
        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("GW xP", f"{breakdown['xp']:.1f}")
        pc2.metric("Expected minutes", f"{breakdown['minutes']:.0f}")
        pc3.metric("Indicative points range", f"{breakdown['lower']:.0f}–{breakdown['upper']:.0f}")
        if selected_player.get("news"):
            st.warning(str(selected_player["news"]))
        if selected_player.get("status", "a") != "a":
            st.caption("FPL availability: " + player_status_label(selected_player))
        per_gw = []
        for week in gws:
            pred = player_prediction(selected_player, week, fixture_map, minutes_overrides)
            games = fixture_map.get((week, int(selected_player["team"])), [])
            opponent_text = ", ".join(
                (clubs.get(int(game["opponent"]), "?") + (" (H)" if game["home"] else " (A)"))
                for game in games) if games else "Blank GW"
            per_gw.append({"Gameweek": f"GW {week}", "Opponent": opponent_text,
                           "Projected points": round(pred["xp"], 2)})
        st.bar_chart(pd.DataFrame(per_gw).set_index("Gameweek")["Projected points"],
                     color="#26d8a0", use_container_width=True)
        st.dataframe(pd.DataFrame(per_gw), hide_index=True, use_container_width=True)
        st.caption("Ranges are model estimates, not guaranteed outcomes or calibrated probabilities.")


st.divider()
st.subheader("🧠 Smart Transfer Advisor")
st.caption("Looks ahead across your selected Gameweeks. Compares rolling, one transfer and two-transfer combinations, including hits and captaincy.")
settings_key = (st.session_state.loaded_id, tuple(sorted(int(p["id"]) for p in squad)),
                bank, ft, tuple(gws), strategy, tuple(sorted(minutes_overrides.items())))
if st.session_state.get("advisor_key") != settings_key:
    st.session_state.advisor_result = None

current_advice = st.session_state.get("advisor_result")
if current_advice and st.session_state.get("advisor_key") == settings_key:
    if current_advice["action"] == "ROLL":
        verdict_text = "Roll your free transfer"
        verdict_reason = "The optimiser prefers waiting across your selected Gameweeks, after accounting for projected XI points, captaincy and hits."
    else:
        verdict_text = "A transfer could improve your squad"
        verdict_reason = f"The current proposed plan estimates {current_advice['expected_gain']:+.1f} net points versus no transfers across the horizon. Check the recommendations below."
else:
    verdict_text = "Your squad is ready for analysis"
    verdict_reason = "Run the Smart Transfer Advisor to compare transfers against rolling. The verdict will use your actual imported squad and selected settings."
st.markdown(f'<div class="ajk-verdict"><div class="eyebrow">✦ AI MANAGER’S VERDICT</div><strong>{html.escape(verdict_text)}</strong><div class="explain">{html.escape(verdict_reason)}</div></div>', unsafe_allow_html=True)

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
        st.markdown(transfer_faces_html(moves, player_by_id), unsafe_allow_html=True)
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
                st.session_state.manual_xi_by_gw = {}
                st.session_state.manual_captain_by_gw = {}
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
              selected_gw, fixture_map, clubs, minutes_overrides,
              squad=result["squad"], display=st.session_state.get("squad_pitch_display", "xP"))
        st.dataframe(squad_frame(result["squad"], chip_gws, fixture_map, clubs, minutes_overrides),
                     hide_index=True, use_container_width=True)
        st.caption("Approximate greedy optimiser. Free Hit is a single-GW simulation, not a chip activation.")
        if st.button("Use this team as my editable draft"):
            st.session_state.draft = [{**p, "selling_price": int(p["now_cost"])} for p in result["squad"]]
            st.session_state.bank = result["bank"]
            st.session_state.manual_xi = []
            st.session_state.manual_captain = None
            st.session_state.manual_xi_by_gw = {}
            st.session_state.manual_captain_by_gw = {}
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
