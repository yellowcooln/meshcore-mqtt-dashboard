import app as dashboard_app


def test_redaction_preserves_client_version_dotted_value():
  payload = {
    "client_version": "meshcoretomqtt/1.0.8.0-e52c5ed",
    "firmware_version": "1.13.0-letsmesh.net-295f67d",
    "ip": "10.9.8.7",
    "note": "Connected from 10.9.8.7",
    "mac": "aa:bb:cc:dd:ee:ff",
  }
  redacted = dashboard_app._redact_sensitive_payload(payload)

  assert redacted["client_version"] == "meshcoretomqtt/1.0.8.0-e52c5ed"
  assert redacted["firmware_version"] == "1.13.0-letsmesh.net-295f67d"
  assert redacted["ip"] == "[redacted]"
  assert redacted["note"] == "Connected from [redacted-ip]"
  assert redacted["mac"] == "[redacted]"
