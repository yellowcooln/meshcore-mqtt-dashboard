import sys
from collections import deque
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_PATH = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_PATH) not in sys.path:
  sys.path.insert(0, str(BACKEND_PATH))

import app as dashboard_app


@pytest.fixture
def client(monkeypatch):
  monkeypatch.setattr(dashboard_app, "start_mqtt", lambda: None)
  monkeypatch.setattr(dashboard_app, "stop_mqtt", lambda: None)
  monkeypatch.setattr(dashboard_app, "_load_role_overrides", lambda: {})
  monkeypatch.setattr(dashboard_app, "_init_packet_db", lambda: None)
  monkeypatch.setattr(dashboard_app, "_close_packet_db", lambda: None)
  monkeypatch.setattr(dashboard_app, "_load_name_cache", lambda: None)

  dashboard_app.packet_db = None
  dashboard_app.role_overrides = {}
  dashboard_app.template_html_cache = {}
  dashboard_app.DASH_API_TOKEN = ""
  dashboard_app.DASH_API_TOKEN_HEADER = "X-Dashboard-Token"
  dashboard_app.DASH_TITLE = "MQTT Observatory"
  dashboard_app.DASH_DESCRIPTION = "Live node presence, roles, and broker telemetry."
  dashboard_app.DASH_BROKER_HOST = ""
  dashboard_app.DASH_LOGO_URL = ""
  dashboard_app.nodes = {}
  dashboard_app.sys_topics = {}
  dashboard_app.message_times = deque()
  dashboard_app.message_total = 0
  dashboard_app.last_message_at = 0.0
  dashboard_app.last_sys_at = 0.0
  dashboard_app.traffic_events = deque()
  dashboard_app.traffic_identity_queue = deque()
  dashboard_app.traffic_identity_seen = {}
  dashboard_app.traffic_packets_total = 0
  dashboard_app.last_traffic_packet_at = 0.0
  dashboard_app.broker_state["display_host"] = dashboard_app.MQTT_HOST
  dashboard_app.broker_state["host"] = dashboard_app.MQTT_HOST
  dashboard_app.broker_state["port"] = dashboard_app.MQTT_PORT
  dashboard_app.broker_state["transport"] = dashboard_app.MQTT_TRANSPORT
  dashboard_app.broker_state["ws_path"] = dashboard_app.MQTT_WS_PATH
  dashboard_app.broker_state["tls"] = dashboard_app.MQTT_TLS
  dashboard_app.broker_state["topic"] = dashboard_app.MQTT_TOPIC_RAW
  dashboard_app.broker_state["title"] = dashboard_app.DASH_TITLE

  with TestClient(dashboard_app.app) as test_client:
    yield test_client
