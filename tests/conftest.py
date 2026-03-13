import sys
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
  dashboard_app.index_template_html = None
  dashboard_app.DASH_API_TOKEN = ""
  dashboard_app.DASH_API_TOKEN_HEADER = "X-Dashboard-Token"
  dashboard_app.DASH_TITLE = "MQTT Observatory"
  dashboard_app.DASH_DESCRIPTION = "Live node presence, roles, and broker telemetry."
  dashboard_app.DASH_BROKER_HOST = ""
  dashboard_app.DASH_LOGO_URL = ""
  dashboard_app.broker_state["display_host"] = dashboard_app.MQTT_HOST

  with TestClient(dashboard_app.app) as test_client:
    yield test_client
