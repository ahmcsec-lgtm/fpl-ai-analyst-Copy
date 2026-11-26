"""Compact optional strategy panel; never mutates draft or applies chips."""
from chip_strategy_v86 import CHIPS, analyse, history_inventory, half_end


def render(st, *, team_id, current_gw, selected_gw, weeks, season, squad, players, fixtures, bank, ft, strategy, allow_hits, max_transfers, minutes_overrides, get_history, signature):
    with st.expander('AI chip strategy', expanded=False):
        if season!='2026-27':
            st.info('Chip rules need verification for this season. Manual optimiser remains available.'); return
        if current_gw!=selected_gw:
            st.info('Select the upcoming Gameweek to evaluate chip timing.'); return
        st.caption(f'2026/27 · current chip set expires after GW {half_end(current_gw)} · advice only')
        history_valid=False
        try:
            history=get_history(f'entry/{team_id}/history/')
            inferred,last_fh=history_inventory(history,current_gw)
            history_valid=True
            active=any(int(r['event'])==current_gw for r in history['chips'])
            if active:
                st.warning('A chip is already recorded for this GW. No new chip recommendation.'); return
        except Exception:
            inferred=[]; last_fh=None
            st.caption('Public chip history unavailable. Confirm manually.')
        key=f'v86_{team_id}_{current_gw}'
        with st.form(key+'_form'):
            available=st.multiselect('Unused chips in this half', list(CHIPS), default=inferred, key=key+'_available')
            previous_fh=st.checkbox('Free Hit used last GW', value=last_fh==current_gw-1, key=key+'_fh')
            confirmed=st.checkbox('I verified unused chips, no active chip, and this is not my first FPL Gameweek.', key=key+'_confirm')
            submitted=st.form_submit_button('Analyse chip timing', type='primary')
        context=(team_id,current_gw,tuple(weeks),bank,ft,strategy,allow_hits,max_transfers,tuple(available),previous_fh,confirmed,tuple(sorted((int(p['id']),p.get('selling_price')) for p in squad)),signature,tuple(sorted((minutes_overrides or {}).items())))
        if submitted:
            st.session_state.pop('v86_result',None)
            if not confirmed:
                st.warning('Verify chip availability in your official FPL account first.'); return
            # Do not allow an override to reactivate a known spent chip.
            if history_valid and any(c not in inferred for c in available):
                st.warning('Selected chip conflicts with public history. Refresh team/history first.'); return
            try:
                with st.spinner('Comparing chip opportunities and ordinary transfer plans...'):
                    result=analyse(squad,players,weeks,fixtures,bank,ft,strategy,available,current_gw-1 if previous_fh or last_fh==current_gw-1 else last_fh,minutes_overrides=minutes_overrides,allow_hits=allow_hits,max_transfers=max_transfers)
                st.session_state['v86_result']=(context,result)
            except Exception as exc:
                st.warning(f'Chip analysis unavailable ({type(exc).__name__}). Manual optimiser remains available.'); return
        cached=st.session_state.get('v86_result')
        if not cached or cached[0]!=context: return
        result=cached[1]; action=result['action']
        st.markdown('**'+('SAVE YOUR CHIPS' if action=='SAVE' else ('USE '+action.upper() if action in CHIPS else 'REVIEW CHIP OPTIONS'))+'**')
        st.write(result['reason'])
        if result.get('future'):
            future=result['future']; st.caption(f"Future candidate: {future['chip']} · GW {future['gw']} · {future['gain']:+.1f} simulated net points")
        st.caption(f"{result['samples']:,} paired simulations · experimental risk proxy · published fixtures only · reanalyse weekly")
        if result['rows']:
            with st.expander('Compare chip opportunities'):
                st.dataframe([{'Chip':r['chip'],'GW':r['gw'],'Net gain':round(r['gain'],1),'Risk-adjusted gain':round(r['utility'],1),'Blank squad players':r['blank_players'],'Double squad players':r['double_players']} for r in result['rows']],hide_index=True,use_container_width=True)
