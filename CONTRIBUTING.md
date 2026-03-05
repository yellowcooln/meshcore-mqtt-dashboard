# Contributing

Thanks for contributing! Here are the basics to keep things consistent.

## Development Setup

```bash
cd /home/yellowcooln/mqtt-dashboard
docker compose up -d --build
```

For local Python development:

```bash
cd /home/yellowcooln/mqtt-dashboard/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8081
```

## Guidelines
- Keep `backend/app.py` and `backend/static/index.html` at **2-space indentation**.
- Prefer small helper functions and avoid dumping full payloads in logs.
- Keep UI changes mobile-friendly and test on narrow screens.

## Testing
- Automated tests:
  - `pip install -r requirements-dev.txt`
  - `pytest -q`
- Manual validation:
  - `http://localhost:8081/snapshot`
  - `http://localhost:8081/stats`
  - `http://localhost:8081/packets?limit=50`
- Validate share/embed metadata with:
  - `curl -s http://localhost:8081 | rg -n "og:title|og:description|twitter:title|twitter:description"`
- Validate favicon behavior:
  - `curl -s http://localhost:8081 | rg -n "rel=\"icon\""`
  - With empty `DASH_LOGO_URL`, icon tag should be absent.
  - With valid `DASH_LOGO_URL` (`.png/.jpg/.jpeg`), icon tag should be present.
- Validate external button behavior:
  - With empty `DASH_EXTERNAL_URL`, confirm the external header button is hidden.
  - With valid `DASH_EXTERNAL_URL`, confirm the button appears with `DASH_EXTERNAL_LABEL`.
- If `DASH_API_TOKEN` is enabled locally, include `?token=<value>` or send header `X-Dashboard-Token` for `/snapshot`, `/stats`, and `/packets`.

## Configuration Changes
- Update `.env.example` when you add or modify environment variables.
- If you change data retention or node lifecycle behavior, update `docs.md`.
- For user-visible behavior changes, update `CHANGES.MD` (newest version at top).
