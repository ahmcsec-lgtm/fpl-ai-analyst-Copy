"""Patch only the existing chip tab; abort if expected anchors differ."""
from pathlib import Path
import ast
import shutil

ROOT=Path(__file__).resolve().parent
MARKER='# V8.2 MILP integration'

def patch(source):
    if MARKER in source: return source
    replacements=[
        ('    if st.button(f"Generate {chip} squad"):', '''    # V8.2 MILP integration
    from milp_v82 import optimise_chip_v82
    solver_choice = st.radio("Squad optimiser", ["MILP", "Original greedy"], horizontal=True, key="v82_solver")
    v82_context = (solver_choice, liquidation, tuple(sorted((int(k), float(v)) for k,v in (minutes_overrides or {}).items())), tuple(sorted(int(p["id"]) for p in squad)))
    if st.button(f"Generate {chip} squad"):'''),
        ('result = optimise_chip_squad(players, chip_gws, fixture_map, liquidation,','result = optimise_chip_v82(players, chip_gws, fixture_map, liquidation,'),
        ('minutes_overrides=minutes_overrides, shortlist=24)','minutes_overrides=minutes_overrides, shortlist=24, method=solver_choice)'),
        ('{"kind": chip, "gws": chip_gws, "result": result}','{"kind": chip, "gws": chip_gws, "result": result, "v82_context": v82_context}'),
        ('and proposed_chip["gws"] == chip_gws:', 'and proposed_chip["gws"] == chip_gws and proposed_chip.get("v82_context") == v82_context:'),
        ('        chip_xi = best_lineup(result["squad"], selected_gw, fixture_map, minutes_overrides)','''        chip_xi = result.get("milp_weekly", {}).get(selected_gw)
        if chip_xi is None:
            chip_xi = best_lineup(result["squad"], selected_gw, fixture_map, minutes_overrides)'''),
        ('        st.caption("Approximate greedy optimiser. Free Hit is a single-GW simulation, not a chip activation.")','''        st.caption(f"Optimiser: {result.get('solver_method', 'Original greedy')} • {result.get('solver_status', '')}")
        if result.get("milp_weekly"):
            gap = result.get("solver_gap")
            st.caption(f"MILP relative gap: {gap:.2%}" if gap is not None else "MILP gap unavailable")
            st.caption("MILP maximises XI + captain + 10% bench xP. Rating above remains the legacy scenario-aware estimate; the two objectives differ.")
            st.dataframe(pd.DataFrame([{"GW": gw, "XI + captain xP": plan["base_xp"], "Captain": plan["captain"].get("web_name", plan["captain"]["id"]), "Vice": plan["vice"].get("web_name", plan["vice"]["id"]), "Bench order (outfield, then GK)": ", ".join(str(p.get("web_name", p["id"])) for p in plan["bench"])} for gw,plan in result["milp_weekly"].items()]),hide_index=True,use_container_width=True)
        st.caption("Free Hit is a single-GW simulation, not a chip activation.")'''),
    ]
    # Limit the replacements to the chip tab, preserving the V8/V8.1 panels.
    anchor='with tab_chips:'
    if source.count(anchor)!=1: raise ValueError('Expected exactly one chip tab.')
    head,tail=source.split(anchor,1)
    for old,new in replacements:
        if tail.count(old)!=1: raise ValueError('Unexpected app structure: '+old)
        tail=tail.replace(old,new,1)
    updated=head+anchor+tail
    ast.parse(updated)
    return updated


def main():
    app=ROOT/'app.py'; req=ROOT/'requirements.txt'
    old=app.read_text(encoding='utf-8'); updated=patch(old)
    requirements=req.read_text(encoding='utf-8')
    extra=''
    for name,line in [('pulp','PuLP>=3.0,<4'),('highspy','highspy>=1.8,<2')]:
        import re
        if not any(re.match(r'^\s*'+name+r'\s*(?:[<>=!~;\[]|$)',s,re.I) for s in requirements.splitlines()): extra+=line+'\n'
    if old!=updated:
        backup=ROOT/'app.py.v81-backup'
        if backup.exists(): raise ValueError('Backup already exists; inspect before retrying.')
        shutil.copy2(app,backup)
        app.write_text(updated,encoding='utf-8')
    if extra:
        backup=ROOT/'requirements.txt.v81-backup'
        if not backup.exists(): shutil.copy2(req,backup)
        req.write_text(requirements.rstrip()+'\n'+extra,encoding='utf-8')
    print('V8.2 integrated. Existing learning dashboards and engine untouched.')

if __name__=='__main__': main()
