import asyncio
from html import escape as html_escape
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import paho.mqtt.client as mqtt

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
TRAFFIC_PATH = os.path.join(STATIC_DIR, "traffic.html")
BATTERYINFO_PATH = os.path.join(STATIC_DIR, "batteryinfo.html")
NEIGHBORS_PATH = os.path.join(STATIC_DIR, "neighbors.html")
BATTERYINFO_DECODER_PATH = os.path.join(ROOT_DIR, "scripts", "batteryinfo-decoder.cjs")
DATA_DIR = os.path.join(os.path.dirname(ROOT_DIR), "data")
APP_VERSION = "v1.3.4"

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
BATTERYINFO_DESCRIPTION = "Decoded #batteryinfo chat telemetry across retained packet history."
NEIGHBORS_DESCRIPTION = "Live observer neighbor topology, signal quality, and flood scopes."
BATTERYINFO_ENABLED = os.getenv("BATTERYINFO_ENABLED", "false").lower() == "true"
BATTERYINFO_CHANNEL_NAME = os.getenv("BATTERYINFO_CHANNEL_NAME", "batteryinfo").strip()
BATTERYINFO_SHOW_CHANNEL_NAME = os.getenv("BATTERYINFO_SHOW_CHANNEL_NAME", "false").lower() == "true"
BATTERYINFO_RETENTION_SECONDS = max(0, int(os.getenv("BATTERYINFO_RETENTION_SECONDS", "172800")))
DASH_LOGO_URL = os.getenv("DASH_LOGO_URL", "").strip()
DASH_BROKER_HOST = os.getenv("DASH_BROKER_HOST", "").strip()
BATTERYINFO_CHANNEL_KEY = os.getenv("BATTERYINFO_CHANNEL_KEY", "").strip().lower()
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
    "neighbors",
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
PAYLOAD_ROLE_HINTS = (
  ("repeater", "repeater"),
  ("relay", "repeater"),
  ("router", "repeater"),
  ("observer", "room"),
  ("meshcore-ha", "room"),
  ("home assistant", "room"),
  (" room ", "room"),
  ("room-", "room"),
  ("-room", "room"),
  ("server", "room"),
  ("mqtt", "room"),
  ("bridge", "room"),
  ("gateway", "room"),
  ("portable", "companion"),
  ("handheld", "companion"),
  ("phone", "companion"),
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
BATTERYINFO_BATTERY_PATTERN = re.compile(
  r"battery\s*=\s*(?P<volts>-?\d+(?:\.\d+)?)v\s+(?P<percent>\d{1,3})%",
  re.IGNORECASE,
)
BATTERYINFO_TEMP_PATTERN = re.compile(r"temp\s*=\s*(?P<value>na|-?\d+(?:\.\d+)?)c", re.IGNORECASE)
BATTERYINFO_HUM_PATTERN = re.compile(r"hum\s*=\s*(?P<value>na|-?\d+(?:\.\d+)?)%", re.IGNORECASE)
BATTERYINFO_PRESS_PATTERN = re.compile(r"press\s*=\s*(?P<value>na|-?\d+(?:\.\d+)?)hpa", re.IGNORECASE)
BATTERYINFO_ALT_PATTERN = re.compile(r"alt\s*=\s*(?P<value>na|-?\d+(?:\.\d+)?)m", re.IGNORECASE)

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

state_lock = threading.Lock()
ws_clients: Set[WebSocket] = set()
ws_client_count = 0
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
TRAFFIC_TOP_TALKERS_LIMIT = 8
TRAFFIC_BURST_LIMIT = 6
TRAFFIC_DRILLDOWN_LIMIT = 200

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
neighbor_snapshots: Dict[str, Dict[str, Any]] = {}
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


def _batteryinfo_channel_label() -> str:
  raw_label = (BATTERYINFO_CHANNEL_NAME or "").strip()
  if not raw_label:
    raw_label = "batteryinfo"
  return raw_label if raw_label.startswith("#") else f"#{raw_label}"


def _format_retention_text(seconds: int, compact: bool = False) -> str:
  seconds = max(0, int(seconds or 0))
  if seconds % 3600 == 0 and seconds >= 3600:
    hours = seconds // 3600
    return f"{hours}h" if compact else f"{hours} hour{'s' if hours != 1 else ''}"
  if seconds % 86400 == 0 and seconds >= 86400:
    days = seconds // 86400
    return f"{days}d" if compact else f"{days} day{'s' if days != 1 else ''}"
  if seconds % 60 == 0 and seconds >= 60:
    minutes = seconds // 60
    return f"{minutes}m" if compact else f"{minutes} minute{'s' if minutes != 1 else ''}"
  return f"{seconds}s" if compact else f"{seconds} seconds"


def _render_html(
  path: str,
  title_text: str,
  description_text: str,
  public_url: str,
  extra_replacements: Optional[Dict[str, str]] = None,
) -> str:
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
  for key, value in (extra_replacements or {}).items():
    rendered = rendered.replace(key, value)
  return rendered


def _render_index_html(public_url: str) -> str:
  battery_link = ""
  if BATTERYINFO_ENABLED:
    battery_link = '<a class="github-link" href="/batteryinfo">Battery</a>'
  return _render_html(
    INDEX_PATH,
    DASH_TITLE,
    DASH_DESCRIPTION,
    public_url,
    {
      "__BATTERY_INDEX_LINK__": battery_link,
      "__NEIGHBORS_INDEX_LINK__": '<a class="github-link" href="/neighbors">Neighbors</a>',
    },
  )


def _render_traffic_html(public_url: str) -> str:
  traffic_title = f"{DASH_TITLE} Traffic"
  battery_link = ""
  if BATTERYINFO_ENABLED:
    battery_link = '<a class="nav-link" href="/batteryinfo">Battery</a>'
  return _render_html(
    TRAFFIC_PATH,
    traffic_title,
    TRAFFIC_DESCRIPTION,
    public_url,
    {"__BATTERY_NAV_LINK__": battery_link},
  )


def _render_neighbors_html(public_url: str) -> str:
  neighbors_title = f"{DASH_TITLE} Neighbors"
  battery_link = ""
  if BATTERYINFO_ENABLED:
    battery_link = '<a class="nav-link" href="/batteryinfo">Battery</a>'
  return _render_html(
    NEIGHBORS_PATH,
    neighbors_title,
    NEIGHBORS_DESCRIPTION,
    public_url,
    {"__BATTERY_NAV_LINK__": battery_link},
  )


def _render_batteryinfo_html(public_url: str) -> str:
  batteryinfo_title = f"{DASH_TITLE} Battery Info"
  channel_label = html_escape(_batteryinfo_channel_label(), quote=False)
  retention_long = _format_retention_text(BATTERYINFO_RETENTION_SECONDS, compact=False)
  retention_short = _format_retention_text(BATTERYINFO_RETENTION_SECONDS, compact=True)
  if BATTERYINFO_SHOW_CHANNEL_NAME:
    subtitle = (
      "Decoded battery telemetry from the retained "
      f'<span class="mono">{channel_label}</span> channel over the last {retention_long}.'
    )
    latest_nodes_sub = (
      "Most recent decoded value set for each sender posting into "
      f'<span class="mono">{channel_label}</span>.'
    )
  else:
    subtitle = f"Decoded battery telemetry from the retained battery channel over the last {retention_long}."
    latest_nodes_sub = "Most recent decoded value set for each sender posting into the battery channel."
  return _render_html(
    BATTERYINFO_PATH,
    batteryinfo_title,
    BATTERYINFO_DESCRIPTION,
    public_url,
    {
      "__BATTERY_ACTIVE_LINK__": '<a class="nav-link" href="/batteryinfo" data-active="true">Battery</a>',
      "__BATTERYINFO_SUBTITLE__": subtitle,
      "__BATTERYINFO_LATEST_NODES_SUB__": latest_nodes_sub,
      "__BATTERYINFO_RETENTION_SHORT__": html_escape(retention_short, quote=True),
      "__BATTERYINFO_FOOTER_RETENTION__": html_escape(retention_long, quote=True),
    },
  )


def _parse_channel_secret(raw_value: str) -> Optional[str]:
  cleaned = (raw_value or "").strip().lower()
  if not cleaned:
    return None
  if len(cleaned) != 32:
    return None
  try:
    bytes.fromhex(cleaned)
  except ValueError:
    return None
  return cleaned


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
  return path in ("/snapshot", "/stats", "/packets", "/neighbors/data")


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


def _normalize_pubkey(value: Any) -> Optional[str]:
  if not isinstance(value, str):
    return None
  cleaned = value.strip().lower()
  if len(cleaned) != 64:
    return None
  try:
    bytes.fromhex(cleaned)
  except ValueError:
    return None
  return cleaned


def _neighbors_observer_from_topic(topic: str) -> Optional[str]:
  segments = [segment for segment in topic.split("/") if segment]
  if len(segments) != 4 or segments[0] != "meshcore" or segments[3] != "neighbors":
    return None
  return _normalize_pubkey(segments[2])


def _normalize_scopes(value: Any) -> list[str]:
  if not isinstance(value, str):
    return []
  scopes = []
  seen = set()
  for raw_scope in value.split(","):
    scope = raw_scope.strip()
    if not scope or scope in seen:
      continue
    scopes.append(scope[:96])
    seen.add(scope)
    if len(scopes) >= 32:
      break
  return scopes


def _normalize_neighbors_snapshot(
  topic: str,
  payload: Any,
  received_at: float,
) -> Optional[Dict[str, Any]]:
  topic_observer_id = _neighbors_observer_from_topic(topic)
  if not topic_observer_id or not isinstance(payload, dict):
    return None

  payload_observer_id = _normalize_pubkey(payload.get("origin_id"))
  if topic_observer_id and payload_observer_id and topic_observer_id != payload_observer_id:
    return None
  observer_id = topic_observer_id or payload_observer_id
  if not observer_id:
    return None

  raw_neighbors = payload.get("neighbors")
  if not isinstance(raw_neighbors, list):
    return None

  normalized_neighbors = []
  seen_neighbors = set()
  allowed_statuses = {"responded", "timeout", "send_failed"}
  for raw_neighbor in raw_neighbors[:100]:
    if not isinstance(raw_neighbor, dict):
      continue
    pubkey = _normalize_pubkey(raw_neighbor.get("pubkey"))
    if not pubkey or pubkey == observer_id or pubkey in seen_neighbors:
      continue
    raw_snr = raw_neighbor.get("snr")
    raw_heard_secs_ago = raw_neighbor.get("heard_secs_ago")
    if isinstance(raw_snr, bool) or not isinstance(raw_snr, (str, int, float)):
      continue
    if isinstance(raw_heard_secs_ago, bool) or not isinstance(raw_heard_secs_ago, (str, int, float)):
      continue
    if isinstance(raw_heard_secs_ago, float) and not raw_heard_secs_ago.is_integer():
      continue
    try:
      snr = float(raw_snr)
      heard_secs_ago = int(raw_heard_secs_ago)
    except (TypeError, ValueError, OverflowError):
      continue
    if not math.isfinite(snr) or heard_secs_ago < 0:
      continue
    status = str(raw_neighbor.get("status") or "").strip().lower()
    if status not in allowed_statuses:
      status = "unknown"
    normalized_neighbors.append(
      {
        "pubkey": pubkey,
        "snr": round(snr, 2),
        "heard_secs_ago": heard_secs_ago,
        "heard_at": max(0.0, received_at - heard_secs_ago),
        "scopes": _normalize_scopes(raw_neighbor.get("scopes")),
        "status": status,
      }
    )
    seen_neighbors.add(pubkey)

  self_info = payload.get("self")
  self_scopes = self_info.get("scopes") if isinstance(self_info, dict) else ""
  origin = payload.get("origin")
  if not isinstance(origin, str):
    origin = ""
  source_timestamp = payload.get("timestamp")
  if not isinstance(source_timestamp, str):
    source_timestamp = ""
  source_timestamp = source_timestamp.strip()[:80]
  reported_at = float(received_at)
  if source_timestamp:
    try:
      parsed_timestamp = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
      if parsed_timestamp.tzinfo is None:
        parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)
      source_epoch = parsed_timestamp.timestamp()
      if 1_577_836_800 <= source_epoch <= reported_at + 86_400:
        reported_at = source_epoch
    except (ValueError, OverflowError, OSError):
      pass

  for neighbor in normalized_neighbors:
    neighbor["heard_at"] = max(0.0, reported_at - neighbor["heard_secs_ago"])

  return {
    "observer_id": observer_id,
    "origin": origin.strip()[:120],
    "topic": topic,
    "source_timestamp": source_timestamp,
    "reported_at": reported_at,
    "received_at": float(received_at),
    "scopes": _normalize_scopes(self_scopes),
    "neighbors": normalized_neighbors,
  }


