"""AJK Bola Wawei AI v6.8 — cinematic premium dashboard, preserving the full FPL planner.

Install: pip install streamlit requests pandas
Run: streamlit run app.py
Read-only access to public Fantasy Premier League APIs. No FPL account login.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import base64
from pathlib import Path
import html
import re

import pandas as pd
import requests
import streamlit as st

from fpl_engine import (
    POSITION_NAMES, best_lineup,
    configure_calibration, configure_projection_context, fixture_lookup,
    horizon_xp, join_actuals, num, optimise_chip_squad,
    player_fixture_xp, player_prediction, projected_minutes,
    smart_transfer_plan, team_rating, valid_squad, validate_snapshots,
)

API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "AJK-Bola-Wawei-AI/6.0 (public FPL data)"}

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
.squad-warning{position:absolute;top:0;right:5%;font-size:16px;line-height:1;
  display:flex;align-items:center;justify-content:center;width:23px;height:23px;
  border-radius:50%;background:rgba(9,34,28,.92);border:1px solid rgba(255,255,255,.75);
  box-shadow:0 2px 7px rgba(0,0,0,.35);z-index:6}
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
 .squad-warning{right:2%;font-size:13px;width:19px;height:19px}
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

/* v6: simple three-tab navigation with a touch-friendly layout */
[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:8px;overflow-x:auto;padding:5px 0 10px}
[data-testid="stTabs"] [data-baseweb="tab"]{border-radius:13px;background:rgba(23,48,49,.84);border:1px solid rgba(129,196,170,.20);padding:11px 17px;white-space:nowrap;font-weight:700}
[data-testid="stTabs"] [aria-selected="true"]{background:rgba(24,125,93,.22);color:#79f0c1;border-color:rgba(50,226,159,.62)}
[data-testid="stTabs"] [data-baseweb="tab-panel"]{padding-top:14px}
@media(max-width:600px){[data-testid="stTabs"] [data-baseweb="tab"]{padding:9px 11px;font-size:12px}}

/* AJK v6.3 — stadium-night premium theme, restrained effects and readable controls */
:root{--ajk-green:#25e0a0;--ajk-border:rgba(100,190,181,.22);--ajk-navy:#061221}
html,body,[data-testid="stAppViewContainer"]{background-color:#06111e!important}
[data-testid="stAppViewContainer"]{
  background-image:
    radial-gradient(ellipse 55% 24% at 50% 0%,rgba(18,130,121,.22),transparent 75%),
    radial-gradient(ellipse 42% 28% at 0% 17%,rgba(10,98,137,.16),transparent 85%),
    radial-gradient(ellipse 36% 32% at 100% 22%,rgba(17,106,130,.12),transparent 90%),
    linear-gradient(165deg,#061322 0%,#081a2c 44%,#06111d 100%)!important;
  color:#eefaff!important;
}
[data-testid="stAppViewContainer"]::before{
  content:"";position:fixed;inset:0;pointer-events:none;opacity:.16;
  background: repeating-linear-gradient(90deg,transparent 0px,transparent 145px,rgba(58,189,170,.10) 146px,transparent 147px);
  mask-image:linear-gradient(to bottom,rgba(0,0,0,.7),transparent 58%);
}
[data-testid="stHeader"]{background:rgba(6,17,30,.4)!important}
.block-container{max-width:1240px!important;padding-top:1rem!important}
.ajk-hero{
  background:
    radial-gradient(circle at 5% 0%,rgba(73,206,245,.15),transparent 17%),
    radial-gradient(circle at 95% 4%,rgba(91,204,246,.14),transparent 16%),
    linear-gradient(104deg,rgba(5,24,43,.98),rgba(9,41,50,.96) 55%,rgba(7,25,45,.99))!important;
  border:1px solid rgba(70,206,169,.30)!important;border-radius:24px!important;
  box-shadow:0 14px 34px rgba(0,0,0,.25),inset 0 1px 0 rgba(232,255,255,.06);
  padding:19px 26px!important;
}
.ajk-hero:before{
  content:"";position:absolute;inset:0;right:0;top:0;width:100%;height:100%;border:0;border-radius:0;
  background:
    linear-gradient(165deg,transparent 76%,rgba(26,219,145,.12) 77%,transparent 78%),
    linear-gradient(15deg,transparent 76%,rgba(26,219,145,.10) 77%,transparent 78%);
  opacity:.7;pointer-events:none;
}
.ajk-hero:after{
  content:"";position:absolute;left:29%;right:8%;bottom:0;height:40%;pointer-events:none;
  border-top:1px solid rgba(57,212,159,.17);transform:perspective(280px) rotateX(52deg);
  background:linear-gradient(90deg,transparent 49.85%,rgba(38,226,153,.16) 50%,transparent 50.15%);
}
.ajk-brandline{display:flex;gap:19px;align-items:center;position:relative;z-index:1}
.ajk-logo-mark{display:block;width:90px;height:90px;object-fit:contain;filter:drop-shadow(0 0 15px rgba(44,222,155,.24));flex:none}
.ajk-brandcopy{min-width:0;flex:1}
.ajk-kicker{color:#6be1c1!important;letter-spacing:.19em!important}
.ajk-hero h1{font-size:clamp(26px,4vw,42px)!important;letter-spacing:-.045em;line-height:1.15}
.ajk-hero h1 span{color:#2be59c}
.ajk-hero p{color:#a9c9d0!important}
[data-testid="stMetric"]{
  background:linear-gradient(135deg,rgba(9,34,49,.96),rgba(8,28,40,.95))!important;
  border-color:rgba(50,175,155,.24)!important;
  box-shadow:0 9px 18px rgba(0,0,0,.11);
}
[data-testid="stExpander"]{background:rgba(9,29,43,.93)!important;border-color:rgba(84,167,161,.25)!important}
[data-testid="stTabs"] [data-baseweb="tab-list"]{background:rgba(7,27,42,.67);border-radius:17px;padding:7px;gap:8px!important}
[data-testid="stTabs"] [data-baseweb="tab"]{background:rgba(12,37,54,.78)!important;border-color:rgba(100,188,173,.24)!important}
[data-testid="stTabs"] [aria-selected="true"]{
  background:linear-gradient(110deg,#12b580,#25d99b)!important;color:#041b17!important;
  box-shadow:0 6px 16px rgba(14,159,109,.22);border-color:transparent!important;
}
.ajk-rating{background:linear-gradient(110deg,#0c2935,#0b2831)!important;border-color:rgba(50,202,152,.28)!important}
.ajk-rating .inner{background:#0e2732!important}
.ajk-verdict{background:linear-gradient(110deg,rgba(16,64,63,.83),rgba(9,39,52,.95))!important}
.st-key-ajk_click_pitch{background:repeating-linear-gradient(180deg,rgba(255,255,255,.035) 0,rgba(255,255,255,.035) 94px,transparent 94px,transparent 188px),linear-gradient(160deg,#008a55,#006943)!important;box-shadow:0 12px 36px rgba(0,0,0,.24),0 0 0 1px rgba(30,221,137,.16)}
.st-key-ajk_click_bench{background:linear-gradient(110deg,#103a39,#0a2d38)!important}
@media(max-width:640px){
  .ajk-hero{padding:13px!important;border-radius:17px!important}
  .ajk-brandline{gap:9px}.ajk-logo-mark{width:59px;height:59px}
  .ajk-hero h1{font-size:clamp(20px,5.3vw,27px)!important}
  .ajk-kicker{font-size:9px}.ajk-hero p{font-size:11px!important}
  [data-testid="stTabs"] [data-baseweb="tab"]{padding:8px 10px!important}
}
@media(prefers-reduced-motion:reduce){.ajk-logo-mark{animation:none!important}}


/* v6.4 compact dashboard: bring the interactive pitch into view sooner */
.block-container{max-width:1160px!important;padding-top:.45rem!important;padding-bottom:2rem!important}
.ajk-hero{padding:11px 18px!important;border-radius:18px!important;margin-bottom:7px!important}
.ajk-brandline{gap:12px!important}
.ajk-logo-mark{width:60px!important;height:60px!important}
.ajk-kicker{font-size:9px!important;margin-bottom:2px!important;letter-spacing:.13em!important}
.ajk-hero h1{font-size:clamp(22px,2.8vw,31px)!important;line-height:1.04!important}
.ajk-hero p{font-size:12px!important;margin:4px 0 0!important}
.ajk-summary{border:1px solid rgba(50,202,152,.27);border-radius:17px;
  background:linear-gradient(110deg,rgba(9,37,50,.98),rgba(8,34,42,.97));
  padding:13px 17px;margin:5px 0 7px;display:flex;align-items:center;gap:18px}
.ajk-summary-main{flex:1;min-width:0}
.ajk-summary-head{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.ajk-summary-label{color:#8fe8c8;font-weight:800;font-size:10px;letter-spacing:.13em}
.ajk-summary-strong{font-size:21px;line-height:1.1;font-weight:850;color:#f5fffa}
.ajk-summary-desc{font-size:11px;color:#a9cbd2;margin-top:3px}
.ajk-summary-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.ajk-summary-stat{border:1px solid rgba(65,175,158,.16);background:rgba(2,17,29,.35);border-radius:10px;padding:8px 11px}
.ajk-summary-stat span{display:block;font-size:11px;color:#a9cbd2}
.ajk-summary-stat strong{display:block;font-size:21px;letter-spacing:-.04em;color:#fff;line-height:1.25}
.ajk-summary-gauge{width:82px;height:82px;border-radius:50%;display:grid;place-items:center;flex:none}
.ajk-summary-gauge .center{width:63px;height:63px;display:flex;flex-direction:column;align-items:center;
 justify-content:center;background:#102b34;border-radius:50%;font-weight:850;font-size:21px;color:#fff}
.ajk-summary-gauge small{font-size:10px;color:#a7ccbe}
/* Tighter Streamlit blocks without changing the native controls' behavior */
[data-testid="stVerticalBlock"]{gap:.55rem}
[data-testid="stExpander"]{margin-bottom:3px!important}
[data-testid="stTabs"] [data-baseweb="tab-list"]{padding:4px 5px!important;gap:5px!important}
[data-testid="stTabs"] [data-baseweb="tab"]{padding:8px 13px!important}
[data-testid="stTabs"] [data-baseweb="tab-panel"]{padding-top:8px!important}
/* The GW radio appears as compact selector buttons. */
div[data-testid="stRadio"] div[role="radiogroup"]{gap:7px;flex-wrap:wrap}
div[data-testid="stRadio"] div[role="radiogroup"] label{
 border:1px solid rgba(67,184,155,.30);border-radius:9px;background:rgba(10,35,49,.90);
 padding:5px 11px;margin:0;min-height:32px}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){
 border-color:#2bdd9d;background:rgba(22,153,111,.30)}
div[data-testid="stRadio"] div[role="radiogroup"] label p{font-weight:700}
@media(max-width:640px){
 .ajk-hero{padding:10px 12px!important}.ajk-brandline{gap:9px!important}
 .ajk-logo-mark{width:46px!important;height:46px!important}.ajk-hero h1{font-size:21px!important}
 .ajk-kicker{font-size:8px!important}.ajk-hero p{font-size:10px!important}
 .ajk-summary{padding:10px;gap:7px}.ajk-summary-head{margin-bottom:7px}
 .ajk-summary-strong{font-size:17px}.ajk-summary-desc{font-size:10px}
 .ajk-summary-stats{gap:5px}.ajk-summary-stat{padding:6px}
 .ajk-summary-stat span{font-size:9px}.ajk-summary-stat strong{font-size:16px}
 .ajk-summary-gauge{width:59px;height:59px}.ajk-summary-gauge .center{width:45px;height:45px;font-size:16px}
 div[data-testid="stRadio"] div[role="radiogroup"]{gap:4px}
 div[data-testid="stRadio"] div[role="radiogroup"] label{padding:4px 7px}
}


/* v6.5 TRUE DASHBOARD: multi-column, restrained stadium atmosphere and usable controls */
.block-container{max-width:1700px!important;padding-left:clamp(12px,2.4vw,34px)!important;
 padding-right:clamp(12px,2.4vw,34px)!important;padding-top:.45rem!important}
[data-testid="stAppViewContainer"]{
 background-image:
 radial-gradient(ellipse 33% 15% at 0% 2%,rgba(78,193,230,.20),transparent 75%),
 radial-gradient(ellipse 33% 15% at 100% 2%,rgba(78,193,230,.18),transparent 75%),
 radial-gradient(ellipse 40% 25% at 50% 2%,rgba(16,148,127,.12),transparent 85%),
 linear-gradient(180deg,#041321,#071a2a 55%,#04111e 100%)!important;
}
/* a hint of stadium lights without loading large images */
[data-testid="stAppViewContainer"]:after{content:"";position:fixed;left:0;right:0;top:70px;height:230px;
 pointer-events:none;opacity:.14;background:
 repeating-linear-gradient(165deg,transparent 0px,transparent 46px,rgba(60,222,189,.12) 47px,transparent 49px);
 mask-image:linear-gradient(to bottom,#000,transparent)}
.ajk-hero{max-width:100%!important}
.ajk-panel-heading{font-size:14px;font-weight:850;color:#effffb;letter-spacing:.025em;margin:6px 0 9px}
.ajk-sidecard{background:linear-gradient(140deg,rgba(8,36,54,.97),rgba(5,28,42,.95));
 border:1px solid rgba(45,173,156,.28);border-radius:16px;padding:16px 14px;
 box-shadow:0 14px 25px rgba(0,0,0,.14);margin:0 0 15px}
.ajk-side-kicker{color:#8ce9cc;font-size:10px;font-weight:800;letter-spacing:.13em;margin-bottom:10px;overflow-wrap:anywhere}
.ajk-side-rating{font-size:44px;color:#26e3a6;font-weight:850;line-height:1;letter-spacing:-.05em}
.ajk-side-rating small{font-size:14px;color:#9abfba;margin-left:3px}
.ajk-side-sub{font-size:13px;color:#c8ece2;margin-top:5px}
.ajk-side-divider{height:1px;background:rgba(165,232,213,.15);margin:16px 0 7px}
.ajk-side-metric{padding:11px 0;border-bottom:1px solid rgba(163,215,200,.11);
 display:flex;gap:6px;justify-content:space-between;align-items:center;min-width:0}
.ajk-side-metric:last-child{border-bottom:0}
.ajk-side-metric span{font-size:12px;color:#b5d6d5}
.ajk-side-metric strong{font-size:16px;font-weight:800;color:#f3fffc;text-align:right;overflow-wrap:anywhere}
.ajk-insight .ajk-side-metric{display:block}
.ajk-insight .ajk-side-metric strong{display:block;text-align:left;margin-top:5px;color:#3be2a7;font-size:15px}
.ajk-fixture-row{display:flex;justify-content:space-between;gap:8px;padding:12px 0;
 border-bottom:1px solid rgba(163,215,200,.12);font-size:12px}
.ajk-fixture-row:last-child{border-bottom:0}
.ajk-fixture-row strong{color:#e8fff7;white-space:nowrap}
.ajk-fixture-row span{color:#a9d5ce;text-align:right}
.ajk-guide>div{margin:0 0 13px}.ajk-guide>div:last-child{margin:0}
.ajk-guide b{color:#eafff5;font-size:13px;display:block}
.ajk-guide small{color:#a9cdd0;display:block;margin-top:4px;font-size:12px;line-height:1.4}
/* preserve portrait readability and formation within the central column */
.st-key-ajk_click_pitch{padding:12px 5px!important}
.st-key-ajk_click_bench{padding:10px 6px!important}
.st-key-ajk_click_pitch .player-portrait,.st-key-ajk_click_bench .player-portrait{max-width:100%}
[data-testid="stTabs"] [data-baseweb="tab-list"]{justify-content:center;gap:12px!important}
[data-testid="stTabs"] [data-baseweb="tab"]{min-width:170px;justify-content:center!important}
@media(max-width:1100px){
 .ajk-sidecard{padding:11px 9px}
 .ajk-side-metric{display:block}
 .ajk-side-metric strong{display:block;text-align:left;margin-top:3px}
 .block-container{padding-left:12px!important;padding-right:12px!important}
}
@media(max-width:780px){
 [data-testid="stTabs"] [data-baseweb="tab"]{min-width:0;padding:8px!important}
 .ajk-side-metric{display:flex}.ajk-side-metric strong{margin-top:0}
 .ajk-panel-heading{margin-top:12px}
 .ajk-sidecard{margin-bottom:8px}
}


/* v6.8 — Cinematic Dashboard Edition. All styling; native Streamlit controls remain interactive. */
:root{--ajk-neon:#20e6a0;--ajk-ice:#d9f8f3;--ajk-gold:#f4c452}
.block-container{max-width:1660px!important;padding-left:clamp(13px,1.6vw,28px)!important;
 padding-right:clamp(13px,1.6vw,28px)!important;padding-top:.15rem!important}
.ajk-hero{margin:0 auto 10px!important;max-width:1220px!important;min-height:130px!important;
 padding:18px clamp(18px,4vw,56px)!important;border-radius:20px!important;
 background:linear-gradient(90deg,rgba(2,21,36,.90),rgba(4,29,44,.68) 53%,rgba(5,28,43,.78))!important;
 border:1px solid rgba(46,209,181,.38)!important;box-shadow:0 18px 42px rgba(0,0,0,.22)!important}
.ajk-hero:before{width:260px!important;height:200px!important;right:10%!important;top:-140px!important;
 border-color:rgba(28,243,167,.28)!important;box-shadow:0 0 85px rgba(22,214,151,.11)}
.ajk-hero .ajk-brandline{justify-content:center!important;gap:22px!important}
.ajk-hero .ajk-logo-mark{width:94px!important;height:94px!important;object-fit:contain!important;
 filter:drop-shadow(0 0 13px rgba(27,243,177,.25))}
.ajk-hero .ajk-brandcopy{text-align:left}
.ajk-hero h1{font-size:clamp(26px,3.5vw,52px)!important;letter-spacing:-.045em!important;
 font-weight:900!important;line-height:1.05!important}
.ajk-hero p{font-size:13px!important;letter-spacing:.045em;color:#bbdce3!important;margin-top:9px!important}
.ajk-hero .ajk-kicker{font-size:10px!important;letter-spacing:.22em!important;color:#88edce!important}
/* Three substantial nav pills rather than tiny default tabs. */
[data-testid="stTabs"] [data-baseweb="tab-list"]{
 display:flex!important;justify-content:center!important;gap:12px!important;
 border-bottom:0!important;margin:8px auto 22px!important;max-width:920px;
 padding:6px!important;border-radius:17px;
 background:rgba(3,22,38,.75)!important;border:1px solid rgba(63,177,176,.30)!important;
 box-shadow:0 10px 35px rgba(0,0,0,.15)}
[data-testid="stTabs"] [data-baseweb="tab"]{
 flex:1!important;min-width:0!important;min-height:52px!important;justify-content:center!important;
 border-radius:12px!important;border:1px solid transparent!important;
 color:#edf9fb!important;font-size:clamp(12px,1vw,17px)!important;font-weight:750!important;
 background:rgba(9,38,58,.63)!important;transition:background .18s ease,box-shadow .18s ease}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"]{
 color:#03251d!important;background:linear-gradient(110deg,#11d79a,#04a86f)!important;
 box-shadow:0 4px 23px rgba(19,224,146,.23)!important;border-color:rgba(63,253,179,.65)!important}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"]{display:none!important}
.ajk-panel-heading{font-size:clamp(13px,1vw,18px)!important;margin:3px 0 12px!important;
 letter-spacing:.014em!important;text-shadow:0 2px 10px rgba(0,0,0,.25)}
.ajk-sidecard{background:linear-gradient(135deg,rgba(5,29,47,.89),rgba(4,27,43,.91))!important;
 border:1px solid rgba(62,192,182,.37)!important;border-radius:20px!important;
 padding:20px 18px!important;box-shadow:0 12px 31px rgba(0,0,0,.26),inset 0 1px 0 rgba(163,250,234,.07)!important;
 backdrop-filter:blur(7px)}
.ajk-side-kicker{font-size:11px!important;color:#69eec3!important}
.ajk-side-metric{padding:13px 0!important}
.ajk-side-metric span{font-size:13px!important}
.ajk-side-metric strong{font-size:17px!important}
.ajk-insight .ajk-side-metric strong{color:#48f7b5!important}
.ajk-fixture-row{padding:14px 0!important}
.ajk-guide{border-color:rgba(53,193,170,.3)!important}
/* Give the pitch the bright stadium turf and clean glowing frame in the approved visual. */
.st-key-ajk_click_pitch{
 position:relative!important;isolation:isolate!important;overflow:hidden!important;
 border:2px solid #20ea9a!important;border-radius:24px 24px 4px 4px!important;
 padding:12px 10px 24px!important;
 background:repeating-linear-gradient(180deg,rgba(255,255,255,.028) 0,rgba(255,255,255,.028) 120px,
 rgba(0,0,0,.027) 120px,rgba(0,0,0,.027) 240px),linear-gradient(160deg,#048c51,#006e41 85%)!important;
 box-shadow:0 0 0 1px rgba(14,228,143,.17),0 12px 37px rgba(1,14,17,.45),0 0 36px rgba(9,222,138,.15)!important}
.st-key-ajk_click_pitch:before{content:"";z-index:-1;position:absolute;inset:22px 14px 15px;
 border:2px solid rgba(202,255,224,.42);pointer-events:none}
.st-key-ajk_click_pitch:after{content:"";z-index:-1;position:absolute;left:28%;width:44%;top:24px;height:62px;
 border:2px solid rgba(211,255,229,.40);border-top:0;pointer-events:none}
.st-key-ajk_click_pitch [data-testid="stButton"] button{
 background:linear-gradient(160deg,rgba(5,54,44,.90),rgba(4,42,36,.93))!important;
 border:1px solid rgba(191,255,223,.28)!important;border-radius:14px!important;
 box-shadow:0 5px 12px rgba(0,0,0,.13)!important;
 min-height:120px!important;color:#fff!important;overflow:hidden}
.st-key-ajk_click_pitch [data-testid="stButton"] button:hover{
 border-color:#8dffd3!important;box-shadow:0 0 12px rgba(51,246,154,.31)!important}
.st-key-ajk_click_pitch [data-testid="stButton"] button[kind="primary"]{
 border-color:#b6ffcf!important;box-shadow:0 0 0 2px rgba(182,255,207,.18)!important}
.st-key-ajk_click_pitch [data-testid="stButton"] button img{max-height:85px!important;object-fit:contain!important}
.st-key-ajk_click_pitch [data-testid="stButton"] button p,
.st-key-ajk_click_bench [data-testid="stButton"] button p{font-weight:700!important;line-height:1.35!important}
.st-key-ajk_click_bench{border-radius:4px 4px 22px 22px!important;
 border:2px solid #1ee79d!important;border-top:0!important;
 background:linear-gradient(180deg,rgba(0,76,58,.92),rgba(3,40,42,.97))!important;
 box-shadow:0 14px 31px rgba(0,0,0,.24),0 0 28px rgba(8,221,131,.12)!important}
.st-key-ajk_click_bench [data-testid="stButton"] button{background:rgba(0,45,41,.8)!important;
 border:1px solid rgba(170,255,222,.22)!important;border-radius:13px!important;min-height:112px!important}
.ajk-best-xi{display:flex;flex-wrap:wrap;align-items:center;gap:10px;justify-content:space-between;
 border:1px solid rgba(42,228,148,.37);border-radius:13px;
 background:linear-gradient(100deg,rgba(5,96,64,.81),rgba(4,47,50,.82));
 padding:11px 15px;margin:6px 0 9px;color:#d7ffed}
.ajk-best-xi strong{color:#54ffb9;font-size:17px}
.ajk-best-xi span{font-size:12px;color:#bcf7de}
/* Keep form readable on dark artwork, and make the top controls less visually dominant. */
[data-testid="stTextInput"] input,[data-testid="stSelectbox"] div[data-baseweb="select"]>div{
 border-radius:11px!important;background:rgba(11,27,43,.91)!important;
 border-color:rgba(130,208,199,.23)!important}
[data-testid="stExpander"]{background:rgba(4,25,40,.79)!important}
@media(max-width:1100px){
 .ajk-sidecard{padding:13px 11px!important}
 .ajk-hero{min-height:100px!important}.ajk-hero .ajk-logo-mark{width:66px!important;height:66px!important}
 .st-key-ajk_click_pitch [data-testid="stButton"] button{min-height:98px!important}
}
@media(max-width:780px){
 .ajk-hero{padding:13px!important;min-height:0!important}
 .ajk-hero .ajk-brandline{gap:10px!important;justify-content:flex-start!important}
 .ajk-hero .ajk-logo-mark{width:52px!important;height:52px!important}
 .ajk-hero h1{font-size:clamp(20px,5.1vw,27px)!important}
 [data-testid="stTabs"] [data-baseweb="tab-list"]{gap:4px!important;padding:4px!important;margin-bottom:13px!important}
 [data-testid="stTabs"] [data-baseweb="tab"]{min-height:40px!important;font-size:11px!important;padding:6px 4px!important}
 .st-key-ajk_click_pitch [data-testid="stButton"] button{min-height:85px!important;padding:5px 2px!important}
 .st-key-ajk_click_pitch{padding:8px 4px 12px!important}
 .st-key-ajk_click_bench{padding:8px 3px!important}
 .st-key-ajk_click_bench [data-testid="stButton"] button{min-height:82px!important}
 .ajk-sidecard{backdrop-filter:none}
}


/* v6.9: mockup-first desktop composition; all original Streamlit interactions remain native. */
:root{--mock-ink:#041725;--mock-card:rgba(4,24,40,.87);--mock-line:rgba(83,198,203,.30);--mock-mint:#25e5a3}
.block-container{max-width: min(96vw, 1820px)!important;width:100%!important;padding:0.65rem clamp(12px,1.2vw,25px) 4rem!important}
[data-testid="stMainBlockContainer"]{max-width:min(96vw,1820px)!important}
[data-testid="stAppViewContainer"]{background-position:center top!important}
/* Full-bleed branding and readable technology-meets-stadium look. */
.ajk-hero{max-width:1440px!important;margin:0 auto 13px!important;background:linear-gradient(90deg,rgba(1,17,33,.55),rgba(2,24,40,.24) 50%,rgba(3,21,37,.55))!important;border:0!important;box-shadow:none!important;padding:12px 25px 19px!important;min-height:142px!important}
.ajk-hero:before{display:none!important}
.ajk-hero .ajk-brandline{justify-content:center!important;gap:18px!important}
.ajk-hero .ajk-logo-mark{width:112px!important;height:112px!important;filter:drop-shadow(0 0 20px rgba(43,237,169,.42))!important}
.ajk-hero .ajk-kicker{font-size:12px!important;letter-spacing:.27em!important;color:#8bd7e8!important;text-align:center!important}
.ajk-hero h1{font-size:clamp(34px,4.0vw,68px)!important;letter-spacing:-.04em!important;font-weight:850!important;text-shadow:0 5px 22px rgba(0,0,0,.46)!important}
.ajk-hero h1 span{color:#26f3a5!important}
.ajk-hero p{font-size:clamp(11px,.95vw,16px)!important;letter-spacing:.12em!important;text-align:center!important;text-transform:uppercase!important}
/* Compact team import remains accessible, but no longer dominates the dashboard. */
[data-testid="stForm"]{background:rgba(2,23,39,.76)!important;border:1px solid var(--mock-line)!important;box-shadow:0 10px 30px rgba(0,0,0,.15)!important;border-radius:15px!important;padding:10px 15px!important}
[data-testid="stForm"] label{font-size:11px!important}
[data-testid="stTextInput"] input{min-height:38px!important}
[data-testid="stSelectbox"] div[data-baseweb="select"]>div{min-height:38px!important}
[data-testid="stButton"] button[kind="primary"],[data-testid="stFormSubmitButton"] button[kind="primary"]{background:linear-gradient(110deg,#12d897,#039964)!important;color:#05281d!important;font-weight:850!important}
/* Primary navigation should look like the large game tabs in the reference. */
[data-testid="stTabs"] [data-baseweb="tab-list"]{width:min(100%,930px)!important;margin:8px auto 22px!important;display:flex!important;justify-content:center!important;gap:0!important;padding:4px!important;background:linear-gradient(120deg,rgba(5,26,44,.95),rgba(6,35,54,.90))!important;border:1px solid rgba(67,173,204,.52)!important;border-radius:19px!important;box-shadow:0 12px 32px rgba(0,0,0,.3)!important}
[data-testid="stTabs"] [data-baseweb="tab"]{flex:1 1 0!important;display:flex!important;justify-content:center!important;align-items:center!important;border-radius:15px!important;min-height:58px!important;padding:12px 7px!important;font-size:clamp(12px,1.3vw,21px)!important;font-weight:800!important;background:transparent!important;border:0!important;color:#effffb!important}
[data-testid="stTabs"] [aria-selected="true"]{background:linear-gradient(105deg,#15da94,#05946d)!important;color:white!important;box-shadow:0 0 18px rgba(27,232,151,.26)!important}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],[data-testid="stTabs"] [data-baseweb="tab-border"]{display:none!important}
[data-testid="stTabs"] [data-baseweb="tab-panel"]{padding-top:6px!important}
/* Side panels: larger typography and softer glass panels. */
.ajk-panel-heading{font-size:clamp(13px,1.18vw,20px)!important;letter-spacing:0!important;font-weight:850!important;color:#f8ffff!important;margin:8px 0 13px!important}
.ajk-sidecard{background:var(--mock-card)!important;border:1px solid var(--mock-line)!important;border-radius:20px!important;padding:clamp(12px,1.5vw,22px)!important;box-shadow:0 16px 44px rgba(0,5,15,.38),inset 0 1px rgba(150,238,229,.05)!important;backdrop-filter:blur(8px)!important}
.ajk-side-kicker{font-size:clamp(10px,.85vw,14px)!important;color:#65f8bc!important}
.ajk-side-rating{font-size:clamp(30px,2.3vw,46px)!important}
.ajk-side-metric{padding:clamp(9px,1vw,16px) 0!important}
.ajk-side-metric span{font-size:clamp(11px,1vw,15px)!important}
.ajk-side-metric strong{font-size:clamp(13px,1.13vw,19px)!important}
.ajk-fixture-row{padding:clamp(11px,.9vw,16px) 0!important;font-size:clamp(11px,.9vw,16px)!important}
/* Put the full squad first: keep gameweek choices compact and let pitch be hero. */
.ajk-best-xi{border-radius:16px!important;background:linear-gradient(100deg,rgba(0,95,65,.90),rgba(1,57,52,.87))!important;min-height:51px!important}
.ajk-best-xi strong{color:#6bffc6!important}
.st-key-ajk_click_pitch{padding:22px 13px 28px!important;border:2px solid #15e995!important;border-radius:25px 25px 0 0!important;box-shadow:0 15px 47px rgba(0,0,0,.36),0 0 40px rgba(13,210,133,.22)!important;background:repeating-linear-gradient(180deg,rgba(255,255,255,.025) 0,rgba(255,255,255,.025) 125px,rgba(0,0,0,.02) 125px,rgba(0,0,0,.02) 250px),linear-gradient(150deg,#07985b,#007846)!important}
.st-key-ajk_click_pitch [data-testid="stButton"] button{background:linear-gradient(180deg,rgba(5,64,53,.36),rgba(2,36,35,.87))!important;min-height:clamp(122px,10vw,172px)!important;padding:8px 2px!important;border:1px solid rgba(185,255,226,.20)!important;border-radius:13px!important}
.st-key-ajk_click_pitch [data-testid="stButton"] button img{max-height:clamp(70px,6.5vw,110px)!important;max-width:100%!important}
.st-key-ajk_click_pitch [data-testid="stButton"] button p{font-size:clamp(9px,.9vw,14px)!important;line-height:1.3!important}
.st-key-ajk_click_bench{padding:12px!important;background:rgba(2,44,43,.95)!important;border:2px solid #15e995!important;border-top:0!important;border-radius:0 0 24px 24px!important}
.st-key-ajk_click_bench [data-testid="stButton"] button{min-height:clamp(99px,7.5vw,140px)!important}
/* At tablet widths, favor native stacking and preserve touch targets. */
@media(max-width:1100px){.ajk-hero{min-height:98px!important}.ajk-hero .ajk-logo-mark{width:76px!important;height:76px!important}.ajk-hero h1{font-size:clamp(24px,4vw,42px)!important}.ajk-sidecard{padding:12px!important}.st-key-ajk_click_pitch [data-testid="stButton"] button{min-height:102px!important}}
@media(max-width:700px){.block-container{max-width:100%!important;padding:0.65rem 9px 3rem!important}.ajk-hero{padding:10px 4px!important;min-height:0!important}.ajk-hero .ajk-brandline{justify-content:center!important;gap:9px!important}.ajk-hero .ajk-logo-mark{width:51px!important;height:51px!important}.ajk-hero h1{font-size:clamp(20px,5.2vw,31px)!important}.ajk-hero .ajk-kicker{font-size:8px!important}.ajk-hero p{font-size:9px!important;letter-spacing:0!important}[data-testid="stTabs"] [data-baseweb="tab-list"]{margin-bottom:10px!important}[data-testid="stTabs"] [data-baseweb="tab"]{font-size:11px!important;min-height:46px!important}.st-key-ajk_click_pitch [data-testid="stButton"] button{min-height:90px!important;padding:3px 1px!important}.st-key-ajk_click_pitch [data-testid="stButton"] button img{max-height:58px!important}.st-key-ajk_click_pitch [data-testid="stButton"] button p{font-size:9px!important}.ajk-sidecard{backdrop-filter:none!important}}

</style>
""", unsafe_allow_html=True)


