import pytest


@pytest.mark.parametrize("route, page", [("/", "dashboard"), ("/traffic", "traffic"), ("/neighbors", "neighbors")])
def test_pages_request_only_their_initial_stream_data(client, route, page):
  response = client.get(route)
  assert response.status_code == 200
  assert f"/ws?page={page}`" in response.text
