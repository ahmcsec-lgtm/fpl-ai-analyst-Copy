# AJK Bola Wawei AI V8.3.3 — Professional Dark (Option A)

This patch is based on the supplied V8.3.2 application, not a new live repository checkout. Only the presentation layer is changed. The existing AI engine, state values and manual controls remain in place.

## Install (Windows / VS Code)
1. Stop Streamlit with Ctrl+C. Back up `app.py` and any existing `.streamlit/config.toml`.
2. Extract this ZIP into the current working V8.3.2 repository (the directory containing `app.py`). Replace `app.py`. Preserve existing data, engine modules, models, requirements and workflows.
3. Copy `.streamlit/config.toml` to the corresponding hidden folder at repository root. If a config already exists, merge only the `[theme]` settings rather than losing unrelated server configuration.
4. Run `py -3.11 -m unittest -v test_ui_v833 test_ui_v832 test_ui_v831 test_decision_v83 test_milp_v82 test_fast_greedy_v821 test_engine`.
5. Run `py -3.11 -m streamlit run app.py`. Verify Team ID import, settings, all three pages, generation, alternatives, applying a plan, pitch edits and diagnostics. Restart Streamlit after changing the theme config; refresh the browser if needed.
6. Commit the updated `app.py`, new `test_ui_v833.py`, `README-V833.md`, `.streamlit/config.toml` and `.github/workflows/professional-dark-v833-tests.yml`. Create hidden folders through GitHub Add file > Create new file using their full paths if necessary. Run the Professional Dark V8.3.3 Tests workflow. Keep older test files and workflows.

## Scope
- Compact original logo/header, solid charcoal canvas, green accent, less visual ornament.
- Native popover and original input values/keys remain unchanged. Summary includes draft bank when available.
- Display navigation labels Overview / Transfers / Chips using a format function, retaining original internal values and navigation key.
- Decision and three existing metrics appear side-by-side on wide screens. Transfer portraits appear only when there are moves. All alternative plans, schedule and draft buttons remain. No fabricated confidence or rank metrics.
- Existing pitch and related controls are retained. The stadium file is not deleted; no full-page background image is loaded.
- The patch adds no dependency. Theme file is needed for native controls to match the dark styling.

## Tests and limitations
53 unittest cases: 51 passed, 2 skipped (PuLP/highspy absent locally). Existing synthetic decision parity and fallback tests included. Six new static contracts compare function bodies, engine call arguments, input widgets and state writes with V8.3.2, plus navigation and theme checks. Python 3.13 local; CI uses Python 3.11 and requires HiGHS. No live FPL API or actual browser rendering was tested locally; Streamlit is unavailable in the test environment. CSS retains legacy pitch rules and uses a final dashboard override, so exact appearance depends on installed Streamlit version and screen size. Native layout approximates the design mockup, rather than a pixel-for-pixel reproduction.
