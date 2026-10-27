# Resilience: circuit breaker and fallback cache

When em-mcp-server or the data provider fails or is slow, the user still gets the last good data,
clearly marked, instead of a 5xx. Code: `backend/app/services/fallback_service.py` (wiring),
`services/circuit_breaker.py` (state machine), `clients/fallback_store.py` (SQLite).

## Circuit breaker (one per tool: `er`, `pharmacy`)

```
            failure (count < 3)
             +-----------+
             |           v
         +--------+   3 consecutive failures   +------+
  start->| CLOSED |--------------------------->| OPEN |<-----------+
         +--------+                            +------+            |
             ^  success resets the count          | 30 s elapsed   | trial fails
             |                                    v                |
             |        trial succeeds        +-----------+          |
             +------------------------------| HALF_OPEN |----------+
                                            +-----------+
                                    exactly one trial call goes upstream;
                                    other callers get the fallback meanwhile
```

Failures are any `McpClientError` (TIMEOUT, UNAVAILABLE, TOOL_ERROR, BAD_RESPONSE). While OPEN no
upstream call is made: the answer comes straight from the store. `GET /health` shows per tool
`state`, consecutive `failures` and `last_error` (the code only, never a message, URL or key).
Breakers are in memory and start CLOSED with each process.

## Fallback store

SQLite file `em_fallback.db` in the repo root (`EM_FALLBACK_DB` to move it; `*.db` is gitignored).
One row per (tool, key) with the last successful result:

| Tool | Key | Notes |
|---|---|---|
| `er` | region (`chungju`) | the bed list is region-wide; distances are recomputed from the current position |
| `pharmacy` | lat/lon rounded to 2 decimals (about 1 km) | `at_time` saved too; served for another time, `is_open` becomes unknown |

Rows hold the domain objects as JSON with their original `fetched_at`; no URLs, keys or error messages.

## What the user gets

| Situation | Result |
|---|---|
| Call succeeds | live data, saved to the store |
| Call fails or circuit OPEN, data saved | saved data within RT-103 (200 ms), `status` CACHED, notice `FALLBACK_CACHE` |
| ... and the saved data is over 180 min old | `status` UNCERTAIN (RT-104 runs on the original `fetched_at`) |
| Nothing saved: `/api/triage` | 200, empty list, notices `ER_UNAVAILABLE` / `PHARMACY_UNAVAILABLE` + `NO_DATA`; severity, advice and the 119 prompt still come back |
| Nothing saved: `/facilities/er`, `/facilities/ph` | the usual mapping: UNAVAILABLE 503 (also for an open circuit), TIMEOUT 504, TOOL_ERROR / BAD_RESPONSE 502 |

RT-103 is the time from the failure (or the OPEN check) to the answer. A hung upstream still costs
the RT-102 timeout (2 s) on the first calls; once 3 have failed the circuit opens and answers are
immediate. A store read slower than 200 ms counts as no saved data.
