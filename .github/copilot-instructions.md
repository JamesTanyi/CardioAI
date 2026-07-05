# Copilot Instructions

This repository is a WeChat Mini Program frontend plus a single-file Flask backend with a cardiovascular analysis engine.

## Key points

- Backend entrypoint: `app.py`
- Analysis engine: `engine/`
- Active frontend: `miniprogram/`
- Do not edit generated build artifacts under `build/`

## Important behavior

- `app.py` supports SQLite and MySQL. Database selection is controlled by `FORCE_SQLITE=true` and `USE_CLOUD_DB=true`.
- `miniprogram/app.js` manages global routing, role-based dashboards, and `globalData.BASE_URL`.
- Binding and permission logic is centered on `GET /get_binding_status` and `GET /get_history`.
- The current share/binding flow is V9 token-based using `generate_invite_token`, `validate_invite_token`, and `bind_by_token`.

## Recommended files to inspect first

- `AGENTS.md` — project-specific AI agent guidance
- `CODEBUDDY.md` — repository architecture and developer notes
- `app.py` — backend API and database logic
- `miniprogram/app.js` — frontend startup and role routing

## Avoid

- Legacy files: `index.py`, `index.js`, `index.wxml`, `index.wxss`
- `push.ps1`
- making edits directly inside `build/`
