import hashlib
import hmac
import sqlite3
import time

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

import app as dashboard_app


def _build_group_text_raw(secret_hex: str, text: str, sender_timestamp: int) -> str:
  secret = bytes.fromhex(secret_hex)
  channel_hash = hashlib.sha256(secret).digest()[:1]
  secret_mac = secret + (b"\0" * 16)
  plaintext = sender_timestamp.to_bytes(4, "little") + b"\0" + text.encode("utf-8")
  pad_len = (-len(plaintext)) % 16
  plaintext += b"\0" * pad_len

  cipher = Cipher(algorithms.AES(secret), modes.ECB(), backend=default_backend())
  encryptor = cipher.encryptor()
  ciphertext = encryptor.update(plaintext) + encryptor.finalize()
  mac = hmac.new(secret_mac, ciphertext, hashlib.sha256).digest()[:2]

  raw = bytes([0x15, 0x00]) + channel_hash + mac + ciphertext
  return raw.hex().upper()


def test_batteryinfo_data_decodes_and_dedupes_channel_reports(monkeypatch, tmp_path):
  db_path = tmp_path / "batteryinfo.db"
  original_path = dashboard_app.PACKET_DB_PATH
  original_db = dashboard_app.packet_db
  original_enabled = dashboard_app.BATTERYINFO_ENABLED
  original_key = dashboard_app.BATTERYINFO_CHANNEL_KEY

  secret_hex = "1cbfc5bff8423774fbf3f5c8db09c60d"
  raw_one = _build_group_text_raw(
    secret_hex,
    "ProMicro Repeater: battery=5.45v 100% temp=19.5c hum=na% press=nahPa alt=nam",
    1710000001,
  )
  raw_two = _build_group_text_raw(
    secret_hex,
    "GRF - POTTER HILL: battery=3.97V 80%",
    1710000301,
  )
  packet_one = (
    '{"packet_type":"5","route":"F","hash":"hash-1","raw":"%s"}'
    % raw_one
  )
  packet_two = (
    '{"packet_type":"5","route":"F","hash":"hash-2","raw":"%s"}'
    % raw_two
  )
  base_ts = time.time() - 60

  try:
    dashboard_app.packet_db = None
    dashboard_app.PACKET_DB_PATH = str(db_path)
    dashboard_app.BATTERYINFO_ENABLED = True
    dashboard_app.BATTERYINFO_CHANNEL_KEY = secret_hex
    dashboard_app._init_packet_db()

    with dashboard_app.packet_db_lock:
      dashboard_app.packet_db.executemany(
        """
        INSERT INTO packets (ts, topic, node_id, name, role, payload_text, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
          (base_ts, "meshcore/BOS/node-a/packets", "node-a", "Observer A", None, packet_one, packet_one),
          (base_ts + 1, "meshcore/BOS/node-b/packets", "node-b", "Observer B", None, packet_one, packet_one),
          (base_ts + 60, "meshcore/BOS/node-c/packets", "node-c", "Observer C", None, packet_two, packet_two),
        ],
      )
      dashboard_app.packet_db.commit()

    with TestClient(dashboard_app.app) as client:
      html = client.get("/batteryinfo")
      assert html.status_code == 200
      response = client.get("/batteryinfo/data")
      assert response.status_code == 200
      with dashboard_app.packet_db_lock:
        persisted = dashboard_app.packet_db.execute(
          "SELECT COUNT(*) FROM batteryinfo_events"
        ).fetchone()[0]

    payload = response.json()
    assert payload["enabled"] is True
    assert payload["stats"]["reports"] == 2
    assert payload["stats"]["nodes"] == 2
    assert persisted == 2
    assert payload["entries"][0]["sender_name"] == "ProMicro Repeater"
    assert payload["entries"][0]["battery_v"] == 5.45
    assert payload["entries"][0]["battery_percent"] == 100
    assert payload["entries"][0]["temp_c"] == 19.5
    assert payload["entries"][0]["humidity_percent"] is None
    assert payload["entries"][1]["sender_name"] == "GRF - POTTER HILL"
    assert payload["entries"][1]["battery_percent"] == 80
    assert payload["nodes"][0]["sender_name"] == "GRF - POTTER HILL"
  finally:
    dashboard_app._close_packet_db()
    dashboard_app.packet_db = original_db
    dashboard_app.PACKET_DB_PATH = original_path
    dashboard_app.BATTERYINFO_ENABLED = original_enabled
    dashboard_app.BATTERYINFO_CHANNEL_KEY = original_key


def test_batteryinfo_data_is_disabled_without_channel_key(monkeypatch, tmp_path):
  db_path = tmp_path / "batteryinfo-disabled.db"
  original_path = dashboard_app.PACKET_DB_PATH
  original_db = dashboard_app.packet_db
  original_enabled = dashboard_app.BATTERYINFO_ENABLED
  original_key = dashboard_app.BATTERYINFO_CHANNEL_KEY

  try:
    dashboard_app.packet_db = None
    dashboard_app.PACKET_DB_PATH = str(db_path)
    dashboard_app.BATTERYINFO_ENABLED = True
    dashboard_app.BATTERYINFO_CHANNEL_KEY = ""
    dashboard_app._init_packet_db()

    payload = dashboard_app._fetch_batteryinfo(now=500.0)
    assert payload["enabled"] is False
    assert payload["reason"] == "missing_channel_key"
  finally:
    dashboard_app._close_packet_db()
    dashboard_app.packet_db = original_db
    dashboard_app.PACKET_DB_PATH = original_path
    dashboard_app.BATTERYINFO_ENABLED = original_enabled
    dashboard_app.BATTERYINFO_CHANNEL_KEY = original_key


def test_batteryinfo_routes_404_when_disabled(client):
  html = client.get("/batteryinfo")
  assert html.status_code == 404
  data = client.get("/batteryinfo/data")
  assert data.status_code == 404
  index = client.get("/")
  assert 'href="/batteryinfo"' not in index.text
  traffic = client.get("/traffic")
  assert 'href="/batteryinfo"' not in traffic.text
