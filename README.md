# FPL AI Analyst

A beginner-friendly Streamlit web app for Fantasy Premier League analysis.

## Features in this starter build

- Personal dashboard preloaded with FPL Team ID `1645144`
- Public manager profile, overall points and rank
- Public Gameweek picks when the FPL API exposes them
- Squad availability flags and FPL injury/news fields
- Transfer shortlist by position
- Incoming Gameweek player rankings and captaincy shortlist
- Public Team Analyzer for any manager ID
- Cached API requests to reduce load

## Important limitations

1. The Fantasy Premier League API is an undocumented public API and can change without notice.
2. The public manager profile and picks endpoints do not expose every private team detail. In particular, a manager's private editable team endpoint (`/my-team/{id}/`) requires that manager's authenticated session. This app does **not** ask for or store your FPL password.
3. The expected-points score is a transparent heuristic using form, points per game, expected goal involvements, minutes, fixture difficulty and FPL availability status. It is not a trained model and is not an official FPL projection.
4. Injury information is only as current as the FPL API fields. Verify late press-conference news before a deadline.
5. Transfer recommendations are candidate shortlists. Exact selling prices, free transfers, squad rules and budget should be checked before confirming a transfer.

## Run locally on Windows 11

1. Install Python 3.11 or newer from https://www.python.org/downloads/
2. Extract this ZIP.
3. Open PowerShell in the extracted `fpl_ai_analyst` folder.
4. Create a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

5. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

6. Start the app:

   ```powershell
   streamlit run app.py
   ```

7. Open the local URL printed by Streamlit (normally http://localhost:8501).

## Deploy online with Streamlit Community Cloud

You need a GitHub account and a Streamlit Community Cloud account.

1. Create a new **public** GitHub repository, e.g. `fpl-ai-analyst`.
2. Upload `app.py`, `requirements.txt`, and `README.md` to the repository root.
3. Sign in at https://share.streamlit.io/ using GitHub.
4. Choose **Create app**, select your repository and branch, and set the main file path to `app.py`.
5. Deploy. Streamlit will install packages from `requirements.txt`.
6. Open the deployed app URL. Your default Team ID is already set to `1645144`; visitors can change it in the sidebar.

Do not add FPL passwords, session cookies, or other secrets to the repository.

## Data endpoints used

- `bootstrap-static/` — players, teams, events and availability fields
- `fixtures/` — fixtures and FPL difficulty ratings
- `entry/{team_id}/` — public manager profile
- `entry/{team_id}/history/` — public gameweek history
- `entry/{team_id}/event/{gw}/picks/` — public Gameweek picks when available

Base API: https://fantasy.premierleague.com/api/

The API is unofficial/undocumented. Be conservative with request frequency and cache data.
