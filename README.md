# 心安健 (BloodTrack)

A WeChat Mini Program frontend plus a single-file Flask backend for cardiovascular health monitoring. Patients record blood pressure and symptoms, the backend runs AI analysis, and family/doctors access patient data through approved bindings.

## Project structure

- `app.py` — backend Flask API, database initialization, and route definitions
- `engine/` — cardiovascular analysis engine modules:
  - `steady_state.py` — baseline vs. recent-window analysis. Produces multiple point-count windows (`3pt`/`5pt`/`10pt`/`20pt`/`30pt`, unlocked progressively as more records accumulate) and real change-point segmentation over SBP (not a single fixed window/segment), so trend and structural-shift signals are based on genuine multi-scale comparison rather than a single snapshot
  - `pattern.py` — nocturnal dip / morning surge / variability classification
  - `risk_level.py` — acute risk level, chronic tension, plaque-stress scoring
  - `structure_shift.py` — detects sustained multi-dimensional shifts using `steady_state.py`'s multi-window trajectory
  - `emergency.py` — short-term acute dynamics + segment-stability instability detection
  - `lifecycle.py` — 90-day UX phase / streak / maturity tracking
  - `timeline.py` — merges all of the above into a single chronological event timeline
  - `language.py` — generates the three role-specific reports (user / watcher / doctor) from the above
  - `plots_risk.py`, `plots_symptoms.py` — matplotlib chart generation (risk-score bar chart, symptom timeline), embedded only in the doctor report
  - `cardiovascular_engine.py` — orchestrates the full pipeline and assembles the final API response
- `miniprogram/` — active WeChat Mini Program source
- `build/` — generated build artifacts; do not edit directly

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

**Python version note:** the production Docker image currently runs Python 3.9. `matplotlib` is pinned to `3.9.4` in `requirements.txt` for that reason — newer matplotlib releases require Python ≥3.10/3.11 and will fail to install under this image. If the base image is ever upgraded to Python ≥3.11, `matplotlib` can be bumped accordingly.

## Docker

```bash
docker build -t bloodtrack .
docker run -p 8080:8080 -e FORCE_SQLITE=true bloodtrack
```

The container listens on **8080** (not 80) to avoid a non-root permission issue seen with port 80. Confirm the deployment environment sets `PORT=8080`, since `app.py` falls back to port 80 if that variable is unset.

**Chinese font dependency:** the doctor-report charts (`plots_risk.py` / `plots_symptoms.py`) render Chinese labels. The base image does not ship a CJK font by default, so the Dockerfile must install one before charts will render correctly, e.g.:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*
```

Without this, chart titles/labels will render as boxes (missing glyphs) instead of Chinese text.

## Environment variables

- `FORCE_SQLITE` — forces SQLite instead of MySQL
- `PORT` — port the Flask app listens on (should be `8080` in production; see Docker note above)
- `CHART_OUTPUT_DIR` — local directory where doctor-report chart PNGs are saved (defaults to `<cwd>/static/reports`, served automatically via Flask's default `/static/` route)
- `PUBLIC_BASE_URL` — optional prefix (e.g. `https://your-domain.com`) prepended to chart URLs in the doctor report; needed if the doctor report is rendered on a different origin than the backend itself. Leave unset if the report is viewed same-origin

## Notes for contributors

- The backend supports both SQLite and MySQL. `FORCE_SQLITE=true` forces SQLite.
- The active share/binding flow uses V9 token APIs: `generate_invite_token`, `validate_invite_token`, and `bind_by_token`.
- Avoid legacy files: `index.py`, `index.js`, `index.wxml`, `index.wxss`, and `push.ps1`.
- `engine/auto_threshold.py` and `engine/interaction.py` are unused/dead code (confirmed via repo-wide search — no other module imports them) and have been removed. Do not re-add similar standalone helper modules without wiring them into `cardiovascular_engine.py`'s pipeline.
- Do not edit generated files under `build/`.

## Documentation

- `AGENTS.md` — agent-specific guidance and repository conventions
- `.github/copilot-instructions.md` — GitHub Copilot instructions
- `CODEBUDDY.md` — deeper architecture notes and commands