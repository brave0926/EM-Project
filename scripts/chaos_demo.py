"""Show the circuit breaker and fallback cache under injected failures, and measure RT-103.

    EM_PROVIDER=mock EM_DEMO_CHAOS=1 scripts/run_dev.sh          # terminal 1 (fresh server)
    python scripts/chaos_demo.py                                  # terminal 2

For each mode (error, then hang): warm-up so the cache is filled, chaos on, N requests (the first 3
fail and open the circuit, the rest skip upstream), chaos off, wait for HALF_OPEN, one request to
show recovery to CLOSED. Prints one line per request and writes
docs/measurements/YYYY-MM-DD-chaos[-live].md. Needs EM_DEMO_CHAOS=1 on the server. Never prints keys.
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.core.config import BREAKER_FAILURES, BREAKER_OPEN_S, KST  # noqa: E402

OUT_DIR = ROOT / "docs" / "measurements"
# One fixed query and point: every request uses the same cache keys (region, ~1 km grid, 02:00).
QUERY = {"query": "Severe burn on my hand, near Chungju Station, 2 AM", "lat": 36.972, "lon": 127.900}
HEADER = f"{'#':>2} {'phase':<9} {'sev':<5} {'badges':<22} {'total':>6} {'er_ms':>6} {'fb_ms':>6}  breakers (er/ph)  notices"


class Row(dict):
    def line(self) -> str:
        def ms(v):
            return "-" if v is None else str(v)
        return (f"{self['n']:>2} {self['phase']:<9} {self['severity']:<5} {self['badges']:<22} {self['total_ms']:>6} "
                f"{ms(self['er_ms']):>6} {ms(self['fallback_ms']):>6}  {self['breakers']:<17} {self['notices']}")


async def one(client: httpx.AsyncClient, n: int, phase: str) -> Row:
    body = (await client.post("/api/triage", json=QUERY)).raise_for_status().json()
    rec = (await client.get("/metrics", params={"recent": 1})).json()["recent"][-1]
    breakers = (await client.get("/health")).json()["breakers"]

    def badge(items):
        return "/".join(sorted({i["status"] for i in items})) or "-"
    return Row(
        n=n, phase=phase, severity=body["severity"], total_ms=body["total_ms"],
        badges=f"ER {badge(body['er'])} PH {badge(body['pharmacies'])}",
        er_ms=rec["er_ms"], pharmacy_ms=rec["pharmacy_ms"], fallback_ms=rec["fallback_ms"],
        breakers=f"{breakers['er']['state']}/{breakers['pharmacy']['state']}",
        notices=",".join(body["notices"]) or "-",
    )


async def wait_half_open(client: httpx.AsyncClient) -> float:
    """Countdown until the ER breaker leaves OPEN; returns seconds waited."""
    t0 = time.monotonic()
    while True:
        state = (await client.get("/health")).json()["breakers"]["er"]["state"]
        if state != "OPEN":
            print(f"\r  breaker er: {state} after {time.monotonic() - t0:.0f} s{' ' * 20}")
            return time.monotonic() - t0
        left = max(0, BREAKER_OPEN_S - (time.monotonic() - t0))
        print(f"\r  breaker er: OPEN, HALF_OPEN in about {left:.0f} s (up to {BREAKER_OPEN_S:.0f} s) ", end="", flush=True)
        await asyncio.sleep(1)


async def cycle(client: httpx.AsyncClient, mode: str, target: str, requests: int) -> list[Row]:
    print(f"\n=== mode {mode} on {target} ===")
    print(HEADER)
    rows = [await one(client, 0, "warm-up")]
    print(rows[-1].line())
    state = (await client.post("/demo/chaos", json={"target": target, "mode": mode, "duration_s": 120})).json()
    print(f"  chaos ON: {mode} on {target}, auto-off in {state['tools']['er']['seconds_left']} s")
    for i in range(1, requests + 1):
        rows.append(await one(client, i, "chaos"))
        print(rows[-1].line())
        if i == BREAKER_FAILURES:
            print(f"  -> {BREAKER_FAILURES} failures: circuit OPEN, next requests skip upstream (er_ms '-')")
    await client.delete("/demo/chaos")
    print("  chaos OFF (DELETE /demo/chaos); the breaker recovers on its own")
    await wait_half_open(client)
    rows.append(await one(client, requests + 1, "recovery"))
    print(rows[-1].line())
    return rows


def table(rows: list[Row]) -> list[str]:
    out = ["| # | Phase | Severity | Badges | total_ms | er_ms | pharmacy_ms | fallback_ms | Breakers er/ph | Notices |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        cells = [r["n"], r["phase"], r["severity"], r["badges"], r["total_ms"], r["er_ms"], r["pharmacy_ms"],
                 r["fallback_ms"], r["breakers"], r["notices"]]
        out.append("| " + " | ".join("-" if c is None else str(c) for c in cells) + " |")
    return out


def render(args, command: str, health: dict, cycles: dict[str, list[Row]], metrics: dict) -> str:
    def stat(contract, metric):
        return next(c for c in metrics["contracts"] if c["contract"] == contract and c["metric"] == metric)
    rt103 = stat("RT-103", "fallback_ms")
    lines = [
        f"# Chaos measurement: {args.provider_label} ({datetime.now(KST):%Y-%m-%d %H:%M} KST)",
        "",
        "## Command and environment",
        "",
        f"- Command: `{command}`",
        f"- Server: `EM_PROVIDER={args.provider_label}`, `EM_DEMO_CHAOS=1`; API version {health.get('version', '?')}",
        f"- Target: `{args.target}`; modes: {', '.join(cycles)}; {args.requests} requests per mode under chaos, "
        "plus warm-up and recovery; POST /api/triage, one fixed query and point",
        f"- Breaker: opens after {BREAKER_FAILURES} consecutive failures, HALF_OPEN after {BREAKER_OPEN_S:.0f} s",
        f"- Client: Python {platform.python_version()} on {platform.system()} {platform.machine()}",
        "",
        "## RT-103 fallback (GET /metrics, whole run)",
        "",
        "| Contract | Metric | Limit ms | Count | p50 ms | p95 ms | Max ms | OK rate |",
        "|---|---|---|---|---|---|---|---|",
        f"| RT-103 | fallback_ms | {rt103['limit_ms']} | {rt103['count']} | {rt103['p50_ms']} | {rt103['p95_ms']} "
        f"| {rt103['max_ms']} | {rt103['ok_rate']:.1%} |",
        "",
        "fallback_ms runs from the moment the tool call failed (or the open circuit skipped it) to the cached",
        "data being served; the failed call itself is RT-102 time.",
        "",
    ]
    if "hang" in cycles:
        hang = [r for r in cycles["hang"] if r["phase"] == "chaos"][:BREAKER_FAILURES]
        lines += [
            f"## The first {BREAKER_FAILURES} hang failures (each costs the RT-102 timeout)",
            "",
            "| # | er_ms | pharmacy_ms | fallback_ms | total_ms |",
            "|---|---|---|---|---|",
            *[f"| {r['n']} | {r['er_ms']} | {r['pharmacy_ms']} | {r['fallback_ms']} | {r['total_ms']} |" for r in hang],
            "",
            "After these the circuit is OPEN: ER and pharmacy skip upstream and come from the cache in 1-2 ms.",
            "total_ms then still includes the OTC call (never targeted, no breaker), which pays the provider's",
            "normal latency (mock: 500-1100 ms injected delay).",
            "",
        ]
    for mode, rows in cycles.items():
        lines += [f"## Requests: mode {mode}", "", *table(rows), ""]
    lines += [
        f"Counters: by_chaos {metrics['by_chaos']}, fallback served {metrics['fallback_served']} requests, "
        f"by_notice {metrics['by_notice']}.",
        "",
        "er_ms `-`: no upstream call (circuit open). Badges: data status of the ER and pharmacy results.",
        "total_ms includes the untargeted OTC call, so it stays near the provider's normal latency.",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--target", choices=["er", "pharmacy", "all"], default="all")
    parser.add_argument("--requests", type=int, default=6, help="requests per mode while chaos is on")
    parser.add_argument("--modes", default="error,hang", help="comma list of error, hang, delay")
    parser.add_argument("--provider-label", choices=["mock", "live"], default="mock")
    args = parser.parse_args()
    if args.provider_label == "live":
        print("WARNING: live mode calls data.go.kr (1000 calls per operation per day); keep --requests small.",
              file=sys.stderr)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        health = (await client.get("/health")).json()
        if (await client.get("/demo/chaos")).status_code == 404:
            print("The server has /demo/chaos off: restart it with EM_DEMO_CHAOS=1.", file=sys.stderr)
            return 1
        await client.delete("/demo/chaos")
        if health["breakers"]["er"]["state"] != "CLOSED":
            print("ER breaker is not CLOSED: waiting for it to recover first.")
            await wait_half_open(client)
        cycles = {}
        for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
            cycles[mode] = await cycle(client, mode, args.target, args.requests)
        metrics = (await client.get("/metrics")).json()

    command = ("python scripts/chaos_demo.py " + " ".join(sys.argv[1:])).strip()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.provider_label == "mock" else f"-{args.provider_label}"
    out = OUT_DIR / f"{datetime.now(KST):%Y-%m-%d}-chaos{suffix}.md"
    out.write_text(render(args, command, health, cycles, metrics), encoding="utf-8")
    rt103 = next(c for c in metrics["contracts"] if c["contract"] == "RT-103")
    print(f"\nRT-103 fallback_ms: n={rt103['count']} p50={rt103['p50_ms']} p95={rt103['p95_ms']} "
          f"max={rt103['max_ms']} ok={rt103['ok_rate']:.0%}")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
