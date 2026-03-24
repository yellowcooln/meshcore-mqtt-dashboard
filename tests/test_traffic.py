import sqlite3

from fastapi.testclient import TestClient

import app as dashboard_app


def test_snapshot_includes_empty_traffic_state(client):
  response = client.get("/snapshot")
  assert response.status_code == 200
  traffic = response.json()["traffic"]
  assert traffic["packets_per_second"] == 0
  assert traffic["route_rates"]["flood"] == 0
  assert traffic["payload_rates"]["trace"] == 0
  assert traffic["window_seconds"] == dashboard_app.TRAFFIC_HISTORY_SECONDS
  assert traffic["history_seconds"] == dashboard_app.TRAFFIC_HISTORY_SECONDS
  assert traffic["bucket_seconds"] >= 1
  assert traffic["top_talkers"] == []
  assert traffic["bursts"] == []
  assert len(traffic["history"]) <= dashboard_app.TRAFFIC_CHART_BUCKETS


def test_extract_packet_event_classifies_route_and_payload():
  payload_info = {
    "json": {
      "packet_type": "8",
      "route": "F",
      "hash": "ABC123",
      "raw": "2100deadbeef",
    },
    "text": "",
  }

  event = dashboard_app._extract_packet_event("meshcore/BOS/node/packets", payload_info)

  assert event is not None
  assert event["route"] == "flood"
  assert event["payload"] == "trace"


def test_record_traffic_event_dedupes_by_hash_and_updates_rates():
  first_event = {
    "ts": 100.0,
    "route": "flood",
    "payload": "trace",
    "dedupe_key": "same-hash",
    "node_id": "node-a",
    "name": "Alpha",
    "topic": "meshcore/BOS/node-a/packets",
  }
  duplicate_event = {
    "ts": 101.0,
    "route": "flood",
    "payload": "trace",
    "dedupe_key": "same-hash",
    "node_id": "node-a",
    "name": "Alpha",
    "topic": "meshcore/BOS/node-a/packets",
  }
  second_event = {
    "ts": 110.0,
    "route": "direct",
    "payload": "advert",
    "dedupe_key": "other-hash",
    "node_id": "node-b",
    "name": "Bravo",
    "topic": "meshcore/BOS/node-b/packets",
  }

  assert dashboard_app._record_traffic_event(first_event) is not None
  assert dashboard_app._record_traffic_event(duplicate_event) is None
  assert dashboard_app._record_traffic_event(second_event) is not None

  traffic = dashboard_app._build_traffic(120.0)

  assert traffic["unique_packets_total"] == 2
  assert traffic["route_counts"]["flood"] == 1
  assert traffic["route_counts"]["direct"] == 1
  assert traffic["payload_counts"]["trace"] == 1
  assert traffic["payload_counts"]["advert"] == 1
  assert traffic["packets_per_second"] == round(2 / dashboard_app.TRAFFIC_HISTORY_SECONDS, 2)
  assert traffic["top_talkers"][0]["node_id"] == "node-b"
  assert len(traffic["bursts"]) >= 1


def test_build_traffic_aggregates_history_to_retention_window(monkeypatch):
  monkeypatch.setattr(dashboard_app, "TRAFFIC_HISTORY_SECONDS", 7200)
  monkeypatch.setattr(dashboard_app, "TRAFFIC_CHART_BUCKETS", 240)
  dashboard_app._reset_traffic_state()

  assert dashboard_app._record_traffic_event(
    {"ts": 1000.0, "route": "flood", "payload": "trace", "dedupe_key": "a"}
  )
  assert dashboard_app._record_traffic_event(
    {"ts": 1030.0, "route": "direct", "payload": "advert", "dedupe_key": "b"}
  )

  traffic = dashboard_app._build_traffic(1100.0)

  assert traffic["history_seconds"] == 7200
  assert traffic["bucket_seconds"] == 30
  assert len(traffic["history"]) == 240
  dashboard_app._reset_traffic_state()


def test_load_traffic_events_restores_saved_rows(monkeypatch, tmp_path):
  db_path = tmp_path / "traffic.db"
  original_path = dashboard_app.PACKET_DB_PATH
  original_db = dashboard_app.packet_db

  try:
    dashboard_app.packet_db = None
    dashboard_app.PACKET_DB_PATH = str(db_path)
    dashboard_app._init_packet_db()

    with dashboard_app.packet_db_lock:
      dashboard_app.packet_db.executemany(
        """
        INSERT INTO traffic_events (ts, dedupe_key, route_class, payload_class)
        VALUES (?, ?, ?, ?)
        """,
        [
          (100.0, "hash-1", "flood", "trace"),
          (110.0, "hash-2", "direct", "advert"),
        ],
      )
      dashboard_app.packet_db.commit()

    monkeypatch.setattr(dashboard_app.time, "time", lambda: 120.0)
    dashboard_app._load_traffic_events()

    traffic = dashboard_app._build_traffic(120.0)
    assert traffic["unique_packets_total"] == 2
    assert traffic["route_counts"]["flood"] == 1
    assert traffic["route_counts"]["direct"] == 1
    assert traffic["payload_counts"]["trace"] == 1
    assert traffic["payload_counts"]["advert"] == 1
  finally:
    dashboard_app._reset_traffic_state()
    dashboard_app._close_packet_db()
    dashboard_app.packet_db = original_db
    dashboard_app.PACKET_DB_PATH = original_path


