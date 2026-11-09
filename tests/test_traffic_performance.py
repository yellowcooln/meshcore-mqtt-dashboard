"""Retained traffic must not rescan packet dictionaries on routine snapshots."""
from collections import deque

import pytest

import app as dashboard_app


@pytest.fixture(autouse=True)
def isolated_broadcast_queue(monkeypatch):
  # Each TestClient lifespan owns a different event loop.
  import asyncio
  monkeypatch.setattr(dashboard_app, "broadcast_queue", asyncio.Queue())


class CountedEvent(dict):
  reads = 0

  def get(self, *args):
    type(self).reads += 1
    return super().get(*args)

  def __iter__(self):
    type(self).reads += 1
    return super().__iter__()

  def __getitem__(self, key):
    type(self).reads += 1
    return super().__getitem__(key)

  def keys(self):
    type(self).reads += 1
    return super().keys()


def test_routine_traffic_does_not_read_retained_events(client, monkeypatch):
  monkeypatch.setattr(dashboard_app, "TRAFFIC_HISTORY_SECONDS", 7200)
  events = [CountedEvent(ts=10000 + i / 1000, route="flood", payload="trace",
                         node_id="a", name="Alpha", topic="mesh/a")
            for i in range(20000)]
  dashboard_app.traffic_events = deque(events)
  dashboard_app.traffic_packets_total = len(events)
  dashboard_app._build_traffic(10030)  # Cold restoration may build the index once.
  CountedEvent.reads = 0
  full = dashboard_app._build_traffic(10030)
  short = dashboard_app._build_traffic(10030, include_history=False)
  assert full["route_counts"]["flood"] == 20000
  assert full["top_talkers"][0]["packets"] == 20000
  assert "history" not in short
  assert short == {key: value for key, value in full.items() if key != "history"}
  assert CountedEvent.reads < 100, "routine snapshots scanned retained packet dictionaries"


@pytest.mark.parametrize("page", ["dashboard", "neighbors"])
def test_light_websocket_snapshot_skips_traffic(client, monkeypatch, page):
  def forbidden(*args, **kwargs):
    raise AssertionError("light page built traffic")
  monkeypatch.setattr(dashboard_app, "_build_traffic", forbidden)
  with client.websocket_connect(f"/ws?page={page}") as ws:
    snapshot = ws.receive_json()
    assert snapshot["type"] == "snapshot"
    assert "traffic" not in snapshot
    assert {"nodes", "stats", "neighbors", "broker", "sys_topics"} <= snapshot.keys()


@pytest.mark.parametrize("suffix", ["", "?page=traffic", "?page=unknown", "?page=batteryinfo"])
def test_legacy_websocket_keeps_traffic(client, suffix):
  with client.websocket_connect("/ws" + suffix) as ws:
    assert "history" in ws.receive_json()["traffic"]
  assert "history" in client.get("/snapshot").json()["traffic"]

