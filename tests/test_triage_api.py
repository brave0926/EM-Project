import pytest

from backend.app.schemas.triage import DEMO_QUERY, TriageRequestSchema, TriageResponseSchema


@pytest.mark.asyncio
async def test_demo_query(api):
    async with api() as client:
        resp = await client.post("/api/triage", json={"query": DEMO_QUERY})
    assert resp.status_code == 200
    body = resp.json()
    assert (body["language"], body["category"], body["severity"], body["call_119"]) == ("en", "burn", "amber", False)
    assert (body["location_source"], body["at_time"]) == ("text", "02:00")
    assert body["pharmacies"][0]["name"] == "Station Night Pharmacy (mock)"
    assert body["er"][0]["hvec"] > 0 and body["otc"] and body["notices"] == []
    assert body["advice"].endswith("Not medical advice. In an emergency call 119.")
    assert 0 <= body["total_ms"] <= 6000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "language"),
    [("Сильный ожог руки у вокзал Чхунджу", "ru"), ("在忠州站附近手被严重烫伤", "zh"), ("충주역 근처에서 손에 심한 화상", "ko")],
)
async def test_demo_in_other_languages(api, query, language):
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": query, "at_time": "02:00"})).json()
    assert (body["language"], body["category"], body["severity"]) == (language, "burn", "amber")
    assert body["location_source"] == "text"
    assert "119" in body["advice"].splitlines()[-1]


@pytest.mark.asyncio
async def test_critical_korean(api):
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": "아버지가 숨을 안 쉬어요"})).json()
    assert body["severity"] == "red" and body["call_119"] is True
    assert body["pharmacies"] == [] and body["otc"] == [] and body["at_time"] is None
    assert body["advice"].startswith("생명이 위험할 수 있습니다")


@pytest.mark.asyncio
async def test_mcp_down_is_still_200_with_notices(api):
    async with api(server="http://127.0.0.1:9/mcp") as client:
        resp = await client.post("/api/triage", json={"query": "He is unconscious"})
    assert resp.status_code == 200  # fail soft: the 119 prompt never depends on MCP
    body = resp.json()
    assert body["call_119"] is True and "ER_UNAVAILABLE" in body["notices"]


@pytest.mark.asyncio
async def test_request_coordinates(api):
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": "small cut", "lat": 36.954, "lon": 127.94})).json()
    assert body["location_source"] == "request"
    assert body["location"]["lat"] == 36.954


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": ""},
        {"query": "x" * 2001},
        {"query": "burn", "lat": 36.9},
        {"query": "burn", "at_time": "2am"},
        {"query": "burn", "language": "fr"},
    ],
)
async def test_bad_request_is_422(api, payload):
    async with api() as client:
        resp = await client.post("/api/triage", json=payload)
    assert resp.status_code == 422


def test_schema_examples_are_valid():
    for schema in (TriageRequestSchema, TriageResponseSchema):
        for example in schema.model_config["json_schema_extra"]["examples"]:
            schema.model_validate(example)


@pytest.mark.asyncio
async def test_openapi_tag(api):
    async with api() as client:
        spec = (await client.get("/openapi.json")).json()
    assert spec["paths"]["/api/triage"]["post"]["tags"] == ["Triage"]
