"""first_aid_worker in the graph: /api/triage, the SSE event, RED, failures, metrics (offline)."""

import json

import pytest

from backend.app.models.enums import Notice
from backend.app.services import first_aid_service

AMBER = "Severe burn on my hand, near Chungju Station, 2 AM"
RED = "He is unconscious, not breathing, near Chungju Station"
GREEN = "Mild sore throat near Chungju Station"


def events_of(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.mark.asyncio
async def test_triage_returns_the_card(api, use_mcp):
    use_mcp()
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": GREEN})).json()
    card = body["first_aid"]
    assert body["severity"] == "green" and card["entry"] == "minor" and card["kind"] == "standard"
    assert card["otc_types"] and card["otc_note"] and card["escalate"] is None
    assert card["sources"][0]["publisher"] == "NHS" and card["reviewed"] is False
    assert body["advice"] and Notice.FIRST_AID_UNAVAILABLE not in body["notices"]


@pytest.mark.asyncio
async def test_red_stream_has_the_minimal_card_and_no_pharmacy(api, use_mcp):
    use_mcp()
    async with api() as client:
        events = events_of((await client.post("/api/triage/stream", json={"query": RED})).text)
    names = [n for n, _ in events]
    assert "pharmacy" not in names and "first_aid" in names and names[0] == "triage"
    card = dict(events)["first_aid"]
    assert card["entry"] == "critical" and card["kind"] == "minimal" and card["otc_types"] == []
    assert card["steps"][0]["id"] == "critical.call_119" and dict(events)["triage"]["call_119"]


@pytest.mark.asyncio
async def test_worker_failure_never_breaks_the_request(api, use_mcp, monkeypatch):
    use_mcp()

    async def boom(*args):
        raise RuntimeError("knowledge base down")

    monkeypatch.setattr(first_aid_service, "get_card", boom)
    async with api() as client:
        body = (await client.post("/api/triage", json={"query": AMBER})).json()
        events = events_of((await client.post("/api/triage/stream", json={"query": AMBER})).text)
    assert body["severity"] == "amber" and body["first_aid"] is None and body["advice"]
    assert Notice.FIRST_AID_UNAVAILABLE in body["notices"]
    assert "first_aid" not in [n for n, _ in events] and dict(events)["done"]["rt105_ok"]
    assert Notice.FIRST_AID_UNAVAILABLE in [d["notice"] for n, d in events if n == "notice"]


@pytest.mark.asyncio
async def test_metrics_count_first_aid_without_user_text(api, use_mcp):
    use_mcp()
    async with api() as client:
        for query in (AMBER, RED, GREEN):
            await client.post("/api/triage", json={"query": query})
        body = (await client.get("/metrics", params={"recent": 3})).json()
    fa = body["first_aid"]
    assert fa["by_category"] == {"burn": 1, "critical": 1, "minor": 1}
    assert fa["outcomes"] == {"ok": 3, "unavailable": 0, "none": 0} and fa["worker_ms"]["count"] == 3
    assert fa["escalated"] == 2 and fa["uncovered"] == 0  # "Severe burn" and "not breathing" are warning signs
    assert [r["first_aid_entry"] for r in body["recent"]] == ["burn", "critical", "minor"]
    assert "hand" not in json.dumps(body).lower() and "sore throat" not in json.dumps(body).lower()