# v6.7.1: Make the actual stadium asset visible and diagnose missing uploads.
# Keep image in the same GitHub directory as app.py; never depend on a remote URL.
@st.cache_data(show_spinner=False)
def stadium_background_css() -> str:
    image_path = Path(__file__).resolve().parent / "stadium_bg.webp"
    if not image_path.is_file():
        return ""
    try:
        image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    # Explicit background overrides the older v6.3/v6.5 CSS gradients.
    # Use a visible image layer and a moderate overlay, retaining text contrast.
    return f"""
    <style>
    html, body, [data-testid="stApp"],
    [data-testid="stAppViewContainer"] {{
       background-color: #03111c !important;
    }}
    [data-testid="stAppViewContainer"] {{
       background-image:
         linear-gradient(180deg, rgba(2,12,23,.19) 0%, rgba(2,12,23,.30) 42%, rgba(2,12,23,.47) 100%),
         url("data:image/webp;base64,{image_data}") !important;
       background-repeat: no-repeat !important;
       background-size: cover !important;
       background-position: center top !important;
       background-attachment: fixed !important;
    }}
    [data-testid="stAppViewContainer"]::before,
    [data-testid="stAppViewContainer"]::after {{
       display:none !important;
       content:none !important;
    }}
    [data-testid="stHeader"] {{background:rgba(2,12,23,.12)!important;}}
    /* Keep side panels readable, allowing the stadium to show around them. */
    .ajk-sidecard {{background:rgba(5,26,41,.88)!important;}}
    @media(max-width:780px) {{
      [data-testid="stAppViewContainer"] {{
        background-attachment: scroll !important;
        background-size: auto 100vh !important;
        background-position: center top !important;
      }}
    }}
    </style>
    """


