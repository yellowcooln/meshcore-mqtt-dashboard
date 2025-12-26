# MQTT Dashboard

A lightweight dashboard for MQTT brokers that tracks nodes, roles, and broker telemetry in real time.
It mirrors the MQTT settings used in `mesh-live-map` and adds a live node table plus $SYS metrics.

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
- `MQTT_TOPIC` (node data)
- `MQTT_SYS_TOPIC` ($SYS telemetry)
- `MQTT_ONLINE_SECONDS` (online window)
- `WEB_PORT` (host port for Docker)
- `MQTT_AUTH_TOKEN` (optional auth token for websocket headers)
- `MQTT_AUTH_TOKEN_HEADER` (default `Authorization`)
- `MQTT_AUTH_TOKEN_SCHEME` (default `Bearer`)
- `PACKET_RETENTION_SECONDS` (packet database retention; default 7200 seconds)
- `PACKET_DB_PATH` (SQLite DB path; default `/data/packets.db`)

## Notes

- Node ids are inferred from payload fields or topic segments. Customize `NODE_ID_KEYS` and `TOPIC_SUFFIXES` in `backend/app.py` if your topics differ.
- $SYS metrics only appear if the broker exposes them.

---

Vibe coded with Codex.
