import asyncio
from html import escape as html_escape
import hmac
import json
import math
import os
import re
import sqlite3
import threading
import time
from urllib.parse import urljoin, urlparse
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import paho.mqtt.client as mqtt

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
TRAFFIC_PATH = os.path.join(STATIC_DIR, "traffic.html")
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
SYS_TOPICS_ENABLED = os.getenv("SYS_TOPICS_ENABLED", "true").lower() == "true"
DASH_API_TOKEN = os.getenv("DASH_API_TOKEN", "")
DASH_API_TOKEN_HEADER = os.getenv("DASH_API_TOKEN_HEADER", "X-Dashboard-Token")
MQTT_AUTH_TOKEN = os.getenv("MQTT_AUTH_TOKEN", "")
MQTT_AUTH_TOKEN_HEADER = os.getenv("MQTT_AUTH_TOKEN_HEADER", "Authorization")
MQTT_AUTH_TOKEN_SCHEME = os.getenv("MQTT_AUTH_TOKEN_SCHEME", "Bearer")
MQTT_ONLINE_SECONDS = int(os.getenv("MQTT_ONLINE_SECONDS", "300"))
SYS_TOPICS_LIMIT = int(os.getenv("SYS_TOPICS_LIMIT", "200"))
STATS_WINDOW_SECONDS = int(os.getenv("STATS_WINDOW_SECONDS", "60"))
DASH_TITLE = os.getenv("DASH_TITLE", "MQTT Observatory")
DASH_DESCRIPTION = "Live node presence, roles, and broker telemetry."
TRAFFIC_DESCRIPTION = "Live unique packet rates by route and packet type."
DASH_LOGO_URL = os.getenv("DASH_LOGO_URL", "").strip()
DASH_BROKER_HOST = os.getenv("DASH_BROKER_HOST", "").strip()
DASH_EXTERNAL_URL_RAW = os.getenv("DASH_EXTERNAL_URL", "").strip()
_external_url_parsed = urlparse(DASH_EXTERNAL_URL_RAW) if DASH_EXTERNAL_URL_RAW else None
if (
  _external_url_parsed
  and _external_url_parsed.scheme in ("http", "https")
  and _external_url_parsed.netloc
):
  DASH_EXTERNAL_URL = DASH_EXTERNAL_URL_RAW
else:
  DASH_EXTERNAL_URL = ""
DASH_EXTERNAL_LABEL = (os.getenv("DASH_EXTERNAL_LABEL", "External").strip() or "External")
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
SENSITIVE_DETAIL_KEYS = {
  "ip",
  "ipaddress",
  "ipaddr",
  "publicip",
  "privateip",
  "clientip",
  "remoteip",
  "sourceip",
  "destip",
  "destinationip",
  "recentip",
  "recentips",
  "mac",
  "macaddress",
}
IPV4_REDACTION_EXEMPT_KEYS = {
  "clientversion",
}
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC_PATTERN = re.compile(r"\b[0-9A-Fa-f]{2}(?::|-){5}[0-9A-Fa-f]{2}\b")

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
template_html_cache: Dict[str, str] = {}
FAVICON_CONTENT_TYPES = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
}
TRAFFIC_ROUTE_KEYS = ("flood", "direct", "other")
TRAFFIC_PAYLOAD_KEYS = ("trace", "advert", "message", "other")
TRAFFIC_HISTORY_SECONDS = (
  PACKET_RETENTION_SECONDS if PACKET_RETENTION_SECONDS > 0 else max(180, STATS_WINDOW_SECONDS)
)
TRAFFIC_CHART_BUCKETS = 240

