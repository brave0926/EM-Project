import asyncio
import time

import pytest

from backend.app.clients.mcp_client import McpClient, McpClientError
from backend.app.core.config import TOOL_TIMEOUT_S
from backend.app.models.domain import ERFacility, Location, PharmacyFacility
from backend.app.models.enums import Category, DataStatus
from mcp_server.providers import MockProvider
from mcp_server.server import build_server

CHUNGJU = Location(name="Chungju City Hall (mock)", lat=36.991, lon=127.926)


def _client(timeout_s: float = TOOL_TIMEOUT_S, **kwargs) -> McpClient:
    provider = MockProvider(**({"delay_ms_range": (0, 0), "seed": 1} | kwargs))
    return McpClient(build_server(provider), timeout_s=timeout_s)


@pytest.mark.asyncio
async def test_round_trip_returns_domain_models():
    async with _client() as mcp:
        ers = await mcp.get_er_beds("Chungju", near=CHUNGJU)
        pharmacies = await mcp.get_pharmacies(CHUNGJU, at_time="05:00")
        otc = await mcp.get_otc(Category.CUT)
    assert len(ers) == 3 and all(isinstance(e, ERFacility) for e in ers)
    assert any(e.hvec == 0 for e in ers)
    assert [p.name for p in pharmacies] == ["Yeonsu Central Pharmacy (mock)"]
    assert isinstance(pharmacies[0], PharmacyFacility)
    assert "Sterile dressing" in otc


@pytest.mark.asyncio
async def test_stale_data_stays_uncertain_across_mcp():
    async with _client(stale_minutes=200) as mcp:
        ers = await mcp.get_er_beds("Chungju")
    assert all(e.status is DataStatus.UNCERTAIN for e in ers)


@pytest.mark.asyncio
async def test_provider_failure_raises_tool_error():
    async with _client(failure_rate=1.0) as mcp:
        with pytest.raises(McpClientError) as err:
            await mcp.get_er_beds("Chungju")
    assert err.value.code == "TOOL_ERROR"
    assert "PROVIDER_ERROR" in str(err.value)


@pytest.mark.asyncio
async def test_slow_tool_times_out():
    # Same mechanism as RT-102 (2.0 s), scaled down to keep the suite fast.
    async with _client(timeout_s=0.2, delay_ms_range=(600, 600)) as mcp:
        t0 = time.perf_counter()
        with pytest.raises(McpClientError) as err:
            await mcp.get_otc(Category.FEVER)
        elapsed = time.perf_counter() - t0
    assert err.value.code == "TIMEOUT"
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_unreachable_server_is_unavailable():
    with pytest.raises(McpClientError) as err:
        async with McpClient("http://127.0.0.1:9/mcp"):
            pass
    assert err.value.code == "UNAVAILABLE"


def test_default_timeout_is_rt102():
    assert McpClient("http://unused/mcp").timeout_s == 2.0


@pytest.mark.asyncio
async def test_lazy_connect_and_close_from_another_task():
    mcp = _client()
    # first call opens the connection inside a separate task (like a request handler)
    otc = await asyncio.create_task(mcp.get_otc(Category.BURN))
    assert otc
    await mcp.aclose()  # closed from this task: must not raise


@pytest.mark.asyncio
async def test_parallel_calls_share_one_connection():
    async with _client(delay_ms_range=(200, 200)) as mcp:
        t0 = time.perf_counter()
        ers, pharmacies = await asyncio.gather(
            mcp.get_er_beds("Chungju", near=CHUNGJU), mcp.get_pharmacies(CHUNGJU, at_time="12:00")
        )
        elapsed = time.perf_counter() - t0
    assert ers and pharmacies
    assert elapsed < 0.35  # parallel, not 0.4 s sequential


@pytest.mark.asyncio
async def test_reconnects_after_dropped_connection():
    async with _client() as mcp:
        await mcp.get_otc(Category.CUT)
        mcp._stop.set()  # simulate the connection dropping
        await asyncio.sleep(0)
        assert await mcp.get_otc(Category.CUT)
