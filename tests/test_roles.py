import app as dashboard_app


def test_infer_role_from_status_payload_observer_like_sources():
  payload = {
    "model": "Generic ESP32",
    "client_version": "meshcore-dev/meshcore-ha:2.4.0",
    "firmware_version": "v1.14.0",
    "origin": "MNK-observer",
    "status": "online",
  }

  role = dashboard_app._infer_role_from_payload(
    "meshcore/BOS/node-a/status",
    payload,
  )

  assert role == "room"


def test_infer_role_from_status_payload_repeater_like_sources():
  payload = {
    "model": "PyMC-Repeater",
    "client_version": "pyMC_repeater/1.0.8.dev48",
    "origin": "YC-Work-Repeater",
    "status": "online",
  }

  role = dashboard_app._infer_role_from_payload(
    "meshcore/BOS/node-b/status",
    payload,
  )

  assert role == "repeater"


def test_update_node_uses_payload_role_hint_before_name_fallback():
  node = dashboard_app._update_node(
    "meshcore/BOS/node-c/status",
    {
      "text": "",
      "json": {
        "origin_id": "node-c",
        "origin": "South Plymouth MQTT",
        "model": "Heltec V4 OLED",
        "client_version": "meshcoretomqtt/1.0.8.0-e52c5ed",
        "status": "online",
      },
    },
  )

  assert node.role == "room"
  assert node.role_source == "payload_hint"
