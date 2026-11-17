"""Generate a weekly Markdown report from public FPL endpoints."""
from datetime import datetime, timezone
from pathlib import Path
import requests
from fpl_engine import num, fixture_lookup, player_fixture_xp

API="https://fantasy.premierleague.com/api/"
TEAM_ID=int(__import__('os').environ.get('FPL_TEAM_ID','1645144'))
HEADERS={"User-Agent":"FPL-AI-Analyst-weekly-report/1.0"}

def get(path):
    r=requests.get(API+path,headers=HEADERS,timeout=30); r.raise_for_status(); return r.json()

boot=get('bootstrap-static/'); fixtures=get('fixtures/'); profile=get(f'entry/{TEAM_ID}/'); events=boot.get('events',[])
next_event=next((e for e in events if e.get('is_next')),None)
current=next((e for e in events if e.get('is_current')),None)
target=next_event or current or next((e for e in events if not e.get('finished')),None)
if not target: raise SystemExit('No current/upcoming Gameweek in FPL API')
gw=target['id']; picks=None
for candidate in [gw]+[e['id'] for e in events if e.get('finished')][-1::-1]:
    try: picks=get(f'entry/{TEAM_ID}/event/{candidate}/picks/'); snapshot=candidate; break
    except Exception: continue
if picks is None: raise SystemExit('No public picks available for this team')
players={p['id']:p for p in boot.get('elements',[])}; teams=boot.get('teams',[]); short={t['id']:t.get('short_name',t['name']) for t in teams}; fx=fixture_lookup(fixtures,teams)
rows=[]
for pick in picks.get('picks',[]):
    p=players.get(pick['element'])
    if not p: continue
    fxs=fx.get((p['team'],gw),[])
    rows.append((p,pick,player_fixture_xp(p,fxs),fxs))
ranked=sorted(rows,key=lambda x:x[2],reverse=True)
manager=profile.get('name','FPL Manager')
lines=[f'# Weekly FPL Report — {manager}', '',f'- Team ID: {TEAM_ID}',f'- Target Gameweek: {gw}',f'- Squad snapshot: GW{snapshot}',f'- Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}', '', '## Squad xP ranking', '', '| Player | Position | Club | Fixture | xP | Status |','|---|---|---|---|---:|---|']
pos={1:'GKP',2:'DEF',3:'MID',4:'FWD'}
for p,pick,xp,fxs in ranked:
    status=p.get('status','a'); chance=p.get('chance_of_playing_next_round')
    status_text={'a':'Available','d':'Doubtful','i':'Injured','s':'Suspended','u':'Unavailable'}.get(status,status)
    if chance is not None: status_text+=f' ({chance}%)'
    lines.append(f"| {p.get('web_name')} | {pos.get(p.get('element_type'))} | {short.get(p['team'])} | {', '.join(x[0] for x in fxs) or '—'} | {xp:.2f} | {status_text} |")
lines += ['', '## Captaincy shortlist','']
for i,(p,pick,xp,fxs) in enumerate([x for x in ranked if x[0].get('element_type')!=1][:5],1):
    lines.append(f"{i}. **{p.get('web_name')}** ({short.get(p['team'])}) — estimated {xp:.2f} xP; {', '.join(x[0] for x in fxs) or 'no fixture listed'}")
lines += ['', '## Availability watch','']
flagged=[p for p,_,_,_ in rows if p.get('status')!='a' or p.get('chance_of_playing_next_round') not in (None,100)]
if flagged:
    for p in flagged: lines.append(f"- **{p.get('web_name')}** — {p.get('news') or p.get('status')}")
else: lines.append('No availability concerns flagged in the FPL public data for this squad snapshot.')
lines += ['', '> xP and captaincy rankings are transparent heuristic estimates, not official FPL projections or guarantees. Check late team news before the deadline.']
Path('reports').mkdir(exist_ok=True)
Path(f'reports/GW{gw:02d}_report.md').write_text('\n'.join(lines),encoding='utf-8')
print(f'Wrote reports/GW{gw:02d}_report.md')
