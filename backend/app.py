import asyncio
import json
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import paho.mqtt.client as mqtt

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
DATA_DIR = os.path.join(os.path.dirname(ROOT_DIR), "data")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TRANSPORT_RAW = os.getenv("MQTT_TRANSPORT", "tcp").strip().lower()
MQTT_TRANSPORT = (
  "websockets"
  if MQTT_TRANSPORT_RAW in ("websockets", "websocket", "ws")
  else "tcp"
)
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/mqtt")
MQTT_TLS = os.getenv("MQTT_TLS", "false").lower() == "true"
MQTT_TLS_INSECURE = os.getenv("MQTT_TLS_INSECURE", "false").lower() == "true"
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "")

# Support multiple MQTT topics separated by commas.  MQTT_TOPIC_RAW holds
# the raw comma-separated string from the environment. MQTT_TOPICS is a list of
# stripped topic strings. For backwards compatibility, MQTT_TOPIC is set to the
# first topic in the list (if any) so existing code referring to MQTT_TOPIC
# continues to work.
MQTT_TOPIC_RAW = os.getenv("MQTT_TOPIC", "meshcore/#")
MQTT_TOPICS = [t.strip() for t in MQTT_TOPIC_RAW.split(",") if t.strip()]
if MQTT_TOPICS:
  MQTT_TOPIC = MQTT_TOPICS[0]
else:
  MQTT_TOPIC = ""

MQTT_SYS_TOPIC = os.getenv("MQTT_SYS_TOPIC", "$SYS/#")
MQTT_AUTH_TOKEN = os.getenv("MQTT_AUTH_TOKEN", "")
MQTT_AUTH_TOKEN_HEADER = os.getenv("MQTT_AUTH_TOKEN_HEADER", "Authorization")
MQTT_AUTH_TOKEN_SCHEME = os.getenv("MQTT_AUTH_TOKEN_SCHEME", "Bearer")
MQTT_ONLINE_SECONDS = int(os.getenv("MQTT_ONLINE_SECONDS", "300"))
SYS_TOPICS_LIMIT = int(os.getenv("SYS_TOPICS_LIMIT", "200"))
STATS_WINDOW_SECONDS = int(os.getenv("STATS_WINDOW_SECONDS", "60"))
DASH_TITLE = os.getenv("DASH_TITLE", "MQTT Observatory")
ROLE_OVERRIDES_FILE = os.getenv(
  "ROLE_OVERRIDES_FILE", os.path.join(DATA_DIR, "device_roles.json")
)
PACKET_DB_PATH = os.getenv("PACKET_DB_PATH", os.path.join(DATA_DIR, "packets.db"))
PACKET_RETENTION_RAW = int(os.getenv("PACKET_RETENTION_SECONDS", "7200"))
PACKET_RETENTION_SECONDS = max(0, min(PACKET_RETENTION_RAW, 86400))
NODE_PURGE_SECONDS = int(os.getenv("NODE_PURGE_SECONDS", "3600"))

NODE_ID_KEYS = (
  "device_id",
  "deviceId",
  "node_id",
  "nodeId",
  "id",
  "pubkey",
  "client_id",
  "clientId",
  "origin_id",
  "originId",
  "sender",
  "from",
  "source",
  "uid",
  "mac",
  "macAddress",
  "serial",
  "callsign",
)
NAME_KEYS = (
  "name",
  "nodeName",
  "deviceName",
  "displayName",
  "label",
  "alias",
  "callsign",
  "origin",
  "originName",
  "origin_name",
)
ROLE_KEYS = ("role", "deviceRoleName", "deviceRole", "nodeRole")
DETAIL_KEYS = (
  "battery",
  "batteryPct",
  "batteryPercent",
  "voltage",
  "rssi",
  "snr",
  "temp",
  "temperature",
  "humidity",
  "pressure",
  "uptime",
  "firmware",
  "version",
  "model",
  "vendor",
  "ip",
  "mac",
  "macAddress",
  "lat",
  "lon",
  "alt",
  "location",
)
DETAIL_SKIP_KEYS = {
  "raw",
  "packet",
  "packets",
  "payload",
  "data",
  "jwt",
  "jwt_payload",
  "origin_id",
  "originId",
  "device_id",
  "deviceId",
  "node_id",
  "nodeId",
}
NESTED_CONTAINERS = (
  "device",
  "node",
  "meta",
  "header",
  "info",
  "status",
  "payload",
  "data",
  "message",
)
TOPIC_SUFFIXES = set(
  (
    "status",
    "state",
    "telemetry",
    "metrics",
    "event",
    "events",
    "position",
    "location",
    "battery",
    "rx",
    "tx",
    "uplink",
    "downlink",
    "internal",
    "packets",
  )
)
ROLE_MAP = {
  "1": "companion",
  "2": "repeater",
  "3": "room",
}
ROLE_ALIASES = {
  "relay": "repeater",
  "router": "repeater",
  "portable": "companion",
}
ROLE_HINTS = (
  ("repeater", "repeater"),
  ("relay", "repeater"),
  ("router", "repeater"),
  ("room", "room"),
  ("companion", "companion"),
  ("portable", "companion"),
)

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