_stadium_css = stadium_background_css()
if _stadium_css:
    st.markdown(_stadium_css, unsafe_allow_html=True)
else:
    st.warning(
        "Stadium background not found. Add stadium_bg.webp to the same GitHub folder as app.py "
        "(exact filename and lowercase extension), then redeploy."
    )


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
    # Show fixture and projected points together on every player card.
    fixture = fixture_badge(player, gw, fixture_map, clubs)
    xp = player_fixture_xp(player, gw, fixture_map, overrides)
    detail = f"{fixture} · {xp:.1f} xP"
    fixture_text = html.escape(fixture)
    # The available flag is from the FPL API, not a guarantee of starting.
    symbol, description = player_status_symbol(player)
    flag = (f'<span class="squad-warning" title="{html.escape(description, quote=True)}">'
            f'{symbol}</span>') if symbol else ''
    bench_tag = (f'<span class="bench-number">{html.escape(str(bench_number))}</span>'
                 if bench_number else '')
    return (f'<div class="squad-player">{bench_tag}<div class="squad-photo">'
            f'{player_portrait_html(player)}{flag}</div>'
            f'<div class="squad-player-label"><strong title="{name}">{name}{marker}</strong>'
            f'<small title="{html.escape(detail)}">{fixture_text}</small>'
            f'<small>{xp:.1f} xP</small></div></div>')


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
                    selected_id: int | None, on_click,
                    awaiting_swap: bool = False) -> None:
    """Clickable portrait pitch: select a player, then choose an action below."""
    starters = {int(p["id"]) for p in xi}
    bench = [p for p in squad if int(p["id"]) not in starters]
    keeper = [p for p in bench if int(p["element_type"]) == 1]
    outfield = sorted(
        (p for p in bench if int(p["element_type"]) != 1),
        key=lambda p: player_fixture_xp(p, gw, fixture_map, overrides), reverse=True,
    )

    def player_button(player: dict, *, bench_no: str = "") -> None:
        pid = int(player["id"])
        name = str(player.get("web_name", "?"))
        photo = player_photo_url(player)
        portrait = f"![photo]({photo})" if photo else "👤"
        fixture = fixture_badge(player, gw, fixture_map, clubs)
        xp = player_fixture_xp(player, gw, fixture_map, overrides)
        detail = f"{fixture}  \n{xp:.1f} xP"
        role = "captain" if pid == captain_id else "vice" if pid == vice_id else "regular"
        symbol, description = player_status_symbol(player)
        warning = f" {symbol}" if symbol else ""
        prefix = f"{bench_no} · " if bench_no else ""
        instruction = (f"Choose {name} as a substitution target" if awaiting_swap
                       else f"Show actions for {name}")
        st.button(
            f"{portrait}  \n{prefix}{name}{warning}  \n{detail}",
            key=f"pitch_click_{gw}_{pid}_{role}", use_container_width=True,
            type="primary" if selected_id == pid else "secondary",
            help=f"{description} · {instruction}" if symbol else instruction,
            on_click=on_click, args=(pid,),
        )

    counts = Counter(int(p["element_type"]) for p in xi)
    formation = f"{counts[2]}-{counts[3]}-{counts[4]}"
    with st.container(key="ajk_click_pitch"):
        st.markdown(f"**GW {gw} · {formation} · Starting XI**")
        for position in (1, 2, 3, 4):
            group = [p for p in xi if int(p["element_type"]) == position]
            if not group:
                continue
            total = max(5, len(group))
            side = (total - len(group)) / 2
            widths = ([side] if side else []) + [1] * len(group) + ([side] if side else [])
            cols = st.columns(widths, gap="small", vertical_alignment="top")
            offset = 1 if side else 0
            for i, player in enumerate(group):
                with cols[i + offset]:
                    player_button(player)
    with st.container(key="ajk_click_bench"):
        st.markdown("**SUBSTITUTES** · Click any player to see available actions")
        cols = st.columns(4, gap="small")
        for i, player in enumerate(keeper + outfield):
            with cols[i]:
                bench_no = "GK" if int(player["element_type"]) == 1 else str(i)
                player_button(player, bench_no=bench_no)


