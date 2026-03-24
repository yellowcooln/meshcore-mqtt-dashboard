# MQTT Dashboard: Implementation Notes

## Overview
This project provides a live MQTT dashboard that tracks broker status, node presence, and retained packet traffic. A FastAPI backend subscribes to MQTT, stores recent packets in SQLite with a retention window, and streams updates to the frontend over WebSockets.

## Key Paths
- `backend/app.py`: FastAPI server, MQTT client, packet storage, websocket broadcasting.
- `backend/static/index.html`: dashboard UI, tables, and theme toggle.
- `backend/static/traffic.html`: retained traffic page UI and charts.
- `docker-compose.yaml`: runtime configuration.
- `data/packets.db`: SQLite packet storage (retained by `PACKET_RETENTION_SECONDS`).
- `.env`: runtime configuration (mirrors `.env.example`).

## Runtime Commands
- `docker compose up -d --build` (run after any file changes).
- `docker compose logs -f mqtt-dashboard` (watch MQTT + app logs).
- Startup logs include the running app version (currently `v1.3.0`).
- `docker-compose.yaml` loads runtime vars from `.env` via `env_file`.
- `curl -s http://localhost:8081/snapshot` (broker + node snapshot).
- `curl -s http://localhost:8081/packets?limit=50` (recent packets).
- `http://localhost:8081/traffic` (retention-backed traffic page).
- If `DASH_API_TOKEN` is set, include `?token=<value>` (or send header `X-Dashboard-Token`) for `/snapshot`, `/stats`, and `/packets`.
- `pip install -r requirements-dev.txt && pytest -q` (run automated test suite).

## MQTT + Broker
- Supports `tcp` or `websockets` with TLS.
- Optional websocket auth token header (`MQTT_AUTH_TOKEN`, `MQTT_AUTH_TOKEN_HEADER`).
- $SYS topics are optional and displayed when available (`SYS_TOPICS_ENABLED=true`).
- `MQTT_HOST` is used for the actual broker connection.
- `DASH_BROKER_HOST` optionally overrides the broker endpoint shown in the dashboard UI.
- If `DASH_BROKER_HOST` is set, it is rendered exactly as provided.

## Dashboard API Token
- `DASH_API_TOKEN` protects `/snapshot`, `/stats`, and `/packets`.
- `/`, `/traffic`, and `/ws` remain accessible so users can view the live dashboard without a token URL.

## Share / Embed Metadata
- `/` is server-rendered so metadata is visible to crawlers and chat previews.
- `title`, `og:title`, and `twitter:title` use `DASH_TITLE`.
- `description`, `og:description`, and `twitter:description` use `Live node presence, roles, and broker telemetry.`.
- Favicon is optional via `DASH_LOGO_URL`.
- `DASH_LOGO_URL` supports `.png`, `.jpg`, and `.jpeg` only.
- `DASH_LOGO_URL` accepts absolute `http`/`https` URLs or local paths (for example `/static/logo.png`).

## Header External Link
- Set `DASH_EXTERNAL_URL` to show an additional header button.
- Set `DASH_EXTERNAL_LABEL` to customize the button text (default `External`).
- Only `http`/`https` URLs are accepted.
- If `DASH_EXTERNAL_URL` is empty (or invalid), the button is hidden.

## Privacy / Redaction
- Sensitive IP and MAC data is redacted from packet payload text/details and API responses.
- `client_version` version-style values (such as `meshcoretomqtt/1.0.8.0-e52c5ed`) are preserved.

## Packet Retention
- Packets are stored in SQLite and purged on write based on `PACKET_RETENTION_SECONDS`.
- Retention is clamped to a maximum of 24 hours.
- Node names are cached from the packet DB on startup.
- Traffic history is persisted in `traffic_events` and rebuilt from `packets` when needed.
- Traffic charts use the full retention window, not the short stats window.

## Traffic Page
- `/traffic` shows retained packet rate summaries, route mix, payload mix, top talkers, and burst bins.
- Traffic metrics are based on unique `*/packets` events and deduped for the retained history view.
- Top talkers use packet topic + payload identity when name data is missing.

## Node Lifecycle
- Nodes are removed from the in-memory list after `NODE_PURGE_SECONDS` of inactivity.
- Purges broadcast a `node_remove` event to connected clients.
- Retained `*/internal` messages are ignored for node presence so retained startup replay does not inflate online counts.
- After restart, node presence repopulates from fresh MQTT traffic rather than restoring the full node list from SQLite.

## Role Inference
- Explicit payload role fields win first.
- If no explicit role is present, payload hints from `/status` and `/internal` metadata are used.
- Name-based hints are the final fallback before per-node overrides.

## UI Notes
- Dark mode is default with a light mode toggle (saved in localStorage).
- Node list focuses on status, name, and last seen only.
- Broker detail shows configuration, auth mode, and packet retention.

## Releases
- Change history is tracked in [CHANGES.MD](./CHANGES.MD) (latest first).
- CI tests run via `.github/workflows/tests.yml`.
