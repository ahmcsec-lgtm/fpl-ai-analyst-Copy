# V8.3.4 Professional Layout Refinement

Based on the supplied V8.3.3 Professional Dark app.py. UI-only patch: horizontal overview stats, compact injury warnings, centered pitch, smaller real portraits, compact header and scoped radio styling. Existing radio widgets/keys and all player callbacks remain unchanged. Chips retains its existing HTML portrait pitch; Transfers retains the V8.3.3 decision-first structure with reduced padding. No new dependencies, no formula or backend changes.

## Install (Windows / PowerShell)
1. Stop Streamlit (Ctrl+C). Back up app.py: `Copy-Item app.py app.py.v833-backup`.
2. Extract ZIP contents into the existing V8.3.3 repository, replacing app.py. Keep the existing .streamlit/config.toml, engine files, data and prior tests.
3. Run `py -3.11 -m unittest -v test_ui_v834 test_ui_v833 test_ui_v832 test_ui_v831 test_decision_v83 test_milp_v82 test_fast_greedy_v821 test_engine`.
4. Run `py -3.11 -m streamlit run app.py`. Verify desktop and phone layouts, settings, preview GW, all portrait actions, bench, transfer generation/apply and chips.
5. Upload app.py, test_ui_v834.py and this README to GitHub. Upload .github/workflows/layout-v834-tests.yml into the workflows folder; run Professional Layout V8.3.4 Tests. Keep earlier tests/workflows.

## Verification and limitations
Offline suite: 57 tests, 55 passed, 2 skipped (PuLP/highspy unavailable). Existing V8.3.3 AST fingerprint tests pass for functions, input widgets, engine calls and session writes; five synthetic recommendation parity cases pass. No live browser rendering or FPL API test was performed. CSS radio decoration depends on Streamlit DOM; native inputs remain present. Portrait loading depends on the existing external image source. No screenshots of current Transfers/Chips were supplied; changes to those pages are limited to shared styles and chip portrait size. No production performance or prediction improvement is claimed.

Rollback: stop Streamlit, restore app.py.v833-backup to app.py. If rolling back on GitHub, revert the V8.3.4 commit and remove its new workflow/test together.
