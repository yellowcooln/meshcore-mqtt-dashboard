# Changes

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