traffic_events = deque()
traffic_identity_queue = deque()
traffic_identity_seen: Dict[str, float] = {}
traffic_packets_total = 0
last_traffic_packet_at = 0.0

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
  "display_host": DASH_BROKER_HOST or MQTT_HOST,
  "port": MQTT_PORT,
  "transport": MQTT_TRANSPORT,
  "ws_path": MQTT_WS_PATH,
  "tls": MQTT_TLS,
  # Store the raw comma-separated topic string to reflect all subscribed topics
  "topic": MQTT_TOPIC_RAW,
  "sys_topic": MQTT_SYS_TOPIC,
  "sys_topics_enabled": SYS_TOPICS_ENABLED,
  "api_token_enabled": bool(DASH_API_TOKEN),
  "client_id": MQTT_CLIENT_ID,
  "title": DASH_TITLE,
  "external_url": DASH_EXTERNAL_URL,
  "external_label": DASH_EXTERNAL_LABEL,
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


def _load_index_template() -> str:
  return _load_html_template(INDEX_PATH)


def _load_html_template(path: str) -> str:
  cached = template_html_cache.get(path)
  if cached is None:
    with open(path, "r", encoding="utf-8") as handle:
      cached = handle.read()
    template_html_cache[path] = cached
  return cached


def _resolve_favicon(public_url: str) -> Dict[str, str]:
  if not DASH_LOGO_URL:
    return {"url": "", "content_type": ""}
  parsed = urlparse(DASH_LOGO_URL)
  if parsed.scheme in ("http", "https") and parsed.netloc:
    candidate = DASH_LOGO_URL
  elif parsed.scheme or parsed.netloc:
    return {"url": "", "content_type": ""}
  else:
    candidate = urljoin(public_url, DASH_LOGO_URL)
  candidate_path = urlparse(candidate).path or ""
  extension = os.path.splitext(candidate_path.lower())[1]
  content_type = FAVICON_CONTENT_TYPES.get(extension, "")
  if not content_type:
    return {"url": "", "content_type": ""}
  return {"url": candidate, "content_type": content_type}


def _render_html(path: str, title_text: str, description_text: str, public_url: str) -> str:
  template = _load_html_template(path)
  title = html_escape(title_text, quote=True)
  description = html_escape(description_text, quote=True)
  url = html_escape(public_url, quote=True)
  favicon = _resolve_favicon(public_url)
  favicon_tags = ""
  if favicon["url"]:
    favicon_url = html_escape(favicon["url"], quote=True)
    favicon_type = html_escape(favicon["content_type"], quote=True)
    favicon_tags = (
      f'<link rel="icon" type="{favicon_type}" href="{favicon_url}" />'
    )
  external_link = ""
  if DASH_EXTERNAL_URL:
    external_url = html_escape(DASH_EXTERNAL_URL, quote=True)
    external_label = html_escape(DASH_EXTERNAL_LABEL or "External", quote=True)
    external_link = (
      f'<a class="github-link" id="external-link" href="{external_url}" '
      f'target="_blank" rel="noopener">{external_label}</a>'
    )
  rendered = template.replace("__DASH_TITLE__", title)
  rendered = rendered.replace("__DASH_DESCRIPTION__", description)
  rendered = rendered.replace("__DASH_URL__", url)
  rendered = rendered.replace("__DASH_FAVICON_TAGS__", favicon_tags)
  rendered = rendered.replace("__DASH_EXTERNAL_LINK__", external_link)
  return rendered


def _render_index_html(public_url: str) -> str:
  return _render_html(INDEX_PATH, DASH_TITLE, DASH_DESCRIPTION, public_url)


def _render_traffic_html(public_url: str) -> str:
  traffic_title = f"{DASH_TITLE} Traffic"
  return _render_html(TRAFFIC_PATH, traffic_title, TRAFFIC_DESCRIPTION, public_url)


def _normalize_key(value: str) -> str:
  if not value:
    return ""
  return "".join(ch for ch in value.lower() if ch.isalnum())


def _is_sensitive_key(key: str) -> bool:
  normalized = _normalize_key(key)
  return normalized in SENSITIVE_DETAIL_KEYS


