import json
import re
import sqlite3
import subprocess
from types import SimpleNamespace

import app as dashboard_app


OBSERVER_ID = "a1" * 32
NEIGHBOR_ID = "b2" * 32
SECOND_NEIGHBOR_ID = "c3" * 32


def _neighbors_payload():
  return {
    "timestamp": "2026-08-07T12:00:00.000000+00:00",
    "origin": "North Observer",
    "origin_id": OBSERVER_ID.upper(),
    "self": {"scopes": "Europe, UK"},
    "neighbors": [
      {
        "pubkey": NEIGHBOR_ID.upper(),
        "snr": 8.5,
        "heard_secs_ago": 120,
        "scopes": "*, Europe",
        "status": "responded",
      },
      {
        "pubkey": SECOND_NEIGHBOR_ID,
        "snr": -3.25,
        "heard_secs_ago": 45,
        "scopes": "UK",
        "status": "timeout",
      },
    ],
  }


def test_normalize_neighbors_snapshot_uses_verified_mqtt_contract():
  snapshot = dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    _neighbors_payload(),
    2_000.0,
  )

  assert snapshot == {
    "observer_id": OBSERVER_ID,
    "origin": "North Observer",
    "topic": f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    "source_timestamp": "2026-08-07T12:00:00.000000+00:00",
    "reported_at": 2_000.0,
    "received_at": 2_000.0,
    "scopes": ["Europe", "UK"],
    "neighbors": [
      {
        "pubkey": NEIGHBOR_ID,
        "snr": 8.5,
        "heard_secs_ago": 120,
        "heard_at": 1_880.0,
        "scopes": ["*", "Europe"],
        "status": "responded",
      },
      {
        "pubkey": SECOND_NEIGHBOR_ID,
        "snr": -3.25,
        "heard_secs_ago": 45,
        "heard_at": 1_955.0,
        "scopes": ["UK"],
        "status": "timeout",
      },
    ],
  }


def test_normalize_neighbors_snapshot_rejects_wrong_topic_and_invalid_observer():
  assert dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/status",
    _neighbors_payload(),
    2_000.0,
  ) is None

  payload = _neighbors_payload()
  payload["origin_id"] = "not-a-public-key"
  assert dashboard_app._normalize_neighbors_snapshot(
    "meshcore/BOS/not-a-public-key/neighbors",
    payload,
    2_000.0,
  ) is None

  assert dashboard_app._normalize_neighbors_snapshot(
    f"prefix/meshcore/BOS/{OBSERVER_ID}/neighbors",
    _neighbors_payload(),
    2_000.0,
  ) is None


def test_normalize_neighbors_snapshot_rejects_topic_payload_identity_mismatch():
  payload = _neighbors_payload()
  payload["origin_id"] = "d4" * 32

  assert dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    payload,
    2_000.0,
  ) is None


def test_normalize_neighbors_snapshot_anchors_age_to_source_timestamp(monkeypatch):
  payload = _neighbors_payload()
  payload["timestamp"] = "2026-01-01T00:00:00+00:00"
  received_at = 1_767_225_900.0

  snapshot = dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    payload,
    received_at,
  )

  assert snapshot["reported_at"] == 1_767_225_600.0
  assert snapshot["received_at"] == received_at
  assert snapshot["neighbors"][0]["heard_at"] == 1_767_225_480.0

  previous_snapshots = dashboard_app.neighbor_snapshots
  try:
    dashboard_app.neighbor_snapshots = {OBSERVER_ID: snapshot}
    monkeypatch.setattr(dashboard_app.time, "time", lambda: received_at)
    topology = dashboard_app._build_neighbors_topology()
    assert topology["stats"]["last_update"] == 1_767_225_600.0
    assert topology["observers"][0]["reported_at"] == 1_767_225_600.0
    assert topology["links"][0]["reported_at"] == 1_767_225_600.0
  finally:
    dashboard_app.neighbor_snapshots = previous_snapshots


def test_normalize_neighbors_snapshot_drops_invalid_and_duplicate_entries():
  payload = _neighbors_payload()
  payload["neighbors"] = [
    payload["neighbors"][0],
    {**payload["neighbors"][0], "snr": 1},
    {"pubkey": "broken", "snr": 4, "heard_secs_ago": 2},
    {"pubkey": OBSERVER_ID, "snr": 12, "heard_secs_ago": 1},
  ]

  snapshot = dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    payload,
    2_000.0,
  )

  assert [entry["pubkey"] for entry in snapshot["neighbors"]] == [NEIGHBOR_ID]