def _build_neighbors_topology() -> Dict[str, Any]:
  now = time.time()
  with state_lock:
    snapshots = list(neighbor_snapshots.values())
    node_names = {
      node_id: node.name
      for node_id, node in nodes.items()
      if node.name
    }
    cached_names = dict(name_cache)

  observers = []
  devices: Dict[str, Dict[str, Any]] = {}
  links = []
  observer_ids = {snapshot["observer_id"] for snapshot in snapshots}
  responded = 0
  unresolved = 0
  last_update = 0.0

  for snapshot in sorted(snapshots, key=lambda item: item["observer_id"]):
    observer_id = snapshot["observer_id"]
    origin = snapshot.get("origin") or node_names.get(observer_id) or cached_names.get(observer_id) or ""
    received_at = float(snapshot.get("received_at") or 0.0)
    reported_at = float(snapshot.get("reported_at") or received_at)
    last_update = max(last_update, reported_at)
    observers.append(
      {
        "observer_id": observer_id,
        "origin": origin,
        "topic": snapshot.get("topic") or "",
        "source_timestamp": snapshot.get("source_timestamp") or "",
        "reported_at": reported_at,
        "received_at": received_at,
        "scopes": list(snapshot.get("scopes") or []),
        "neighbor_count": len(snapshot.get("neighbors") or []),
      }
    )
    observer_device = devices.setdefault(
      observer_id,
      {
        "device_id": observer_id,
        "name": origin,
        "kind": "observer",
        "observer_count": 0,
      },
    )
    observer_device["kind"] = "observer"
    if origin:
      observer_device["name"] = origin
    for neighbor in snapshot.get("neighbors") or []:
      neighbor_id = neighbor["pubkey"]
      status = neighbor.get("status") or "unknown"
      if status == "responded":
        responded += 1
      else:
        unresolved += 1
      link = {
        "observer_id": observer_id,
        "neighbor_id": neighbor_id,
        "snr": neighbor.get("snr"),
        "heard_secs_ago": neighbor.get("heard_secs_ago"),
        "heard_at": neighbor.get("heard_at"),
        "scopes": list(neighbor.get("scopes") or []),
        "status": status,
        "reported_at": reported_at,
        "received_at": received_at,
      }
      links.append(link)
      device = devices.setdefault(
        neighbor_id,
        {
          "device_id": neighbor_id,
          "name": node_names.get(neighbor_id) or cached_names.get(neighbor_id) or "",
          "kind": "observer" if neighbor_id in observer_ids else "neighbor",
          "observer_count": 0,
        },
      )
      device["observer_count"] += 1

  links.sort(key=lambda item: (item["observer_id"], item["neighbor_id"]))
  device_list = sorted(
    devices.values(),
    key=lambda item: (item["kind"] != "observer", (item["name"] or item["device_id"]).lower()),
  )
  return {
    "generated_at": now,
    "observers": observers,
    "devices": device_list,
    "links": links,
    "stats": {
      "observers": len(observers),
      "devices": len(device_list),
      "links": len(links),
      "responded": responded,
      "unresolved": unresolved,
      "last_update": last_update,
    },
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


def _infer_role_from_payload(topic: str, payload: Any) -> Optional[str]:
  signals = []
  topic_lower = topic.strip().lower()
  if topic_lower:
    signals.append(topic_lower)
  if not isinstance(payload, dict):
    combined = " ".join(signals)
  else:
    for key in ("origin", "name", "model", "client_version", "firmware_version", "vendor"):
      value = payload.get(key)
      if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned:
          signals.append(cleaned)
    combined = " ".join(signals)
  if not combined:
    return None
  for token, role in PAYLOAD_ROLE_HINTS:
    if token in combined:
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
      hinted_payload_role = _infer_role_from_payload(topic, payload_json)
      if name:
        node.name = name
        name_cache[node_id] = name
      if role:
        node.role = role
        node.role_source = "payload"
      elif hinted_payload_role:
        node.role = hinted_payload_role
        node.role_source = "payload_hint"
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


def _should_ignore_retained_message(topic: str, msg: mqtt.MQTTMessage) -> bool:
  if not getattr(msg, "retain", False):
    return False
  return topic.endswith("/internal")


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


def _resolve_packet_name(node_id: Optional[str], name_hint: Optional[str]) -> Optional[str]:
  if name_hint:
    cleaned = str(name_hint).strip()
    if cleaned:
      return cleaned
  if not node_id:
    return None
  with state_lock:
    node = nodes.get(node_id)
    if node and node.name:
      return node.name
    cached = name_cache.get(node_id)
  return cached or None


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
  node_id = _extract_node_id(payload_json, topic)
  packet_name = _resolve_packet_name(node_id, _extract_name(payload_json))
  return {
    "ts": time.time(),
    "route": _classify_route_label(route_value),
    "payload": _classify_payload_label(packet_type),
    "dedupe_key": dedupe_key,
    "node_id": node_id,
    "name": packet_name,
    "topic": topic,
  }


def _build_packet_event_from_row(
  topic: str,
  payload_json_text: str,
  ts: float,
  node_id: Optional[str] = None,
  name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
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
  resolved_node_id = node_id or _extract_node_id(payload_json, topic)
  packet_name = _resolve_packet_name(resolved_node_id, name or _extract_name(payload_json))
  return {
    "ts": float(ts or time.time()),
    "route": _classify_route_label(route_value),
    "payload": _classify_payload_label(packet_type),
    "dedupe_key": dedupe_key,
    "node_id": resolved_node_id,
    "name": packet_name,
    "topic": topic,
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


def _append_loaded_traffic_event(
  ts: float,
  route: str,
  payload: str,
  dedupe_key: str,
  node_id: Optional[str] = None,
  name: Optional[str] = None,
  topic: Optional[str] = None,
) -> None:
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
      "node_id": node_id,
      "name": name,
      "topic": topic or "",
    }
  )
  traffic_identity_queue.append((dedupe_key, ts))
  traffic_identity_seen[dedupe_key] = ts


def _persist_traffic_event(packet_event: Dict[str, Any]) -> None:
  global last_packet_purge
  if packet_db is None or PACKET_RETENTION_SECONDS <= 0:
    return
  now = float(packet_event.get("ts") or time.time())
  with packet_db_lock:
    packet_db.execute(
      """
      INSERT INTO traffic_events (ts, dedupe_key, route_class, payload_class, node_id, name, topic)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      """,
      (
        now,
        packet_event.get("dedupe_key", ""),
        packet_event.get("route", "other"),
        packet_event.get("payload", "other"),
        packet_event.get("node_id"),
        packet_event.get("name"),
        packet_event.get("topic", ""),
      ),
    )
    if now - last_packet_purge >= 60:
      cutoff = now - PACKET_RETENTION_SECONDS
      battery_cutoff = now - BATTERYINFO_RETENTION_SECONDS
      packet_db.execute("DELETE FROM packets WHERE ts < ?", (cutoff,))
      packet_db.execute("DELETE FROM traffic_events WHERE ts < ?", (cutoff,))
      packet_db.execute("DELETE FROM batteryinfo_events WHERE ts < ?", (battery_cutoff,))
      last_packet_purge = now
    packet_db.commit()


def _backfill_traffic_events_from_packets() -> None:
  if packet_db is None or PACKET_RETENTION_SECONDS <= 0:
    return
  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT ts, topic, node_id, name, payload_json
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
  for ts, topic, node_id, name, payload_json_text in rows:
    packet_event = _build_packet_event_from_row(topic, payload_json_text, ts, node_id, name)
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
        packet_event.get("node_id"),
        packet_event.get("name"),
        packet_event.get("topic", topic),
      )
    )

  if not inserts:
    return

  with packet_db_lock:
    packet_db.executemany(
      """
      INSERT INTO traffic_events (ts, dedupe_key, route_class, payload_class, node_id, name, topic)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      """,
      inserts,
    )
    packet_db.commit()