def _redact_sensitive_text(value: str, key_hint: Optional[str] = None) -> str:
  if not value:
    return ""
  normalized_hint = _normalize_key(key_hint or "")
  redacted = value
  if normalized_hint not in IPV4_REDACTION_EXEMPT_KEYS:
    redacted = IPV4_PATTERN.sub("[redacted-ip]", redacted)
  redacted = MAC_PATTERN.sub("[redacted-mac]", redacted)
  return redacted


def _redact_sensitive_payload(value: Any, key_hint: Optional[str] = None) -> Any:
  if key_hint and _is_sensitive_key(key_hint):
    return "[redacted]"
  if isinstance(value, dict):
    sanitized: Dict[str, Any] = {}
    for key, nested_value in value.items():
      sanitized[key] = _redact_sensitive_payload(nested_value, key)
    return sanitized
  if isinstance(value, list):
    return [_redact_sensitive_payload(item, key_hint) for item in value]
  if isinstance(value, str):
    return _redact_sensitive_text(value, key_hint)
  return value


def _redact_payload_json_text(value: str) -> str:
  if not value:
    return ""
  try:
    parsed = json.loads(value)
  except json.JSONDecodeError:
    return _redact_sensitive_text(value)
  redacted = _redact_sensitive_payload(parsed)
  return json.dumps(redacted, ensure_ascii=True)


def _extract_bearer_token(value: Optional[str]) -> Optional[str]:
  if not value:
    return None
  parts = value.split(" ", 1)
  if len(parts) != 2:
    return None
  if parts[0].strip().lower() != "bearer":
    return None
  token = parts[1].strip()
  return token or None


def _is_api_token_valid(candidate: Optional[str]) -> bool:
  if not DASH_API_TOKEN:
    return True
  if not candidate:
    return False
  return hmac.compare_digest(candidate, DASH_API_TOKEN)


def _is_api_authorized(headers: Mapping[str, str], query_params: Mapping[str, str]) -> bool:
  if not DASH_API_TOKEN:
    return True
  header_token = headers.get(DASH_API_TOKEN_HEADER)
  if _is_api_token_valid(header_token):
    return True
  bearer_token = _extract_bearer_token(headers.get("authorization"))
  if _is_api_token_valid(bearer_token):
    return True
  query_token = query_params.get("token")
  return _is_api_token_valid(query_token)


def _is_protected_path(path: str) -> bool:
  return path in ("/snapshot", "/stats", "/packets")


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
      payload_obj = _redact_sensitive_payload(payload_obj)
      text = json.dumps(payload_obj, ensure_ascii=True)
    except json.JSONDecodeError:
      payload_obj = None
      text = _redact_sensitive_text(text)
  else:
    text = _redact_sensitive_text(text)
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
    if _is_sensitive_key(key):
      continue
    value = payload.get(key)
    if value is None:
      continue
    if isinstance(value, (str, int, float, bool)):
      details[key] = _redact_sensitive_text(value, key) if isinstance(value, str) else value
  for key, value in payload.items():
    if key in DETAIL_SKIP_KEYS:
      continue
    if _is_sensitive_key(key):
      continue
    if key in details:
      continue
    if isinstance(value, (str, int, float, bool)):
      if isinstance(value, str) and len(value) > 120:
        continue
      if len(details) >= 12:
        break
      details[key] = _redact_sensitive_text(value, key) if isinstance(value, str) else value
  return details


def _is_sys_topic(topic: str) -> bool:
  if not SYS_TOPICS_ENABLED:
    return False
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


def _empty_traffic_counts(keys: tuple) -> Dict[str, int]:
  return {key: 0 for key in keys}


def _classify_route_label(value: Any) -> str:
  if value is None:
    return "other"
  route = str(value).strip().upper()
  if route == "F":
    return "flood"
  if route == "D":
    return "direct"
  return "other"


