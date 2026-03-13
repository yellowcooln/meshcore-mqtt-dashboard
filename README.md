# MQTT Dashboard

Live MQTT dashboard for node presence, roles, traffic stats, and broker telemetry.

- Release notes: [CHANGES.MD](./CHANGES.MD)
- Preview: [https://mcmqttdashboard.bostonme.sh/](https://mcmqttdashboard.bostonme.sh/)

![Dashboard preview](./docs/example.png)

## Quick Start (Docker)

```bash
git clone https://github.com/yellowcooln/meshcore-mqtt-dashboard
cd meshcore-mqtt-dashboard
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:8081` (or set `WEB_PORT`).

## Local Development (Python)

```bash
git clone https://github.com/yellowcooln/meshcore-mqtt-dashboard
cd meshcore-mqtt-dashboard/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8081
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI runs the same suite in GitHub Actions on pull requests and pushes to `main`/`dev`.

## API and Auth

- Public:
  - `/` (dashboard page)
  - `/ws` (live dashboard websocket)
- Protected when `DASH_API_TOKEN` is set:
  - `/snapshot`
  - `/stats`
  - `/packets`
- Token can be sent by:
  - header `X-Dashboard-Token` (or `DASH_API_TOKEN_HEADER`)
  - `Authorization: Bearer <token>`
  - query `?token=<token>`

## Configuration

Copy `.env.example` and set what you need.

### Dashboard
- `WEB_PORT`
- `DASH_TITLE`
- `DASH_BROKER_HOST` (optional broker endpoint shown in the UI; for example `broker.example.net` or `broker.example.net:443`)
- `DASH_LOGO_URL` (favicon only; `.png`, `.jpg`, `.jpeg`)
- `DASH_EXTERNAL_URL` (optional header button URL; `http`/`https`)
- `DASH_EXTERNAL_LABEL`
- `DASH_API_TOKEN`
- `DASH_API_TOKEN_HEADER`

### MQTT Broker
- `MQTT_HOST`, `MQTT_PORT`
- `MQTT_USERNAME`, `MQTT_PASSWORD`
- `MQTT_TRANSPORT` (`tcp` or `websockets`)
- `MQTT_WS_PATH`
- `MQTT_TLS`, `MQTT_TLS_INSECURE`, `MQTT_CA_CERT`
- `MQTT_CLIENT_ID`
- `MQTT_AUTH_TOKEN`, `MQTT_AUTH_TOKEN_HEADER`, `MQTT_AUTH_TOKEN_SCHEME`

### Topics and Runtime
- `MQTT_TOPIC` (comma-separated topics supported)
- `MQTT_SYS_TOPIC`
- `SYS_TOPICS_ENABLED`
- `MQTT_ONLINE_SECONDS`
- `NODE_PURGE_SECONDS`
- `SYS_TOPICS_LIMIT`
- `STATS_WINDOW_SECONDS`

### Packet Storage
- `PACKET_DB_PATH` (default `/data/packets.db`)
- `PACKET_RETENTION_SECONDS` (max 24 hours)
- `ROLE_OVERRIDES_FILE`

## Behavior Notes

- `$SYS` panel is hidden when `SYS_TOPICS_ENABLED=false`.
- Sensitive IP/MAC values are redacted before UI/API exposure.
- `client_version` dotted versions (for example `1.0.8.0-e52c5ed`) are preserved.
- Share/embed metadata uses:
  - title from `DASH_TITLE`
  - description `Live node presence, roles, and broker telemetry.`
- `MQTT_HOST` and `MQTT_PORT` control the actual connection target; `DASH_BROKER_HOST` only changes what the dashboard displays.
- If `DASH_BROKER_HOST` is set, the dashboard shows it exactly as provided.
- Favicon is rendered only when `DASH_LOGO_URL` is valid and supported.