def _load_traffic_events() -> None:
  with state_lock:
    _reset_traffic_state()
  if packet_db is None or PACKET_RETENTION_SECONDS <= 0:
    return

  with packet_db_lock:
    traffic_count = packet_db.execute(
      "SELECT COUNT(*) FROM traffic_events"
    ).fetchone()[0]
    enriched_count = packet_db.execute(
      """
      SELECT COUNT(*)
      FROM traffic_events
      WHERE node_id IS NOT NULL OR name IS NOT NULL OR (topic IS NOT NULL AND topic != '')
      """
    ).fetchone()[0]
    packet_count = packet_db.execute(
      "SELECT COUNT(*) FROM packets WHERE topic LIKE '%/packets'"
    ).fetchone()[0]
  if traffic_count == 0:
    _backfill_traffic_events_from_packets()
  elif enriched_count < traffic_count and packet_count > 0:
    with packet_db_lock:
      packet_db.execute("DELETE FROM traffic_events")
      packet_db.commit()
    _backfill_traffic_events_from_packets()

  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT ts, dedupe_key, route_class, payload_class, node_id, name, topic
      FROM traffic_events
      ORDER BY ts ASC
      """
    ).fetchall()

  with state_lock:
    _reset_traffic_state()
    for ts, dedupe_key, route_class, payload_class, node_id, name, topic in rows:
      _append_loaded_traffic_event(
        float(ts or 0.0),
        str(route_class or "other"),
        str(payload_class or "other"),
        str(dedupe_key or ""),
        str(node_id) if node_id else None,
        str(name) if name else None,
        str(topic) if topic else "",
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
        "node_id": packet_event.get("node_id"),
        "name": packet_event.get("name"),
        "topic": packet_event.get("topic", ""),
      }
    )
    traffic_packets_total += 1
    last_traffic_packet_at = now
  _persist_traffic_event(packet_event)
  return {
    "ts": now,
    "route": packet_event.get("route", "other"),
    "payload": packet_event.get("payload", "other"),
    "node_id": packet_event.get("node_id"),
    "name": packet_event.get("name"),
    "topic": packet_event.get("topic", ""),
  }


def _dominant_traffic_key(counts: Dict[str, int], keys: tuple) -> str:
  best_key = keys[0]
  best_value = -1
  for key in keys:
    value = int(counts.get(key, 0))
    if value > best_value:
      best_key = key
      best_value = value
  return best_key


def _build_top_talkers(events: list, packets_total: int) -> list:
  talkers: Dict[str, Dict[str, Any]] = {}
  for event in events:
    node_id = event.get("node_id")
    topic = str(event.get("topic") or "")
    talker_key = str(node_id or topic or "unknown")
    entry = talkers.get(talker_key)
    if entry is None:
      entry = {
        "node_id": node_id,
        "name": event.get("name"),
        "topic": topic,
        "packets": 0,
        "last_seen": 0.0,
        "route_counts": _empty_traffic_counts(TRAFFIC_ROUTE_KEYS),
        "payload_counts": _empty_traffic_counts(TRAFFIC_PAYLOAD_KEYS),
      }
      talkers[talker_key] = entry
    entry["packets"] += 1
    entry["last_seen"] = max(float(entry["last_seen"]), float(event.get("ts") or 0.0))
    route_key = str(event.get("route") or "other")
    payload_key = str(event.get("payload") or "other")
    entry["route_counts"][route_key] = entry["route_counts"].get(route_key, 0) + 1
    entry["payload_counts"][payload_key] = entry["payload_counts"].get(payload_key, 0) + 1
    if not entry.get("name") and event.get("name"):
      entry["name"] = event.get("name")
    if not entry.get("topic") and topic:
      entry["topic"] = topic

  top_talkers = sorted(
    talkers.values(),
    key=lambda item: (-int(item["packets"]), -float(item["last_seen"])),
  )[:TRAFFIC_TOP_TALKERS_LIMIT]
  for item in top_talkers:
    item["share"] = round((item["packets"] / packets_total) * 100, 1) if packets_total else 0.0
    item["route_lead"] = _dominant_traffic_key(item["route_counts"], TRAFFIC_ROUTE_KEYS)
    item["payload_lead"] = _dominant_traffic_key(item["payload_counts"], TRAFFIC_PAYLOAD_KEYS)
  return top_talkers


def _build_bursts(history: list) -> list:
  bursts = []
  for bucket in history:
    total = int(bucket.get("total", 0))
    if total <= 0:
      continue
    route_counts = bucket.get("route_counts") or _empty_traffic_counts(TRAFFIC_ROUTE_KEYS)
    payload_counts = bucket.get("payload_counts") or _empty_traffic_counts(TRAFFIC_PAYLOAD_KEYS)
    route_lead = _dominant_traffic_key(route_counts, TRAFFIC_ROUTE_KEYS)
    payload_lead = _dominant_traffic_key(payload_counts, TRAFFIC_PAYLOAD_KEYS)
    bursts.append(
      {
        "ts": bucket["ts"],
        "bucket_seconds": bucket["bucket_seconds"],
        "total": total,
        "route_lead": route_lead,
        "route_lead_share": round((route_counts.get(route_lead, 0) / total) * 100, 1),
        "payload_lead": payload_lead,
        "payload_lead_share": round((payload_counts.get(payload_lead, 0) / total) * 100, 1),
      }
    )
  bursts.sort(key=lambda item: (-int(item["total"]), -float(item["ts"])))
  return bursts[:TRAFFIC_BURST_LIMIT]


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
  return traffic


def _decode_group_text_payloads(
  raw_hex_values: list[str],
  channel_key: str,
) -> tuple[Dict[str, Dict[str, Any]], str]:
  normalized = []
  seen = set()
  for raw_hex in raw_hex_values:
    candidate = str(raw_hex or "").strip().upper()
    if not candidate or candidate in seen:
      continue
    seen.add(candidate)
    normalized.append(candidate)
  if not normalized:
    return {}, ""

  decoded_by_raw: Dict[str, Dict[str, Any]] = {}
  chunk_size = 500
  for index in range(0, len(normalized), chunk_size):
    chunk = normalized[index:index + chunk_size]
    try:
      completed = subprocess.run(
        ["node", BATTERYINFO_DECODER_PATH],
        input=json.dumps({
          "channelKey": channel_key,
          "rawHexes": chunk,
        }),
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT_DIR,
        timeout=20,
      )
    except FileNotFoundError:
      print("[mqtt-dashboard] batteryinfo decoder unavailable: node missing")
      return {}, "decoder_unavailable"
    except subprocess.TimeoutExpired:
      print("[mqtt-dashboard] batteryinfo decoder timed out")
      return {}, "decoder_failed"
    except subprocess.CalledProcessError as exc:
      stderr = (exc.stderr or "").strip()
      if stderr:
        print(f"[mqtt-dashboard] batteryinfo decoder failed: {stderr}")
      else:
        print("[mqtt-dashboard] batteryinfo decoder failed")
      return {}, "decoder_failed"

    try:
      payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
      print("[mqtt-dashboard] batteryinfo decoder returned invalid JSON")
      return {}, "decoder_failed"

    results = payload.get("results")
    if not isinstance(results, dict):
      print("[mqtt-dashboard] batteryinfo decoder returned invalid payload")
      return {}, "decoder_failed"

    for raw_hex, decoded in results.items():
      normalized_raw = str(raw_hex or "").strip().upper()
      if not normalized_raw or not isinstance(decoded, dict):
        continue
      text = str(decoded.get("text") or "").strip()
      if not text:
        continue
      decoded_by_raw[normalized_raw] = {
        "sender_timestamp": int(decoded.get("sender_timestamp") or 0),
        "flags": int(decoded.get("flags") or 0),
        "text": text,
      }

  return decoded_by_raw, ""


def _parse_optional_metric(match: Optional[re.Match]) -> Optional[float]:
  if not match:
    return None
  raw_value = str(match.group("value") or "").strip().lower()
  if raw_value == "na":
    return None
  try:
    return float(raw_value)
  except ValueError:
    return None


def _parse_batteryinfo_message(text: str) -> Optional[Dict[str, Any]]:
  text = (text or "").strip()
  if not text:
    return None
  prefix = ""
  body = text
  if ":" in text:
    prefix, body = text.split(":", 1)
    prefix = prefix.strip()
    body = body.strip()
  battery_match = BATTERYINFO_BATTERY_PATTERN.search(body)
  if not battery_match:
    return None
  return {
    "sender_name": prefix or None,
    "message_body": body,
    "battery_v": float(battery_match.group("volts")),
    "battery_percent": int(battery_match.group("percent")),
    "temp_c": _parse_optional_metric(BATTERYINFO_TEMP_PATTERN.search(body)),
    "humidity_percent": _parse_optional_metric(BATTERYINFO_HUM_PATTERN.search(body)),
    "pressure_hpa": _parse_optional_metric(BATTERYINFO_PRESS_PATTERN.search(body)),
    "altitude_m": _parse_optional_metric(BATTERYINFO_ALT_PATTERN.search(body)),
  }


def _batteryinfo_key_fingerprint(channel_key: str) -> str:
  return hashlib.sha256(channel_key.encode("ascii", "ignore")).hexdigest()


def _decode_batteryinfo_entries(
  rows: list[tuple[Any, Any, Any, Any, Any]],
  channel_key: str,
) -> tuple[list[Dict[str, Any]], str]:
  raw_hex_values = []
  for _, _, _, _, payload_json_text in rows:
    if not payload_json_text:
      continue
    try:
      payload_json = json.loads(payload_json_text)
    except json.JSONDecodeError:
      continue
    if not isinstance(payload_json, dict):
      continue
    if str(payload_json.get("packet_type") or "").strip() != "5":
      continue
    raw_hex = str(payload_json.get("raw") or "").strip().upper()
    if raw_hex:
      raw_hex_values.append(raw_hex)

  decoded_packets, decoder_error = _decode_group_text_payloads(raw_hex_values, channel_key)
  if raw_hex_values and decoder_error:
    return [], decoder_error

  entries = []
  seen: Set[str] = set()
  for ts, topic, node_id, packet_name, payload_json_text in rows:
    if not payload_json_text:
      continue
    try:
      payload_json = json.loads(payload_json_text)
    except json.JSONDecodeError:
      continue
    if not isinstance(payload_json, dict):
      continue
    if str(payload_json.get("packet_type") or "").strip() != "5":
      continue
    raw_hex = str(payload_json.get("raw") or "").strip().upper()
    decoded = decoded_packets.get(raw_hex)
    if not decoded:
      continue
    parsed = _parse_batteryinfo_message(decoded["text"])
    if not parsed:
      continue
    dedupe_key = f"{decoded['sender_timestamp']}|{parsed['message_body']}"
    if dedupe_key in seen:
      continue
    seen.add(dedupe_key)
    sender_name = parsed["sender_name"] or packet_name or node_id or "Unknown"
    entries.append(
      {
        "ts": float(ts),
        "dedupe_key": dedupe_key,
        "sender_timestamp": int(decoded["sender_timestamp"]),
        "node_id": node_id,
        "packet_name": packet_name,
        "sender_name": sender_name,
        "topic": topic,
        "text": decoded["text"],
        "message_body": parsed["message_body"],
        "battery_v": parsed["battery_v"],
        "battery_percent": parsed["battery_percent"],
        "temp_c": parsed["temp_c"],
        "humidity_percent": parsed["humidity_percent"],
        "pressure_hpa": parsed["pressure_hpa"],
        "altitude_m": parsed["altitude_m"],
      }
    )
  return entries, ""


def _persist_batteryinfo_entries(entries: list[Dict[str, Any]], key_fingerprint: str) -> None:
  if packet_db is None or not entries:
    return
  with packet_db_lock:
    packet_db.executemany(
      """
      INSERT OR IGNORE INTO batteryinfo_events (
        ts, dedupe_key, sender_timestamp, node_id, packet_name, sender_name,
        topic, text, message_body, battery_v, battery_percent, temp_c,
        humidity_percent, pressure_hpa, altitude_m, key_fingerprint
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      [
        (
          entry["ts"],
          entry["dedupe_key"],
          entry["sender_timestamp"],
          entry.get("node_id"),
          entry.get("packet_name"),
          entry["sender_name"],
          entry["topic"],
          entry["text"],
          entry["message_body"],
          entry["battery_v"],
          entry["battery_percent"],
          entry.get("temp_c"),
          entry.get("humidity_percent"),
          entry.get("pressure_hpa"),
          entry.get("altitude_m"),
          key_fingerprint,
        )
        for entry in entries
      ],
    )
    packet_db.commit()