# Frozen pre-index differential oracle; never used by the server.
LEGACY_BUILD_TRAFFIC = '''
def _build_traffic(now: float, include_history: bool = True) -> Dict[str, Any]:
  with state_lock:
    _prune_traffic_state(now)
    events = [dict(event) for event in traffic_events]
    packets_total = traffic_packets_total
    last_packet_at = last_traffic_packet_at

  summary_window_seconds = max(1, TRAFFIC_HISTORY_SECONDS)
  route_counts = _empty_traffic_counts(TRAFFIC_ROUTE_KEYS)
  payload_counts = _empty_traffic_counts(TRAFFIC_PAYLOAD_KEYS)
  packet_rate_count = 0

  for event in events:
    packet_rate_count += 1
    route_key = event.get("route", "other")
    payload_key = event.get("payload", "other")
    route_counts[route_key] = route_counts.get(route_key, 0) + 1
    payload_counts[payload_key] = payload_counts.get(payload_key, 0) + 1

  scale = 1.0 / summary_window_seconds

  traffic = {
    "window_seconds": summary_window_seconds,
    "history_seconds": TRAFFIC_HISTORY_SECONDS,
    "unique_packets_total": packets_total,
    "packets_per_second": round(packet_rate_count * scale, 2),
    "last_packet_at": last_packet_at,
    "route_counts": route_counts,
    "route_rates": {
      key: round(route_counts[key] * scale, 2)
      for key in TRAFFIC_ROUTE_KEYS
    },
    "payload_counts": payload_counts,
    "payload_rates": {
      key: round(payload_counts[key] * scale, 2)
      for key in TRAFFIC_PAYLOAD_KEYS
    },
  }

  history_seconds = max(1, TRAFFIC_HISTORY_SECONDS)
  bucket_seconds = max(1, math.ceil(history_seconds / TRAFFIC_CHART_BUCKETS))
  bucket_count = max(1, math.ceil(history_seconds / bucket_seconds))
  start_second = int(now) - history_seconds + 1
  bucket_start = (start_second // bucket_seconds) * bucket_seconds
  history = []
  history_by_second: Dict[int, Dict[str, Any]] = {}
  for index in range(bucket_count):
    ts_value = bucket_start + (index * bucket_seconds)
    bucket = {
      "ts": ts_value,
      "bucket_seconds": bucket_seconds,
      "total": 0,
      "route_counts": _empty_traffic_counts(TRAFFIC_ROUTE_KEYS),
      "payload_counts": _empty_traffic_counts(TRAFFIC_PAYLOAD_KEYS),
    }
    history.append(bucket)
    history_by_second[ts_value] = bucket

  for event in events:
    bucket_key = (int(event["ts"]) // bucket_seconds) * bucket_seconds
    bucket = history_by_second.get(bucket_key)
    if not bucket:
      continue
    bucket["total"] += 1
    route_key = event.get("route", "other")
    payload_key = event.get("payload", "other")
    bucket["route_counts"][route_key] = bucket["route_counts"].get(route_key, 0) + 1
    bucket["payload_counts"][payload_key] = bucket["payload_counts"].get(payload_key, 0) + 1

  traffic["top_talkers"] = _build_top_talkers(events, packets_total)
  traffic["bursts"] = _build_bursts(history)

  if not include_history:
    traffic["bucket_seconds"] = bucket_seconds
    return traffic

  traffic["bucket_seconds"] = bucket_seconds
  traffic["history"] = history
  return traffic'''

def legacy_traffic(now, include_history=True):
  namespace = dict(vars(dashboard_app))
  exec(LEGACY_BUILD_TRAFFIC, namespace)
  return namespace["_build_traffic"](now, include_history)


def test_index_matches_legacy_through_expiry_metadata_and_dedupe(client, monkeypatch):
  import random
  randomizer = random.Random(728)
  monkeypatch.setattr(dashboard_app, "TRAFFIC_HISTORY_SECONDS", 67)
  monkeypatch.setattr(dashboard_app, "TRAFFIC_CHART_BUCKETS", 9)
  for index in range(300):
    now = 1000 + index * 0.71
    event = {
      "ts": now, "dedupe_key": str(index % 80),
      "route": randomizer.choice(["flood", "direct", "other", "new-route"]),
      "payload": randomizer.choice(["trace", "advert", "other"]),
      "node_id": randomizer.choice(["a", "b", "c", None]),
      "name": randomizer.choice([None, "", "old", "new"]),
      "topic": randomizer.choice(["", "mesh/a", "mesh/b"]),
    }
    dashboard_app._record_traffic_event(event)
    for offset in (0, 0.001, 0.99):
      actual = dashboard_app._build_traffic(now + offset)
      assert actual == legacy_traffic(now + offset)
      assert dashboard_app._build_traffic(now + offset, False) == legacy_traffic(now + offset, False)
  for now in (1280, 1300, 1400):
    assert dashboard_app._build_traffic(now) == legacy_traffic(now)
  assert not dashboard_app.traffic_events
  assert not dashboard_app.traffic_events.talkers
  assert not dashboard_app.traffic_events.buckets
  assert not dashboard_app.traffic_identity_seen


def test_talker_ties_follow_first_retained_packet_not_first_ever(client, monkeypatch):
  monkeypatch.setattr(dashboard_app, "TRAFFIC_HISTORY_SECONDS", 10)
  for index, (ts, node, name, topic) in enumerate([
    (100, "a", "old", "old-topic"), (101, "b", None, ""),
    (102, "a", None, ""), (103, "a", "new", "new-topic"),
    (103, "b", "Bravo", "b-topic"),
  ]):
    dashboard_app._record_traffic_event(dict(ts=ts, node_id=node, name=name, topic=topic,
      route="flood", payload="trace", dedupe_key=str(index)))
  before = dashboard_app._build_traffic(110)
  assert before == legacy_traffic(110)
  assert before["top_talkers"][0]["name"] == "old"
  after = dashboard_app._build_traffic(110.001)
  assert after == legacy_traffic(110.001)
  assert [item["node_id"] for item in after["top_talkers"]] == ["b", "a"]
  assert after["top_talkers"][1]["name"] == "new"
  assert after["top_talkers"][1]["topic"] == "new-topic"
  assert before["top_talkers"][0]["name"] == "old"


