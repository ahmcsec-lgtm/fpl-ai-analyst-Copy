import math
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
import streamlit as st
from fpl_engine import num, estimate_xp, fixture_lookup, player_fixture_xp, build_squad, best_starting_xi

API = "https://fantasy.premierleague.com/api"

HEADERS = {"User-Agent": "FPL-AI-Analyst/1.0 (personal analytics app)"}
POS_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

st.set_page_config(page_title="FPL AI Analyst", page_icon="⚽", layout="wide")
st.markdown("<style>.block-container{padding-top:1.3rem;max-width:1600px}[data-testid='stMetric']{background:rgba(120,130,145,.09);padding:12px 14px;border-radius:12px}.small-note{color:#8b93a1;font-size:.84rem}</style>", unsafe_allow_html=True)

@st.cache_data(ttl=600, show_spinner=False)
def get_json(path):
    r = requests.get(f"{API}/{path.lstrip('/')}", headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.json()

def status_label(p):
    labels = {"a":"Available","d":"Doubtful","i":"Injured","s":"Suspended","u":"Unavailable","n":"Not available"}
    label = labels.get(p.get("status"), str(p.get("status", "Unknown")))
    if p.get("chance_of_playing_next_round") is not None:
        label += f" · {p['chance_of_playing_next_round']}% chance"
    return label

def money(tenths): return f"£{num(tenths)/10:.1f}m"
def fx_text(fxs): return ", ".join(x[0] for x in fxs) if fxs else "—"

def report_files():
    folder = Path("reports")
    return sorted(folder.glob("GW*_report.md"), reverse=True) if folder.exists() else []


with st.sidebar:
    st.header("⚽ FPL Manager")
    st.caption("Enter your own Fantasy Premier League Team ID.")

    team_id_input = st.text_input(
        "Your FPL Team ID",
        value="",
        placeholder="e.g. 1645144",
        help="Enter any valid public FPL Team ID."
    )

    if st.button("↻ Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption("Free public FPL data. No FPL password required.")

if not team_id_input.strip():
    st.info("👈 Enter your FPL Team ID in the sidebar to start analysing your team.")
    st.stop()

if not team_id_input.strip().isdigit():
    st.error("Please enter a valid numeric FPL Team ID.")
    st.stop()

team_id = int(team_id_input.strip())


try:
    with st.spinner("Loading current FPL data…"):
        boot = get_json("bootstrap-static/")
        fixtures = get_json("fixtures/")
        profile = get_json(f"entry/{int(team_id)}/")
except Exception as e:
    st.error(f"Unable to load FPL data: {e}"); st.stop()

players, teams, events = boot.get("elements", []), boot.get("teams", []), boot.get("events", [])
player_by_id = {p["id"]: p for p in players}
team_names = {t["id"]: t["name"] for t in teams}
team_short = {t["id"]: t.get("short_name", t["name"]) for t in teams}
fx_map = fixture_lookup(fixtures, teams)
current = next((e for e in events if e.get("is_current")), None)
upcoming = next((e for e in events if e.get("is_next")), None)
if upcoming: target_gw = upcoming
elif current and not current.get("finished"): target_gw = current
else: target_gw = next((e for e in events if not e.get("finished") and e.get("deadline_time")), None)
if not target_gw:
    st.warning("No upcoming Gameweek is currently published by the FPL API."); st.stop()
gw = int(target_gw["id"])
try:
    picks_data = get_json(f"entry/{int(team_id)}/event/{gw}/picks/")
    snapshot_gw = gw
except Exception:
    completed = [e for e in events if e.get("finished")]
    snapshot_gw = int(completed[-1]["id"]) if completed else gw
    try: picks_data = get_json(f"entry/{int(team_id)}/event/{snapshot_gw}/picks/")
    except Exception: picks_data = None
try:
    history = get_json(f"entry/{int(team_id)}/history/").get("current", [])
except Exception: history = []
latest = history[-1] if history else {}
manager = f"{profile.get('player_first_name','')} {profile.get('player_last_name','')}".strip()
deadline = target_gw.get("deadline_time")
deadline_text = datetime.fromisoformat(deadline.replace("Z", "+00:00")).astimezone().strftime("%d %b %Y, %H:%M local") if deadline else "TBC"

st.title("⚽ FPL AI Analyst")
st.caption(f"{profile.get('name','FPL Manager')} · {manager} · Team ID {int(team_id)} · GW{gw} · Deadline: {deadline_text}")
c1,c2,c3,c4 = st.columns(4)
c1.metric("Overall points", f"{profile.get('summary_overall_points',0):,}")
c2.metric("Overall rank", f"{profile.get('summary_overall_rank',0):,}")
c3.metric("Target Gameweek", str(gw))
c4.metric("Team value", money(latest.get("value", profile.get("last_deadline_value",0))))

# Build a full player projection table for the target GW.
proj_rows=[]
for p in players:
    fxs=fx_map.get((p["team"],gw),[])
    xp=player_fixture_xp(p,fxs)
    proj_rows.append({"id":p["id"],"Player":p.get("web_name",""),"Position":POS_NAMES.get(p.get("element_type"),"?"),"Club":team_short.get(p["team"],""),"Price":num(p.get("now_cost"))/10,"Price label":money(p.get("now_cost")),"Fixture":fx_text(fxs),"xP":xp,"Form":num(p.get("form")),"xGI":num(p.get("expected_goal_involvements")),"Minutes":num(p.get("minutes")),"Ownership %":num(p.get("selected_by_percent")),"Status":status_label(p),"status_code":p.get("status","a"),"team":p["team"],"element_type":p["element_type"]})
proj=pd.DataFrame(proj_rows)

squad=[]; picks=[]
if picks_data:
    picks=picks_data.get("picks",[])
    squad=[player_by_id[x["element"]] for x in picks if x.get("element") in player_by_id]
owned_ids={p["id"] for p in squad}

# Tabs
tabs=st.tabs(["Overview","Captain & xP","Transfers","Wildcard / Free Hit","Differentials","Fixtures & Rotation","Weekly Reports","Public Team Analyzer"])
with tabs[0]:
    left,right=st.columns([1.3,1])
    with left:
        st.subheader("Your squad")
        if picks:
            pick_rows=[]
            for pick in picks:
                p=player_by_id.get(pick.get("element"));
                if not p: continue
                fxs=fx_map.get((p["team"],gw),[])
                pick_rows.append({"Slot":"XI" if pick.get("position",99)<=11 else "Bench","Player":p["web_name"],"Pos":POS_NAMES.get(p["element_type"],"?"),"Club":team_short.get(p["team"],""),"Fixture":fx_text(fxs),"xP":player_fixture_xp(p,fxs),"Status":status_label(p),"Captain":"C" if pick.get("is_captain") else ("VC" if pick.get("is_vice_captain") else "")})
            st.dataframe(pd.DataFrame(pick_rows),use_container_width=True,hide_index=True)
            st.caption(f"Squad snapshot GW{snapshot_gw}. If the target GW picks are not yet published, the latest available public picks are shown.")
        else: st.info("Public picks are not available for this manager/Gameweek. Other player analysis remains available.")
    with right:
        st.subheader("Squad health")
        if squad:
            flagged=[p for p in squad if p.get("status")!="a" or p.get("chance_of_playing_next_round") not in (None,100)]
            st.metric("Availability concerns",len(flagged))
            for p in flagged: st.warning(f"**{p['web_name']}** — {status_label(p)}\n\n{p.get('news') or 'No additional FPL news supplied.'}")
        st.subheader("Next deadlines")
        for e in [x for x in events if not x.get("finished") and x.get("deadline_time")][:5]:
            dt=datetime.fromisoformat(e['deadline_time'].replace('Z','+00:00')).astimezone().strftime('%d %b %H:%M')
            st.write(f"**GW{e['id']}** · {dt} local")

with tabs[1]:
    st.subheader("Captain and vice-captain recommendations")
    st.caption("Ranked by the free xP heuristic. Captaincy doubles the selected player's points in FPL; the xP column itself is per player, not doubled.")
    pool=proj[(proj["Position"]!="GKP") & (proj["status_code"].isin(["a","d"]))].sort_values("xP",ascending=False).head(12).copy()
    if not pool.empty:
        pool.insert(0,"Recommendation",["Captain candidate" if i==0 else "Vice-captain candidate" if i==1 else "Alternative" for i in range(len(pool))])
        st.dataframe(pool[["Recommendation","Player","Position","Club","Fixture","xP","Ownership %","Status"]],use_container_width=True,hide_index=True)
        st.metric("Top captain projected points",f"{pool.iloc[0]['xP']:.2f}")
    st.subheader("Expected points — player explorer")
    pos=st.selectbox("Position filter",["All","GKP","DEF","MID","FWD"],key="xp_pos")
    view=proj if pos=="All" else proj[proj.Position==pos]
    st.dataframe(view.sort_values("xP",ascending=False).head(35)[["Player","Position","Club","Price label","Fixture","xP","Form","xGI","Status"]],use_container_width=True,hide_index=True)
    st.caption("xP is a transparent statistical estimate using xG/xA or xGI, minutes, appearance, clean-sheet history, form and fixture difficulty. It is not official FPL data or a guarantee.")

with tabs[2]:
    st.subheader("Transfer planner")
    if not squad: st.info("Transfer planner needs a public squad snapshot for this team.")
    else:
        bank_tenths=num(latest.get("bank",profile.get("last_deadline_bank",0)))
        st.write(f"Latest public bank estimate: **{money(bank_tenths)}**. Selling prices below use the public picks data where available; if unavailable, current price is shown as a rough fallback.")
        transfer_rows=[]
        for pick in picks:
            old=player_by_id.get(pick.get("element"))
            if not old: continue
            sell= num(pick.get("selling_price"),old.get("now_cost",0))
            posid=old.get("element_type")
            candidates=proj[(proj.element_type==posid)&(~proj.id.isin(owned_ids))&(proj.status_code.isin(["a","d"]))].copy()
            candidates["cost_tenths"]=candidates.id.map({p["id"]:num(p.get("now_cost")) for p in players})
            candidates=candidates[candidates.cost_tenths <= sell+bank_tenths]
            if candidates.empty: continue
            best=candidates.sort_values("xP",ascending=False).iloc[0]
            old_xp=player_fixture_xp(old,fx_map.get((old["team"],gw),[]))
            delta=best.xP-old_xp
            transfer_rows.append({"Sell candidate":old["web_name"],"Buy candidate":best.Player,"Position":POS_NAMES.get(posid),"Sell price":money(sell),"Buy price":best["Price label"],"Next GW xP gain":round(delta,2),"New fixture":best.Fixture,"New status":best.Status})
        if transfer_rows:
            tdf=pd.DataFrame(transfer_rows).sort_values("Next GW xP gain",ascending=False)
            st.dataframe(tdf.head(20),use_container_width=True,hide_index=True)
        else: st.info("No affordable same-position transfer candidates were found from the available public data.")
        st.warning("These are one-transfer comparisons, not automatic transfer instructions. The app cannot reliably infer every private selling-price rule or your exact free-transfer state. Check bank, free transfers, squad limits and hit cost in the official FPL site before confirming.")

with tabs[3]:
    st.subheader("Wildcard / Free Hit squad optimiser")
    st.caption("Builds an indicative 15-player squad with FPL position quotas and a maximum of three players per club. It uses current market prices and the budget you enter; it does not guarantee a mathematically global optimum.")
    budget=st.number_input("Squad budget (£m)",min_value=80.0,max_value=120.0,value=100.0,step=0.5)
    chip_mode=st.radio("Planning mode",["Wildcard (longer-term squad)","Free Hit (one Gameweek)"],horizontal=True)
    if st.button("Optimise 15-player squad",type="primary"):
        optim=build_squad(players,fx_map,gw,budget)
        if len(optim)<15: st.error(f"Only {len(optim)} eligible players found within constraints. Try increasing the budget.")
        else:
            xi=best_starting_xi(optim,fx_map,gw)
            rows=[]
            for p in optim:
                fxs=fx_map.get((p["team"],gw),[])
                rows.append({"Line-up":"Starting XI" if p in xi else "Bench","Player":p["web_name"],"Position":POS_NAMES.get(p["element_type"]),"Club":team_short.get(p["team"]),"Price":money(p.get("now_cost")),"Fixture":fx_text(fxs),"xP":player_fixture_xp(p,fxs)})
            st.dataframe(pd.DataFrame(rows).sort_values(["Line-up","Position","xP"],ascending=[True,True,False]),use_container_width=True,hide_index=True)
            total=sum(num(p.get("now_cost")) for p in optim)/10
            st.metric("Estimated squad cost",f"£{total:.1f}m")
            st.success(f"{chip_mode} draft generated. Review player availability and club limits before using it.")

with tabs[4]:
    st.subheader("Differential and hidden-gem finder")
    max_own=st.slider("Maximum ownership %",1,30,10)
    max_price=st.slider("Maximum price (£m)",4.0,15.0,9.0,0.5)
    min_minutes=st.slider("Minimum minutes played",0,1500,300,50)
    gems=proj[(proj["Ownership %"]<=max_own)&(proj["Price"]<=max_price)&(proj["Minutes"]>=min_minutes)&(~proj["id"].isin(owned_ids))&proj["status_code"].isin(["a","d"])].copy()
    gems["Value (xP/£m)"]=gems["xP"]/gems["Price"].clip(lower=0.1)
    st.dataframe(gems.sort_values(["xP","Value (xP/£m)"],ascending=False).head(30)[["Player","Position","Club","Price label","Ownership %","Fixture","xP","Value (xP/£m)","Status"]],use_container_width=True,hide_index=True)
    st.caption("Differentials are defined here by your selected ownership, price and minutes thresholds. They are not guaranteed breakout picks.")

with tabs[5]:
    st.subheader("Fixture difficulty and rotation planner")
    horizon=st.slider("Upcoming Gameweeks",2,8,5)
    upcoming_gws=[e["id"] for e in events if not e.get("finished") and e.get("deadline_time")][:horizon]
    fixture_rows=[]
    for t in teams:
        row={"Club":t.get("name")}
        diffs=[]
        for event_id in upcoming_gws:
            fxs=fx_map.get((t["id"],event_id),[])
            row[f"GW{event_id}"]=fx_text(fxs) or "Blank"
            diffs.extend([d for _,d in fxs])
        row["Avg FDR"]=round(sum(diffs)/len(diffs),2) if diffs else None
        fixture_rows.append(row)
    fixture_df=pd.DataFrame(fixture_rows).sort_values("Avg FDR",ascending=True,na_position="last")
    st.dataframe(fixture_df,use_container_width=True,hide_index=True)
    st.subheader("Rotation notes from your squad")
    if squad:
        rot=[]
        for p in squad:
            fxs=[fx_map.get((p["team"],g),[]) for g in upcoming_gws]
            difficulties=[d for group in fxs for _,d in group]
            rot.append({"Player":p["web_name"],"Club":team_short.get(p["team"]),"Position":POS_NAMES.get(p["element_type"]),"Minutes":p.get("minutes"),"Status":status_label(p),"Avg FDR":round(sum(difficulties)/len(difficulties),2) if difficulties else None,"Upcoming": " | ".join(f"GW{g}: {fx_text(fx_map.get((p['team'],g),[]))}" for g in upcoming_gws)})
        st.dataframe(pd.DataFrame(rot).sort_values(["Avg FDR","Minutes"],ascending=[True,False]),use_container_width=True,hide_index=True)
    else: st.info("Load public picks to see squad rotation notes.")

with tabs[6]:
    st.subheader("Automatic weekly FPL reports")
    st.write("The GitHub Actions workflow can generate a Markdown report every Monday at 09:00 Malaysia time (01:00 UTC) and save it in this repository. Reports appear here after the repository syncs.")
    files=report_files()
    if files:
        for path in files[:12]:
            with st.expander(path.stem.replace("_"," ")):
                content=path.read_text(encoding="utf-8")
                st.markdown(content)
                st.download_button("Download report",content,file_name=path.name,mime="text/markdown",key=path.name)
    else:
        st.info("No scheduled reports have been generated yet. The workflow runs on its next schedule or can be started manually from GitHub Actions.")
    st.caption("Scheduled reports depend on GitHub Actions being enabled and the public FPL API being available. GitHub may delay scheduled runs; this is not a guaranteed real-time service.")

with tabs[7]:
    st.subheader("Public Team Analyzer")
    other_id=st.number_input("Another FPL Team ID",min_value=1,value=int(team_id),step=1,key="other_id")
    if st.button("Analyze public team",key="analyze_public"):
        try:
            other=get_json(f"entry/{int(other_id)}/")
            st.success(f"Found {other.get('name','FPL team')}")
            a,b,c=st.columns(3); a.metric("Points",f"{other.get('summary_overall_points',0):,}"); b.metric("Overall rank",f"{other.get('summary_overall_rank',0):,}"); c.metric("Team ID",str(other_id))
            other_hist=get_json(f"entry/{int(other_id)}/history/").get("current",[])
            if other_hist: st.line_chart(pd.DataFrame(other_hist).set_index("event")[["points"]])
        except Exception as e: st.error(f"Could not load this public team: {e}")

st.divider()
st.caption("Independent fan-made tool; not affiliated with the Premier League. All xP, captain, transfer and optimisation outputs are estimates from transparent statistical heuristics, not official FPL projections or guaranteed outcomes.")
