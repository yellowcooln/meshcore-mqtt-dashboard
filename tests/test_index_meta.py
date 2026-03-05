import app as dashboard_app


def test_index_uses_dash_title_and_description(client):
  dashboard_app.DASH_TITLE = "Mesh Test Dashboard"
  response = client.get("/")
  assert response.status_code == 200
  html = response.text
  assert "<title>Mesh Test Dashboard</title>" in html
  assert 'name="description" content="Live node presence, roles, and broker telemetry."' in html
  assert 'property="og:title" content="Mesh Test Dashboard"' in html


def test_index_includes_png_favicon_when_logo_is_png(client):
  dashboard_app.DASH_LOGO_URL = "/static/logo.png"
  response = client.get("/")
  assert response.status_code == 200
  assert 'rel="icon" type="image/png" href="http://testserver/static/logo.png"' in response.text


def test_index_includes_jpeg_favicon_when_logo_is_jpg(client):
  dashboard_app.DASH_LOGO_URL = "https://example.com/logo.jpg"
  response = client.get("/")
  assert response.status_code == 200
  assert 'rel="icon" type="image/jpeg" href="https://example.com/logo.jpg"' in response.text


def test_index_omits_favicon_for_unsupported_extension(client):
  dashboard_app.DASH_LOGO_URL = "https://example.com/logo.svg"
  response = client.get("/")
  assert response.status_code == 200
  assert 'rel="icon"' not in response.text
