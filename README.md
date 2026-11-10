# MQTT Dashboard

Live MeshCore MQTT dashboard for node activity, neighbor topology, and traffic analysis.

**Version:** `v1.3.5` · [Live preview](https://mcmqttdashboard.bostonme.sh/) · [Changelog](./CHANGES.MD) · [Docker Hub](https://hub.docker.com/r/yellowcooln/meshcore-mqtt-dashboard)

![Dashboard preview](./docs/example.png)

## Features

- **Dashboard:** online nodes, device roles, packet inspection, and optional broker `$SYS` telemetry.
- **Traffic:** retained packet history, route/payload charts, top talkers, and burst activity.
- **Neighbors:** observer topology, SNR, last-heard ages, and a filterable link table.
- **Battery Info:** optional decoded battery telemetry from a configured channel.
- Shared light/dark themes and mobile layouts, with batched live updates and stable node sorting.

## Quick start

```bash
git clone https://github.com/yellowcooln/meshcore-mqtt-dashboard
cd meshcore-mqtt-dashboard
cp .env.example .env
```

Edit `.env` with your broker address, credentials, and topics. `MQTT_HOST` must be reachable from the container; `localhost` refers to the container itself.

```bash
docker compose up -d --build
```

Open **http://localhost:8081**, or use your server's address and configured `WEB_PORT`.

To use a prebuilt image, replace `build: ./backend` in `docker-compose.yaml` with `image: yellowcooln/meshcore-mqtt-dashboard:latest`, then run `docker compose up -d`. Use the `:dev` tag for development builds.

## Configuration

Settings are loaded from `.env`. See [`.env.example`](./.env.example) for the complete list.

| Setting | Purpose |
| --- | --- |
| `MQTT_HOST`, `MQTT_PORT` | Broker connection address. |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | Broker credentials, when required. |
| `MQTT_TOPIC` | Topic subscription; comma-separated topics are supported. |
| `MQTT_TRANSPORT`, `MQTT_WS_PATH` | TCP or WebSocket transport and WebSocket path. |
| `MQTT_TLS`, `MQTT_CA_CERT` | TLS connection settings. |
| `WEB_PORT`, `DASH_TITLE` | Web port and dashboard title. |
| `DASH_BROKER_HOST` | Display-only broker label; does not change the connection address. |
| `SYS_TOPICS_ENABLED` | Show or hide broker `$SYS` telemetry. |
| `PACKET_RETENTION_SECONDS` | Packet history retention, capped at 24 hours. |
| `DASH_API_TOKEN` | Optional protection for the HTTP data endpoints below. |
| `BATTERYINFO_ENABLED` | Enable Battery Info; disabled by default. |

Battery decoding also requires `BATTERYINFO_CHANNEL_NAME` and `BATTERYINFO_CHANNEL_KEY`. Battery history has its own retention setting, `BATTERYINFO_RETENTION_SECONDS`.

The `./data` volume stores packet history and the latest neighbor snapshots across restarts. Keep it when updating. Node presence repopulates from fresh MQTT traffic after a restart.

## Pages and API

| Path | Description |
| --- | --- |
| `/` | Node dashboard. |
| `/traffic` | Traffic analysis. |
| `/neighbors` | Neighbor graph and link table. |
| `/batteryinfo` | Battery telemetry, when enabled. |
| `/ws` | Public live WebSocket stream. |
| `/snapshot`, `/stats`, `/packets`, `/neighbors/data` | HTTP data endpoints. |

When `DASH_API_TOKEN` is set, HTTP data requests require an `X-Dashboard-Token` header, an `Authorization: Bearer <token>` header, or a `?token=<token>` query parameter. The token header name can be changed with `DASH_API_TOKEN_HEADER`.

**The pages and WebSocket stream remain public**, including neighbor topology. The API token does not make the dashboard private.

## Development

From the repository root:

```bash
pip install -r requirements-dev.txt
npm ci --prefix backend
pytest -q
```

Node.js is needed for decoder tests. Rebuild the local application with `docker compose up -d --build`.

## Star History

<a href="https://www.star-history.com/?repos=yellowcooln%2Fmeshcore-mqtt-dashboard&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=yellowcooln/meshcore-mqtt-dashboard&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=yellowcooln/meshcore-mqtt-dashboard&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=yellowcooln/meshcore-mqtt-dashboard&type=date&legend=top-left" />
 </picture>
</a>
