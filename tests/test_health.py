from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    closed = {"state": "CLOSED", "failures": 0, "last_error": None}
    assert resp.json() == {"status": "ok", "version": "0.1.0", "breakers": {"er": closed, "pharmacy": closed}}


def test_openapi_metadata():
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "EM-Agent API"
    assert spec["info"]["version"] == "0.1.0"
    assert spec["paths"]["/health"]["get"]["tags"] == ["Health"]
