# Repository Guidelines

## Project Structure & Module Organization
- `backend/app.py` holds the FastAPI server, MQTT ingest, SQLite packet storage, and websocket broadcasting.
- `backend/static/index.html` is the dashboard UI and client-side rendering.
- `backend/requirements.txt` defines Python dependencies.
- `backend/Dockerfile` builds the service image.
- `docker-compose.yaml` runs the service as `mqtt-dashboard`.
- `data/` stores the SQLite packet database and optional role overrides.
- `.env` holds runtime settings; `.env.example` mirrors template defaults.

## Build, Test, and Development Commands
- `docker compose up -d --build` rebuilds and restarts the backend (preferred workflow).
- `docker compose logs -f mqtt-dashboard` follows server logs.
- `curl -s http://localhost:8081/snapshot` checks broker + node state.
- `curl -s http://localhost:8081/packets?limit=50` inspects recent packets.

## Coding Style & Naming Conventions
- Python in `backend/app.py` uses **2-space indentation**; keep it consistent.
- HTML/CSS/JS in `backend/static/index.html` uses 2 spaces as well.
- Use lowercase, underscore-separated names for Python variables/functions.
- Keep logging concise and avoid dumping full payloads.

## Testing Guidelines
- Automated tests are run with `pytest` from repo root.
- Install deps with `pip install -r requirements-dev.txt`.
- Validate changes manually with `/snapshot` and `/packets`.

## Configuration & Operations
- MQTT settings are configured via `.env` (`MQTT_HOST`, `MQTT_PORT`, `MQTT_TRANSPORT`, TLS, topics).
- Dashboard branding/share metadata is set by `DASH_TITLE`.
- Optional favicon is configured with `DASH_LOGO_URL` (`.png/.jpg/.jpeg`).
- Optional header external button is configured with `DASH_EXTERNAL_URL` and `DASH_EXTERNAL_LABEL`.
- Packet retention is controlled by `PACKET_RETENTION_SECONDS` (clamped to 24h max).
- Packet DB lives at `PACKET_DB_PATH` (default `/data/packets.db` in Docker).
- Names are cached from the packet DB on startup.
- Nodes are purged after `NODE_PURGE_SECONDS` of inactivity (default 600 seconds).