def _backfill_batteryinfo_events_from_packets(channel_key: str) -> str:
  if packet_db is None:
    return ""
  cutoff = time.time() - max(0, BATTERYINFO_RETENTION_SECONDS)
  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT ts, topic, node_id, name, payload_json
      FROM packets
      WHERE ts >= ?
        AND topic LIKE '%/packets'
        AND payload_json IS NOT NULL
        AND payload_json != ''
        AND payload_json LIKE '%"packet_type":"5"%'
      ORDER BY ts ASC
      """,
      (cutoff,),
    ).fetchall()
  if not rows:
    return ""
  entries, decoder_error = _decode_batteryinfo_entries(rows, channel_key)
  if decoder_error:
    return decoder_error
  _persist_batteryinfo_entries(entries, _batteryinfo_key_fingerprint(channel_key))
  return ""


def _load_batteryinfo_events() -> None:
  if packet_db is None:
    return
  if not BATTERYINFO_ENABLED:
    return
  channel_key = _parse_channel_secret(BATTERYINFO_CHANNEL_KEY)
  if channel_key is None:
    return
  fingerprint = _batteryinfo_key_fingerprint(channel_key)
  with packet_db_lock:
    total_count = packet_db.execute(
      "SELECT COUNT(*) FROM batteryinfo_events"
    ).fetchone()[0]
    matching_count = packet_db.execute(
      "SELECT COUNT(*) FROM batteryinfo_events WHERE key_fingerprint = ?",
      (fingerprint,),
    ).fetchone()[0]
  if total_count == 0:
    error = _backfill_batteryinfo_events_from_packets(channel_key)
    if error:
      print(f"[mqtt-dashboard] batteryinfo backfill failed: {error}")
    return
  if matching_count == total_count:
    return
  with packet_db_lock:
    packet_db.execute("DELETE FROM batteryinfo_events")
    packet_db.commit()
  error = _backfill_batteryinfo_events_from_packets(channel_key)
  if error:
    print(f"[mqtt-dashboard] batteryinfo rebuild failed: {error}")


def _record_batteryinfo_event(
  topic: str,
  payload_info: Dict[str, Any],
  node: NodeState,
  ts: float,
) -> None:
  if packet_db is None:
    return
  if not BATTERYINFO_ENABLED:
    return
  channel_key = _parse_channel_secret(BATTERYINFO_CHANNEL_KEY)
  if channel_key is None:
    return
  payload_json = payload_info.get("json")
  if not isinstance(payload_json, dict):
    return
  if str(payload_json.get("packet_type") or "").strip() != "5":
    return
  payload_json_text = json.dumps(payload_json, ensure_ascii=True)
  entries, decoder_error = _decode_batteryinfo_entries(
    [(ts, topic, node.node_id, node.name, payload_json_text)],
    channel_key,
  )
  if decoder_error:
    print(f"[mqtt-dashboard] batteryinfo live decode failed: {decoder_error}")
    return
  _persist_batteryinfo_entries(entries, _batteryinfo_key_fingerprint(channel_key))


def _fetch_batteryinfo(now: Optional[float] = None) -> Dict[str, Any]:
  if packet_db is None:
    return {
      "enabled": False,
      "reason": "packet_db_disabled",
      "retention_seconds": BATTERYINFO_RETENTION_SECONDS,
      "entries": [],
      "nodes": [],
      "metrics": [],
      "stats": {"reports": 0, "nodes": 0, "latest_report_at": 0.0},
    }
  secret = _parse_channel_secret(BATTERYINFO_CHANNEL_KEY)
  if secret is None:
    return {
      "enabled": False,
      "reason": "missing_channel_key",
      "retention_seconds": BATTERYINFO_RETENTION_SECONDS,
      "entries": [],
      "nodes": [],
      "metrics": [],
      "stats": {"reports": 0, "nodes": 0, "latest_report_at": 0.0},
    }

  now = float(now or time.time())
  cutoff = now - max(0, BATTERYINFO_RETENTION_SECONDS)
  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT
        ts,
        sender_timestamp,
        node_id,
        packet_name,
        sender_name,
        topic,
        text,
        message_body,
        battery_v,
        battery_percent,
        temp_c,
        humidity_percent,
        pressure_hpa,
        altitude_m
      FROM batteryinfo_events
      WHERE ts >= ?
      ORDER BY ts ASC
      """,
      (cutoff,),
    ).fetchall()

  entries = []
  metrics_present = set()
  latest_by_node: Dict[str, Dict[str, Any]] = {}
  for (
    ts,
    sender_timestamp,
    node_id,
    packet_name,
    sender_name,
    topic,
    text,
    message_body,
    battery_v,
    battery_percent,
    temp_c,
    humidity_percent,
    pressure_hpa,
    altitude_m,
  ) in rows:
    entry = {
      "ts": float(ts),
      "sender_timestamp": int(sender_timestamp or 0),
      "node_id": node_id,
      "packet_name": packet_name,
      "sender_name": sender_name or packet_name or node_id or "Unknown",
      "topic": topic,
      "text": text,
      "message_body": message_body,
      "battery_v": float(battery_v),
      "battery_percent": int(battery_percent),
      "temp_c": temp_c,
      "humidity_percent": humidity_percent,
      "pressure_hpa": pressure_hpa,
      "altitude_m": altitude_m,
    }
    entries.append(entry)
    for metric_key in (
      "battery_v",
      "battery_percent",
      "temp_c",
      "humidity_percent",
      "pressure_hpa",
      "altitude_m",
    ):
      if entry.get(metric_key) is not None:
        metrics_present.add(metric_key)
    if sender_name not in latest_by_node or entry["ts"] >= latest_by_node[sender_name]["ts"]:
      latest_by_node[sender_name] = entry

  entries.sort(key=lambda item: item["ts"])
  nodes = sorted(
    latest_by_node.values(),
    key=lambda item: (-item["ts"], item["sender_name"].lower()),
  )

  latest_report = nodes[0] if nodes else None
  stats = {
    "reports": len(entries),
    "nodes": len(nodes),
    "latest_report_at": latest_report["ts"] if latest_report else 0.0,
    "latest_battery_v": latest_report["battery_v"] if latest_report else None,
    "latest_battery_percent": latest_report["battery_percent"] if latest_report else None,
  }

  return {
    "enabled": True,
    "reason": "",
    "retention_seconds": BATTERYINFO_RETENTION_SECONDS,
    "entries": entries,
    "nodes": nodes,
    "metrics": sorted(metrics_present),
    "stats": stats,
  }


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
    "neighbors": _build_neighbors_topology(),
  }


