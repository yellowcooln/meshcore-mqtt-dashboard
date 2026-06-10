from pathlib import Path

import app as dashboard_app


STATIC_DIR = Path(__file__).resolve().parents[1] / "backend" / "static"


def test_template_replacements_escape_html(client):
  dashboard_app.DASH_TITLE = '<img src=x onerror="window.__xssHit=true">'
  dashboard_app.DASH_EXTERNAL_URL = 'https://example.com/?q=<script>alert(1)</script>'
  dashboard_app.DASH_EXTERNAL_LABEL = '<svg onload="window.__xssHit=true">'
  dashboard_app.DASH_LOGO_URL = 'https://example.com/logo.png?x=<script>alert(1)</script>'

  response = client.get("/")

  assert response.status_code == 200
  html = response.text
  assert '<img src=x onerror="window.__xssHit=true">' not in html
  assert '&lt;img src=x onerror=&quot;window.__xssHit=true&quot;&gt;' in html
  assert '<svg onload="window.__xssHit=true">' not in html
  assert '&lt;svg onload=&quot;window.__xssHit=true&quot;&gt;' in html
  assert '<script>alert(1)</script>' not in html
  assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_node_dashboard_escapes_untrusted_meshcore_fields():
  html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

  assert "idCell.textContent = displayName;" in html
  assert "topicSpan.textContent = topic;" in html
  assert "valueSpan.textContent = formatNumber(data.value);" in html
  assert "${escapeHtml(node.node_id)}" in html
  assert "${escapeHtml(node.name || \"--\")}" in html
  assert "${escapeHtml(node.role || \"Unknown\")}" in html
  assert "${escapeHtml(node.role_source || \"--\")}" in html
  assert "${escapeHtml(key)}" in html
  assert "${escapeHtml(formatNumber(value))}" in html


def test_traffic_page_escapes_untrusted_talker_fields():
  html = (STATIC_DIR / "traffic.html").read_text(encoding="utf-8")

  assert "${escapeHtml(label)}" in html
  assert "${escapeHtml(detail)}" in html
  assert "${escapeHtml(talker.route_lead || \"other\")}" in html
  assert "${escapeHtml(talker.payload_lead || \"other\")}" in html


def test_batteryinfo_page_escapes_untrusted_sender_and_message_fields():
  html = (STATIC_DIR / "batteryinfo.html").read_text(encoding="utf-8")

  assert "${escapeHtml(node.sender_name)}" in html
  assert "${escapeHtml(entry.sender_name)}" in html
  assert "${escapeHtml(entry.text)}" in html
  assert "${escapeHtml(item.name)}" in html
  assert "${escapeHtml(config.title)} has no decoded values" in html