state_lock = threading.Lock()
ws_clients: Set[WebSocket] = set()
broadcast_queue: asyncio.Queue = asyncio.Queue()

mqtt_client: Optional[mqtt.Client] = None
packet_db: Optional[sqlite3.Connection] = None
packet_db_lock = threading.Lock()
last_packet_purge = 0.0
name_cache: Dict[str, str] = {}

role_overrides: Dict[str, str] = {}

@dataclass
class NodeState:
  node_id: str
  name: Optional[str] = None
  role: Optional[str] = None
  role_source: Optional[str] = None
  last_seen: float = 0.0
  first_seen: float = 0.0
  last_topic: str = ""
  last_payload_preview: str = ""
  message_count: int = 0
  details: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self, now: float) -> Dict[str, Any]:
    last_seen = self.last_seen or 0.0
    return {
      "node_id": self.node_id,
      "name": self.name,
      "role": self.role,
      "role_source": self.role_source,
      "last_seen": last_seen,
      "first_seen": self.first_seen,
      "last_topic": self.last_topic,
      "last_payload_preview": self.last_payload_preview,
      "message_count": self.message_count,
      "details": self.details,
      "online": bool(last_seen and (now - last_seen) <= MQTT_ONLINE_SECONDS),
    }

nodes: Dict[str, NodeState] = {}
sys_topics: Dict[str, Dict[str, Any]] = {}
message_times = deque()
message_total = 0
last_message_at = 0.0
last_sys_at = 0.0
broker_state: Dict[str, Any] = {
  "connected": False,
  "last_connect": 0.0,
  "last_disconnect": 0.0,
  "last_error": "",
  "host": MQTT_HOST,
  "port": MQTT_PORT,
  "transport": MQTT_TRANSPORT,
  "ws_path": MQTT_WS_PATH,
  "tls": MQTT_TLS,
  # Store the raw comma-separated topic string to reflect all subscribed topics
  "topic": MQTT_TOPIC_RAW,
  "sys_topic": MQTT_SYS_TOPIC,
  "client_id": MQTT_CLIENT_ID,
  "title": DASH_TITLE,
  "online_seconds": MQTT_ONLINE_SECONDS,
  "stats_window_seconds": STATS_WINDOW_SECONDS,
  "auth_mode": (
    "token"
    if MQTT_AUTH_TOKEN
    else ("userpass" if MQTT_USERNAME else "none")
  ),
  "packet_retention_seconds": PACKET_RETENTION_SECONDS,
}


def _sanitize_text(value: str, limit: int = 160) -> str:
  if not value:
    return ""
  cleaned = value.replace("\n", " ").replace("\r", " ")
  if len(cleaned) <= limit:
    return cleaned
  return f"{cleaned[:limit - 3]}..."


def _coerce_sys_value(text: str) -> Any:
  stripped = text.strip()
  if not stripped:
    return ""
  try:
    return int(stripped)
  except ValueError:
    pass
  try:
    return float(stripped)
  except ValueError:
    return stripped


