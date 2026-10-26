"""Exercise the production image without pytest, HTTPX or cryptography.

Run inside the built image with a disposable /data mount and --network none.
The encrypted packet is a generated test fixture, never a real radio message.
"""
from contextlib import closing
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from websockets.sync.client import connect


NODE_PROBE = r"""
const crypto = require('node:crypto');
if (Number(process.versions.node.split('.')[0]) !== 24) {
  throw new Error('Expected the supported Node 24 LTS runtime');
}
const key = Buffer.from('00112233445566778899aabbccddeeff', 'hex');
const text = 'Dependency Smoke: battery=4.10V 91%';
const plain = Buffer.alloc(5 + Buffer.byteLength(text));
plain.writeUInt32LE(Math.floor(Date.now() / 1000), 0);
plain.write(text, 5);
const padded = Buffer.concat([plain, Buffer.alloc((16 - plain.length % 16) % 16)]);
// Match MeshCore's AES-ECB plus HMAC wire protocol for this test fixture only;
// this is not a recommendation for general-purpose encryption.
const cipher = crypto.createCipheriv('aes-128-ecb', key, null);
cipher.setAutoPadding(false);
const encrypted = Buffer.concat([cipher.update(padded), cipher.final()]);
const mac = crypto.createHmac('sha256', Buffer.concat([key, Buffer.alloc(16)]))
  .update(encrypted).digest().subarray(0, 2);
const raw = Buffer.concat([
  Buffer.from([0x15, 0]), crypto.createHash('sha256').update(key).digest().subarray(0, 1),
  mac, encrypted
]).toString('hex').toUpperCase();
const output = require('node:child_process').execFileSync(
  process.execPath, ['/app/scripts/batteryinfo-decoder.cjs'], {
    input: JSON.stringify({ channelKey: key.toString('hex'), rawHexes: [raw] }),
    encoding: 'utf8'
  }
);
const decoded = JSON.parse(output).results[raw];
if (!decoded || decoded.text !== text) throw new Error('Encrypted decoder roundtrip failed');
console.log(JSON.stringify({ raw, node: process.version }));
"""


def main():
  assert sys.version_info[:2] == (3, 15), "Expected the production Python 3.15 runtime"
  for name in ("pytest", "httpx", "httpx2", "cryptography"):
    try:
      importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
      continue
    raise AssertionError(f"Test-only dependency leaked into production: {name}")

  fixture = json.loads(subprocess.check_output(["node", "-e", NODE_PROBE], text=True, timeout=15))
  with tempfile.TemporaryDirectory(prefix="dashboard-smoke-", dir="/data") as directory:
    data = Path(directory)
    token = secrets.token_urlsafe(24)
    os.environ.update({
      "MQTT_HOST": "127.0.0.1", "MQTT_PORT": "1", "MQTT_TOPIC": "dependency-smoke/#",
      "SYS_TOPICS_ENABLED": "false", "PACKET_DB_PATH": str(data / "packets.db"),
      "ROLE_OVERRIDES_FILE": str(data / "roles.json"), "DASH_API_TOKEN": token,
      "DASH_API_TOKEN_HEADER": "X-Dashboard-Token", "DASH_TITLE": "Dependency runtime smoke",
      "BATTERYINFO_ENABLED": "true", "BATTERYINFO_CHANNEL_KEY": "00112233445566778899aabbccddeeff",
    })
    sys.path.insert(0, "/app")
    dashboard = importlib.import_module("app")

    dashboard._init_packet_db()
    # Seed the compact historical format supported by the existing backfill.
    # Live MQTT ingestion is exercised separately with the normal writer path.
    packet = json.dumps(
      {"packet_type": "5", "route": "F", "hash": "runtime-smoke", "raw": fixture["raw"]},
      separators=(",", ":"),
    )
    now = time.time() - 2
    with dashboard.packet_db_lock:
      dashboard.packet_db.executemany(
        "INSERT INTO packets (ts,topic,node_id,name,role,payload_text,payload_json) VALUES (?,?,?,?,?,?,?)",
        [(now, "dependency-smoke/a/packets", "fixture-a", "Fixture A", None, packet, packet),
         (now + 1, "dependency-smoke/b/packets", "fixture-b", "Fixture B", None, packet, packet)],
      )
      dashboard.packet_db.commit()
    dashboard._close_packet_db()

    headers = {"X-Dashboard-Token": token}
    def request(path, authorized=True):
      req = urllib.request.Request("http://127.0.0.1:8081" + path, headers=headers if authorized else {})
      with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        return response.read()

    for cycle in range(2):
      log_path = data / f"server-{cycle}.log"
      with log_path.open("w") as log:
        process = subprocess.Popen(
          [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8081"],
          cwd="/app", stdout=log, stderr=subprocess.STDOUT,
        )
        try:
          deadline = time.monotonic() + 15
          while True:
            try:
              html = request("/").decode()
              break
            except (urllib.error.URLError, TimeoutError):
              if process.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("Production HTTP bootstrap failed: " + log_path.read_text())
              time.sleep(0.1)
          # The dashboard exposes its version in startup logs, not in HTML.
          assert f"Starting {dashboard.APP_VERSION}" in log_path.read_text()
          assert "Dependency runtime smoke" in html
          request("/traffic")
          request("/batteryinfo")
          for path in ("/snapshot", "/stats", "/packets"):
            try:
              request(path, authorized=False)
            except urllib.error.HTTPError as error:
              assert error.code == 401
            else:
              raise AssertionError(f"Anonymous protected API was accepted: {path}")
            json.loads(request(path))
          packets = json.loads(request("/packets?limit=10"))
          assert packets["enabled"] and len(packets["packets"]) == 2
          battery = json.loads(request("/batteryinfo/data"))
          assert battery["stats"]["reports"] == 1
          assert battery["entries"][0]["sender_name"] == "Dependency Smoke"
          assert battery["entries"][0]["battery_percent"] == 91
          with connect("ws://127.0.0.1:8081/ws", open_timeout=5) as websocket:
            assert json.loads(websocket.recv(timeout=5))["type"] == "snapshot"
        finally:
          if process.poll() is None:
            process.terminate()
          try:
            process.wait(timeout=15)
          except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise AssertionError("Production process did not stop gracefully")
      shutdown_log = log_path.read_text()
      assert "Application shutdown complete." in shutdown_log, shutdown_log
      # Uvicorn deliberately re-emits SIGTERM after graceful ASGI shutdown.
      assert process.returncode in (0, -signal.SIGTERM), (process.returncode, shutdown_log)

    with closing(sqlite3.connect(data / "packets.db")) as connection:
      assert connection.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok"
      retained = connection.execute("SELECT count(*) FROM packets").fetchone()[0]
      assert retained == 2
    print(json.dumps({"python": platform.python_version(), "node": fixture["node"],
                      "version": dashboard.APP_VERSION, "http_auth_websocket": "passed",
                      "encrypted_decoder": "passed", "retained_after_restart": retained}))


if __name__ == "__main__":
  main()