def _queue_broadcast(message: Dict[str, Any]) -> None:
  if not _has_ws_clients():
    return
  loop = getattr(app.state, "loop", None)
  if loop and loop.is_running():
    loop.call_soon_threadsafe(broadcast_queue.put_nowait, message)


def _has_ws_clients() -> bool:
  with state_lock:
    return ws_client_count > 0


def _ensure_neighbor_snapshots_table() -> None:
  if packet_db is None:
    return
  with packet_db_lock:
    packet_db.execute(
      """
      CREATE TABLE IF NOT EXISTS neighbor_snapshots (
        observer_id TEXT PRIMARY KEY,
        received_at REAL NOT NULL,
        topic TEXT NOT NULL,
        payload_json TEXT NOT NULL
      )
      """
    )
    packet_db.commit()


def _store_neighbor_snapshot(snapshot: Dict[str, Any]) -> bool:
  observer_id = snapshot["observer_id"]
  with state_lock:
    existing = neighbor_snapshots.get(observer_id)
    existing_time = (
      float(existing.get("reported_at") or existing.get("received_at") or 0.0)
      if existing
      else 0.0
    )
    snapshot_time = float(snapshot.get("reported_at") or snapshot.get("received_at") or 0.0)
    if existing_time > snapshot_time:
      return False
    neighbor_snapshots[observer_id] = snapshot
  if packet_db is None:
    return True
  payload_json = json.dumps(snapshot, ensure_ascii=True, separators=(",", ":"))
  with packet_db_lock:
    packet_db.execute(
      """
      INSERT INTO neighbor_snapshots (observer_id, received_at, topic, payload_json)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(observer_id) DO UPDATE SET
        received_at = excluded.received_at,
        topic = excluded.topic,
        payload_json = excluded.payload_json
      """,
      (
        observer_id,
        float(snapshot.get("received_at") or 0.0),
        snapshot.get("topic") or "",
        payload_json,
      ),
    )
    packet_db.commit()
  return True