# Friendly availability labels for the official FPL player status codes.
# Distinct icons for the statuses returned by the public FPL API.
# Available players intentionally receive no badge on the pitch.
STATUS_META = {
    "a": ("", "Available"),
    "d": ("❔", "Doubtful"),
    "i": ("🩹", "Injured"),
    "s": ("🚫", "Suspended"),
    "u": ("⛔", "Unavailable"),
    "n": ("❌", "Not available"),
}


def player_status_symbol(player: dict) -> tuple[str, str]:
    code = str(player.get("status") or "").strip().lower()
    if code in STATUS_META:
        return STATUS_META[code]
    return ("⚠️", "Unknown status")


def player_status_label(player: dict) -> str:
    symbol, description = player_status_symbol(player)
    return f"{symbol} {description}" if symbol else "🟢 Available"


def availability_legend(squad: list[dict]) -> None:
    """Small reference legend; always visible, highlights currently flagged players."""
    active = {str(p.get("status") or "").strip().lower() for p in squad}
    labels = [("❔", "Doubtful", "d"), ("🩹", "Injured", "i"),
              ("🚫", "Suspended", "s"), ("⛔", "Unavailable", "u"),
              ("❌", "Not available", "n")]
    with st.container():
        st.caption("**Availability symbols** · shown beside flagged players on the pitch and bench")
        cols = st.columns(5, gap="small")
        for col, (symbol, label, code) in zip(cols, labels):
            with col:
                st.markdown(f"{symbol} **{label}**" if code in active else f"{symbol} {label}")
        if any(code and code not in STATUS_META for code in active):
            st.caption("⚠️ Unknown status — check the latest FPL availability data.")
        st.caption("No symbol = FPL lists the player as available. Availability does not guarantee a start.")


