# Metrics: GET /metrics and contract measurements

`GET /metrics` returns a JSON summary of the last requests, per latency contract (RT-101..105).
Code: `backend/app/services/metrics_service.py` (store + summary), `services/request_timing.py`
(per-request collector), `models/metrics.py` (record), `schemas/metrics.py` (response).

## What is recorded

One record per finished `POST /api/triage` (kind `triage`) and `POST /api/triage/stream` (kind `stream`):

| Field | Meaning |
|---|---|
| `ttft_ms` | stream only: time to the first event (RT-101) |
| `er_ms`, `pharmacy_ms` | one upstream MCP tool call, success or failure (RT-102); none if the circuit was open or the tool was not called (RED skips the pharmacy) |
| `fallback_ms` | from the moment the tool call failed (or the open circuit skipped it) to cached data served (RT-103); slowest of the request |
| `total_ms` | whole request (RT-105) |
| `severity`, `notices`, `sources` | triage level, warnings, data behind the answer (`MOCK`, `LIVE`, `CACHED`) |
| `rt101_ok` .. `rt105_ok`, `timed_out` | per-request contract flags; a stream cut at the RT-105 cap fails RT-105 |
| `chaos_active` | `/demo/chaos` was on during the request (`docs/chaos.md`) |

Tool and fallback times are taken in `services/fallback_service.py`, where the MCP call happens.
`request_timing.track()` opens a collector in a ContextVar for the request; the graph's worker
tasks copy the context, so the services need no extra parameters. A stream the client abandons
before `done` is not recorded.

## What is not recorded (privacy)

Never the user's text, location (named or coordinates), time of day, advice, facility names or
any key. `MetricsRecord` forbids extra fields, and a test checks the response holds no user text.
Records live in memory only (lost on restart, never written to disk).

## Summary

- Ring buffer of the last 1000 records (`METRICS_CAPACITY` in `core/config.py`); counts and
  percentiles are over this window. `requests_total` and `fallback_served_total` count since start
  (`fallback_served_total` also counts cache answers to `/facilities/*`).
- Per contract and metric: `count`, `p50_ms`, `p95_ms`, `max_ms`, `ok_rate` against the limits in
  `core/config.py`. An empty window gives zeros, not an error.
- Percentiles are **nearest-rank**: sort the n samples and take the value at rank `ceil(p/100 * n)`
  (1-based). Every reported value was really measured; with few samples p95 equals the max.
- Counters: by kind, severity, notice, source mix (`MOCK`, `CACHED+LIVE`, `NONE`, ...), by chaos
  (`on`/`off`), fallback served, and the circuit breaker per tool (same as `/health`).
- `GET /metrics?recent=N` (max 50) also returns the last N records, newest last (no user text).

## Measuring the contracts: scripts/bench_contracts.py

Start a fresh server (so `/metrics` holds only the run), then:

```bash
EM_PROVIDER=mock scripts/run_dev.sh                       # terminal 1
python scripts/bench_contracts.py --provider-label mock   # terminal 2, n=30 by default

EM_PROVIDER=live scripts/run_dev.sh                       # keys in .env
python scripts/bench_contracts.py --provider-label live   # n=10 by default
```

Options: `--base-url` (default `http://127.0.0.1:8000`), `--n`, `--provider-label mock|live`
(only a label: the server's `EM_PROVIDER` decides the data). The script sends n sequential stream
requests (the 4 demo chips rotated over EN/RU/ZH/KO, with the demo place coordinates), times each
stream on the client (TTFT and total from arrival times), reads `GET /metrics`, and writes
`docs/measurements/YYYY-MM-DD-<label>.md` with the command and environment.

Live mode: data.go.kr allows 1000 calls per operation per day, so keep n small (the script warns).
LiveProvider caches ER beds for 60 s and basic ER info for 24 h, so most `er_ms` samples in a
short live run are cache hits; the max is the cold call. Pharmacy calls are not cached.