def _delete_neighbor_snapshot(observer_id: str) -> bool:
  with state_lock:
    removed = neighbor_snapshots.pop(observer_id, None) is not None
  if packet_db is not None:
    with packet_db_lock:
      cursor = packet_db.execute(
        "DELETE FROM neighbor_snapshots WHERE observer_id = ?",
        (observer_id,),
      )
      packet_db.commit()
      removed = removed or cursor.rowcount > 0
  return removed


def _load_neighbor_snapshots() -> None:
  if packet_db is None:
    return
  with packet_db_lock:
    rows = packet_db.execute(
      "SELECT observer_id, payload_json FROM neighbor_snapshots ORDER BY received_at DESC"
    ).fetchall()
  loaded = {}
  for observer_id, payload_json in rows:
    normalized_id = _normalize_pubkey(observer_id)
    if not normalized_id:
      continue
    try:
      snapshot = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
      continue
    if not isinstance(snapshot, dict) or snapshot.get("observer_id") != normalized_id:
      continue
    if not isinstance(snapshot.get("neighbors"), list):
      continue
    loaded[normalized_id] = snapshot
  with state_lock:
    neighbor_snapshots.update(loaded)


def _init_packet_db() -> None:
  global packet_db
  if not PACKET_DB_PATH:
    return
  os.makedirs(os.path.dirname(PACKET_DB_PATH), exist_ok=True)
  packet_db = sqlite3.connect(PACKET_DB_PATH, check_same_thread=False)
  packet_db.execute("PRAGMA journal_mode=WAL")
  packet_db.execute("PRAGMA synchronous=NORMAL")
  packet_db.execute("PRAGMA temp_store=MEMORY")
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
  traffic_columns = {
    row[1]
    for row in packet_db.execute("PRAGMA table_info(traffic_events)").fetchall()
  }
  for column_name, column_type in (
    ("node_id", "TEXT"),
    ("name", "TEXT"),
    ("topic", "TEXT"),
  ):
    if column_name not in traffic_columns:
      packet_db.execute(
        f"ALTER TABLE traffic_events ADD COLUMN {column_name} {column_type}"
      )
  packet_db.execute("CREATE INDEX IF NOT EXISTS idx_traffic_events_ts ON traffic_events (ts)")
  packet_db.execute(
    "CREATE INDEX IF NOT EXISTS idx_traffic_events_dedupe_ts ON traffic_events (dedupe_key, ts)"
  )
  packet_db.execute(
    """
    CREATE TABLE IF NOT EXISTS batteryinfo_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      dedupe_key TEXT NOT NULL,
      sender_timestamp INTEGER NOT NULL,
      node_id TEXT,
      packet_name TEXT,
      sender_name TEXT NOT NULL,
      topic TEXT NOT NULL,
      text TEXT NOT NULL,
      message_body TEXT NOT NULL,
      battery_v REAL NOT NULL,
      battery_percent INTEGER NOT NULL,
      temp_c REAL,
      humidity_percent REAL,
      pressure_hpa REAL,
      altitude_m REAL,
      key_fingerprint TEXT NOT NULL
    )
    """
  )
  packet_db.execute(
    "CREATE INDEX IF NOT EXISTS idx_batteryinfo_events_ts ON batteryinfo_events (ts)"
  )
  packet_db.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_batteryinfo_events_dedupe ON batteryinfo_events (dedupe_key)"
  )
  packet_db.commit()
  _ensure_neighbor_snapshots_table()


