"""Read-only Streamlit dashboard; does not alter the live engine."""
import pandas as pd
import streamlit as st
from learning_foundation import DATA, archive, paired, metrics

def render_learning_dashboard():
    st.subheader('🧠 AI Learning Foundation — V8.0')
    st.caption('Batch forecasts frozen before deadline • finalized outcomes only • no paid AI API')
    seasons=sorted([p for p in DATA.glob('*') if p.is_dir()],reverse=True)
    if not seasons:
        st.info('No archive yet. Run the AI Learning V8 workflow in GitHub Actions.'); return
    folder=st.selectbox('Season',seasons,format_func=lambda p:p.name,key='v8_season')
    forecasts=archive(folder,'forecasts'); actuals=archive(folder,'actuals'); rows=paired(folder)
    a,b,c=st.columns(3); a.metric('Historical GWs',len(actuals)); b.metric('Captured GWs',len(forecasts)); c.metric('Matched forecasts',len(rows))
    st.caption('Historical outcomes alone cannot reconstruct an authentic old forecast. Missing or uncaptured weeks are not scored.')
    if forecasts:
        st.dataframe(pd.DataFrame([{ 'GW':d['gw'],'Captured (UTC)':d['captured_utc'],'Deadline (UTC)':d['deadline_utc'],'Players':len(d['rows'])} for d in forecasts]),hide_index=True,use_container_width=True)
    if not rows:
        st.info('Accuracy metrics appear after the first captured Gameweek is finalized.'); return
    positions={1:'GKP',2:'DEF',3:'MID',4:'FWD'}
    pos=st.selectbox('Position',['All']+list(positions.values()),key='v8_position')
    if pos!='All': rows=[r for r in rows if positions.get(r['position'])==pos]
    if not rows: st.info('No matching rows.'); return
    m=metrics(rows,'predicted_xp'); a,b,c=st.columns(3)
    a.metric('MAE',f"{m['mae']:.2f}"); b.metric('RMSE',f"{m['rmse']:.2f}"); c.metric('Bias',f"{m['bias']:+.2f}")
    st.caption('Lower MAE/RMSE is better. Positive bias = overprediction. Batch forecasts omit per-session recent-minutes overrides.')
    keys={'Raw engine':'raw_xp','Captured calibrated':'predicted_xp','Last 5 finalized GW mean':'baseline_xp'}
    common=[r for r in rows if r.get('baseline_xp') is not None]
    if common:
        st.markdown('**Model comparison — identical player-GW sample**')
        st.dataframe(pd.DataFrame([{'Model':label,**metrics(common,key)} for label,key in keys.items()]),hide_index=True,use_container_width=True)
    else: st.info('No common baseline sample yet.')
    trend=[]
    for gw in sorted({r['gw'] for r in rows}):
        group=[r for r in rows if r['gw']==gw]
        trend.append({'GW':gw,'Raw MAE':metrics(group,'raw_xp')['mae'],'Calibrated MAE':metrics(group,'predicted_xp')['mae']})
    st.line_chart(pd.DataFrame(trend).set_index('GW'))
    st.markdown('**Prediction audit**')
    df=pd.DataFrame([{k:v for k,v in r.items() if k!='features'} for r in rows]); df['error']=df['predicted_xp']-df['actual_points']
    st.dataframe(df[['gw','name','predicted_xp','actual_points','error','actual_minutes']].sort_values(['gw','error'],ascending=[False,False]),hide_index=True,use_container_width=True)
    st.download_button('Download evaluation CSV',df.to_csv(index=False).encode('utf-8'),'ajk_v8_evaluation.csv','text/csv',key='v8_csv')


# AJK_V81_WRAPPER
_render_v80_dashboard = render_learning_dashboard
def render_learning_dashboard():
    _render_v80_dashboard()
    try:
        from ml_dashboard_v81 import render_ml_dashboard
        render_ml_dashboard()
    except Exception as exc:
        st.warning(f"V8.1 panel unavailable; V8.0 remains active: {type(exc).__name__}")
