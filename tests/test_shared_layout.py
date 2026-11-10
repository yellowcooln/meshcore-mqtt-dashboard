from html.parser import HTMLParser

import app as dashboard_app
import pytest


class PageShell(HTMLParser):
  def __init__(self):
    super().__init__()
    self.stylesheets = []
    self.active_links = []

  def handle_starttag(self, tag, attrs):
    attrs = dict(attrs)
    if tag == "link" and attrs.get("rel") == "stylesheet":
      self.stylesheets.append(attrs.get("href"))
    if tag == "a" and attrs.get("data-active") == "true":
      self.active_links.append(attrs.get("href"))


@pytest.mark.parametrize("route", ["/", "/traffic", "/neighbors", "/batteryinfo"])
def test_pages_share_neighbors_styles_and_active_navigation(client, monkeypatch, route):
  monkeypatch.setattr(dashboard_app, "BATTERYINFO_ENABLED", True)
  response = client.get(route)
  assert response.status_code == 200
  shell = PageShell()
  shell.feed(response.text)
  assert "/static/dashboard.css" in shell.stylesheets
  assert shell.active_links == [route]
  css = client.get("/static/dashboard.css")
  assert css.status_code == 200
  assert "--bg: #09111b" in css.text
  assert "--bg: #eef3f8" in css.text
