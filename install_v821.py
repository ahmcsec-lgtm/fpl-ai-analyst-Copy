"""Apply only to an already installed V8.2 app. Keeps a rollback copy."""
from pathlib import Path
import ast
import shutil

MARKER='# V8.2.1 bounded fallback'

def patch(source):
    if MARKER in source: return source
    if source.count('with tab_chips:')!=1 or '# V8.2 MILP integration' not in source: raise ValueError('Install V8.2 first.')
    head,tail=source.split('with tab_chips:',1)
    changes=[
        ('from milp_v82 import optimise_chip_v82',MARKER+'\n    from fast_greedy_v821 import optimise_chip_v821'),
        ('["MILP", "Original greedy"], horizontal=True, key="v82_solver"','["MILP", "Fast Greedy"], index=0, horizontal=True, key="v821_solver"'),
        ('result = optimise_chip_v82(','result = optimise_chip_v821('),
        ('    if st.button(f"Generate {chip} squad"):\n        try:', '    if st.button(f"Generate {chip} squad"):\n        st.session_state.chip_result = None\n        try:'),
        ('''st.caption(f"Optimiser: {result.get('solver_method', 'Original greedy')} • {result.get('solver_status', '')}")''','''st.caption(f"Optimiser: {result.get('solver_method', 'Unknown')} • {result.get('solver_status', '')}")
        if result.get("fallback_reason"):
            st.warning(f"MILP fallback: {result['fallback_reason']}. Using Fast Greedy.")
        if "execution_seconds" in result:
            st.caption(f"Execution: {result['execution_seconds']:.2f}s • Projection: {result['projection_seconds']:.2f}s • Optimisation: {result['optimisation_seconds']:.2f}s • Rating: {result['rating_seconds']:.2f}s")
        if "greedy_iterations" in result:
            st.caption(f"Fast Greedy: {result['greedy_iterations']} iterations • {result['greedy_evaluations']} evaluations • search {result['search_seconds']:.2f}s")'''),
        ('''st.caption(f"MILP relative gap: {gap:.2%}" if gap is not None else "MILP gap unavailable")''','''if result.get("solver_method") == "MILP / HiGHS":
                st.caption(f"MILP relative gap: {gap:.2%}" if gap is not None else "MILP gap unavailable")'''),
        ('MILP maximises XI + captain + 10% bench xP.', 'Optimiser objective: XI + captain + 10% bench xP.'),
    ]
    for old,new in changes:
        if tail.count(old)!=1: raise ValueError('Unexpected V8.2 app structure: '+old)
        tail=tail.replace(old,new,1)
    result=head+'with tab_chips:'+tail
    ast.parse(result)
    return result

def main():
    app=Path(__file__).resolve().with_name('app.py'); old=app.read_text(encoding='utf-8'); new=patch(old)
    if old!=new:
        backup=app.with_name('app.py.v82-backup')
        if backup.exists(): raise ValueError('Backup already exists; inspect before retrying.')
        shutil.copy2(app,backup)
        app.write_text(new,encoding='utf-8')
    print('V8.2.1 integrated. MILP default; bounded Fast Greedy fallback.')
if __name__=='__main__': main()