def squad_frame(squad: list[dict], gws: list[int], fixture_map: dict,
                clubs: dict, overrides: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Player": label(p, clubs), "Position": POSITION_NAMES[int(p["element_type"])],
        "GW xP": round(player_fixture_xp(p, gws[0], fixture_map, overrides), 2),
        "Horizon xP": round(horizon_xp(p, gws, fixture_map, overrides), 2),
        "Sell price": money(p.get("selling_price", p.get("now_cost", 0))),
        "Status": player_status_label(p),
    } for p in squad])


def clear_pitch_actions() -> None:
    """Close old player menus and pending substitutions after squad-wide edits."""
    for key in list(st.session_state):
        if str(key).startswith(("pitch_action_selected_", "pitch_action_swap_", "pitch_swap_selected_", "quick_transfer_")):
            st.session_state.pop(key, None)


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
    st.session_state.manual_vice_by_gw = {}
    st.session_state.draft_moves = []
    st.session_state.chip_result = None
    clear_pitch_actions()


def restore_original_team() -> None:
    """Undo all draft transfers/chip simulations, retaining the imported snapshot."""
    st.session_state.draft = [dict(p) for p in st.session_state.original_squad]
    st.session_state.bank = int(st.session_state.original_bank)
    st.session_state.draft_moves = []
    st.session_state.manual_xi = []
    st.session_state.manual_captain = None
    st.session_state.manual_xi_by_gw = {}
    st.session_state.manual_captain_by_gw = {}
    st.session_state.manual_vice_by_gw = {}
    st.session_state.chip_result = None
    st.session_state.advisor_result = None
    st.session_state.advisor_key = None
    clear_pitch_actions()


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
            or bool(st.session_state.get("manual_captain_by_gw"))
            or bool(st.session_state.get("manual_vice_by_gw")))