def _classify_payload_label(value: Any) -> str:
  try:
    packet_type = int(str(value).strip())
  except (TypeError, ValueError):
    return "other"
  if packet_type == 4:
    return "advert"
  if packet_type in (8, 9):
    return "trace"
  if packet_type in (2, 5):
    return "message"
  return "other"


def _extract_packet_event(topic: str, payload_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
  if not topic.endswith("/packets"):
    return None
  payload_json = payload_info.get("json")
  if not isinstance(payload_json, dict):
    return None
  packet_type = payload_json.get("packet_type")
  route_value = payload_json.get("route")
  packet_hash = payload_json.get("hash")
  raw_payload = payload_json.get("raw")
  if packet_type is None and route_value is None and not packet_hash and not raw_payload:
    return None
  dedupe_parts = [
    str(packet_hash or "").strip(),
    str(raw_payload or "").strip(),
    str(packet_type or "").strip(),
    str(route_value or "").strip(),
  ]
  dedupe_key = "|".join(part for part in dedupe_parts if part)
  if not dedupe_key:
    dedupe_key = f"{topic}|{payload_info.get('text', '')}"
  return {
    "ts": time.time(),
    "route": _classify_route_label(route_value),
    "payload": _classify_payload_label(packet_type),
    "dedupe_key": dedupe_key,
  }


def _build_packet_event_from_row(topic: str, payload_json_text: str, ts: float) -> Optional[Dict[str, Any]]:
  if not topic.endswith("/packets"):
    return None
  if not payload_json_text:
    return None
  try:
    payload_json = json.loads(payload_json_text)
  except json.JSONDecodeError:
    return None
  if not isinstance(payload_json, dict):
    return None
  packet_type = payload_json.get("packet_type")
  route_value = payload_json.get("route")
  packet_hash = payload_json.get("hash")
  raw_payload = payload_json.get("raw")
  if packet_type is None and route_value is None and not packet_hash and not raw_payload:
    return None
  dedupe_parts = [
    str(packet_hash or "").strip(),
    str(raw_payload or "").strip(),
    str(packet_type or "").strip(),
    str(route_value or "").strip(),
  ]
  dedupe_key = "|".join(part for part in dedupe_parts if part)
  if not dedupe_key:
    dedupe_key = f"{topic}|{payload_json_text}"
  return {
    "ts": float(ts or time.time()),
    "route": _classify_route_label(route_value),
    "payload": _classify_payload_label(packet_type),
    "dedupe_key": dedupe_key,
  }


def _prune_traffic_state(now: float) -> None:
  cutoff = now - TRAFFIC_HISTORY_SECONDS
  while traffic_events and traffic_events[0]["ts"] < cutoff:
    traffic_events.popleft()
  while traffic_identity_queue and traffic_identity_queue[0][1] < cutoff:
    dedupe_key, seen_at = traffic_identity_queue.popleft()
    if traffic_identity_seen.get(dedupe_key) == seen_at:
      traffic_identity_seen.pop(dedupe_key, None)


def _reset_traffic_state() -> None:
  global traffic_packets_total, last_traffic_packet_at
  traffic_events.clear()
  traffic_identity_queue.clear()
  traffic_identity_seen.clear()
  traffic_packets_total = 0
  last_traffic_packet_at = 0.0


def _append_loaded_traffic_event(ts: float, route: str, payload: str, dedupe_key: str) -> None:
  global traffic_packets_total, last_traffic_packet_at
  traffic_packets_total += 1
  if ts > last_traffic_packet_at:
    last_traffic_packet_at = ts
  history_cutoff = time.time() - TRAFFIC_HISTORY_SECONDS
  if ts < history_cutoff:
    return
  traffic_events.append(
    {
      "ts": ts,
      "route": route,
      "payload": payload,
    }
  )
  traffic_identity_queue.append((dedupe_key, ts))
  traffic_identity_seen[dedupe_key] = ts


def _persist_traffic_event(packet_event: Dict[str, Any]) -> None:
  global last_packet_purge
  if packet_db is None:
    return
  now = float(packet_event.get("ts") or time.time())
  with packet_db_lock:
    packet_db.execute(
      """
      INSERT INTO traffic_events (ts, dedupe_key, route_class, payload_class)
      VALUES (?, ?, ?, ?)
      """,
      (
        now,
        packet_event.get("dedupe_key", ""),
        packet_event.get("route", "other"),
        packet_event.get("payload", "other"),
      ),
    )
    if now - last_packet_purge >= 60:
      cutoff = now - PACKET_RETENTION_SECONDS
      packet_db.execute("DELETE FROM packets WHERE ts < ?", (cutoff,))
      packet_db.execute("DELETE FROM traffic_events WHERE ts < ?", (cutoff,))
      last_packet_purge = now
    packet_db.commit()


def _backfill_traffic_events_from_packets() -> None:
  if packet_db is None:
    return
  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT ts, topic, payload_json
      FROM packets
      WHERE topic LIKE '%/packets' AND payload_json IS NOT NULL AND payload_json != ''
      ORDER BY ts ASC
      """
    ).fetchall()
  if not rows:
    return

  seen_recent: Dict[str, float] = {}
  recent_queue = deque()
  inserts = []
  for ts, topic, payload_json_text in rows:
    packet_event = _build_packet_event_from_row(topic, payload_json_text, ts)
    if not packet_event:
      continue
    event_ts = float(packet_event["ts"])
    cutoff = event_ts - TRAFFIC_HISTORY_SECONDS
    while recent_queue and recent_queue[0][1] < cutoff:
      old_key, old_ts = recent_queue.popleft()
      if seen_recent.get(old_key) == old_ts:
        seen_recent.pop(old_key, None)
    dedupe_key = packet_event["dedupe_key"]
    if dedupe_key in seen_recent:
      continue
    seen_recent[dedupe_key] = event_ts
    recent_queue.append((dedupe_key, event_ts))
    inserts.append(
      (
        event_ts,
        dedupe_key,
        packet_event["route"],
        packet_event["payload"],
      )
    )

  if not inserts:
    return

  with packet_db_lock:
    packet_db.executemany(
      """
      INSERT INTO traffic_events (ts, dedupe_key, route_class, payload_class)
      VALUES (?, ?, ?, ?)
      """,
      inserts,
    )
    packet_db.commit()


def _load_traffic_events() -> None:
  if packet_db is None:
    return
  with state_lock:
    _reset_traffic_state()

  with packet_db_lock:
    traffic_count = packet_db.execute(
      "SELECT COUNT(*) FROM traffic_events"
    ).fetchone()[0]
  if traffic_count == 0:
    _backfill_traffic_events_from_packets()

  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT ts, dedupe_key, route_class, payload_class
      FROM traffic_events
      ORDER BY ts ASC
      """
    ).fetchall()

  with state_lock:
    _reset_traffic_state()
    for ts, dedupe_key, route_class, payload_class in rows:
      _append_loaded_traffic_event(
        float(ts or 0.0),
        str(route_class or "other"),
        str(payload_class or "other"),
        str(dedupe_key or ""),
      )
    _prune_traffic_state(time.time())


