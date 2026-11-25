# AJK Bola Wawei AI V8.3.5 — Final Professional UI

Base: supplied V8.3.4 app.py. No engine files or model data are replaced.

- Native segmented navigation, preview Gameweek and chip selection where supported; old Streamlit versions retain radio fallback.
- Compact header and Overview statistics; draft bank/FT are omitted in the Overview header to avoid repetition, but retained for future applied-plan previews where values can differ. Settings remain mounted in the popover.
- Compact Analyse button, real portrait transfer pairs, four inline metrics (including existing transfer-first vs roll-first net xP difference), draft apply and alternatives.
- Horizontal chip selector/budget/generate toolbar and reduced pitch/bench spacing. All original portrait and manual-action functions are unchanged.

## Install on Windows
1. Stop Streamlit with Ctrl+C. Back up `app.py` and `test_ui_v832.py` (e.g. `Copy-Item app.py app.py.v834-backup` and `Copy-Item test_ui_v832.py test_ui_v832.py.v834-backup`).
2. Extract this ZIP into the existing V8.3.4 repository. Replace app.py and test_ui_v832.py. Keep the existing .streamlit/config.toml and all engine/data files. The old popover test is updated only to test its summary text on Transfers, where FT is still shown.
3. Run `py -3.11 -m unittest -v test_ui_v835 test_ui_v834 test_ui_v833 test_ui_v832 test_ui_v831 test_decision_v83 test_milp_v82 test_fast_greedy_v821 test_engine test_learning_v8 test_ml_v81`.
4. Run `py -3.11 -m streamlit run app.py`. If radio buttons persist, upgrade Streamlit within the existing supported major version: `py -3.11 -m pip install --upgrade "streamlit<2"` and restart.
5. Verify all pages, settings after navigation, each GW preview, portraits, captain/vice, substitutions, manual transfers, Analyse, alternatives, apply to draft and both chip modes. Verify both desktop and phone.
6. Upload app.py, test_ui_v832.py, test_ui_v835.py, README-V835.md and .github/workflows/final-ui-v835-tests.yml to GitHub in one commit. Run Final Professional UI V8.3.5 Tests. Keep old workflows and config.

## Test scope and limitations
Offline Python 3.13.5 regression tests only: no browser or live FPL API verification. The two production PuLP/HiGHS tests are skipped locally because those dependencies are unavailable; CI requires them. Older Streamlit versions use the existing radio fallback. Native widget behaviour and CSS rendering must be verified on the actual deployed Streamlit version. No prediction accuracy or performance improvement is claimed. The difference between transfer-first and roll-first is the existing engine output, not a new scoring rule.

Rollback: restore both backed-up files and remove the new test and workflow (or revert the commit).
