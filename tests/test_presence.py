from types import SimpleNamespace

import app as dashboard_app


def test_retained_internal_message_does_not_create_online_node():
  msg = SimpleNamespace(
    topic="meshcore/BOS/node-retained/internal",
    payload=b'{"origin_id":"node-retained"}',
    retain=True,
  )

  dashboard_app.mqtt_on_message(None, None, msg)

  assert "node-retained" not in dashboard_app.nodes
  assert dashboard_app.message_total == 0


def test_non_retained_internal_message_still_updates_node():
  msg = SimpleNamespace(
    topic="meshcore/BOS/node-live/internal",
    payload=b'{"origin_id":"node-live"}',
    retain=False,
  )

  dashboard_app.mqtt_on_message(None, None, msg)

  assert "node-live" in dashboard_app.nodes
  assert dashboard_app.message_total == 1