st.markdown("""<div class="ajk-hero"><div class="ajk-brandline"><img class="ajk-logo-mark" alt="AJK Bola Wawei AI football intelligence logo" src="data:image/png;base64,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"><div class="ajk-brandcopy"><div class="ajk-kicker">FOOTBALL INTELLIGENCE · FREE</div><h1>AJK Bola Wawei <span>AI</span></h1><p>Best XI · Smart Transfers · Wildcard &amp; Free Hit</p></div></div></div>""", unsafe_allow_html=True)

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
        "manual_xi", "manual_captain", "manual_xi_by_gw", "manual_captain_by_gw", "manual_vice_by_gw", "draft_moves", "chip_result",
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

# The two controls people need most are visible; advanced planner settings stay tucked away.
settings_a, settings_b = st.columns(2, gap="small")
with settings_a:
    selected_gw = st.selectbox("Starting Gameweek", available_gws,
                               format_func=lambda gw: f"GW {gw}")
horizon_list = [gw for gw in available_gws if gw >= selected_gw]
with settings_b:
    horizon = st.selectbox(
        "Look Ahead", options=list(range(1, len(horizon_list) + 1)),
        index=min(5, len(horizon_list)) - 1,
        format_func=lambda n: f"{n} GW" if n == 1 else f"{n} GWs",
    )
with st.expander("⚙️ Advanced planning options", expanded=False):
    strategy = st.selectbox("AI Strategy", ["Balanced", "Safe", "Aggressive"])
    ft = st.number_input("Free transfers available (check your FPL account)",
                         min_value=0, max_value=5, value=1)
    st.caption("Safe favours reliable minutes; Aggressive favours upside. "
               "These are heuristic projections, not guaranteed outcomes.")
minutes_overrides = {}  # Keep the automatic expected-minutes model.

ft = int(ft)
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
# One cohesive team header + rating/metrics panel instead of four stacked cards.
team_name = html.escape(str(profile.get("name", "My FPL Team")))
st.markdown(f"**{team_name}** · GW {gws[0]}–{gws[-1]} · Simulated planning only")
rating_value = max(0, min(100, int(assessment["rating"])))
rating_label = "Excellent" if rating_value >= 85 else "Strong" if rating_value >= 70 else "Promising" if rating_value >= 55 else "Needs attention"

