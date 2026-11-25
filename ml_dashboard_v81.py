"""Read-only V8.1 panel; no ML dependency or network on Streamlit."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parent/'data'
D=ROOT/'learning_v81'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def render_ml_dashboard():
    st.divider(); st.subheader('🧠 Hybrid Machine Learning — V8.1')
    st.caption('Shadow evaluation only • existing recommendations remain unchanged')
    if not (D/'model.json').exists():
        st.info('Run AI Learning V8.1 in GitHub Actions to train the first model.'); return
    m=read(D/'model.json')
    a,b,c=st.columns(3); a.metric('Historical seasons',len(m['sources'])); b.metric('Training examples',m['rows']); c.metric('xP historical gate','PASS' if m['points_gate'] else 'Fallback')
    st.caption('Minutes gate: '+('PASS' if m['minutes_gate'] else 'Fallback')+' • Model: '+m['version'])
    st.markdown('**Historical walk-forward validation**')
    rows=[]
    for f in m['folds']:
        for t in ('points','minutes'):
            for model in ('ml','baseline'):
                rows.append({'Test season':f['test'],'Target':t,'Model':model,**f[t][model]})
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    st.caption('Historical test uses a conservative kickoff-based cutoff proxy, not archived FPL deadlines. Baseline = prior 5 eligible observations; not the V8.0 engine.')
    paths=sorted((D/'forecasts').glob('*/gw*.json'))
    if not paths: st.info('No prospective forecasts yet. Wait for the pre-deadline capture window.'); return
    season=st.selectbox('ML season',sorted({p.parent.name for p in paths},reverse=True),key='v81_season')
    docs=[read(p) for p in paths if p.parent.name==season]
    st.dataframe(pd.DataFrame([{'GW':d['gw'],'Captured UTC':d['captured_utc'],'Players':len(d['rows']),'Model':d['model_version']} for d in docs]),hide_index=True,use_container_width=True)
    gw=st.selectbox('ML forecast GW',[d['gw'] for d in docs],index=len(docs)-1,key='v81_gw')
    d=next(x for x in docs if x['gw']==gw); df=pd.DataFrame(d['rows'])
    st.dataframe(df.sort_values('hybrid_xp',ascending=False),hide_index=True,use_container_width=True)
    st.download_button('Download ML forecasts',df.to_csv(index=False).encode(),'ajk_v81_forecast.csv','text/csv',key='v81_csv')
    paired=[]
    for d in docs:
        p=ROOT/'learning_v8'/season/'actuals'/f"gw{d['gw']:02d}.json"
        if not p.exists(): continue
        a=read(p); outcomes={r['id']:r['stats'] for r in a['elements']}
        from datetime import datetime
        dt=lambda x:datetime.fromisoformat(x.replace('Z','+00:00'))
        if dt(d['captured_utc'])>=min(dt(d['deadline_utc']),dt(a['deadline_utc'])): continue
        for r in d['rows']:
            if r['player_id'] in outcomes:
                x=outcomes[r['player_id']]; paired.append({**r,'actual_points':x['total_points'],'actual_minutes':x['minutes']})
    if not paired: st.info('Live accuracy will appear after a captured GW is finalized.'); return
    q=pd.DataFrame(paired); st.markdown('**Prospective xP comparison — same player-GW sample**')
    q=q[q.ml_xp.notna()]; result=[]
    for col in ('v8_xp','ml_xp','hybrid_xp'):
        if q.empty: break
        e=q[col]-q.actual_points; result.append({'Model':col,'n':len(e),'MAE':e.abs().mean(),'RMSE':(e.pow(2).mean())**.5,'Bias':e.mean()})
    if result: st.dataframe(pd.DataFrame(result),hide_index=True,use_container_width=True)
    else: st.info('No ML-eligible matched forecasts yet.')
    q=q[q.ml_minutes.notna() & (q.fixtures_count==1)]; result=[]
    for col in ('v8_minutes','ml_minutes','hybrid_minutes'):
        if q.empty: break
        e=q[col]-q.actual_minutes; result.append({'Model':col,'n':len(e),'MAE':e.abs().mean(),'RMSE':(e.pow(2).mean())**.5,'Bias':e.mean()})
    if result: st.markdown('**Prospective minutes comparison**'); st.dataframe(pd.DataFrame(result),hide_index=True,use_container_width=True)