def test_mqtt_neighbors_message_updates_topology_and_api(client, monkeypatch):
  dashboard_app.neighbor_snapshots = {}
  monkeypatch.setattr(dashboard_app.time, "time", lambda: 2_000.0)
  msg = SimpleNamespace(
    topic=f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    payload=json.dumps(_neighbors_payload()).encode(),
    retain=True,
  )

  dashboard_app.mqtt_on_message(None, None, msg)
  response = client.get("/neighbors/data")

  assert response.status_code == 200
  topology = response.json()
  assert topology["stats"] == {
    "observers": 1,
    "devices": 3,
    "links": 2,
    "responded": 1,
    "unresolved": 1,
    "last_update": 2_000.0,
  }
  assert topology["observers"][0]["observer_id"] == OBSERVER_ID
  assert topology["links"][0]["observer_id"] == OBSERVER_ID
  assert {link["neighbor_id"] for link in topology["links"]} == {
    NEIGHBOR_ID,
    SECOND_NEIGHBOR_ID,
  }


def test_retained_neighbors_tombstone_removes_memory_and_persistence(client):
  previous_db = dashboard_app.packet_db
  previous_snapshots = dashboard_app.neighbor_snapshots
  try:
    dashboard_app.packet_db = sqlite3.connect(":memory:", check_same_thread=False)
    dashboard_app.neighbor_snapshots = {}
    dashboard_app._ensure_neighbor_snapshots_table()
    snapshot = dashboard_app._normalize_neighbors_snapshot(
      f"meshcore/BOS/{OBSERVER_ID}/neighbors",
      _neighbors_payload(),
      2_000.0,
    )
    dashboard_app._store_neighbor_snapshot(snapshot)

    dashboard_app.mqtt_on_message(
      None,
      None,
      SimpleNamespace(
        topic=f"meshcore/BOS/{OBSERVER_ID}/neighbors",
        payload=b"",
        retain=True,
      ),
    )

    assert client.get("/neighbors/data").json()["stats"]["observers"] == 0
    row_count = dashboard_app.packet_db.execute(
      "SELECT COUNT(*) FROM neighbor_snapshots"
    ).fetchone()[0]
    assert row_count == 0
  finally:
    if dashboard_app.packet_db is not None and dashboard_app.packet_db is not previous_db:
      dashboard_app.packet_db.close()
    dashboard_app.packet_db = previous_db
    dashboard_app.neighbor_snapshots = previous_snapshots


def test_neighbor_snapshots_persist_and_reload():
  previous_db = dashboard_app.packet_db
  previous_snapshots = dashboard_app.neighbor_snapshots
  try:
    dashboard_app.packet_db = sqlite3.connect(":memory:", check_same_thread=False)
    dashboard_app.neighbor_snapshots = {}
    dashboard_app._ensure_neighbor_snapshots_table()
    snapshot = dashboard_app._normalize_neighbors_snapshot(
      f"meshcore/BOS/{OBSERVER_ID}/neighbors",
      _neighbors_payload(),
      2_000.0,
    )

    dashboard_app._store_neighbor_snapshot(snapshot)
    dashboard_app.neighbor_snapshots = {}
    dashboard_app._load_neighbor_snapshots()

    assert dashboard_app.neighbor_snapshots[OBSERVER_ID] == snapshot
  finally:
    if dashboard_app.packet_db is not None and dashboard_app.packet_db is not previous_db:
      dashboard_app.packet_db.close()
    dashboard_app.packet_db = previous_db
    dashboard_app.neighbor_snapshots = previous_snapshots


def test_neighbor_persistence_stays_enabled_when_packet_history_is_disabled(tmp_path, monkeypatch):
  previous_db = dashboard_app.packet_db
  previous_snapshots = dashboard_app.neighbor_snapshots
  try:
    dashboard_app.packet_db = None
    dashboard_app.neighbor_snapshots = {}
    monkeypatch.setattr(dashboard_app, "PACKET_DB_PATH", str(tmp_path / "neighbors.db"))
    monkeypatch.setattr(dashboard_app, "PACKET_RETENTION_SECONDS", 0)

    dashboard_app._init_packet_db()
    snapshot = dashboard_app._normalize_neighbors_snapshot(
      f"meshcore/BOS/{OBSERVER_ID}/neighbors",
      _neighbors_payload(),
      2_000.0,
    )
    dashboard_app._store_neighbor_snapshot(snapshot)
    dashboard_app.neighbor_snapshots = {}
    dashboard_app._load_neighbor_snapshots()

    assert dashboard_app.neighbor_snapshots[OBSERVER_ID] == snapshot
    assert dashboard_app._fetch_packets(10, None) == {"enabled": False, "packets": []}
  finally:
    if dashboard_app.packet_db is not None and dashboard_app.packet_db is not previous_db:
      dashboard_app.packet_db.close()
    dashboard_app.packet_db = previous_db
    dashboard_app.neighbor_snapshots = previous_snapshots


