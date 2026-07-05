# 心安健 (BloodTrack)

A WeChat Mini Program frontend plus a single-file Flask backend for cardiovascular health monitoring. Patients record blood pressure and symptoms, the backend runs AI analysis, and family/doctors access patient data through approved bindings.

## Project structure

- `app.py` — backend Flask API, database initialization, and route definitions
- `engine/` — cardiovascular analysis engine modules
- `miniprogram/` — active WeChat Mini Program source
- `build/` — generated build artifacts; do not edit directly

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

## Docker

```bash
docker build -t bloodtrack .
docker run -p 80:80 -e FORCE_SQLITE=true bloodtrack
```

## Notes for contributors

- The backend supports both SQLite and MySQL. `FORCE_SQLITE=true` forces SQLite.
- The active share/binding flow uses V9 token APIs: `generate_invite_token`, `validate_invite_token`, and `bind_by_token`.
- Avoid legacy files: `index.py`, `index.js`, `index.wxml`, `index.wxss`, and `push.ps1`.
- Do not edit generated files under `build/`.

## Documentation

- `AGENTS.md` — agent-specific guidance and repository conventions
- `.github/copilot-instructions.md` — GitHub Copilot instructions
- `CODEBUDDY.md` — deeper architecture notes and commands
