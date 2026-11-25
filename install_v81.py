from pathlib import Path
import ast, shutil
root=Path(__file__).resolve().parent
p=root/'learning_dashboard.py'; app=root/'app.py'
s=p.read_text(encoding='utf-8'); marker='# AJK_V81_WRAPPER'
if marker in s: print('V8.1 already installed'); raise SystemExit(0)
if 'render_learning_dashboard()' not in app.read_text(encoding='utf-8') or not any(isinstance(n,ast.FunctionDef) and n.name=='render_learning_dashboard' for n in ast.parse(s).body): raise SystemExit('V8.0 integration not found; no changes made')
new=s+'\n\n'+marker+'''
_render_v80_dashboard = render_learning_dashboard
def render_learning_dashboard():
    _render_v80_dashboard()
    try:
        from ml_dashboard_v81 import render_ml_dashboard
        render_ml_dashboard()
    except Exception as exc:
        st.warning(f"V8.1 panel unavailable; V8.0 remains active: {type(exc).__name__}")
'''
ast.parse(new)
b=p.with_name(p.name+'.v80-backup')
if b.exists(): raise SystemExit('Backup exists; inspect before installing')
shutil.copy2(p,b); p.write_text(new,encoding='utf-8'); print('Installed V8.1 panel. Backup:',b.name)