def test_store_neighbor_snapshot_does_not_replace_newer_report():
  newer = dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    _neighbors_payload(),
    2_000.0,
  )
  older = dashboard_app._normalize_neighbors_snapshot(
    f"meshcore/BOS/{OBSERVER_ID}/neighbors",
    _neighbors_payload(),
    1_000.0,
  )
  previous_snapshots = dashboard_app.neighbor_snapshots
  previous_db = dashboard_app.packet_db
  try:
    dashboard_app.packet_db = None
    dashboard_app.neighbor_snapshots = {}
    assert dashboard_app._store_neighbor_snapshot(newer) is True
    assert dashboard_app._store_neighbor_snapshot(older) is False
    assert dashboard_app.neighbor_snapshots[OBSERVER_ID]["reported_at"] == 2_000.0
  finally:
    dashboard_app.packet_db = previous_db
    dashboard_app.neighbor_snapshots = previous_snapshots


def test_observer_device_keeps_inbound_link_count(client):
  second_payload = _neighbors_payload()
  second_payload["origin"] = "South Observer"
  second_payload["origin_id"] = NEIGHBOR_ID
  second_payload["neighbors"] = []
  dashboard_app.neighbor_snapshots = {
    OBSERVER_ID: dashboard_app._normalize_neighbors_snapshot(
      f"meshcore/BOS/{OBSERVER_ID}/neighbors",
      _neighbors_payload(),
      2_000.0,
    ),
    NEIGHBOR_ID: dashboard_app._normalize_neighbors_snapshot(
      f"meshcore/BOS/{NEIGHBOR_ID}/neighbors",
      second_payload,
      2_001.0,
    ),
  }

  topology = client.get("/neighbors/data").json()
  device = next(item for item in topology["devices"] if item["device_id"] == NEIGHBOR_ID)

  assert device["kind"] == "observer"
  assert device["observer_count"] == 1


def test_zero_neighbor_observer_remains_in_topology(client):
  payload = _neighbors_payload()
  payload["neighbors"] = []
  dashboard_app.neighbor_snapshots = {
    OBSERVER_ID: dashboard_app._normalize_neighbors_snapshot(
      f"meshcore/BOS/{OBSERVER_ID}/neighbors",
      payload,
      2_000.0,
    ),
  }

  topology = client.get("/neighbors/data").json()

  assert topology["stats"]["observers"] == 1
  assert topology["stats"]["devices"] == 1
  assert topology["stats"]["links"] == 0


def test_neighbors_page_exposes_graph_table_filter_and_detail(client):
  response = client.get("/neighbors")

  assert response.status_code == 200
  assert 'id="topology-graph"' in response.text
  assert 'id="topology-filter"' in response.text
  assert 'id="neighbor-table"' in response.text
  assert 'id="topology-detail"' in response.text
  assert ".graph-empty[hidden]" in response.text
  assert "Observers have reported no current neighbor links." in response.text
  assert "function connectWebSocket()" in response.text
  assert 'href="/neighbors"' in client.get("/").text


def test_graph_layout_keeps_unrelated_nodes_away_from_edges(client):
  html = client.get("/neighbors").text
  geometry = re.search(
    r"// layout-geometry:start\n(.*?)// layout-geometry:end",
    html,
    re.DOTALL,
  )
  assert geometry, "neighbors page must expose its pure layout geometry for regression testing"

  script = geometry.group(1) + """
const links = [
  { observer_id: "6f", neighbor_id: "26" },
  { observer_id: "97", neighbor_id: "24" },
  { observer_id: "97", neighbor_id: "2b" },
];
const deviceIds = ["24", "26", "2b", "6f", "97"];
const positions = calculatePositions(deviceIds, new Set(["6f", "97"]));
separateNodesFromEdges(deviceIds, positions, links);
for (const link of links) {
  const start = positions.get(link.observer_id);
  const end = positions.get(link.neighbor_id);
  for (const deviceId of deviceIds) {
    if (deviceId === link.observer_id || deviceId === link.neighbor_id) continue;
    const distance = distanceToSegment(positions.get(deviceId), start, end);
    if (distance < 76) {
      throw new Error(`${deviceId} is only ${distance}px from ${link.observer_id}->${link.neighbor_id}`);
    }
  }
}
"""
  subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