tab_team, tab_transfers, tab_chips = st.tabs(
    ["🏟️ My Team", "🧠 Smart Transfers", "✨ Wildcard / Free Hit"]
)
with tab_team:
    # Desktop: team/AI overview | full interactive squad | fixtures/decision support.
    # Streamlit's columns stack naturally on narrow/mobile screens.
    overview_col, pitch_col, upcoming_col = st.columns([1.03, 2.62, 1.03], gap="medium")
    with overview_col:
        st.markdown("<div class='ajk-panel-heading'>◈ TEAM OVERVIEW</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="ajk-sidecard">
          <div class="ajk-side-kicker">AI TEAM RATING</div>
          <div class="ajk-side-rating">{rating_value}<small>/100</small></div>
          <div class="ajk-side-sub">{rating_label} squad</div>
          <div class="ajk-side-divider"></div>
          <div class="ajk-side-metric"><span>GW {preview_gw} xP</span><strong>{lineup['total_xp']:.1f}</strong></div>
          <div class="ajk-side-metric"><span>{len(gws)}-GW xP</span><strong>{assessment['total_xp']:.1f}</strong></div>
          <div class="ajk-side-metric"><span>Bank</span><strong>{html.escape(money(bank))}</strong></div>
          <div class="ajk-side-metric"><span>Free transfers</span><strong>{ft}</strong></div>
        </div>""", unsafe_allow_html=True)
        st.markdown("<div class='ajk-panel-heading'>✦ AI INSIGHTS</div>", unsafe_allow_html=True)
        automatic_captain = lineup.get("captain", {})
        captain_name = html.escape(str(automatic_captain.get("web_name", "—")))
        st.markdown(f"""
        <div class="ajk-sidecard ajk-insight">
          <div class="ajk-side-metric"><span>👑 Best captain</span><strong>{captain_name}</strong></div>
          <div class="ajk-side-metric"><span>⚽ GW formation</span><strong>{Counter(int(p['element_type']) for p in lineup['xi'])[2]}-{Counter(int(p['element_type']) for p in lineup['xi'])[3]}-{Counter(int(p['element_type']) for p in lineup['xi'])[4]}</strong></div>
          <div class="ajk-side-metric"><span>🧠 Team status</span><strong>{rating_label}</strong></div>
        </div>""", unsafe_allow_html=True)
        st.caption("Estimated points are forecasts, not guarantees.")

    with upcoming_col:
        st.markdown("<div class='ajk-panel-heading'>▤ UPCOMING FIXTURES</div>", unsafe_allow_html=True)
        # Display fixtures for the AI-recommended captain across the horizon.
        captain_team_id = int(automatic_captain.get("team", 0)) if automatic_captain else 0
        fixtures_rows = []
        for week in gws:
            matches = fixture_map.get((int(week), captain_team_id), []) if captain_team_id else []
            if matches:
                opponent_text = " · ".join(
                    html.escape(str(clubs.get(int(fx.get("opponent", 0)), "?"))) +
                    (" (H)" if fx.get("home") else " (A)") for fx in matches
                )
            else:
                opponent_text = "Blank GW"
            fixtures_rows.append(
                f'<div class="ajk-fixture-row"><strong>GW {week}</strong><span>{opponent_text}</span></div>'
            )
        fixture_player_name = captain_name
        st.markdown(
            '<div class="ajk-sidecard"><div class="ajk-side-kicker">CAPTAIN FIXTURES · '
            + fixture_player_name + '</div>' + ''.join(fixtures_rows) + '</div>',
            unsafe_allow_html=True,
        )
        st.markdown("<div class='ajk-panel-heading'>⚡ QUICK ACTIONS</div>", unsafe_allow_html=True)
        st.markdown("""
        <div class="ajk-sidecard ajk-guide">
          <div><b>↔ Smart Transfer Advisor</b><small>Open the Smart Transfers tab for the strongest move—or advice to roll.</small></div>
          <div><b>◇ Wildcard Squad Builder</b><small>Open Wildcard / Free Hit to explore your optimal squad.</small></div>
          <div><b>⚡ Free Hit Builder</b><small>Plan a one-Gameweek squad without changing your real FPL team.</small></div>
        </div>""", unsafe_allow_html=True)

    with pitch_col:
        with st.container():
            st.markdown("### My Team · Gameweek Preview")
            preview_gw = st.radio(
                "Preview Gameweek", options=gws, index=gws.index(preview_gw),
                horizontal=True, format_func=lambda gw: f"GW {gw}",
                label_visibility="collapsed",
            )
            # Streamlit widgets update on rerun; changing the preview only changes this view.
            if int(preview_gw) != int(st.session_state.preview_gw):
                st.session_state.preview_gw = int(preview_gw)
                st.rerun()
            # Keep the Gameweek selector close to the interactive pitch.
            # Future GW previews always use the current simulated squad.
            # The engine selects the optimal legal XI for this GW. No alternative-formation UI.
            gw_xp = {int(p["id"]): player_fixture_xp(p, preview_gw, fixture_map, minutes_overrides)
                     for p in squad}
            auto_xi = lineup["xi"]
            ai_counts = Counter(int(p["element_type"]) for p in auto_xi)
            ai_formation = f"{ai_counts[2]}-{ai_counts[3]}-{ai_counts[4]}"
            st.markdown(
                f'<div class="ajk-best-xi"><div>AI Best Formation: '
                f'<strong>{ai_formation}</strong> <span> · GW {preview_gw}</span></div>'
                f'<div><strong>{lineup["total_xp"]:.2f} xP</strong> '
                '<span>including captain</span></div></div>',
                unsafe_allow_html=True,
            )
            # One-time migration: the previous version saved chosen formations as manual
            # overrides. Clear them once so upgrading immediately enables auto-XI for every GW.
            if not st.session_state.get("auto_formations_v524_initialized", False):
                st.session_state.manual_xi_by_gw = {}
                st.session_state.manual_captain_by_gw = {}
                st.session_state.manual_vice_by_gw = {}
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
                        f"The AI recommends {ai_formation}. Use Reset to Original FPL Team above to discard all draft changes.")
            else:
                pass  # AI status is displayed in the formation banner above.
            cap_ids = [int(p["id"]) for p in xi]
            cap_default = st.session_state.get("manual_captain_by_gw", {}).get(
                preview_gw, st.session_state.get("manual_captain") if preview_gw == selected_gw else None
            )
            cap = cap_default if cap_default in cap_ids else int(lineup["captain"]["id"])
            if cap not in cap_ids:
                cap = max(xi, key=lambda p: player_fixture_xp(p, preview_gw, fixture_map, minutes_overrides))["id"]
            vice_override = st.session_state.get("manual_vice_by_gw", {}).get(preview_gw)
            vice = (vice_override if vice_override in cap_ids and vice_override != cap
                    else max((pid for pid in cap_ids if pid != cap), key=lambda pid: gw_xp[pid]))
            # Keep the single reset control within reach of the interactive pitch.
            # It restores the full imported squad and clears manual GW overrides.
            if draft_has_changes():
                st.caption("✏️ Simulated changes active · Reset to discard transfers, substitutions and captaincy edits across all GWs.")
                if st.button("↩️ Reset to Original FPL Team", key="reset_team_main",
                             use_container_width=True, type="secondary"):
                    restore_original_team()
                    st.rerun()

            selection_key = f"pitch_action_selected_{st.session_state.loaded_id}_{preview_gw}"
            pending_key = f"pitch_action_swap_{st.session_state.loaded_id}_{preview_gw}"
            selected_player_id = st.session_state.get(selection_key)
            pending_player_id = st.session_state.get(pending_key)
            available_ids = {int(p["id"]) for p in squad}
            current_starters = {int(p["id"]) for p in xi}
            if selected_player_id not in available_ids:
                st.session_state.pop(selection_key, None)
                selected_player_id = None
            if pending_player_id not in available_ids:
                st.session_state.pop(pending_key, None)
                pending_player_id = None

            def make_substitution(first_id: int, second_id: int) -> None:
                """Safely swap a starter and bench player within this GW only."""
                if (first_id in current_starters) == (second_id in current_starters):
                    st.session_state["pitch_swap_message"] = "Choose one starter and one bench player."
                    return
                outgoing_id = first_id if first_id in current_starters else second_id
                incoming_id = second_id if first_id in current_starters else first_id
                proposed_ids = (current_starters - {outgoing_id}) | {incoming_id}
                proposed = [p for p in squad if int(p["id"]) in proposed_ids]
                ct = Counter(int(p["element_type"]) for p in proposed)
                if not (len(proposed) == 11 and ct[1] == 1 and
                        3 <= ct[2] <= 5 and 2 <= ct[3] <= 5 and 1 <= ct[4] <= 3):
                    st.session_state["pitch_swap_message"] = (
                        "⚠️ Invalid FPL formation. Select a different bench/starter pairing."
                    )
                    return
                st.session_state.setdefault("manual_xi_by_gw", {})[preview_gw] = list(proposed_ids)
                current_captain = st.session_state.get("manual_captain_by_gw", {}).get(preview_gw, cap)
                if current_captain not in proposed_ids:
                    current_captain = max(proposed_ids, key=lambda pid: gw_xp[pid])
                st.session_state.setdefault("manual_captain_by_gw", {})[preview_gw] = current_captain
                current_vice = st.session_state.get("manual_vice_by_gw", {}).get(preview_gw, vice)
                if current_vice not in proposed_ids or current_vice == current_captain:
                    current_vice = max((pid for pid in proposed_ids if pid != current_captain),
                                       key=lambda pid: gw_xp[pid])
                st.session_state.setdefault("manual_vice_by_gw", {})[preview_gw] = current_vice
                if preview_gw == selected_gw:
                    st.session_state.manual_xi = list(proposed_ids)
                    st.session_state.manual_captain = current_captain
                st.session_state["pitch_swap_message"] = "✅ Substitution applied to GW " + str(preview_gw) + "."

            def on_pitch_player_click(clicked_id: int) -> None:
                pending = st.session_state.get(pending_key)
                if pending is not None:
                    if pending == clicked_id:
                        st.session_state.pop(pending_key, None)
                        st.session_state.pop(selection_key, None)
                        return
                    if (pending in current_starters) == (clicked_id in current_starters):
                        st.session_state["pitch_swap_message"] = "Choose a player on the other side of the bench."
                        return
                    make_substitution(pending, clicked_id)
                    st.session_state.pop(pending_key, None)
                    st.session_state.pop(selection_key, None)
                    return
                if st.session_state.get(selection_key) == clicked_id:
                    st.session_state.pop(selection_key, None)
                else:
                    st.session_state[selection_key] = clicked_id

            if pending_player_id is not None:
                chosen = next(p for p in squad if int(p["id"]) == pending_player_id)
                direction = "bench player" if pending_player_id in current_starters else "starter"
                st.info(f"🔄 Substituting **{chosen.get('web_name', '?')}** — click a {direction} on the pitch to complete the swap.")
                if st.button("Cancel substitution", key=f"cancel_swap_{preview_gw}"):
                    st.session_state.pop(pending_key, None)
                    st.session_state.pop(selection_key, None)
                    st.rerun()
            else:
                st.caption("👆 Click a player's photo to choose Captain, Vice-Captain, Substitute or Transfer.")
            if st.session_state.get("pitch_swap_message"):
                st.caption(st.session_state.pop("pitch_swap_message"))
            clickable_pitch(xi, squad, cap, vice, preview_gw, fixture_map, clubs,
                            minutes_overrides, "Combined",
                            pending_player_id if pending_player_id is not None else selected_player_id,
                            on_pitch_player_click, awaiting_swap=pending_player_id is not None)
            availability_legend(squad)

            # The action menu appears only after the user clicks a player portrait/card.
            selected_player_id = st.session_state.get(selection_key)
            if pending_player_id is None and selected_player_id in available_ids:
                chosen = next(p for p in squad if int(p["id"]) == selected_player_id)
                is_starter = selected_player_id in current_starters
                with st.container(key="ajk_player_actions"):
                    st.markdown(f"**{html.escape(str(chosen.get('web_name', '?')))} · Player actions**")
                    if is_starter:
                        a, b, c = st.columns(3, gap="small")
                        with a:
                            if st.button("👑 Captain", key=f"action_captain_{preview_gw}",
                                         use_container_width=True, disabled=selected_player_id == cap):
                                st.session_state.setdefault("manual_captain_by_gw", {})[preview_gw] = selected_player_id
                                if selected_player_id == vice:
                                    st.session_state.setdefault("manual_vice_by_gw", {})[preview_gw] = cap
                                if preview_gw == selected_gw:
                                    st.session_state.manual_captain = selected_player_id
                                st.session_state.pop(selection_key, None)
                                st.rerun()
                        with b:
                            if st.button("◆ Vice-Captain", key=f"action_vice_{preview_gw}",
                                         use_container_width=True, disabled=selected_player_id == vice):
                                st.session_state.setdefault("manual_vice_by_gw", {})[preview_gw] = selected_player_id
                                if selected_player_id == cap:
                                    st.session_state.setdefault("manual_captain_by_gw", {})[preview_gw] = vice
                                    if preview_gw == selected_gw:
                                        st.session_state.manual_captain = vice
                                st.session_state.pop(selection_key, None)
                                st.rerun()
                        with c:
                            if st.button("🔄 Substitute", key=f"action_sub_{preview_gw}", use_container_width=True):
                                st.session_state[pending_key] = selected_player_id
                                st.session_state.pop(selection_key, None)
                                st.rerun()
                    else:
                        st.caption("Bench players can be substituted into the XI. Captaincy is available after they become starters.")
                        if st.button("🔄 Substitute In", key=f"action_sub_in_{preview_gw}", use_container_width=True):
                            st.session_state[pending_key] = selected_player_id
                            st.session_state.pop(selection_key, None)
                            st.rerun()
                    # Every player (starter or bench) can be replaced from the same menu.
                    if st.button("🔁 Transfer · Replace player", key=f"action_transfer_{preview_gw}",
                                 use_container_width=True):
                        st.session_state["quick_transfer_out"] = selected_player_id
                        st.session_state.pop("quick_transfer_in", None)
                        st.session_state.pop(selection_key, None)
                        st.session_state.pop(pending_key, None)
                        st.rerun()
                    if st.button("Close player actions", key=f"close_action_{preview_gw}"):
                        st.session_state.pop(selection_key, None)
                        st.rerun()
            # v5.8: A transfer begins from the player's own pitch action menu.
            # Do not show the old select-player-to-sell dropdown or an always-visible panel.
            transfer_out_id = st.session_state.get("quick_transfer_out")
            owned_ids = {int(p["id"]) for p in squad}
            if transfer_out_id is not None and transfer_out_id not in owned_ids:
                st.session_state.pop("quick_transfer_out", None)
                st.session_state.pop("quick_transfer_in", None)
                transfer_out_id = None

            if transfer_out_id is not None:
                outgoing = next(p for p in squad if int(p["id"]) == transfer_out_id)
                selling_price = int(outgoing.get("selling_price", outgoing.get("now_cost", 0)))
                budget = bank + selling_price
                club_counts = Counter(int(p["team"]) for p in squad if int(p["id"]) != transfer_out_id)
                candidates = [p for p in players
                              if int(p["id"]) not in owned_ids
                              and int(p["element_type"]) == int(outgoing["element_type"])
                              and int(p["now_cost"]) <= budget
                              and club_counts[int(p["team"])] < 3]
                # A small default shortlist, backed by the same horizon projection as the advisor.
                candidates.sort(key=lambda p: (
                    horizon_xp(p, gws, fixture_map, minutes_overrides),
                    player_fixture_xp(p, preview_gw, fixture_map, minutes_overrides),
                ), reverse=True)
                eligible_by_id = {int(p["id"]): p for p in candidates}
                chosen_in_id = st.session_state.get("quick_transfer_in")
                if chosen_in_id not in eligible_by_id:
                    chosen_in_id = None
                    st.session_state.pop("quick_transfer_in", None)

                with st.container(key="ajk_quick_transfer_market"):
                    heading, cancel_col = st.columns([4, 1], vertical_alignment="center")
                    with heading:
                        st.markdown("### 🔁 Transfer Market")
                        st.caption(f"Replacing **{outgoing.get('web_name', '?')}** · "
                                   f"{POSITION_NAMES[int(outgoing['element_type'])]} · "
                                   f"Budget {money(budget)} (sell {money(selling_price)} + bank {money(bank)})")
                    with cancel_col:
                        if st.button("✕ Close", key="quick_transfer_close", use_container_width=True):
                            st.session_state.pop("quick_transfer_out", None)
                            st.session_state.pop("quick_transfer_in", None)
                            st.rerun()
                    st.caption(f"Top five eligible replacements, ranked by predicted points over {len(gws)} GWs. "
                               "Prices use your selling value and current FPL prices.")
                    if not candidates:
                        st.warning("There are no affordable and legal replacements for this player.")
                    else:
                        for rank, player in enumerate(candidates[:5], start=1):
                            pid = int(player["id"])
                            photo_col, info_col, pred_col, choose_col = st.columns(
                                [0.8, 2.4, 1.1, 1.2], vertical_alignment="center", gap="small"
                            )
                            with photo_col:
                                src = player_photo_url(player)
                                if src:
                                    st.markdown(f'<img src="{html.escape(src, quote=True)}" '
                                                f'alt="" style="height:58px;max-width:100%;object-fit:contain">',
                                                unsafe_allow_html=True)
                                else:
                                    st.markdown("👤")
                            with info_col:
                                st.markdown(f"**{rank}. {html.escape(str(player.get('web_name', '?')))}**")
                                st.caption(f"{clubs.get(int(player['team']), '?')} · {money(player['now_cost'])} · "
                                           f"{player_status_label(player)}")
                            with pred_col:
                                st.markdown(f"**{horizon_xp(player, gws, fixture_map, minutes_overrides):.1f} xP**")
                                st.caption(f"GW {preview_gw}: {player_fixture_xp(player, preview_gw, fixture_map, minutes_overrides):.1f}")
                            with choose_col:
                                if st.button("✓ Selected" if pid == chosen_in_id else "Select",
                                             key=f"quick_transfer_pick_{pid}",
                                             type="primary" if pid == chosen_in_id else "secondary",
                                             use_container_width=True):
                                    st.session_state["quick_transfer_in"] = pid
                                    st.rerun()

                        with st.expander(f"🔎 Search all {len(candidates)} eligible replacements", expanded=False):
                            query = st.text_input("Search name or club", key="quick_transfer_search", placeholder="Type a player or club...")
                            query = query.strip().casefold()
                            matching = [p for p in candidates if
                                        query in str(p.get('web_name', '')).casefold()
                                        or query in str(clubs.get(int(p['team']), '')).casefold()]
                            if not matching:
                                st.caption("No eligible players match your search.")
                            else:
                                found_ids = [int(p["id"]) for p in matching]
                                searched_id = st.selectbox(
                                    "Eligible players", found_ids,
                                    format_func=lambda pid: (
                                        f"{label(eligible_by_id[pid], clubs)} · "
                                        f"{horizon_xp(eligible_by_id[pid], gws, fixture_map, minutes_overrides):.1f} xP"
                                    ), key="quick_transfer_search_pick"
                                )
                                if st.button("Preview this replacement", key="quick_transfer_search_preview",
                                             use_container_width=True):
                                    st.session_state["quick_transfer_in"] = searched_id
                                    st.rerun()

                        if chosen_in_id is not None:
                            incoming = eligible_by_id[chosen_in_id]
                            revised = [p for p in squad if int(p["id"]) != transfer_out_id] + [
                                {**incoming, "selling_price": int(incoming["now_cost"])}
                            ]
                            remaining_bank = budget - int(incoming["now_cost"])
                            if valid_squad(revised) and remaining_bank >= 0:
                                revised_rating = team_rating(revised, gws, fixture_map, minutes_overrides)
                                team_gain = revised_rating["total_xp"] - assessment["total_xp"]
                                player_gain = (player_fixture_xp(incoming, preview_gw, fixture_map, minutes_overrides)
                                               - player_fixture_xp(outgoing, preview_gw, fixture_map, minutes_overrides))
                                st.markdown("**Your transfer preview**")
                                st.markdown(transfer_faces_html([{"out": transfer_out_id, "in": chosen_in_id}], player_by_id),
                                            unsafe_allow_html=True)
                                m1, m2, m3 = st.columns(3)
                                m1.metric(f"GW {preview_gw} player xP", f"{player_gain:+.1f}")
                                m2.metric(f"{len(gws)}-GW team xP", f"{team_gain:+.1f}")
                                m3.metric("Bank after", money(remaining_bank))
                                st.caption("Team xP uses optimised XIs and captaincy. Changes are simulations only; "
                                           "these numbers exclude any transfer-hit costs.")
                                if st.button("✅ Apply transfer to my draft", key="quick_transfer_apply",
                                             type="primary", use_container_width=True):
                                    st.session_state.draft = revised
                                    st.session_state.bank = remaining_bank
                                    st.session_state.setdefault("draft_moves", []).append(
                                        {"out": transfer_out_id, "in": chosen_in_id}
                                    )
                                    st.session_state.manual_xi = []
                                    st.session_state.manual_captain = None
                                    st.session_state.manual_xi_by_gw = {}
                                    st.session_state.manual_captain_by_gw = {}
                                    st.session_state.manual_vice_by_gw = {}
                                    st.session_state.advisor_result = None
                                    st.session_state.advisor_key = None
                                    clear_pitch_actions()
                                    st.rerun()
                            else:
                                st.warning("This replacement would make the squad invalid. Choose someone else.")

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


with tab_transfers:
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
                    st.session_state.manual_vice_by_gw = {}
                    st.session_state.advisor_result = None
                    clear_pitch_actions()
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



with tab_chips:
    st.subheader("✨ Wildcard / Free Hit")
    st.caption("Optional advanced squad builder. Simulations do not activate chips on FPL.")
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
              squad=result["squad"], display="Combined")
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
            st.session_state.manual_vice_by_gw = {}
            st.session_state.draft_moves = []
            st.session_state.chip_result = None
            st.rerun()


st.divider()
st.caption("Independent, free FPL analysis using the public official FPL API. No affiliation with Fantasy Football Hub or the Premier League. This app cannot submit transfers or activate chips. Optimised results are estimates, not guaranteed points.")