def _record_traffic_event(packet_event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
  global traffic_packets_total, last_traffic_packet_at
  if not packet_event:
    return None
  now = float(packet_event.get("ts") or time.time())
  dedupe_key = packet_event.get("dedupe_key")
  if not dedupe_key:
    return None
  with state_lock:
    _prune_traffic_state(now)
    if dedupe_key in traffic_identity_seen:
      return None
    traffic_identity_seen[dedupe_key] = now
    traffic_identity_queue.append((dedupe_key, now))
    traffic_events.append(
      {
        "ts": now,
        "route": packet_event.get("route", "other"),
        "payload": packet_event.get("payload", "other"),
      }
    )
    traffic_packets_total += 1
    last_traffic_packet_at = now
  _persist_traffic_event(packet_event)
  return {
    "ts": now,
    "route": packet_event.get("route", "other"),
    "payload": packet_event.get("payload", "other"),
  }


def _build_traffic(now: float, include_history: bool = True) -> Dict[str, Any]:
  with state_lock:
    _prune_traffic_state(now)
    events = [dict(event) for event in traffic_events]
    packets_total = traffic_packets_total
    last_packet_at = last_traffic_packet_at

  rate_cutoff = now - STATS_WINDOW_SECONDS
  route_counts = _empty_traffic_counts(TRAFFIC_ROUTE_KEYS)
  payload_counts = _empty_traffic_counts(TRAFFIC_PAYLOAD_KEYS)
  packet_rate_count = 0

  for event in events:
    if event["ts"] < rate_cutoff:
      continue
    packet_rate_count += 1
    route_key = event.get("route", "other")
    payload_key = event.get("payload", "other")
    route_counts[route_key] = route_counts.get(route_key, 0) + 1
    payload_counts[payload_key] = payload_counts.get(payload_key, 0) + 1

  if STATS_WINDOW_SECONDS > 0:
    scale = 1.0 / STATS_WINDOW_SECONDS
  else:
    scale = 0.0

  traffic = {
    "window_seconds": STATS_WINDOW_SECONDS,
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

  if not include_history:
    return traffic

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

  traffic["bucket_seconds"] = bucket_seconds
  traffic["history"] = history
  return traffic


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
    "traffic": _build_traffic(now),
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
  packet_db.execute(
    """
    CREATE TABLE IF NOT EXISTS traffic_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      dedupe_key TEXT NOT NULL,
      route_class TEXT NOT NULL,
      payload_class TEXT NOT NULL
    )
    """
  )
  packet_db.execute("CREATE INDEX IF NOT EXISTS idx_traffic_events_ts ON traffic_events (ts)")
  packet_db.execute(
    "CREATE INDEX IF NOT EXISTS idx_traffic_events_dedupe_ts ON traffic_events (dedupe_key, ts)"
  )
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
      packet_db.execute("DELETE FROM traffic_events WHERE ts < ?", (cutoff,))
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
      "payload_text": _redact_sensitive_text(row[5] or ""),
      "payload_json": _redact_payload_json_text(row[6] or ""),
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
  if SYS_TOPICS_ENABLED and MQTT_SYS_TOPIC:
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

  packet_event = _extract_packet_event(topic, payload_info)
  node = _update_node(topic, payload_info)
  _record_message()
  now = time.time()
  _save_packet(topic, payload_info, node)
  unique_packet_event = _record_traffic_event(packet_event)
  traffic_summary = None
  if unique_packet_event:
    traffic_summary = _build_traffic(now, include_history=False)
  _queue_broadcast(
    {
      "type": "node_update",
      "node": node.to_dict(now),
      "stats": _build_stats(now),
    }
  )
  if unique_packet_event and traffic_summary is not None:
    _queue_broadcast(
      {
        "type": "traffic_update",
        "event": unique_packet_event,
        "traffic": traffic_summary,
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
  _load_traffic_events()
  start_mqtt()


@app.on_event("shutdown")
async def on_shutdown():
  stop_mqtt()
  _close_packet_db()
  await broadcast_queue.put(None)


@app.middleware("http")
async def api_token_middleware(request: Request, call_next):
  if _is_protected_path(request.url.path):
    if not _is_api_authorized(request.headers, request.query_params):
      return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
  return await call_next(request)


@app.get("/")
async def index(request: Request) -> HTMLResponse:
  return HTMLResponse(_render_index_html(str(request.url)))


@app.get("/traffic")
async def traffic(request: Request) -> HTMLResponse:
  return HTMLResponse(_render_traffic_html(str(request.url)))


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
