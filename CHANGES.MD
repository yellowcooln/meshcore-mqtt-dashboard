# Changes

## v1.1.1 - 2026-02-28
- Adjusted token scope so public dashboard viewing works without token.
- Kept token protection on direct API endpoints `/snapshot`, `/stats`, and `/packets`.
- Left websocket stream (`/ws`) open for public dashboard rendering.

## v1.1.0 - 2026-02-28
- Added endpoint token protection for `/snapshot`, `/stats`, `/packets`, and `/ws` using `DASH_API_TOKEN`.
- Kept the dashboard page (`/`) publicly loadable while data APIs and websocket require a token when configured.
- Added frontend token pass-through via `?token=...` for snapshot and websocket connections.
- Added `SYS_TOPICS_ENABLED` to toggle `$SYS` subscription/processing and hide/show the `$SYS` panel in the UI.
- Added redaction of sensitive IP/MAC values from payload text/details before exposing data to UI/API.
- Added read-time redaction for packet history responses so older DB rows are also sanitized.

## v1 - 2026-02-21
- Baseline release at commit `bc88183` (`Merge pull request #1 from s3m1s0n1c/main`).
- Included multi-topic MQTT support from PR #1 and associated README updates.
