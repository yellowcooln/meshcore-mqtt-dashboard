# MQTT Dashboard

A lightweight dashboard for MQTT brokers that tracks nodes, roles, and broker telemetry in real time.
It mirrors the MQTT settings used in `mesh-live-map` and adds a live node table plus $SYS metrics.
Latest release notes: [CHANGES.MD](./CHANGES.MD)

![Dashboard preview](./docs/example.png)

## Quick start (recommended: Docker)

```bash
git clone https://github.com/yellowcooln/meshcore-mqtt-dashboard
cd meshcore-mqtt-dashboard
docker compose up -d --build
```

Open `http://localhost:8081` (or set `WEB_PORT` in your environment).

## Local run (Python)

```bash
git clone https://github.com/yellowcooln/meshcore-mqtt-dashboard
cd meshcore-mqtt-dashboard/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8081
```

Open `http://localhost:8081`.

## Configuration

Copy `.env.example` into your environment or export variables before running. These mirror the live map settings.

- `MQTT_HOST`, `MQTT_PORT`
- `MQTT_USERNAME`, `MQTT_PASSWORD`
- `MQTT_TRANSPORT` (`tcp` or `websockets`)
- `MQTT_WS_PATH`
- `MQTT_TLS`, `MQTT_TLS_INSECURE`, `MQTT_CA_CERT`
- `MQTT_CLIENT_ID`
- `MQTT_TOPIC` (node data; comma-separated supported, e.g. `meshcore/ABC/#,meshcore/DEF/#`)
- `MQTT_SYS_TOPIC` ($SYS telemetry)
- `SYS_TOPICS_ENABLED` (`true`/`false` toggle for $SYS subscription + dashboard display)
- `DASH_TITLE` (dashboard title used in UI and share/embed metadata)
- `DASH_LOGO_URL` (optional favicon URL/path; supports `.png`, `.jpg`, `.jpeg`)
- `DASH_API_TOKEN` (optional token required for `/snapshot`, `/stats`, and `/packets`)
- `DASH_API_TOKEN_HEADER` (optional token header name; default `X-Dashboard-Token`)
- `DASH_EXTERNAL_URL` (optional external link button in header; hidden when empty)
- `DASH_EXTERNAL_LABEL` (button text for external link; default `External`)
- `MQTT_ONLINE_SECONDS` (online window)
- `WEB_PORT` (host port for Docker)
- `MQTT_AUTH_TOKEN` (optional auth token for websocket headers)
- `MQTT_AUTH_TOKEN_HEADER` (default `Authorization`)
- `MQTT_AUTH_TOKEN_SCHEME` (default `Bearer`)
- `PACKET_RETENTION_SECONDS` (packet database retention; default 7200 seconds)
- `PACKET_DB_PATH` (SQLite DB path; default `/data/packets.db`)
- `NODE_PURGE_SECONDS` (remove nodes after inactivity; default 600 seconds)

## Notes

- Node ids are inferred from payload fields or topic segments. Customize `NODE_ID_KEYS` and `TOPIC_SUFFIXES` in `backend/app.py` if your topics differ.
- $SYS metrics only appear if enabled and the broker exposes them.
- IP and MAC values in payload text/details are redacted before they are stored or sent to the UI.
- `client_version` dotted version values (for example `1.0.8.0-e52c5ed`) are preserved.
- If `DASH_API_TOKEN` is set, direct API calls to `/snapshot`, `/stats`, and `/packets` without token return `401`.
- Dashboard page (`/`) and websocket feed (`/ws`) remain accessible so viewers can still use the UI.
- Share/embed metadata on `/` uses `DASH_TITLE` with description `Live node presence, roles, and broker telemetry.`.
- Favicon is set from `DASH_LOGO_URL` when provided (`.png`, `.jpg`, `.jpeg` only).
- The external header button only appears when `DASH_EXTERNAL_URL` is set to a valid `http` or `https` URL.

## Releases

- Change log: [CHANGES.MD](./CHANGES.MD)

---

Vibe coded with Codex.
