import app as dashboard_app


def test_public_index_is_accessible_without_token(client):
  response = client.get("/")
  assert response.status_code == 200


def test_snapshot_requires_token_when_enabled(client):
  dashboard_app.DASH_API_TOKEN = "test-token"
  response = client.get("/snapshot")
  assert response.status_code == 401
  assert response.json() == {"detail": "Unauthorized"}


def test_snapshot_accepts_configured_header_token(client):
  dashboard_app.DASH_API_TOKEN = "test-token"
  dashboard_app.DASH_API_TOKEN_HEADER = "X-Dashboard-Token"
  response = client.get("/snapshot", headers={"X-Dashboard-Token": "test-token"})
  assert response.status_code == 200
  payload = response.json()
  assert "broker" in payload
  assert "stats" in payload


def test_stats_accepts_bearer_token(client):
  dashboard_app.DASH_API_TOKEN = "test-token"
  response = client.get("/stats", headers={"Authorization": "Bearer test-token"})
  assert response.status_code == 200
  assert "messages_total" in response.json()


def test_packets_accepts_query_token(client):
  dashboard_app.DASH_API_TOKEN = "test-token"
  response = client.get("/packets?token=test-token")
  assert response.status_code == 200
  payload = response.json()
  assert "packets" in payload


def test_snapshot_exposes_display_host_override(client):
  dashboard_app.broker_state["host"] = "host.docker.internal"
  dashboard_app.broker_state["display_host"] = "Boston MQTT"
  response = client.get("/snapshot")
  assert response.status_code == 200
  payload = response.json()
  assert payload["broker"]["host"] == "host.docker.internal"
  assert payload["broker"]["display_host"] == "Boston MQTT"


def test_snapshot_allows_display_host_with_public_port(client):
  dashboard_app.broker_state["host"] = "host.docker.internal"
  dashboard_app.broker_state["port"] = 8883
  dashboard_app.broker_state["display_host"] = "mqttmc01.bostonme.sh:443"
  response = client.get("/snapshot")
  assert response.status_code == 200
  payload = response.json()
  assert payload["broker"]["host"] == "host.docker.internal"
  assert payload["broker"]["port"] == 8883
  assert payload["broker"]["display_host"] == "mqttmc01.bostonme.sh:443"
