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
- No automated test suite is present.
- Validate changes manually with:
  - `http://localhost:8081/snapshot`
  - `http://localhost:8081/stats`
  - `http://localhost:8081/packets?limit=50`
- If `DASH_API_TOKEN` is enabled locally, include `?token=<value>` or send header `X-Dashboard-Token` for `/snapshot`, `/stats`, and `/packets`.

## Configuration Changes
- Update `.env.example` when you add or modify environment variables.
- If you change data retention or node lifecycle behavior, update `docs.md`.
- For user-visible behavior changes, update `CHANGES.MD` (newest version at top).
