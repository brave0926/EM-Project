"""Run LiveProvider once for Chungju against data.go.kr and print what it returns.

Usage: python scripts/live_smoke.py
Reads the keys from the environment or .env; never prints them. Uses 4 upstream calls.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.env import load_env  # noqa: E402
from backend.app.models.domain import Location  # noqa: E402
from mcp_server.providers import KST, LiveProvider, ProviderError  # noqa: E402

PATIENT = Location(name="Chungju", lat=36.99, lon=127.93)


async def main() -> int:
    load_env()
    provider = LiveProvider()
    try:
        t0 = time.perf_counter()
        ers = await provider.get_er_beds("Chungju", near=PATIENT)
        t1 = time.perf_counter()
        pharmacies = await provider.get_pharmacies(PATIENT)
        t2 = time.perf_counter()
    except ProviderError as e:
        print(f"ProviderError {e}")
        return 1
    finally:
        await provider.aclose()

    print(f"ER ({len(ers)}, {(t1 - t0) * 1000:.0f} ms)")
    for e in ers:
        print(
            f"  {e.name}  free={e.hvec}  icu={e.hvicc}  {e.distance_km:.2f} km  "
            f"updated_at={e.fetched_at.astimezone(KST):%Y-%m-%d %H:%M:%S %Z}  {e.status.value} {e.source}"
        )
    print(f"Pharmacies open now ({len(pharmacies)}, {(t2 - t1) * 1000:.0f} ms)")
    for p in pharmacies[:5]:
        print(f"  {p.name}  {p.distance_km:.2f} km  is_open={p.is_open}  until={p.open_until}  {p.source}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
