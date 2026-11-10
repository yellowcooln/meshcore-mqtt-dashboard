# MeshCore MQTT Dashboard Guide

Setup, configuration, and day-to-day operation for the MeshCore MQTT Dashboard.
For the project overview and installation commands, start with the [README](./README.md#quick-start).
For release changes, see [CHANGES.MD](./CHANGES.MD).

## Contents

- [Installation options](#installation-options)
- [Connect your MQTT broker](#connect-your-mqtt-broker)
- [Dashboard pages](#dashboard-pages)
- [Neighbor reports](#neighbor-reports)
- [Battery telemetry](#battery-telemetry)
- [Branding and links](#branding-and-links)
- [API access and privacy](#api-access-and-privacy)
- [Storage and retention](#storage-and-retention)
- [Updates and backups](#updates-and-backups)
- [Troubleshooting](#troubleshooting)
- [Development and project layout](#development-and-project-layout)

## Installation options

Docker Compose is the simplest way to run the dashboard. The README includes a
complete [prebuilt-image quick start](./README.md#run-the-prebuilt-docker-image)
and a separate [source-build option](./README.md#build-from-source-instead).

| Image tag | Source | Intended use |
| --- | --- | --- |
| `yellowcooln/meshcore-mqtt-dashboard:latest` | `main` | Production releases/builds. |
| `yellowcooln/meshcore-mqtt-dashboard:dev` | `dev` | Development builds; may include unreleased changes. |

Both methods load configuration from `.env` and mount `./data` at `/data`.
The default web address is `http://localhost:8081`; remote clients should use
the server's hostname or IP address. `WEB_PORT` changes the published host port,
not the container's internal port `8081`.

Keep `.env` private. When updating an existing installation, do not overwrite it
with a fresh copy of the template.

## Connect your MQTT broker

The [`.env.example`](./.env.example) file lists the available settings. Configure
the broker and subscriptions before starting the dashboard.

| Setting | Purpose |
| --- | --- |
| `MQTT_HOST`, `MQTT_PORT` | Broker hostname/IP and listener port. |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | Broker credentials, if required. |
| `MQTT_CLIENT_ID` | Optional explicit MQTT client ID; use a unique value per instance. |
| `MQTT_TRANSPORT` | `tcp` or `websockets`. |
| `MQTT_WS_PATH` | Broker's WebSocket endpoint, commonly `/mqtt`. |
| `MQTT_TLS` | Enable TLS for the selected transport. |
| `MQTT_CA_CERT` | Optional trusted CA file, at a path readable inside the container. |
| `MQTT_TLS_INSECURE` | Disable certificate verification; leave `false` for normal use. |
| `MQTT_TOPIC` | One subscription or several comma-separated subscriptions. |

Example for a broker with an authenticated TLS WebSocket listener:

```env
MQTT_HOST=mqtt.example.com
MQTT_PORT=443
MQTT_TRANSPORT=websockets
MQTT_WS_PATH=/mqtt
MQTT_TLS=true
MQTT_TLS_INSECURE=false
MQTT_USERNAME=your-subscriber-name
MQTT_PASSWORD=replace-with-your-password
MQTT_TOPIC=meshcore/#
```

The port, path, and credentials must match your broker; port `443` is only an
example. For plain TCP, select the broker's TCP listener and set TLS according
to that listener's configuration.

**Container networking:** `MQTT_HOST=localhost` points at the dashboard container,
not your Docker host. Use a reachable LAN hostname/IP, or the broker's service
name on a shared Docker network. A hostname alone does not join two separate
Compose networks.

If using a custom CA, mount it read-only and set `MQTT_CA_CERT` to the container
path. Disabling verification keeps encryption but removes broker identity
verification; it is not a substitute for configuring a trusted certificate.

### Broker telemetry and optional authentication headers

- `SYS_TOPICS_ENABLED=true` subscribes to broker `$SYS` telemetry when available.
  The broker must publish it and permit your subscriber to read it.
- `.env.example` uses `MQTT_SYS_TOPIC=$$SYS/#` to preserve the literal `$SYS/#`
  through Compose interpolation.
- `SYS_TOPICS_LIMIT` bounds the stored `$SYS` entries.
- `MQTT_AUTH_TOKEN`, `MQTT_AUTH_TOKEN_HEADER`, and `MQTT_AUTH_TOKEN_SCHEME`
  configure an optional WebSocket request authentication header. They do not
  replace MQTT username/password authentication on a TCP listener.

## Dashboard pages

| Path | What it shows |
| --- | --- |
| `/` | Node presence, roles, last-seen times, packet details, and broker telemetry. |
| `/traffic` | Retained unique-packet rates, route/payload mix, top talkers, and bursts. |
| `/neighbors` | Observer-reported neighbor topology, signal quality, scopes, and link table. |
| `/batteryinfo` | Optional decoded channel telemetry; returns 404 while disabled. |

Pages share light/dark themes and responsive layouts. The theme preference is
saved in browser local storage. Node sorting supports a stable online/name view
and a most-recent view; live display batching does not discard incoming packets.

Node presence is separate from persisted history. Fresh MQTT messages repopulate
the live node list after a restart. Retained `*/internal` messages do not create
live presence. `MQTT_ONLINE_SECONDS` controls online age, while
`NODE_PURGE_SECONDS` controls removal from the in-memory list. The supplied env
template uses `300` and `600` seconds respectively; the code's fallback for an
unset `NODE_PURGE_SECONDS` is `3600`.

Roles use explicit payload fields, then metadata/name hints, with per-node
overrides available through `ROLE_OVERRIDES_FILE`. A displayed inferred role is
not independent proof of the device's firmware configuration.

## Neighbor reports

**Enable neighbor uploads in the MQTT uploader.** Regular packet uploads alone
do not populate the topology. Firmware/uploader support may need updating;
neighbor uploads are available in openHop Repeater.

The dashboard consumes the latest neighbor document per observer from topics
in the form `meshcore/<region>/<observer-public-key>/neighbors`. Ensure your
`MQTT_TOPIC` subscriptions include those topics. Each document replaces that
observer's previous snapshot; an empty MQTT payload on a valid neighbor topic
removes the saved snapshot and updates connected browsers.

Snapshots persist in SQLite across restarts. The page distinguishes **snapshot
age** from **RF last-heard age**: a retained or restored report can display a
graph without representing fresh RF observations. Check source ages as well as
the MQTT connection indicator when assessing freshness.

Reported scopes describe the uploaded neighbor information; the graph should
not be treated as proof of every possible RF path or repeater membership.

## Battery telemetry

Battery Info is disabled by default. To enable it, configure:

```env
BATTERYINFO_ENABLED=true
BATTERYINFO_CHANNEL_NAME=batteryinfo
BATTERYINFO_CHANNEL_KEY=replace-with-your-channel-key
BATTERYINFO_SHOW_CHANNEL_NAME=false
BATTERYINFO_RETENTION_SECONDS=172800
```

Use the actual channel name/key for your telemetry source, and subscribe to its
packet feed. The app uses `@michaelhart/meshcore-decoder` to decode the configured
channel; ordinary node status messages are not a substitute for that channel's
telemetry. Treat its key as a secret.

Battery history is persisted separately and can be backfilled from compatible
retained packet records. Its default retention is 48 hours, independent of the
packet-history window. Apply `.env` changes by recreating the service as described
under [Updates and backups](#updates-and-backups).

## Branding and links

| Setting | Effect |
| --- | --- |
| `DASH_TITLE` | Dashboard title and associated share metadata. |
| `DASH_BROKER_HOST` | Display-only broker label, rendered as supplied; does not change `MQTT_HOST`. |
| `DASH_LOGO_URL` | Optional favicon URL/path ending in `.png`, `.jpg`, or `.jpeg`. |
| `DASH_EXTERNAL_URL` | Optional header link; only valid HTTP/HTTPS URLs are accepted. |
| `DASH_EXTERNAL_LABEL` | Header link text; defaults to `External`. |

A local favicon path such as `/static/logo.png` must point to a file actually
available inside the container. Custom assets need their own persistent mount
or custom image; setting the URL does not copy the file. Use an HTTPS URL for
externally hosted assets on HTTPS sites. The optional link is hidden when its
URL is blank or invalid.

## API access and privacy

`DASH_API_TOKEN` optionally protects these HTTP endpoints:

- `/snapshot`
- `/stats`
- `/packets`
- `/neighbors/data`

Send the token using `X-Dashboard-Token` (or `DASH_API_TOKEN_HEADER`), an
`Authorization: Bearer <token>` header, or `?token=<token>`. Prefer a header so
credentials do not appear in copied URLs or URL logs. With no configured token,
these endpoints are public.

**This setting does not make the dashboard private.** Pages and `/ws` stay
public, including neighbor topology delivered over WebSockets. `/traffic/packets`
and enabled `/batteryinfo/data` are also outside this token middleware. Put the
whole application behind an authenticated reverse proxy or restrict network
access if the deployment must be private. The proxy must support WebSocket
upgrades for `/ws`.

Example requests when no API token is configured:

```bash
curl -fsS http://localhost:8081/snapshot
curl -fsS http://localhost:8081/stats
curl -fsS 'http://localhost:8081/packets?limit=50'
curl -fsS http://localhost:8081/neighbors/data
```

`/packets` accepts `limit` from 1 to 1000 and an optional `node_id` filter.
`/traffic/packets` accepts required epoch-time `start` and `end` parameters and an
optional result limit. `/ws` supplies an initial snapshot and live updates.

Payload redaction covers recognized sensitive fields and IP/MAC patterns, while
preserving version-style `client_version` values. It is not complete
anonymization: names, public keys, topology, and other operational information
can remain visible. Review your feed and access policy before public exposure.

## Storage and retention

The standard Compose mount is `./data:/data`, with SQLite at
`/data/packets.db` (`PACKET_DB_PATH`). Keep that mount when replacing containers.

- `PACKET_RETENTION_SECONDS` defaults to `7200` (two hours) and is clamped to
  `0`–`86400` seconds. Packet history is purged on writes.
- `STATS_WINDOW_SECONDS` controls short-window statistics; Traffic uses the
  retained history rather than only this short window.
- Node names are cached from saved packet records at startup, but the full live
  presence list is not restored.
- Traffic events and battery events are persisted, with backfill paths from
  retained packets when needed.
- Latest neighbor snapshots are persisted separately from packet retention.

`ROLE_OVERRIDES_FILE` defaults to `/data/device_roles.json` in the supplied env
template. Keep operator-owned files under a persistent mount.

## Updates and backups

Back up `.env`, your Compose file, custom mounts, and `data/` before upgrades.
For a consistent simple file backup, stop this service before copying its data,
then start it again. Preserve the entire data directory, including any SQLite
WAL/SHM files; copying only a live `packets.db` can miss pending writes.

### Published-image installations

From the directory containing your image-based Compose file:

```bash
docker compose pull mqtt-dashboard
docker compose up -d --no-build mqtt-dashboard
```

To apply `.env` edits, force recreation with the intended image already pulled:

```bash
docker compose up -d --no-build --pull never --force-recreate mqtt-dashboard
```

### Source-build installations

Update your source to the intended revision, preserving `.env`, overrides, and
data. Build first, then recreate the service:

```bash
docker compose build mqtt-dashboard
docker compose up -d --no-build --pull never --force-recreate mqtt-dashboard
```

**`docker compose restart` does not reload Compose environment-file values.**
Do not use `docker compose down -v` as an upgrade step, delete `data/`, or copy
the example env file over a working configuration.

After an upgrade, inspect logs and load the dashboard, Traffic, and Neighbors
pages. Check advancing packet activity, not only a connected indicator, and
check neighbor source ages separately. Startup logs show the app version;
compare it with the intended release in [CHANGES.MD](./CHANGES.MD).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| MQTT disconnected | Host reachability from Docker, listener port, transport, TLS, credentials, and WebSocket path. |
| Connected but no nodes | Subscription topic/ACL, active uploader traffic, and whether only retained internal messages were received. |
| Missing broker telemetry | `$SYS` publication/ACL and `SYS_TOPICS_ENABLED`; node traffic can work without broker telemetry. |
| Neighbors empty | Uploader supports/enables neighbor reports and subscription includes `*/neighbors`. |
| Neighbors look old | Source snapshot timestamp and RF last-heard ages; saved/retained reports are not fresh measurements. |
| Battery page returns 404 | `BATTERYINFO_ENABLED=true`, followed by service recreation. |
| Battery page has no data | Correct channel name/key, telemetry messages, and packet subscription. |
| HTTP data endpoint returns 401 | Supply the configured API token using an accepted header. |
| Env edit has no effect | Recreate the service; a plain restart retains the old environment. |
| History missing after replacement | Original data directory is still mounted at the configured database path. |

Follow logs without rebuilding or changing the running service:

```bash
docker compose logs --tail=100 -f mqtt-dashboard
```

Do not share tokens, broker passwords, channel keys, or unreviewed raw payloads
when reporting a problem.

## Development and project layout

| Path | Responsibility |
| --- | --- |
| `backend/app.py` | FastAPI routes, MQTT lifecycle, SQLite state, decoding, and live broadcasts. |
| `backend/static/index.html` | Node dashboard. |
| `backend/static/traffic.html` | Traffic charts and packet drilldown. |
| `backend/static/neighbors.html` | Topology graph and link table. |
| `backend/static/batteryinfo.html` | Optional decoded telemetry page. |
| `backend/static/dashboard.css` | Shared page styling. |
| `docker-compose.yaml` | Source-build Compose configuration. |
| `.env.example` | Configuration template. |
| `tests/` | Automated regression tests and runtime smoke checks. |

Run the source checks from the repository root:

```bash
pip install -r requirements-dev.txt
npm ci --prefix backend
pytest -q
```

Node.js is required for decoder tests. See [CONTRIBUTING.md](./CONTRIBUTING.md)
for contribution guidance. The workflow files
[tests.yml](./.github/workflows/tests.yml) and
[docker-publish.yml](./.github/workflows/docker-publish.yml) define CI and
multi-architecture Docker publication. Keep release history in
[CHANGES.MD](./CHANGES.MD); do not hard-code a second current-version value here.
