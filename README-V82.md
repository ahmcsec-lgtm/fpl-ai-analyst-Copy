# AJK Bola Wawei AI V8.2 — Mathematical Squad Optimisation

Additive upgrade for existing V8.1 repository. No paid API, no changes to statistical projections, Smart Transfers, learning archives, ML training or shadow mode.

## Windows installation
1. Download latest main branch ZIP, extract into a fresh directory, then copy this upgrade's contents into the directory containing app.py. Preserve `.github/workflows` and `data`.
2. Open that directory in VS Code. Run `dir` to confirm `app.py`, `install_v82.py` and `requirements.txt` exist.
3. Run `py -3 install_v82.py`. Installer patches only `with tab_chips:` and appends PuLP/highspy to existing requirements.txt. It stops if expected anchors differ. Backups: `app.py.v81-backup`, `requirements.txt.v81-backup`. Never upload backups.
4. Recommended local interpreter: Python 3.11 or 3.12. Example: `py -3.11 -m pip install -r requirements.txt -r requirements-v82.txt`. If not installed, use `py -0p` to inspect installed interpreters; install a compatible Python first. `py -3.11 -m unittest test_milp_v82 test_engine`, then `py -3.11 -m streamlit run app.py`.
5. In Wildcard / Free Hit choose MILP, generate. Confirm legal 15 players, bank nonnegative, pitch, weekly table, solver label and gap. Try Original greedy too. V8.0 and V8.1 panels should still be visible. Test Free Hit separately (one GW).
6. Upload app.py and requirements.txt (modified by installer), milp_v82.py, install_v82.py, test_milp_v82.py, requirements-v82.txt and README-V82.md. Upload `.github/workflows/milp-v82-tests.yml` inside `.github/workflows`. Keep all existing files and data; do not upload stale archives or backups.
7. GitHub Actions > MILP V8.2 Tests > Run workflow on main. Tests include existing engine tests. Production PuLP/HiGHS test is mandatory in CI; no skip allowed. Check logs. Streamlit Cloud may rebuild dependencies; reboot if needed. Test again online.

## Optimisation model
Binary squad membership S, starting XI X and captain C for every player and GW. Maximise sum of XI xP + captain extra xP + 0.10 * bench xP. The bench weight is a heuristic tie/coverage preference, NOT predicted autosub points. One fixed squad across horizon, independently selected legal XI and captain per GW. Full eligible input pool, not old shortlist. Squad quotas 2/5/5/3; max 3 per club; integer prices in tenths; total cost <= estimated liquidation budget. XI 1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD. Captain must start. Vice is highest remaining starter xP; bench outfield ordered by xP, GK last; neither vice nor bench order is scenario-optimised. A single GW for Free Hit; Wildcard uses selected horizon 1–6. No transfers within horizon. Uses current buy prices, same budget approximation as original app; not exact retained-player selling-price treatment. Double/blank weeks use existing engine projections.

PuLP HiGHS uses 15-second solver limit, one thread, 0.5% relative gap tolerance; modelling and legacy fallback time are additional. A feasible incumbent can be returned at timeout. Every binary value and constraint is checked, then legacy valid_squad and budget checked. No feasible incumbent, missing dependency, or solver exception -> original greedy; existing error handling if both fail. Display solver status and gap; do not imply exact optimality at positive gap. Existing rating remains legacy scenario-aware rating, may use a different XI from MILP. Weekly table shows actual MILP XI+captain projections without bench weight. Existing pitch receives MILP XI/captain/vice; original pitch styling unchanged. Draft behaviour unchanged.

## Test and limitations
Local environment: no PuLP/highspy and no direct GitHub clone. Formulation tested with SciPy's HiGHS MILP backend using synthetic player projections. Production adapter and full repository integration require GitHub CI. No real FPL benchmark yet. GitHub raw app source reviewed for patch anchors, but live deployment not tested. If installer reports mismatch do not force replace: send exact error. Existing global projection context and public API limitations unchanged. No guarantees of actual future points or improvement versus legacy scenario objective.

## Rollback
Select Original greedy in UI immediately. To fully remove upgrade, restore backups (or revert the upgrade commit via GitHub); leave V8.0/V8.1 data and workflows intact.
