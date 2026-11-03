# Chaos measurement: live (2026-11-03 11:19 KST)

## Command and environment

- Command: `python scripts/chaos_demo.py --base-url http://127.0.0.1:8040 --provider-label live --requests 4`
- Server: `EM_PROVIDER=live`, `EM_DEMO_CHAOS=1`; API version 0.1.0
- Target: `all`; modes: error, hang; 4 requests per mode under chaos, plus warm-up and recovery; POST /api/triage, one fixed query and point
- Breaker: opens after 3 consecutive failures, HALF_OPEN after 30 s
- Client: Python 3.14.6 on Linux x86_64

## RT-103 fallback (GET /metrics, whole run)

| Contract | Metric | Limit ms | Count | p50 ms | p95 ms | Max ms | OK rate |
|---|---|---|---|---|---|---|---|
| RT-103 | fallback_ms | 200 | 8 | 1 | 3 | 3 | 100.0% |

fallback_ms runs from the moment the tool call failed (or the open circuit skipped it) to the cached
data being served; the failed call itself is RT-102 time.

## The first 3 hang failures (each costs the RT-102 timeout)

| # | er_ms | pharmacy_ms | fallback_ms | total_ms |
|---|---|---|---|---|
| 1 | 2001 | 2001 | 1 | 2004 |
| 2 | 2001 | 2001 | 1 | 2004 |
| 3 | 2000 | 2001 | 1 | 2004 |

After these the circuit is OPEN: ER and pharmacy skip upstream and come from the cache in 1-2 ms.
total_ms then still includes the OTC call (never targeted, no breaker), which pays the provider's
normal latency (mock: 500-1100 ms injected delay).

## Requests: mode error

| # | Phase | Severity | Badges | total_ms | er_ms | pharmacy_ms | fallback_ms | Breakers er/ph | Notices |
|---|---|---|---|---|---|---|---|---|---|
| 0 | warm-up | amber | ER LIVE PH LIVE | 298 | 263 | 281 | - | CLOSED/CLOSED | NO_OPEN_PHARMACY |
| 1 | chaos | amber | ER CACHED PH CACHED | 5 | 0 | 0 | 2 | CLOSED/CLOSED | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 2 | chaos | amber | ER CACHED PH CACHED | 4 | 0 | 0 | 2 | CLOSED/CLOSED | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 3 | chaos | amber | ER CACHED PH CACHED | 5 | 0 | 0 | 2 | OPEN/OPEN | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 4 | chaos | amber | ER CACHED PH CACHED | 4 | - | - | 1 | OPEN/OPEN | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 5 | recovery | amber | ER LIVE PH LIVE | 212 | 6 | 199 | - | CLOSED/CLOSED | NO_OPEN_PHARMACY |

## Requests: mode hang

| # | Phase | Severity | Badges | total_ms | er_ms | pharmacy_ms | fallback_ms | Breakers er/ph | Notices |
|---|---|---|---|---|---|---|---|---|---|
| 0 | warm-up | amber | ER LIVE PH LIVE | 165 | 6 | 161 | - | CLOSED/CLOSED | NO_OPEN_PHARMACY |
| 1 | chaos | amber | ER CACHED PH CACHED | 2004 | 2001 | 2001 | 1 | CLOSED/CLOSED | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 2 | chaos | amber | ER CACHED PH CACHED | 2004 | 2001 | 2001 | 1 | CLOSED/CLOSED | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 3 | chaos | amber | ER CACHED PH CACHED | 2004 | 2000 | 2001 | 1 | OPEN/OPEN | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 4 | chaos | amber | ER CACHED PH CACHED | 7 | - | - | 3 | OPEN/OPEN | FALLBACK_CACHE,NO_OPEN_PHARMACY |
| 5 | recovery | amber | ER LIVE PH LIVE | 205 | 103 | 199 | - | CLOSED/CLOSED | NO_OPEN_PHARMACY |

Counters: by_chaos {'on': 8, 'off': 4}, fallback served 8 requests, by_notice {'NO_OPEN_PHARMACY': 12, 'FALLBACK_CACHE': 8}.

er_ms `-`: no upstream call (circuit open). Badges: data status of the ER and pharmacy results.
total_ms includes the untargeted OTC call, so it stays near the provider's normal latency.
