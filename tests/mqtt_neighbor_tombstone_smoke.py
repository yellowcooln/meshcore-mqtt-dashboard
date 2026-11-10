"""Standalone real-wire regression for issue #16 (no pytest required).

Run INSIDE the disposable candidate app's isolated network namespace, where
Mosquitto is at 127.0.0.1:1883 and Uvicorn is at 127.0.0.1:8081:

  python /tests/mqtt_neighbor_tombstone_smoke.py seed-delete --isolated
  # Restart ONLY the disposable app, preserving its scratch /data and broker.
  python /tests/mqtt_neighbor_tombstone_smoke.py after-restart --isolated

Requires installed production paho-mqtt and websockets; uses stdlib HTTP/SQLite.
--isolated acknowledges a dedicated, credential-free, no-egress test namespace;
loopback alone cannot prove isolation. Never run against production. Ports are
configurable, hosts are deliberately not. /data/packets.db must be the candidate
app's dedicated scratch DB. Start with empty neighbor state and run both phases
promptly, before packet retention expires. Fixed synthetic IDs allow restart
verification without a sidecar state file. Only seed-delete publishes; it leaves
B retained intentionally. No fixtures are sent to RF or external services.

Stdout is JSON Lines (including wire metadata BEFORE deletion assertions).
A failed assertion emits a JSON error and exits nonzero. This script neither
starts/restarts services nor imports app internals; parent orchestration owns
container isolation, restart and evidence capture.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import queue
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request


A = "11" * 32
B = "22" * 32
NEIGHBOR_A = "33" * 32
NEIGHBOR_B = "44" * 32
TOPIC_A = f"meshcore/VERIFY/{A}/neighbors"
TOPIC_B = f"meshcore/VERIFY/{B}/neighbors"
STATUS_TOPIC = f"meshcore/VERIFY/{B}/status"
STATUS_MARKER = "isolated-tombstone-normal-status"


def emit(event, **data):
  print(json.dumps({"event": event, **data}, sort_keys=True), flush=True)


def require(condition, message):
  if not condition:
    raise AssertionError(message)


def poll(label, operation, timeout):
  deadline = time.monotonic() + timeout
  last = None
  while True:
    try:
      last = operation()
      if last:
        return last
    except (OSError, urllib.error.URLError, sqlite3.OperationalError) as error:
      last = str(error)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
      raise AssertionError(f"Timed out waiting for {label}; last result: {last!r}")
    threading.Event().wait(min(0.1, remaining))


def http(args, path):
  # Ignore proxy environment variables: all test traffic must remain loopback.
  opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
  with opener.open(f"http://127.0.0.1:{args.http_port}{path}",
                   timeout=min(args.timeout, 3)) as response:
    return json.load(response)


def observer_ids(topology):
  return {item["observer_id"] for item in topology["observers"]}


def topology_is(topology, expected):
  if observer_ids(topology) != set(expected):
    return False
  expected_links = {(key, NEIGHBOR_A if key == A else NEIGHBOR_B)
                    for key in expected}
  actual_links = {(item["observer_id"], item["neighbor_id"])
                  for item in topology["links"]}
  return actual_links == expected_links


def database(args):
  # Live WAL database: read-only, NOT immutable (must observe uncheckpointed WAL).
  with sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro",
                       uri=True, timeout=min(args.timeout, 2)) as connection:
    observers = [row[0] for row in connection.execute(
      "SELECT observer_id FROM neighbor_snapshots ORDER BY observer_id")]
    empty_packets = connection.execute(
      "SELECT COUNT(*) FROM packets WHERE topic = ? "
      "AND COALESCE(payload_text, '') = ''", (TOPIC_A,)).fetchone()[0]
    status_packets = connection.execute(
      "SELECT COUNT(*) FROM packets WHERE topic = ? AND node_id = ? "
      "AND payload_text LIKE ?",
      (STATUS_TOPIC, B, f"%{STATUS_MARKER}%")).fetchone()[0]
  return {"observers": observers, "empty_tombstone_packets": empty_packets,
          "normal_status_packets": status_packets}


def check_database(args, normal_status=False):
  result = database(args)
  require(set(result["observers"]) == {B},
          f"SQLite must contain B only, not A: {result}")
  require(result["empty_tombstone_packets"] == 0,
          f"Empty neighbor tombstone leaked into packets: {result}")
  if normal_status:
    require(result["normal_status_packets"] >= 1,
            f"Normal status packet missing from SQLite: {result}")
  return result


def ws_wait(ws, args, label, predicate):
  deadline = time.monotonic() + args.timeout
  seen = []
  while time.monotonic() < deadline:
    try:
      message = json.loads(ws.recv(timeout=max(0.001, deadline - time.monotonic())))
    except TimeoutError:
      break
    seen.append(message.get("type"))
    if predicate(message):
      return message
  raise AssertionError(f"Timed out waiting for WebSocket {label}; event types: {seen[-20:]}")


class MQTTProbe:
  def __init__(self, args):
    import paho.mqtt.client as mqtt
    self.args = args
    self.messages = queue.Queue()
    self.connected = threading.Event()
    self.subscribed = threading.Event()
    self.errors = []
    self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              protocol=mqtt.MQTTv311)
    self.client.on_connect = self.on_connect
    self.client.on_subscribe = self.on_subscribe
    self.client.on_message = self.on_message
    self.client.connect_timeout = min(args.timeout, 5)

  def on_connect(self, client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
      self.errors.append(f"CONNACK: {reason_code}")
    self.connected.set()

  def on_subscribe(self, client, userdata, mid, reason_codes, properties):
    if any(code.is_failure for code in reason_codes):
      self.errors.append(f"SUBACK: {reason_codes}")
    self.subscribed.set()

  def on_message(self, client, userdata, message):
    self.messages.put({"topic": message.topic, "payload": bytes(message.payload),
                       "retain": bool(message.retain), "qos": message.qos})

  def wait_event(self, event, label):
    require(event.wait(self.args.timeout), f"Timed out waiting for MQTT {label}")
    require(not self.errors, f"MQTT callback errors: {self.errors}")

  def __enter__(self):
    try:
      self.client.connect("127.0.0.1", self.args.mqtt_port, keepalive=15)
      self.client.loop_start()
      self.wait_event(self.connected, "CONNACK")
      code, _ = self.client.subscribe([(TOPIC_A, 1), (TOPIC_B, 1)])
      require(code == 0, f"MQTT subscribe returned {code}")
      self.wait_event(self.subscribed, "SUBACK")
      return self
    except BaseException:
      self.__exit__(None, None, None)
      raise

  def __exit__(self, *unused):
    try:
      self.client.disconnect()
    finally:
      self.client.loop_stop()

  def publish(self, topic, payload, retain=False):
    info = self.client.publish(topic, payload, qos=1, retain=retain)
    require(info.rc == 0, f"MQTT publish failed for {topic}: {info.rc}")
    info.wait_for_publish(timeout=self.args.timeout)
    require(info.is_published(), f"Timed out waiting for PUBACK: {topic}")

  def empty_delivery(self):
    deadline = time.monotonic() + self.args.timeout
    while time.monotonic() < deadline:
      try:
        message = self.messages.get(timeout=max(0.001, deadline - time.monotonic()))
      except queue.Empty:
        break
      if message["topic"] == TOPIC_A and message["payload"] == b"":
        metadata = {key: value for key, value in message.items() if key != "payload"}
        emit("tombstone_wire_delivery", payload_bytes=0, **metadata)
        require(message["retain"] is False,
                "Expected retain=False on a live MQTTv311 subscription delivery")
        return
    raise AssertionError("Observer did not receive the zero-length tombstone on topic A")


def fixture(observer, neighbor, name):
  return json.dumps({"origin_id": observer, "origin": name,
                     "timestamp": datetime.now(timezone.utc).isoformat(),
                     "self": {"scopes": "test"},
                     "neighbors": [{"pubkey": neighbor, "snr": 9.5,
                                    "heard_secs_ago": 2, "status": "responded",
                                    "scopes": "test"}]})


def retained_replay(args):
  # A genuinely fresh connection/subscription; existing subscription deliveries
  # cannot establish what Mosquitto retained. Keep observing after B arrives to
  # catch an erroneous A replay, rather than returning on the first message.
  with MQTTProbe(args) as fresh:
    received = []
    deadline = time.monotonic() + args.replay_wait
    while time.monotonic() < deadline:
      try:
        item = fresh.messages.get(timeout=max(0.001, deadline - time.monotonic()))
      except queue.Empty:
        break
      received.append(item)
    require(received, "Fresh subscriber received no retained B snapshot")
    require(all(item["topic"] == TOPIC_B and item["retain"] and item["payload"]
                for item in received),
            "Fresh subscriber replay must contain retained B only (no A)")
    for item in received:
      payload = json.loads(item["payload"])
      require(payload["origin_id"] == B and payload["neighbors"][0]["pubkey"] == NEIGHBOR_B,
              "Retained B fixture content differs")
    emit("retained_replay", topics=[item["topic"] for item in received],
         observation_seconds=args.replay_wait, deleted_topic_absent=True)


@contextmanager
def websocket(args):
  from websockets.sync.client import connect
  # Explicitly disable environment proxies, including for websocket connections.
  with connect(f"ws://127.0.0.1:{args.http_port}/ws?page=neighbors",
               open_timeout=args.timeout, close_timeout=2, proxy=None) as ws:
    initial = ws_wait(ws, args, "initial snapshot", lambda m: m.get("type") == "snapshot")
    yield ws, initial


def seed_delete(args):
  require(topology_is(http(args, "/neighbors/data"), set()),
          "seed-delete requires empty neighbor topology in a dedicated scratch app")
  with MQTTProbe(args) as probe, websocket(args) as (ws, initial):
    require(topology_is(initial["neighbors"], set()), "Initial WS topology must be empty")
    probe.publish(TOPIC_A, fixture(A, NEIGHBOR_A, "Fixture A"), retain=True)
    probe.publish(TOPIC_B, fixture(B, NEIGHBOR_B, "Fixture B"), retain=True)
    ws_wait(ws, args, "neighbors_update containing both seeded observers",
            lambda m: m.get("type") == "neighbors_update" and
            topology_is(m["neighbors"], {A, B}))
    require(topology_is(http(args, "/neighbors/data"), {A, B}), "Seed API topology mismatch")
    require(set(database(args)["observers"]) == {A, B}, "Seed rows missing from SQLite")
    emit("seeded", observers=[A, B])

    probe.publish(TOPIC_A, b"", retain=True)
    # Emit actual MQTT delivery metadata first: old images fail AFTER this proof.
    probe.empty_delivery()
    ws_wait(ws, args, "neighbors_update removing A and preserving B",
            lambda m: m.get("type") == "neighbors_update" and
            topology_is(m["neighbors"], {B}))
    require(topology_is(http(args, "/neighbors/data"), {B}), "Deletion API topology mismatch")
    emit("deleted", database=check_database(args))

    probe.publish(TOPIC_A, b"", retain=True)
    probe.empty_delivery()
    # Same publisher and QoS1 order give an application-processing barrier:
    # receipt of normal status follows repeated deletion, which need not emit WS.
    status = json.dumps({"device_id": B, "name": "Fixture B", "status": "online",
                         "verification": STATUS_MARKER})
    probe.publish(STATUS_TOPIC, status)
    ws_wait(ws, args, "normal status node_update after repeated deletion",
            lambda m: m.get("type") == "node_update" and
            m.get("node", {}).get("node_id") == B and
            m["node"].get("last_topic") == STATUS_TOPIC)
    require(topology_is(http(args, "/neighbors/data"), {B}),
            "Repeated deletion removed B or resurrected A")
    # Packet persistence is synchronous before node_update in the actual app.
    emit("repeated_delete_and_normal_ingest", database=check_database(args, normal_status=True))
  retained_replay(args)


def after_restart(args):
  require(topology_is(http(args, "/neighbors/data"), {B}),
          "Restart API topology must contain only B and its distinct neighbor")
  with websocket(args) as (ws, initial):
    require(topology_is(initial["neighbors"], {B}),
            "Restart WebSocket initial snapshot resurrected A or lost B")
  emit("restart_verified", database=check_database(args, normal_status=True))
  retained_replay(args)


def main():
  parser = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("mode", choices=("seed-delete", "after-restart"))
  parser.add_argument("--isolated", action="store_true", required=True,
                      help="acknowledge dedicated loopback-only scratch broker/app")
  parser.add_argument("--http-port", type=int, default=8081)
  parser.add_argument("--mqtt-port", type=int, default=1883)
  parser.add_argument("--db", default="/data/packets.db")
  parser.add_argument("--timeout", type=float, default=15)
  parser.add_argument("--replay-wait", type=float, default=2,
                      help="bounded observation window for retained replay (seconds)")
  args = parser.parse_args()
  require(0 < args.timeout <= 120 and 0 < args.replay_wait <= 30,
          "timeout must be in (0,120], replay-wait in (0,30]")
  require(all(0 < port < 65536 for port in (args.http_port, args.mqtt_port)),
          "Ports must be in 1..65535")
  poll("HTTP /snapshot broker.connected", lambda: http(args, "/snapshot").get(
    "broker", {}).get("connected") is True, args.timeout)
  emit("ready", mode=args.mode, http_port=args.http_port, mqtt_port=args.mqtt_port)
  (seed_delete if args.mode == "seed-delete" else after_restart)(args)
  emit("result", mode=args.mode, success=True)


if __name__ == "__main__":
  try:
    main()
  except Exception as error:
    emit("result", success=False, error_type=type(error).__name__, error=str(error))
    sys.exit(1)