def _decode_payload(payload: bytes) -> Dict[str, Any]:
  text = payload.decode("utf-8", errors="replace") if payload else ""
  payload_obj: Optional[Any] = None
  stripped = text.strip()
  if stripped.startswith("{") or stripped.startswith("["):
    try:
      payload_obj = json.loads(stripped)
    except json.JSONDecodeError:
      payload_obj = None
  return {
    "text": text,
    "json": payload_obj,
  }


def _find_value(payload: Any, keys: tuple) -> Optional[Any]:
  if not isinstance(payload, dict):
    return None
  for key in keys:
    if key in payload:
      value = payload.get(key)
      if value is not None:
        return value
  for container_key in NESTED_CONTAINERS:
    container = payload.get(container_key)
    if isinstance(container, dict):
      for key in keys:
        if key in container:
          value = container.get(key)
          if value is not None:
            return value
  return None


def _normalize_role(value: Any) -> Optional[str]:
  if value is None:
    return None
  if isinstance(value, (int, float)):
    value = str(int(value))
  if isinstance(value, str):
    cleaned = value.strip().lower()
    if not cleaned:
      return None
    if cleaned in ROLE_MAP:
      return ROLE_MAP[cleaned]
    if cleaned in ROLE_ALIASES:
      return ROLE_ALIASES[cleaned]
    return cleaned
  return None


def _extract_node_id(payload: Any, topic: str) -> Optional[str]:
  value = _find_value(payload, NODE_ID_KEYS)
  if value is not None:
    if isinstance(value, (int, float)):
      return str(int(value))
    if isinstance(value, str):
      cleaned = value.strip()
      if cleaned:
        return cleaned
  segments = [segment for segment in topic.split("/") if segment]
  if segments:
    candidate = segments[-1]
    if candidate in TOPIC_SUFFIXES and len(segments) > 1:
      candidate = segments[-2]
    if 0 < len(candidate) <= 64:
      return candidate
  return None


def _extract_name(payload: Any) -> Optional[str]:
  value = _find_value(payload, NAME_KEYS)
  if isinstance(value, (int, float)):
    return str(int(value))
  if isinstance(value, str):
    cleaned = value.strip()
    return cleaned or None
  return None


def _extract_role(payload: Any) -> Optional[str]:
  value = _find_value(payload, ROLE_KEYS)
  return _normalize_role(value)


def _infer_role_from_name(name: Optional[str]) -> Optional[str]:
  if not name:
    return None
  lowered = name.strip().lower()
  for token, role in ROLE_HINTS:
    if token in lowered:
      return role
  return None


def _extract_details(payload: Any) -> Dict[str, Any]:
  if not isinstance(payload, dict):
    return {}
  details: Dict[str, Any] = {}
  for key in DETAIL_KEYS:
    value = payload.get(key)
    if value is None:
      continue
    if isinstance(value, (str, int, float, bool)):
      details[key] = value
  for key, value in payload.items():
    if key in DETAIL_SKIP_KEYS:
      continue
    if key in details:
      continue
    if isinstance(value, (str, int, float, bool)):
      if isinstance(value, str) and len(value) > 120:
        continue
      if len(details) >= 12:
        break
      details[key] = value
  return details


def _is_sys_topic(topic: str) -> bool:
  if not MQTT_SYS_TOPIC:
    return False
  if MQTT_SYS_TOPIC.startswith("$SYS"):
    return topic.startswith("$SYS/")
  if MQTT_SYS_TOPIC.endswith("/#"):
    prefix = MQTT_SYS_TOPIC[:-2]
    return topic.startswith(prefix)
  return topic == MQTT_SYS_TOPIC