def test_index_reset_and_external_deque_replacement(client, monkeypatch):
  monkeypatch.setattr(dashboard_app.time, "time", lambda: 1000)
  dashboard_app._append_loaded_traffic_event(999, "flood", "trace", "a", "a", "Alpha", "mesh/a")
  assert dashboard_app._build_traffic(1000) == legacy_traffic(1000)
  dashboard_app.traffic_events = deque()
  assert dashboard_app._build_traffic(1000)["top_talkers"] == []
  dashboard_app._reset_traffic_state()
  assert dashboard_app._build_traffic(1000)["unique_packets_total"] == 0
  dashboard_app._append_loaded_traffic_event(999, "direct", "advert", "b", "b", "Bravo", "mesh/b")
  monkeypatch.setattr(dashboard_app, "TRAFFIC_CHART_BUCKETS", 17)
  assert dashboard_app._build_traffic(1000) == legacy_traffic(1000)
  dashboard_app.traffic_events.clear()
  assert dashboard_app._build_traffic(1000)["route_counts"]["direct"] == 0


def test_restore_keeps_lifetime_totals_but_only_indexes_retained_rows(client, monkeypatch):
  monkeypatch.setattr(dashboard_app.time, "time", lambda: 1000)
  monkeypatch.setattr(dashboard_app, "TRAFFIC_HISTORY_SECONDS", 10)
  dashboard_app._reset_traffic_state()
  dashboard_app._append_loaded_traffic_event(980, "flood", "trace", "a", "a", "Old", "old")
  dashboard_app._append_loaded_traffic_event(990, "direct", "advert", "b", "b", "Bravo", "new")
  actual = dashboard_app._build_traffic(1000)
  assert actual == legacy_traffic(1000)
  assert actual["unique_packets_total"] == 2
  assert sum(actual["route_counts"].values()) == 1
  assert actual["top_talkers"][0]["share"] == 50
  assert dashboard_app._record_traffic_event(dict(ts=1000, dedupe_key="b")) is None
  assert dashboard_app._record_traffic_event(dict(ts=1000.001, dedupe_key="b")) is not None
  assert dashboard_app._build_traffic(1000.001) == legacy_traffic(1000.001)


def test_database_restore_rebuilds_index_and_does_not_accumulate(client, monkeypatch):
  import sqlite3
  database = sqlite3.connect(":memory:", check_same_thread=False)
  database.executescript("""
    CREATE TABLE packets (topic TEXT);
    CREATE TABLE traffic_events (
      ts REAL, dedupe_key TEXT, route_class TEXT, payload_class TEXT,
      node_id TEXT, name TEXT, topic TEXT
    );
  """)
  database.executemany("INSERT INTO traffic_events VALUES (?, ?, ?, ?, ?, ?, ?)", [
    (980, "old", "flood", "trace", "a", "Old", "old-topic"),
    (990, "boundary", "direct", "advert", "b", None, ""),
    (995, "recent", "flood", "trace", "b", "Bravo", "new-topic"),
  ])
  database.commit()
  monkeypatch.setattr(dashboard_app, "packet_db", database)
  monkeypatch.setattr(dashboard_app.time, "time", lambda: 1000)
  monkeypatch.setattr(dashboard_app, "TRAFFIC_HISTORY_SECONDS", 10)
  monkeypatch.setattr(dashboard_app, "PACKET_RETENTION_SECONDS", 100)
  try:
    for _ in range(2):
      dashboard_app._load_traffic_events()
      actual = dashboard_app._build_traffic(1000)
      assert actual == legacy_traffic(1000)
      assert actual["unique_packets_total"] == 3
      assert actual["route_counts"]["flood"] == 1
      assert actual["top_talkers"][0]["name"] == "Bravo"
      assert len(dashboard_app.traffic_events) == 2
      assert dashboard_app.traffic_identity_seen == {"boundary": 990, "recent": 995}
  finally:
    database.close()
