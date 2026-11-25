"""Add the fourth tab without rewriting existing application code."""
from pathlib import Path
import ast, shutil
p=Path(__file__).resolve().parent/'app.py'
s=p.read_bytes().decode('utf-8'); newline='\r\n' if '\r\n' in s else '\n'; s=s.replace('\r\n','\n')
marker='# AJK_V8_LEARNING_TAB'
if marker in s: print('V8 already installed'); raise SystemExit(0)
old='tab_team, tab_transfers, tab_chips = st.tabs(\n    ["🏟️ My Team", "🧠 Smart Transfers", "✨ Wildcard / Free Hit"]\n)'
new='tab_team, tab_transfers, tab_chips, tab_learning = st.tabs(\n    ["🏟️ My Team", "🧠 Smart Transfers", "✨ Wildcard / Free Hit", "📊 AI Performance"]\n)\n'+marker+'\nwith tab_learning:\n    from learning_dashboard import render_learning_dashboard\n    render_learning_dashboard()'
if s.count(old)!=1: raise SystemExit('App layout differs from verified v7.21.1. No changes made.')
updated=s.replace(old,new,1); ast.parse(updated)
backup=p.with_name('app.py.v7-backup');
if not backup.exists(): shutil.copy2(p,backup)
p.write_bytes(updated.replace('\n',newline).encode('utf-8')); print('Installed V8 tab. Backup:',backup)