def _update_node(topic: str, payload_info: Dict[str, Any]) -> NodeState:
  payload_json = payload_info.get("json")
  payload_text = payload_info.get("text", "")
  node_id = _extract_node_id(payload_json, topic) or f"topic:{topic}"
  now = time.time()

  with state_lock:
    node = nodes.get(node_id)
    if node is None:
      node = NodeState(node_id=node_id)
      nodes[node_id] = node
    if not node.first_seen:
      node.first_seen = now
    node.last_seen = now
    node.last_topic = topic
    node.message_count += 1
    node.last_payload_preview = _sanitize_text(payload_text)

    if payload_json is not None:
      name = _extract_name(payload_json)
      role = _extract_role(payload_json)
      if name:
        node.name = name
        name_cache[node_id] = name
      if role:
        node.role = role
        node.role_source = "payload"
      details = _extract_details(payload_json)
      if details:
        node.details.update(details)

    if not node.name:
      cached_name = name_cache.get(node_id)
      if cached_name:
        node.name = cached_name
    if not node.role and node.name:
      hinted_role = _infer_role_from_name(node.name)
      if hinted_role:
        node.role = hinted_role
        node.role_source = "name_hint"

    override_role = role_overrides.get(node_id)
    if override_role:
      node.role = override_role
      node.role_source = "override"

    return node


def _update_sys(topic: str, payload_info: Dict[str, Any]) -> Any:
  global last_sys_at
  now = time.time()
  value = payload_info.get("text", "")
  sys_value = _coerce_sys_value(value)
  with state_lock:
    sys_topics[topic] = {"value": sys_value, "ts": now}
    last_sys_at = now
    if SYS_TOPICS_LIMIT and len(sys_topics) > SYS_TOPICS_LIMIT:
      oldest_topic = min(sys_topics.items(), key=lambda item: item[1].get("ts", 0.0))[0]
      sys_topics.pop(oldest_topic, None)
  return sys_value


def _record_message() -> None:
  global message_total, last_message_at
  now = time.time()
  removed_nodes = []
  with state_lock:
    message_total += 1
    last_message_at = now
    message_times.append(now)
    cutoff = now - STATS_WINDOW_SECONDS
    while message_times and message_times[0] < cutoff:
      message_times.popleft()
    if NODE_PURGE_SECONDS > 0:
      purge_cutoff = now - NODE_PURGE_SECONDS
      for node_id, node in list(nodes.items()):
        if node.last_seen and node.last_seen < purge_cutoff:
          nodes.pop(node_id, None)
          removed_nodes.append(node_id)
  for node_id in removed_nodes:
    _queue_broadcast({"type": "node_remove", "node_id": node_id})


def _build_stats(now: float) -> Dict[str, Any]:
  with state_lock:
    online_count = sum(
      1
      for node in nodes.values()
      if node.last_seen and (now - node.last_seen) <= MQTT_ONLINE_SECONDS
    )
    messages_per_min = 0.0
    if STATS_WINDOW_SECONDS > 0:
      messages_per_min = len(message_times) * (60.0 / STATS_WINDOW_SECONDS)
    return {
      "nodes_total": len(nodes),
      "nodes_online": online_count,
      "messages_total": message_total,
      "messages_per_min": round(messages_per_min, 2),
      "last_message_at": last_message_at,
      "sys_topics": len(sys_topics),
      "last_sys_at": last_sys_at,
    }


def _build_snapshot() -> Dict[str, Any]:
  now = time.time()
  with state_lock:
    nodes_list = [node.to_dict(now) for node in nodes.values()]
    sys_copy = dict(sys_topics)
    broker_copy = dict(broker_state)
  return {
    "broker": broker_copy,
    "nodes": nodes_list,
    "sys_topics": sys_copy,
    "stats": _build_stats(now),
  }


def _queue_broadcast(message: Dict[str, Any]) -> None:
  loop = getattr(app.state, "loop", None)
  if loop and loop.is_running():
    loop.call_soon_threadsafe(broadcast_queue.put_nowait, message)


def _init_packet_db() -> None:
  global packet_db
  if not PACKET_DB_PATH or PACKET_RETENTION_SECONDS <= 0:
    return
  os.makedirs(os.path.dirname(PACKET_DB_PATH), exist_ok=True)
  packet_db = sqlite3.connect(PACKET_DB_PATH, check_same_thread=False)
  packet_db.execute(
    """
    CREATE TABLE IF NOT EXISTS packets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      topic TEXT NOT NULL,
      node_id TEXT,
      name TEXT,
      role TEXT,
      payload_text TEXT,
      payload_json TEXT
    )
    """
  )
  packet_db.execute("CREATE INDEX IF NOT EXISTS idx_packets_ts ON packets (ts)")
  packet_db.execute("CREATE INDEX IF NOT EXISTS idx_packets_node ON packets (node_id)")
  packet_db.commit()


