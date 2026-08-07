# Changes

## v1.3.4 - 2026-08-07
- Added a live `/neighbors` topology page with an observer-to-neighbor graph, synchronized filters, link table, and selection details.
- Added validated ingestion for MeshCore `*/neighbors` MQTT snapshots, including SNR, last-heard age, discovery status, and flood scopes.
- Persisted the latest neighbor snapshot per observer in SQLite and exposed normalized topology data through `/neighbors/data` and websocket updates.
- Anchored retained neighbor ages to firmware report timestamps, rejected topic/payload identity mismatches, ignored out-of-order reports, and removed topology state when retained topics are deleted.
- Kept neighbor persistence active when packet history is disabled, kept zero-neighbor observers visible, and added bounded websocket reconnection for the live topology page.
- Added collision-aware graph positioning so unrelated nodes and labels do not overlap neighbor edges.

## v1.3.3 - 2026-06-10
- Synced the `dev` branch with `main` while preserving the self-hosted Docker publish runner workflow change.
- Hardened the dashboard against CVE-2026-45323-style stored XSS by auditing untrusted MeshCore/MQTT render paths and escaping the remaining battery chart title HTML interpolation.
- Added regression coverage for untrusted dashboard metadata, MeshCore node fields, retained traffic talkers, and decoded battery sender/message fields.
- Updated non-major Python dependencies: FastAPI `0.136.3`, Uvicorn `0.49.0`, and HTTPX `0.28.1`.
- Added Docker image build validation on pull requests targeting `main` without pushing images or requiring Docker Hub secrets.
- Restored Docker image workflow runs on `dev` pushes while keeping the self-hosted Linux x64 runner configuration.

## v1.3.2 - 2026-05-08
- Reduced idle CPU work in the MQTT hot path.
- Skip the battery decode path entirely when `BATTERYINFO_ENABLED=false`.
- Skip websocket stats, traffic summary building, and broadcast queue work when no dashboard clients are connected.
- Enabled SQLite `WAL` mode with `NORMAL` sync and in-memory temp storage for the write-heavy packet database path.
- Added regression coverage for the disabled battery path and no-client websocket fast path.
- Documented the published Docker Hub image `yellowcooln/meshcore-mqtt-dashboard` and its GitHub Actions publish workflow.

## v1.3.1 - 2026-03-29
- Added an optional public `/batteryinfo` page for decoded channel telemetry charts and recent battery reports.
- Added `batteryinfo_events` SQLite persistence so battery telemetry is backfilled from retained packets and stays fast on reload.
- Added battery feature env controls for enable/disable, channel name, channel name visibility, channel key, and a separate battery retention window.
- Set battery info to default off in `.env.example` so fresh deploys do not expose the page unless configured.
- Switched the battery decoder dependency to the official `@michaelhart/meshcore-decoder` package.

## v1.3.0 - 2026-03-24
- Added a dedicated public `/traffic` page for retained packet analysis.
- Added retained traffic charts, top talkers, and burst bins backed by SQLite history.
- Persisted traffic history in `traffic_events` and rebuild it from `packets` when needed.
- Added payload-based role inference from `/status` and `/internal` metadata before name fallback.
- Ignored retained `*/internal` MQTT messages for node presence so startup replay does not create ghost online nodes.
- Added a startup console log that prints the running app version on launch.
- Added regression tests for retained `/internal` presence handling and payload-based role inference.

## v1.2.1 - 2026-03-13
- Simplified `docker-compose.yaml` to load container runtime vars from `.env` via `env_file`.
- Added `DASH_BROKER_HOST` so the dashboard can show a cleaner broker endpoint than the actual `MQTT_HOST`.
- Updated `DASH_BROKER_HOST` handling so values like `broker.example.net:443` are rendered exactly as provided.
- Updated docs for the broker display endpoint override.
- New env vars:
  - `DASH_BROKER_HOST`: optional broker endpoint shown in the UI only.

## v1.2.0 - 2026-03-03
- Added server-rendered share/embed metadata on `/` so previews use live config values.
- Wired `title`, `og:title`, and `twitter:title` to `DASH_TITLE`.
- Added optional favicon support via `DASH_LOGO_URL` (`.png`, `.jpg`, `.jpeg`).
- Added optional external header button controlled by env vars with URL validation.
- Added a pytest test suite (`tests/`) for API auth, index metadata/favicon rendering, and redaction behavior.
- Added GitHub Actions CI test workflow at `.github/workflows/tests.yml` for PRs and pushes.
- Updated docs to cover embeds, external link behavior, and manual verification steps.
- New env vars:
  - `DASH_LOGO_URL`: optional favicon URL/path (`.png`, `.jpg`, `.jpeg`).
  - `DASH_EXTERNAL_URL`: optional external header button URL (must be `http` or `https`).
  - `DASH_EXTERNAL_LABEL`: external header button label (default `External`).

## v1.1.0 - 2026-02-28
- Added endpoint token protection for `/snapshot`, `/stats`, and `/packets` using `DASH_API_TOKEN`.
- Kept the dashboard page (`/`) and websocket stream (`/ws`) publicly loadable for browser access.
- Added `SYS_TOPICS_ENABLED` to toggle `$SYS` subscription/processing and hide/show the `$SYS` panel in the UI.
- Added redaction of sensitive IP/MAC values from payload text/details before exposing data to UI/API.
- Preserved `client_version` dotted version strings (for example `1.0.8.0-e52c5ed`) while keeping IP/MAC redaction for sensitive fields.
- Added read-time redaction for packet history responses so older DB rows are also sanitized.
- New env vars:
  - `DASH_API_TOKEN`: token required for protected API routes when set.
  - `DASH_API_TOKEN_HEADER`: request header name for the API token (default `X-Dashboard-Token`).
  - `SYS_TOPICS_ENABLED`: enables/disables `$SYS` topic subscription and SYS panel data.

## v1 - 2026-02-21
- Baseline release at commit `bc88183` (`Merge pull request #1 from s3m1s0n1c/main`).
- Included multi-topic MQTT support from PR #1 and associated README updates.