def test_load_traffic_events_backfills_from_packets(monkeypatch, tmp_path):
  db_path = tmp_path / "traffic-backfill.db"
  original_path = dashboard_app.PACKET_DB_PATH
  original_db = dashboard_app.packet_db

  packet_json = (
    '{"packet_type":"8","route":"F","hash":"same-hash","raw":"2100deadbeef"}'
  )
  other_json = (
    '{"packet_type":"4","route":"D","hash":"other-hash","raw":"0400feedface"}'
  )

  try:
    dashboard_app.packet_db = None
    dashboard_app.PACKET_DB_PATH = str(db_path)
    dashboard_app._init_packet_db()

    with dashboard_app.packet_db_lock:
      dashboard_app.packet_db.executemany(
        """
        INSERT INTO packets (ts, topic, node_id, name, role, payload_text, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
          (100.0, "meshcore/BOS/node-a/packets", "node-a", None, None, packet_json, packet_json),
          (101.0, "meshcore/BOS/node-b/packets", "node-b", None, None, packet_json, packet_json),
          (110.0, "meshcore/BOS/node-c/packets", "node-c", None, None, other_json, other_json),
        ],
      )
      dashboard_app.packet_db.commit()

    monkeypatch.setattr(dashboard_app.time, "time", lambda: 120.0)
    dashboard_app._load_traffic_events()

    traffic = dashboard_app._build_traffic(120.0)
    assert traffic["unique_packets_total"] == 2
    assert traffic["route_counts"]["flood"] == 1
    assert traffic["route_counts"]["direct"] == 1
    assert traffic["payload_counts"]["trace"] == 1
    assert traffic["payload_counts"]["advert"] == 1

    with dashboard_app.packet_db_lock:
      count = dashboard_app.packet_db.execute(
        "SELECT COUNT(*) FROM traffic_events"
      ).fetchone()[0]
    assert count == 2
  finally:
    dashboard_app._reset_traffic_state()
    dashboard_app._close_packet_db()
    dashboard_app.packet_db = original_db
    dashboard_app.PACKET_DB_PATH = original_path


def test_public_traffic_packets_endpoint_returns_deduped_redacted_rows(monkeypatch, tmp_path):
  db_path = tmp_path / "traffic-public.db"
  original_path = dashboard_app.PACKET_DB_PATH
  original_db = dashboard_app.packet_db

  packet_json = (
    '{"packet_type":"8","route":"F","hash":"same-hash","raw":"2100deadbeef","ip":"192.168.1.50"}'
  )
  other_json = (
    '{"packet_type":"4","route":"D","hash":"other-hash","raw":"0400feedface"}'
  )

  try:
    monkeypatch.setattr(dashboard_app, "start_mqtt", lambda: None)
    monkeypatch.setattr(dashboard_app, "stop_mqtt", lambda: None)
    dashboard_app.DASH_API_TOKEN = ""
    dashboard_app.packet_db = None
    dashboard_app.PACKET_DB_PATH = str(db_path)
    dashboard_app._init_packet_db()
    with dashboard_app.packet_db_lock:
      dashboard_app.packet_db.executemany(
        """
        INSERT INTO packets (ts, topic, node_id, name, role, payload_text, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
          (100.0, "meshcore/BOS/node-a/packets", "node-a", "Alpha", None, packet_json, packet_json),
          (101.0, "meshcore/BOS/node-a/packets", "node-a", "Alpha", None, packet_json, packet_json),
          (102.0, "meshcore/BOS/node-b/packets", "node-b", "Bravo", None, other_json, other_json),
        ],
      )
      dashboard_app.packet_db.commit()

    with TestClient(dashboard_app.app) as client:
      response = client.get("/traffic/packets?start=99&end=103&limit=10")
      assert response.status_code == 200
      payload = response.json()
    assert payload["enabled"] is True
    assert len(payload["packets"]) == 2
    assert payload["packets"][0]["route"] in ("flood", "direct")
    assert "[redacted" in payload["packets"][1]["payload_json"] or "[redacted" in payload["packets"][0]["payload_json"]
  finally:
    dashboard_app._reset_traffic_state()
    dashboard_app._close_packet_db()
    dashboard_app.packet_db = original_db
    dashboard_app.PACKET_DB_PATH = original_path
