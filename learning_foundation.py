"""V8.0: persistent, pre-deadline forecast and finalized outcome archive."""
from datetime import datetime, timezone
from pathlib import Path
import json, math, os, time, subprocess
from collections import defaultdict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'learning_v8'
API = 'https://fantasy.premierleague.com/api/'

def now(): return datetime.now(timezone.utc)
def stamp(s):
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone required')
    return d

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n', encoding='utf-8')
    os.replace(tmp, path)

def session():
    s = requests.Session()
    s.headers['User-Agent'] = 'AJK-FPL-Learning/8.0 (public statistics)'
    s.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504], allowed_methods=['GET'])))
    return s

def get(s, endpoint):
    r = s.get(API+endpoint, timeout=(10,40)); r.raise_for_status(); return r.json()

def season_of(events):
    year = stamp(next(e['deadline_time'] for e in events if int(e['id'])==1)).year
    return f'{year}-{(year+1)%100:02d}'

def collect_actuals(s, events, folder):
    for e in events:
        if not (e.get('finished') and e.get('data_checked')): continue
        gw = int(e['id']); path = folder/'actuals'/f'gw{gw:02d}.json'
        if path.exists(): continue
        payload = get(s, f'event/{gw}/live/')
        rows = payload['elements']
        if not rows or len({int(r['id']) for r in rows}) != len(rows): raise ValueError('Invalid live results')
        for r in rows:
            if 'total_points' not in r['stats'] or 'minutes' not in r['stats']: raise ValueError('Incomplete result')
        write(path, {'gw':gw,'observed_utc':now().isoformat(),'deadline_utc':e['deadline_time'],'elements':rows})
        print('Collected actuals', gw); time.sleep(.35)

def archive(folder, kind):
    return [read(p) for p in sorted((folder/kind).glob('gw*.json'))]

def actual_map(doc): return {int(r['id']):r['stats'] for r in doc['elements']}

def paired(folder):
    actuals = {d['gw']:d for d in archive(folder,'actuals')}
    output=[]
    for doc in archive(folder,'forecasts'):
        gw=doc['gw']; a=actuals.get(gw)
        if not a or stamp(doc['captured_utc']) >= stamp(doc['deadline_utc']): continue
        if stamp(doc['captured_utc']) >= stamp(a['deadline_utc']): continue
        stats=actual_map(a)
        for r in doc['rows']:
            if r['player_id'] not in stats: continue
            v=stats[r['player_id']]
            output.append({**r,'gw':gw,'actual_points':v['total_points'],'actual_minutes':v['minutes'],'captured_utc':doc['captured_utc'],'actual_observed_utc':a['observed_utc']})
    return output

def prior_rows(folder, gw, cutoff):
    return [r for r in paired(folder) if r['gw']<gw and stamp(r['actual_observed_utc'])<=cutoff]

def baseline(actuals, gw, cutoff):
    recent=sorted([d for d in actuals if d['gw']<gw and stamp(d['observed_utc'])<=cutoff],key=lambda d:d['gw'])[-5:]
    values=defaultdict(list)
    for d in recent:
        for pid, stats in actual_map(d).items(): values[pid].append(float(stats['total_points']))
    return {pid:sum(v)/len(v) for pid,v in values.items()}

def capture(s, folder, window=24):
    import fpl_engine as engine
    # Refresh after historical downloads; never use a stale bootstrap near deadline.
    boot=get(s,'bootstrap-static/'); events=boot['events']; captured=now()
    if season_of(events)!=folder.name: raise ValueError('Season changed during collection')
    upcoming=sorted([e for e in events if stamp(e['deadline_time'])>captured],key=lambda e:stamp(e['deadline_time']))
    if not upcoming: return
    e=upcoming[0]; gw=int(e['id']); deadline=stamp(e['deadline_time']); path=folder/'forecasts'/f'gw{gw:02d}.json'
    if path.exists() or (deadline-captured).total_seconds()>window*3600: return
    fixtures=get(s,'fixtures/'); players=boot['elements']; teams=boot['teams']
    engine.configure_projection_context(teams, fixtures)
    engine.configure_availability_context(events, gw)
    report=ROOT/'availability_reports.json'
    if report.exists():
        records=read(report)
        if isinstance(records,dict): records=records.get('reports',[])
        engine.attach_verified_availability_reports(players,teams,records,now())
    engine.configure_calibration(prior_rows(folder,gw,captured),gw)
    lookup=engine.fixture_lookup(fixtures)
    base=baseline(archive(folder,'actuals'),gw,captured)
    rows=[]
    for p in players:
        f=engine.player_prediction(p,gw,lookup)
        if not f['fixtures_count']: continue
        rows.append({'player_id':int(p['id']),'name':p.get('web_name','?'),'position':int(p['element_type']),'team_id':int(p['team']), 'raw_xp':float(f['raw_xp']),'predicted_xp':float(f['xp']), 'baseline_xp':base.get(int(p['id'])), 'expected_minutes_per_match':f['minutes'],'fixtures_count':f['fixtures_count'],'lower':f['lower'],'upper':f['upper'],'features':{k:p.get(k) for k in ('now_cost','minutes','total_points','form','expected_goals','expected_assists','expected_goal_involvements','expected_goals_conceded','selected_by_percent','status','chance_of_playing_next_round','starts','code')}})
    end=now()
    if end>=deadline: raise RuntimeError('Deadline passed during capture; discarded')
    if not rows: raise ValueError('No forecasts generated')
    try: version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except (OSError,subprocess.CalledProcessError): version='unknown'
    write(path,{'season':folder.name,'gw':gw,'captured_utc':end.isoformat(),'input_started_utc':captured.isoformat(),'deadline_utc':deadline.isoformat(),'engine_commit':version,'model':'v8 batch / existing engine','rows':rows,'fixtures': [f for f in fixtures if f.get('event')==gw], 'teams':teams})
    print('Captured',gw,len(rows))

def metrics(rows, key):
    errors=[float(r[key])-float(r['actual_points']) for r in rows if r.get(key) is not None]
    n=len(errors)
    if not n: return {'n':0,'mae':None,'rmse':None,'bias':None}
    return {'n':n,'mae':sum(map(abs,errors))/n,'rmse':math.sqrt(sum(e*e for e in errors)/n),'bias':sum(errors)/n}

def main():
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--window-hours',type=int,default=24); p.add_argument('--actuals-only',action='store_true'); args=p.parse_args()
    if not 1<=args.window_hours<=72: p.error('window must be 1–72 hours')
    with session() as s:
        boot=get(s,'bootstrap-static/'); folder=DATA/season_of(boot['events'])
        collect_actuals(s,boot['events'],folder)
        if not args.actuals_only: capture(s,folder,args.window_hours)

if __name__=='__main__': main()