def _load_name_cache() -> None:
  if packet_db is None:
    return
  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT node_id, name
      FROM packets
      WHERE name IS NOT NULL AND name != ''
      ORDER BY ts DESC
      """
    ).fetchall()
  for node_id, name in rows:
    if not node_id or not name:
      continue
    if node_id not in name_cache:
      name_cache[node_id] = name


def _close_packet_db() -> None:
  global packet_db
  if packet_db is None:
    return
  try:
    packet_db.close()
  finally:
    packet_db = None


def _save_packet(topic: str, payload_info: Dict[str, Any], node: NodeState) -> None:
  global last_packet_purge
  if packet_db is None:
    return
  now = time.time()
  payload_text = payload_info.get("text") or ""
  payload_json = payload_info.get("json")
  payload_json_text = ""
  if payload_json is not None:
    payload_json_text = json.dumps(payload_json, ensure_ascii=True)
  with packet_db_lock:
    packet_db.execute(
      """
      INSERT INTO packets (ts, topic, node_id, name, role, payload_text, payload_json)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      """,
      (
        now,
        topic,
        node.node_id,
        node.name,
        node.role,
        payload_text,
        payload_json_text,
      ),
    )
    if now - last_packet_purge >= 60:
      cutoff = now - PACKET_RETENTION_SECONDS
      packet_db.execute("DELETE FROM packets WHERE ts < ?", (cutoff,))
      last_packet_purge = now
    packet_db.commit()


def _fetch_packets(limit: int, node_id: Optional[str]) -> Dict[str, Any]:
  if packet_db is None:
    return {"enabled": False, "packets": []}
  limit = max(1, min(limit, 1000))
  with packet_db_lock:
    if node_id:
      rows = packet_db.execute(
        """
        SELECT ts, topic, node_id, name, role, payload_text, payload_json
        FROM packets
        WHERE node_id = ?
        ORDER BY ts DESC
        LIMIT ?
        """,
        (node_id, limit),
      ).fetchall()
    else:
      rows = packet_db.execute(
        """
        SELECT ts, topic, node_id, name, role, payload_text, payload_json
        FROM packets
        ORDER BY ts DESC
        LIMIT ?
        """,
        (limit,),
      ).fetchall()
  packets = [
    {
      "ts": row[0],
      "topic": row[1],
      "node_id": row[2],
      "name": row[3],
      "role": row[4],
      "payload_text": row[5],
      "payload_json": row[6],
    }
    for row in rows
  ]
  return {"enabled": True, "packets": packets}


async def _broadcast_worker() -> None:
  while True:
    message = await broadcast_queue.get()
    if message is None:
      return
    dead = []
    for ws in list(ws_clients):
      try:
        await ws.send_json(message)
      except Exception:
        dead.append(ws)
    for ws in dead:
      ws_clients.discard(ws)


def mqtt_on_connect(client, userdata, flags, reason_code, properties=None):
  now = time.time()
  with state_lock:
    broker_state["connected"] = True
    broker_state["last_connect"] = now
    broker_state["last_error"] = ""
  # Subscribe to every topic in MQTT_TOPICS. This allows multiple topics to be
  # specified using a comma-separated string in MQTT_TOPIC_RAW.
  for _topic in MQTT_TOPICS:
    if _topic:
      client.subscribe(_topic, qos=0)
  if MQTT_SYS_TOPIC:
    client.subscribe(MQTT_SYS_TOPIC, qos=0)
  _queue_broadcast({"type": "broker_status", "broker": dict(broker_state)})


def mqtt_on_disconnect(client, userdata, disconnect_flags=None, reason_code=None, properties=None):
  now = time.time()
  error = reason_code if reason_code is not None else disconnect_flags
  with state_lock:
    broker_state["connected"] = False
    broker_state["last_disconnect"] = now
    broker_state["last_error"] = str(error) if error is not None else ""
  _queue_broadcast({"type": "broker_status", "broker": dict(broker_state)})


def mqtt_on_message(client, userdata, msg: mqtt.MQTTMessage):
  payload_info = _decode_payload(msg.payload)
  topic = msg.topic

  if _is_sys_topic(topic):
    sys_value = _update_sys(topic, payload_info)
    _queue_broadcast(
      {
        "type": "sys_update",
        "topic": topic,
        "value": sys_value,
        "received_at": time.time(),
      }
    )
    return

  node = _update_node(topic, payload_info)
  _record_message()
  now = time.time()
  _save_packet(topic, payload_info, node)
  _queue_broadcast(
    {
      "type": "node_update",
      "node": node.to_dict(now),
      "stats": _build_stats(now),
    }
  )


def _load_role_overrides() -> Dict[str, str]:
  if not ROLE_OVERRIDES_FILE:
    return {}
  if not os.path.exists(ROLE_OVERRIDES_FILE):
    return {}
  try:
    with open(ROLE_OVERRIDES_FILE, "r", encoding="utf-8") as handle:
      raw = json.load(handle)
  except (OSError, json.JSONDecodeError):
    return {}
  if not isinstance(raw, dict):
    return {}
  overrides: Dict[str, str] = {}
  for key, value in raw.items():
    if not key:
      continue
    role = _normalize_role(value)
    if role:
      overrides[str(key).strip()] = role
  return overrides


def start_mqtt() -> None:
  global mqtt_client
  if mqtt_client is not None:
    return

  transport = "websockets" if MQTT_TRANSPORT == "websockets" else "tcp"
  mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=(MQTT_CLIENT_ID or None),
    transport=transport,
  )
  mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

  if transport == "websockets":
    headers = None
    if MQTT_AUTH_TOKEN:
      header_name = MQTT_AUTH_TOKEN_HEADER or "Authorization"
      token_value = MQTT_AUTH_TOKEN
      if MQTT_AUTH_TOKEN_SCHEME:
        token_value = f"{MQTT_AUTH_TOKEN_SCHEME} {MQTT_AUTH_TOKEN}"
      headers = {header_name: token_value}
    mqtt_client.ws_set_options(path=MQTT_WS_PATH, headers=headers)

  if MQTT_USERNAME:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

  if MQTT_TLS:
    if MQTT_CA_CERT:
      mqtt_client.tls_set(ca_certs=MQTT_CA_CERT)
    else:
      mqtt_client.tls_set()
    if MQTT_TLS_INSECURE:
      mqtt_client.tls_insecure_set(True)

  mqtt_client.on_connect = mqtt_on_connect
  mqtt_client.on_disconnect = mqtt_on_disconnect
  mqtt_client.on_message = mqtt_on_message

  mqtt_client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
  mqtt_client.loop_start()


def stop_mqtt() -> None:
  global mqtt_client
  if mqtt_client is None:
    return
  try:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
  finally:
    mqtt_client = None


@app.on_event("startup")
async def on_startup():
  app.state.loop = asyncio.get_running_loop()
  app.state.broadcast_task = asyncio.create_task(_broadcast_worker())
  global role_overrides
  role_overrides = _load_role_overrides()
  _init_packet_db()
  _load_name_cache()
  start_mqtt()


@app.on_event("shutdown")
async def on_shutdown():
  stop_mqtt()
  _close_packet_db()
  await broadcast_queue.put(None)


@app.get("/")
async def index() -> FileResponse:
  return FileResponse(INDEX_PATH)


@app.get("/snapshot")
async def snapshot() -> JSONResponse:
  return JSONResponse(_build_snapshot())


@app.get("/stats")
async def stats() -> JSONResponse:
  return JSONResponse(_build_stats(time.time()))


@app.get("/packets")
async def packets(
  limit: int = Query(100, ge=1, le=1000),
  node_id: Optional[str] = Query(None),
) -> JSONResponse:
  return JSONResponse(_fetch_packets(limit, node_id))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
  await ws.accept()
  ws_clients.add(ws)
  await ws.send_json({"type": "snapshot", **_build_snapshot()})
  try:
    while True:
      await ws.receive_text()
  except WebSocketDisconnect:
    ws_clients.discard(ws)
