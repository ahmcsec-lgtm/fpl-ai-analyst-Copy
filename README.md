# FPL AI Analyst — upgraded free core

A Streamlit app for FPL manager `1645144`, with a public Team ID analyzer.

## Included features

- Statistical captain and vice-captain shortlist
- Transparent one-Gameweek expected-points (xP) estimates
- Same-position transfer comparisons using public picks selling-price fields when available
- Indicative Wildcard / Free Hit 15-player squad builder with position quotas and max-three-per-club constraint
- Differential finder filtered by ownership, price and minutes
- Fixture difficulty matrix and squad rotation view
- Weekly Markdown report generator and GitHub Actions schedule
- Public team profile/history analyzer

## Cost and limitations

The app uses Python, Streamlit, pandas, requests, GitHub Actions and public FPL endpoints. No paid AI API is needed for the core features. Streamlit Community Cloud and GitHub free-tier limits apply. Scheduled GitHub Actions can be delayed or disabled by GitHub, and the public FPL API is undocumented and may change.

The xP formula is a transparent heuristic based on public season data (xG/xA or xGI, minutes, appearance, clean-sheet history, form and fixture difficulty). It is not a trained machine-learning model, official FPL projection or guarantee. The squad optimiser is a greedy constrained heuristic, not a globally optimal mathematical solver. Transfer advice cannot fully infer private selling-price rules, free transfers or all chip/transfer state. Always verify decisions in the official FPL site.

## Deploy / update on Streamlit Community Cloud

1. Extract the ZIP.
2. In your existing GitHub repository `fpl-ai-analyst`, upload and replace `app.py`, `requirements.txt`, and `README.md`.
3. Upload the new `fpl_engine.py` and `weekly_report.py` to the repository root.
4. Upload `.github/workflows/weekly-report.yml` preserving its folder path.
5. Keep the `reports` folder; GitHub does not track empty folders, so it may be omitted until the first report is generated.
6. Commit the changes. Streamlit Community Cloud should rebuild the app automatically.
7. In GitHub, open Settings → Actions → General and ensure workflow permissions allow read and write access to repository contents. Save if you change it.
8. Open Actions → Weekly FPL report → Run workflow to test the first report. The workflow is also scheduled for Mondays at 01:00 UTC (09:00 Malaysia time).

No FPL password, session cookie, or paid API key is required.
