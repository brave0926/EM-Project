from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_page_is_served_at_root():
    resp = client.get("/")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")
    assert 'STREAM_URL="/api/triage/stream"' in resp.text
    assert "HOSP=" not in resp.text  # the in-page mock data is gone


def test_api_routes_and_docs_still_win():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    assert "/api/triage/stream" in client.get("/openapi.json").json()["paths"]
    assert client.get("/no-such-page").status_code == 404


def test_demo_controls_only_with_demo_param():
    page = client.get("/").text
    assert 'id="demo"' in page and "#demo{display:none" in page  # hidden unless the script shows it
    assert 'get("demo")==="1"' in page  # the only place that shows it and starts polling
    for label in ("Simulate API failure", "Simulate slow API (3 s)", "Reset"):
        assert label in page
    assert "/demo/chaos" in page and 'fetch("/health")' in page
