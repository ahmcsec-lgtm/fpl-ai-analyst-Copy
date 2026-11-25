"""AJK V8.1: historical ML and immutable prospective shadow forecasts."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse, hashlib, json, os, math
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'learning_v81'
SEASONS = ['2020-21','2021-22','2022-23','2023-24','2024-25']
SOURCE = 'https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{}/gws/merged_gw.csv'
STATS = ['total_points','minutes','goals_scored','assists','clean_sheets','bonus']
FEATURES = ['position','history_count'] + [f'{s}_{w}' for w in (3,5) for s in STATS]
SCHEMA = 'v81-lag2-single-gw-1'

def utc(): return datetime.now(timezone.utc)
def stamp(s): return datetime.fromisoformat(s.replace('Z','+00:00'))
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    t=p.with_suffix('.tmp'); t.write_text(json.dumps(obj, allow_nan=False, indent=2),encoding='utf-8'); os.replace(t,p)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def features(pos, history):
    # history: ordered finalized player-GW totals, never target GW.
    out={'position':int(pos),'history_count':len(history)}
    for w in (3,5):
        for s in STATS:
            vals=[float(r[s]) for r in history[-w:] if r.get(s) is not None and math.isfinite(float(r[s]))]
            out[f'{s}_{w}']=float(np.mean(vals)) if vals else np.nan
    return out

def historical_frame(raw, season):
    required={'element','GW','position','fixture','kickoff_time',*STATS}
    if not required.issubset(raw): raise ValueError(f'{season}: missing {required-set(raw)}')
    d=raw[list(required)].copy()
    d['position']=d.position.astype(str).str.upper().map({'GK':1,'GKP':1,'DEF':2,'MID':3,'FWD':4})
    for k in ['element','GW','fixture',*STATS]: d[k]=pd.to_numeric(d[k],errors='coerce')
    d['kickoff_time']=pd.to_datetime(d.kickoff_time,utc=True,errors='coerce')
    d=d.dropna(subset=['position','element','GW','fixture','kickoff_time',*STATS])
    if d.duplicated(['element','fixture']).any(): raise ValueError(f'{season}: duplicate player fixture')
    if d.GW.nunique()!=38: raise ValueError(f'{season}: incomplete season')
    if (d.minutes<0).any() or (d.minutes>90).any(): raise ValueError(f'{season}: invalid minutes')
    times=d.groupby('GW').kickoff_time.agg(['min','max']).to_dict('index')
    agg=d.groupby(['element','GW'],as_index=False).agg({**{s:'sum' for s in STATS},'position':'first','fixture':'count'})
    rows=[]
    for _, group in agg.groupby('element'):
        history=[]
        for r in group.sort_values('GW').to_dict('records'):
            gw=int(r['GW']); cutoff=times[gw]['min']-pd.Timedelta(days=2)
            # Historical deadlines/finalization not available: conservative proxy.
            prior=[x for x in history if x['GW']<=gw-2 and times[x['GW']]['max']+pd.Timedelta(days=2)<=cutoff]
            if r['fixture']==1 and len(prior)>=3:
                rows.append({'season':season,'gw':gw,**features(r['position'],prior),'points':r['total_points'],'minutes':r['minutes']})
            history.append(r)
    if len(rows)<1000: raise ValueError(f'{season}: insufficient examples')
    return pd.DataFrame(rows)

def download(cache):
    cache.mkdir(parents=True,exist_ok=True); frames=[]; sources=[]
    for season in SEASONS:
        p=cache/f'{season}.csv'
        try:
            if not p.exists():
                r=requests.get(SOURCE.format(season),timeout=(15,120)); r.raise_for_status(); p.write_bytes(r.content)
            frame=historical_frame(pd.read_csv(p,low_memory=False),season)
            frames.append(frame); sources.append({'season':season,'rows':len(frame),'sha256':sha(p),'url':SOURCE.format(season)})
            print('Imported',season,len(frame),flush=True)
        except (requests.RequestException,ValueError, OSError) as exc:
            print('Skipped',season,str(exc),flush=True)
    if len(frames)<3: raise RuntimeError('Need at least three valid historical seasons; previous model untouched')
    return pd.concat(frames,ignore_index=True),sources

def fit(d,target):
    from lightgbm import LGBMRegressor
    model=LGBMRegressor(objective='regression',n_estimators=160,learning_rate=.035,num_leaves=15,min_child_samples=80,reg_lambda=2,random_state=81,n_jobs=2,verbosity=-1)
    return model.fit(d[FEATURES],d[target])
def score(y,p):
    e=np.asarray(p)-np.asarray(y)
    return {'n':len(e),'mae':float(np.abs(e).mean()),'rmse':float(np.sqrt((e**2).mean())),'bias':float(e.mean())}
def walk_forward(d):
    seasons=sorted(d.season.unique()); folds=[]
    for i in range(2,len(seasons)):
        train=d[d.season.isin(seasons[:i])]; test=d[d.season==seasons[i]]
        fold={'train':seasons[:i],'test':seasons[i]}
        for target,base in [('points','total_points_5'),('minutes','minutes_5')]:
            p=fit(train,target).predict(test[FEATURES]); b=test[base].to_numpy()
            if target=='minutes': p=np.clip(p,0,90); b=np.clip(b,0,90)
            fold[target]={'ml':score(test[target],p),'baseline':score(test[target],b)}
        folds.append(fold)
    return folds

def train(cache, root=DATA):
    d,sources=download(cache); folds=walk_forward(d)
    gate=all(f['points']['ml']['rmse']<f['points']['baseline']['rmse'] for f in folds)
    min_gate=all(f['minutes']['ml']['rmse']<f['minutes']['baseline']['rmse'] for f in folds)
    # Versioned native LightGBM files, manifest written last; no pickle.
    version=utc().strftime('%Y%m%dT%H%M%S%fZ'); folder=root/'models'/version; folder.mkdir(parents=True)
    for target in ('points','minutes'): fit(d,target).booster_.save_model(str(folder/f'{target}.txt'))
    meta={'schema':SCHEMA,'version':version,'trained_utc':utc().isoformat(),'features':FEATURES,'sources':sources,'rows':len(d),'folds':folds,'points_gate':gate,'minutes_gate':min_gate,'files':{t:sha(folder/f'{t}.txt') for t in ('points','minutes')}}
    save(root/'model.json',meta); print('Trained',version,'historical gate',gate, min_gate)
    return meta

def model_bundle(root):
    from lightgbm import Booster
    meta=load(root/'model.json')
    if meta['schema']!=SCHEMA or meta['features']!=FEATURES: raise ValueError('Incompatible model schema')
    version=meta['version']
    if not version.isalnum(): raise ValueError('Invalid model version')
    models={}
    for t in ('points','minutes'):
        p=root/'models'/version/f'{t}.txt'
        if sha(p)!=meta['files'][t]: raise ValueError('Model checksum mismatch')
        models[t]=Booster(model_file=str(p))
    return meta,models

def live_history(actuals,pid,gw,cutoff):
    history=[]
    for a in sorted(actuals,key=lambda a:a['gw']):
        if a['gw']>gw-2 or stamp(a['observed_utc'])>cutoff: continue
        for r in a['elements']:
            if int(r['id'])==pid:
                history.append(r['stats']); break
    return history

def blend(base, ml, weight): return (1-weight)*float(base)+weight*float(ml)

def capture(root=DATA):
    from learning_foundation import DATA as V8, archive
    try: meta,models=model_bundle(root)
    except (ImportError,OSError,ValueError,KeyError,RuntimeError) as exc:
        print('Fallback: model unavailable:',exc); return
    for season in sorted(V8.glob('*')):
        if not season.is_dir(): continue
        actuals=archive(season,'actuals')
        for doc in archive(season,'forecasts'):
            gw=int(doc['gw']); deadline=stamp(doc['deadline_utc']); cutoff=stamp(doc['captured_utc'])
            dest=root/'forecasts'/season.name/f'gw{gw:02d}.json'
            if dest.exists() or not cutoff<=utc()<deadline: continue
            # Model may be trained after V8 capture, but never after deadline.
            if stamp(meta['trained_utc'])>=deadline: continue
            rows=[]
            for r in doc['rows']:
                base=float(r['predicted_xp']); mins=float(r['expected_minutes_per_match']); pid=int(r['player_id'])
                h=live_history(actuals,pid,gw,cutoff); ml=mm=None; weight=mweight=0.; reason='fallback: insufficient history, status or multiple fixtures'
                if len(h)>=3 and r['fixtures_count']==1 and r.get('features',{}).get('status')=='a':
                    x=pd.DataFrame([features(r['position'],h)])[FEATURES]
                    ml=float(models['points'].predict(x,num_threads=1)[0]); mm=float(np.clip(models['minutes'].predict(x,num_threads=1)[0],0,90))
                    if not math.isfinite(ml) or not math.isfinite(mm): ml=mm=None
                    else:
                        weight=.25 if meta['points_gate'] else 0.; mweight=.25 if meta['minutes_gate'] else 0.
                        reason='shadow blend' if weight else 'fallback: historical gate not passed'
                rows.append({'player_id':pid,'name':r['name'],'position':r['position'],'fixtures_count':r['fixtures_count'],'v8_xp':base,'ml_xp':ml,'hybrid_xp':blend(base,ml,weight) if ml is not None else base,'v8_minutes':mins,'ml_minutes':mm,'hybrid_minutes':blend(mins,mm,mweight) if mm is not None else mins,'weight':weight,'minutes_weight':mweight,'reason':reason})
            end=utc()
            if end>=deadline: print('Deadline passed; discarded',gw); continue
            save(dest,{'season':season.name,'gw':gw,'deadline_utc':doc['deadline_utc'],'v8_captured_utc':doc['captured_utc'],'captured_utc':end.isoformat(),'model_version':meta['version'],'rows':rows}); print('V8.1 shadow captured',season.name,gw,len(rows))

def main():
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['train','capture','auto']); p.add_argument('--cache',type=Path,default=ROOT/'.v81-cache'); a=p.parse_args()
    if a.mode=='train': train(a.cache)
    elif a.mode=='capture': capture()
    else:
        manifest=DATA/'model.json'
        if not manifest.exists() or utc()-stamp(load(manifest)['trained_utc'])>=timedelta(days=30): train(a.cache)
        capture()
if __name__=='__main__': main()
