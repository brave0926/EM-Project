"""Measure the RT contracts against a running app and write docs/measurements/YYYY-MM-DD-<label>.md.

    python scripts/bench_contracts.py --provider-label mock --n 30
    python scripts/bench_contracts.py --provider-label live          # n defaults to 10 for live

Sends n POST /api/triage/stream requests one after another (the 4 demo chips x 4 languages, with
the demo place coordinates), times each SSE stream on the client (TTFT = first event, total =
done event), then reads GET /metrics for the server-side view. --provider-label is only a label:
the provider is whatever the server runs (EM_PROVIDER). Start the server fresh so /metrics holds
only this run. Never prints or writes keys.
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

from backend.app.core.config import END_TO_END_S, KST, TTFT_S  # noqa: E402
from backend.app.services.metrics_service import percentile  # noqa: E402  same nearest-rank rule as /metrics

OUT_DIR = ROOT / "docs" / "measurements"
LIVE_DEFAULT_N = 10

STATION, YEONSU, CITY_HALL = (36.972, 127.900), (36.957, 127.938), (36.991, 127.926)
# The frontend's demo chips (frontend/index.html), same order in every language: place per chip.
CHIP_PLACES = [STATION, YEONSU, CITY_HALL, STATION]
CHIPS = {
    "en": ["Severe burn on my hand, near Chungju Station, 2 AM", "Deep cut, bleeding, Yeonsu-dong, 11 PM",
           "Fever and headache near City Hall, 3 AM", "Chest pain, hard to breathe, near Chungju Station"],
    "ru": ["Сильный ожог руки, у вокзала Чхунджу, 2 часа ночи", "Глубокий порез, кровь, Ёнсу-дон, 23:00",
           "Температура и головная боль, у мэрии, 3 часа ночи", "Боль в груди, трудно дышать, у вокзала Чхунджу"],
    "zh": ["手部严重烧伤,忠州站附近,凌晨2点", "深度割伤出血,莲水洞,晚上11点",
           "发烧头痛,市政府附近,凌晨3点", "胸痛呼吸困难,忠州站附近"],
    "ko": ["손에 심한 화상, 충주역 근처, 새벽 2시", "깊은 상처, 출혈, 연수동, 밤 11시",
           "열과 두통, 시청 근처, 새벽 3시", "가슴 통증, 호흡 곤란, 충주역 근처"],
}
LANGS = list(CHIPS)
# Request i: chip i % 4 in a rotating language, so every 4 requests cover all chips (RED included)
# and every 16 cover all 16 chip x language pairs.
CASES = [(LANGS[(i + i // 4) % 4], CHIPS[LANGS[(i + i // 4) % 4]][i % 4], CHIP_PLACES[i % 4]) for i in range(16)]
LIVE_NOTE = ("LiveProvider keeps ER beds in memory for 60 s (`BEDS_TTL_S`) and basic ER info for 24 h "
             "(`BASIC_TTL_S`, saves the daily quota), so only the first ER call per minute goes to data.go.kr; "
             "pharmacy calls are not cached. er_ms max is the cold call.")


async def one_stream(client: httpx.AsyncClient, query: str, lat: float, lon: float) -> tuple[int | None, int | None]:
    """Client-side (ttft_ms, total_ms); None when that event never arrived."""
    ttft = total = None
    t0 = time.perf_counter()
    async with client.stream("POST", "/api/triage/stream", json={"query": query, "lat": lat, "lon": lon}) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("event:"):
                continue
            ms = round((time.perf_counter() - t0) * 1000)
            ttft = ms if ttft is None else ttft
            if line.split(":", 1)[1].strip() == "done":
                total = ms
    return ttft, total


def row(name: str, limit_ms: int, values: list[int], ok: list[bool]) -> str:
    if not values:
        return f"| {name} | {limit_ms} | 0 | - | - | - | - |"
    rate = sum(ok) / len(ok)
    return (f"| {name} | {limit_ms} | {len(values)} | {percentile(values, 50)} | {percentile(values, 95)} "
            f"| {max(values)} | {rate:.1%} |")


def render(args: argparse.Namespace, n: int, client_rows: list[tuple[int | None, int | None]],
           metrics: dict, health: dict, before_total: int, command: str) -> str:
    ttfts = [t for t, _ in client_rows if t is not None]
    totals = [t for _, t in client_rows if t is not None]
    ttft_ms, total_ms = round(TTFT_S * 1000), round(END_TO_END_S * 1000)
    lines = [
        f"# Contract measurement: {args.provider_label} ({datetime.now(KST):%Y-%m-%d %H:%M} KST)",
        "",
        "## Command and environment",
        "",
        f"- Command: `{command}`",
        f"- Provider (label): `{args.provider_label}`; server must run `EM_PROVIDER={args.provider_label}`",
        f"- Requests: n={n}, sequential POST /api/triage/stream, 4 demo chips x 4 languages (EN/RU/ZH/KO) "
        "with the demo place coordinates",
        f"- Base URL: `{args.base_url}`; API version {health.get('version', '?')}",
        f"- Client: Python {platform.python_version()} on {platform.system()} {platform.machine()}",
        f"- Server records before the run: {before_total}"
        + (" (WARNING: server-side numbers include earlier requests)" if before_total else " (fresh server)"),
        f"- Streams completed: {len(totals)}/{n}",
        "",
        "## Client side (arrival times over HTTP)",
        "",
        "| Contract | Limit ms | Count | p50 ms | p95 ms | Max ms | OK rate |",
        "|---|---|---|---|---|---|---|",
        row("RT-101 TTFT", ttft_ms, ttfts, [t <= ttft_ms for t in ttfts]),
        row("RT-105 total", total_ms, totals, [t <= total_ms for t in totals]),
        "",
        "## Server side (GET /metrics)",
        "",
        "| Contract | Metric | Limit ms | Count | p50 ms | p95 ms | Max ms | OK rate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in metrics["contracts"]:
        rate = f"{c['ok_rate']:.1%}" if c["count"] else "-"
        lines.append(f"| {c['contract']} | {c['metric']} | {c['limit_ms']} | {c['count']} | {c['p50_ms']} "
                     f"| {c['p95_ms']} | {c['max_ms']} | {rate} |")
    breakers = ", ".join(f"{k}: {v['state']} ({v['failures']} failures)" for k, v in metrics["breakers"].items())
    lines += [
        "",
        "## Counters (GET /metrics)",
        "",
        f"- Requests in window: {metrics['window']} (since start: {metrics['requests_total']})",
        f"- By severity: {metrics['by_severity']}",
        f"- By source: {metrics['by_source']}",
        f"- By notice: {metrics['by_notice'] or '{}'}",
        f"- Fallback served: {metrics['fallback_served']} requests (cache answers since start: "
        f"{metrics['fallback_served_total']})",
        f"- Breakers: {breakers}",
        "",
        "Percentiles are nearest-rank (docs/metrics.md). Tool calls (RT-102) and fallback (RT-103) are "
        "timed on the server only. RED cases skip the pharmacy, so pharmacy_ms has fewer samples.",
        "",
    ]
    if args.provider_label == "live":
        lines += [LIVE_NOTE, ""]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--n", type=int, default=None, help=f"requests (default 30; {LIVE_DEFAULT_N} for live)")
    parser.add_argument("--provider-label", choices=["mock", "live"], default="mock")
    args = parser.parse_args()
    n = args.n if args.n is not None else (LIVE_DEFAULT_N if args.provider_label == "live" else 30)
    if args.provider_label == "live":
        print(f"WARNING: live mode calls data.go.kr (limit 1000 calls per operation per day); n={n}.",
              file=sys.stderr)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        health = (await client.get("/health")).json()
        before_total = (await client.get("/metrics")).json()["requests_total"]
        rows = []
        for i in range(n):
            lang, query, (lat, lon) = CASES[i % len(CASES)]
            rows.append(await one_stream(client, query, lat, lon))
            print(f"{i + 1}/{n} {lang}: ttft={rows[-1][0]} ms total={rows[-1][1]} ms", file=sys.stderr)
        metrics = (await client.get("/metrics")).json()

    command = "python scripts/bench_contracts.py " + " ".join(sys.argv[1:])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.now(KST):%Y-%m-%d}-{args.provider_label}.md"
    out.write_text(render(args, n, rows, metrics, health, before_total, command.strip()), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
