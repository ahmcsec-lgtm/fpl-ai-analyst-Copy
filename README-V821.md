# AJK Bola Wawei AI V8.2.1
Patch for the already installed V8.2. No new dependencies. Keep V8.0/V8.1, existing models and workflows. Do not run the V8.2 installer again.

## Install (Windows PowerShell)
1. Stop Streamlit with Ctrl+C. Back up your entire working V8.2 folder (the local version, not the older GitHub ZIP).
2. Extract this patch into the directory containing app.py and milp_v82.py. Run `py -3.11 install_v821.py`.
3. Run `py -3.11 -m unittest -v test_fast_greedy_v821 test_milp_v82 test_engine`.
4. Run `py -3.11 -m streamlit run app.py`. Test MILP and Fast Greedy, Wildcard and Free Hit, and verify AI Performance is intact.
5. Upload the patched app.py and all new root files. If V8.2 was not uploaded, upload milp_v82.py, install_v82.py, test_milp_v82.py, requirements.txt, requirements-v82.txt, README-V82.md as well. Do not replace the online historical archive with stale local data. Upload both V8.2 and V8.2.1 workflows under .github/workflows. Run CI; verify online app.
6. Rollback: restore app.py.v82-backup to app.py (stop Streamlit first). No dependency change is needed.

## Behavior
MILP uses the existing solver unchanged; new app adapter computes xP once per player/GW per generation, reuses it on fallback, and does not cache across user sessions. Fast Greedy tries 24 cheap positional orders, then at most eight single-swap rounds over up to 24 candidates per position. It evaluates legal XI/captain and 10% bench objective for every week. Search deadline is cooperative, 5 seconds, not a hard process timeout. It returns a legal incumbent or raises a clear error. It may fail to find a legal seed even when one exists. Final rating is still the original scenario-aware rating, called once after search. UI displays projection, search, rating and total adapter timings; rendering/API outside adapter not included. Existing global engine context is unchanged. No ML activation.

## Tests
Synthetic 800-player, six-GW test: 0.531 seconds, 2143 evaluations on development environment. 8 passed, 1 skipped (full app absent). Wall time varies by hardware; CI threshold 7s for synthetic search. Real API, full app, production HiGHS and cloud performance not verified here. Installer requires exact V8.2 anchors and aborts if they differ.