def _load_name_cache() -> None:
  if packet_db is None or PACKET_RETENTION_SECONDS <= 0:
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
  if packet_db is None or PACKET_RETENTION_SECONDS <= 0:
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
      packet_db.execute("DELETE FROM batteryinfo_events WHERE ts < ?", (cutoff,))
      last_packet_purge = now
    packet_db.commit()


def _fetch_packets(limit: int, node_id: Optional[str]) -> Dict[str, Any]:
  if packet_db is None or PACKET_RETENTION_SECONDS <= 0:
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


def _fetch_traffic_packets(start: float, end: float, limit: int) -> Dict[str, Any]:
  if packet_db is None:
    return {"enabled": False, "packets": []}
  start_ts = max(0.0, float(start or 0.0))
  end_ts = max(start_ts, float(end or start_ts))
  limit = max(1, min(int(limit or 0), TRAFFIC_DRILLDOWN_LIMIT))
  fetch_limit = max(limit * 4, 200)
  with packet_db_lock:
    rows = packet_db.execute(
      """
      SELECT ts, topic, node_id, name, role, payload_text, payload_json
      FROM packets
      WHERE ts >= ? AND ts < ? AND topic LIKE '%/packets'
      ORDER BY ts DESC
      LIMIT ?
      """,
      (start_ts, end_ts, fetch_limit),
    ).fetchall()

  packets = []
  seen: Set[str] = set()
  for row in rows:
    packet_event = _build_packet_event_from_row(row[1], row[6] or "", row[0], row[2], row[3])
    dedupe_key = packet_event.get("dedupe_key") if packet_event else None
    if dedupe_key and dedupe_key in seen:
      continue
    if dedupe_key:
      seen.add(dedupe_key)
    packets.append(
      {
        "ts": row[0],
        "topic": row[1],
        "node_id": row[2],
        "name": row[3],
        "role": row[4],
        "route": packet_event.get("route", "other") if packet_event else "other",
        "payload": packet_event.get("payload", "other") if packet_event else "other",
        "payload_text": _redact_sensitive_text(row[5] or ""),
        "payload_json": _redact_payload_json_text(row[6] or ""),
      }
    )
    if len(packets) >= limit:
      break
  return {
    "enabled": True,
    "start": start_ts,
    "end": end_ts,
    "packets": packets,
  }


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
  should_broadcast = _has_ws_clients()
  now = time.time()

  if _is_sys_topic(topic):
    sys_value = _update_sys(topic, payload_info)
    if should_broadcast:
      _queue_broadcast(
        {
          "type": "sys_update",
          "topic": topic,
          "value": sys_value,
          "received_at": time.time(),
        }
      )
    return

  if _should_ignore_retained_message(topic, msg):
    return

  tombstone_observer_id = _neighbors_observer_from_topic(topic)
  if tombstone_observer_id and getattr(msg, "retain", False) and not msg.payload:
    neighbor_updated = _delete_neighbor_snapshot(tombstone_observer_id)
    if should_broadcast and neighbor_updated:
      _queue_broadcast(
        {
          "type": "neighbors_update",
          "neighbors": _build_neighbors_topology(),
        }
      )
    return

  neighbor_snapshot = _normalize_neighbors_snapshot(topic, payload_info.get("json"), now)
  neighbor_updated = bool(neighbor_snapshot and _store_neighbor_snapshot(neighbor_snapshot))

  packet_event = _extract_packet_event(topic, payload_info)
  node = _update_node(topic, payload_info)
  _record_message()
  _save_packet(topic, payload_info, node)
  unique_packet_event = _record_traffic_event(packet_event)
  if BATTERYINFO_ENABLED:
    _record_batteryinfo_event(topic, payload_info, node, now)
  if not should_broadcast:
    return
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
  if neighbor_updated:
    _queue_broadcast(
      {
        "type": "neighbors_update",
        "neighbors": _build_neighbors_topology(),
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
  print(f"[mqtt-dashboard] Starting {APP_VERSION}", flush=True)
  app.state.loop = asyncio.get_running_loop()
  app.state.broadcast_task = asyncio.create_task(_broadcast_worker())
  global role_overrides
  role_overrides = _load_role_overrides()
  _init_packet_db()
  _load_name_cache()
  _load_neighbor_snapshots()
  _load_traffic_events()
  _load_batteryinfo_events()
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


@app.get("/neighbors")
async def neighbors(request: Request) -> HTMLResponse:
  return HTMLResponse(_render_neighbors_html(str(request.url)))


@app.get("/neighbors/data")
async def neighbors_data() -> JSONResponse:
  return JSONResponse(_build_neighbors_topology())


@app.get("/batteryinfo")
async def batteryinfo(request: Request) -> HTMLResponse:
  if not BATTERYINFO_ENABLED:
    raise HTTPException(status_code=404, detail="Not Found")
  return HTMLResponse(_render_batteryinfo_html(str(request.url)))


@app.get("/batteryinfo/data")
async def batteryinfo_data() -> JSONResponse:
  if not BATTERYINFO_ENABLED:
    raise HTTPException(status_code=404, detail="Not Found")
  return JSONResponse(_fetch_batteryinfo())


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


@app.get("/traffic/packets")
async def traffic_packets(
  start: float = Query(..., ge=0),
  end: float = Query(..., ge=0),
  limit: int = Query(80, ge=1, le=TRAFFIC_DRILLDOWN_LIMIT),
) -> JSONResponse:
  return JSONResponse(_fetch_traffic_packets(start, end, limit))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
  global ws_client_count
  await ws.accept()
  with state_lock:
    ws_clients.add(ws)
    ws_client_count = len(ws_clients)
  await ws.send_json({"type": "snapshot", **_build_snapshot()})
  try:
    while True:
      await ws.receive_text()
  except WebSocketDisconnect:
    with state_lock:
      ws_clients.discard(ws)
      ws_client_count = len(ws_clients)
