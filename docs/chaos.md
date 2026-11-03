# Demo chaos: failure injection for the circuit breaker and fallback demo

`/demo/chaos` switches failures and delays on and off while the app runs, so the demo can show
the circuit breaker (`docs/resilience.md`) and the fallback cache at work, and RT-103 gets real
samples. **Demo only: off unless `EM_DEMO_CHAOS=1`.**

## Enable

```bash
EM_PROVIDER=mock EM_DEMO_CHAOS=1 scripts/run_dev.sh     # or EM_DEMO_CHAOS=1 in .env
EM_DEMO_CHAOS=1 docker compose up                        # passed to the api container
```

Without it, `GET/POST/DELETE /demo/chaos` answer 404, the routes are not listed in Swagger, and
the MCP client is never wrapped. The flag is read per request.

## Endpoints

| Method | Body / answer |
|---|---|
| `POST /demo/chaos` | `{"target": "er" \| "pharmacy" \| "all", "mode": "off" \| "delay" \| "error" \| "hang", "delay_ms"?: int, "duration_s"?: int}` -> state |
| `GET /demo/chaos` | state: `{"enabled", "active", "tools": {"er": {"mode", "delay_ms", "seconds_left"}, "pharmacy": {...}}}` |
| `DELETE /demo/chaos` | turns everything off -> state |

Modes, per tool:

- `error`: `McpClientError TOOL_ERROR` at once; upstream is not called.
- `hang`: no answer until the client's RT-102 timeout (2 s), then `TIMEOUT`, like a hung server; upstream not called.
- `delay`: wait `delay_ms` (default 3000, max 10000), then call upstream. The RT-102 budget still
  applies: past 2 s it ends as `TIMEOUT`, so "slow API (3 s)" behaves like a slow real server.
- `off`: removes the rule for the target.

`all` means er + pharmacy, the two tools with a breaker and a fallback cache. OTC is never targeted:
it is a static first-aid list with no breaker, so a hang there would only slow every answer down.
Every activation expires after `duration_s` (default 60, max 300): a forgotten switch cannot
break the app. `DELETE` does not reset the breakers: an open circuit recovers the normal way
(HALF_OPEN after 30 s, one trial call, CLOSED on success), which is part of the demo.

## Where it lives (and why)

```
services/chaos_service.py  --writes-->  clients/chaos.py (ChaosStore: rule per tool, expiry clock)
                                              ^ reads
services/* -> clients/mcp_client.get_mcp_client() -> ChaosMcpClient(real client) while a rule is active
```

- The injection is at the backend boundary, around the MCP client calls, so it works the same
  with the mock and the live provider, and the backend still never imports `mcp_server`.
- The state is in `clients/chaos.py`, which imports only core and models. `mcp_client` reads it,
  `chaos_service` writes it; neither imports the other, so there is no cycle, and the layering
  test stays green (services -> clients is allowed, clients never import services).
- The wrapper `ChaosMcpClient` sits in `mcp_client.py`, next to `McpClientError`, and raises
  exactly the errors a real failure gives, so `fallback_service` and the breaker cannot tell the
  difference.
- When no rule is active (or the flag is off), `get_mcp_client()` returns the plain client
  object itself: chaos off cannot change any response.
- Chaos writes nothing to the fallback cache. Injected failures never reach upstream, so nothing
  new is saved; in `delay` mode a call that still succeeds returns real upstream data, which is
  saved as usual.

## Metrics

Each request record carries `chaos_active` (chaos was on when it ran); `GET /metrics` adds
`by_chaos: {"on", "off"}`. `GET /metrics?recent=N` (max 50) also returns the last N records (no
user text), which the demo script uses to print fallback_ms per request. Without chaos nothing
changes: `chaos_active` is false and the contracts are computed the same way.

## Demo script

```bash
python scripts/chaos_demo.py --base-url http://127.0.0.1:8000 --target all
python scripts/chaos_demo.py --provider-label live --requests 4    # live: few requests
```

For `error`, then `hang`: warm-up (fills the cache), chaos on, N requests, chaos off, countdown to
HALF_OPEN, one recovery request. One line per request (severity, badges, total_ms, er_ms,
fallback_ms, breaker states, notices); writes `docs/measurements/YYYY-MM-DD-chaos[-live].md` with
the RT-103 table from `/metrics` and the first 3 hang failures that cost the RT-102 timeout. It
takes about 75 s (two 30 s waits). Start a fresh server so `/metrics` holds only this run.

## What to say while showing it

1. "Normal request: LIVE data, breakers CLOSED." (warm-up)
2. "Now the data API fails." (chaos on) "The answer still comes: same ERs and pharmacies, marked
   CACHED, with the FALLBACK_CACHE notice and their original update time, so RT-104 still
   flags old data UNCERTAIN. Serving it takes 1-2 ms: RT-103 is 200 ms."
3. "After 3 failures in a row the breaker opens: we stop calling the broken API at all
   (er_ms is empty) and answer from the cache straight away."
4. "Hang is worse: each of the first 3 calls waits the full 2 s RT-102 timeout. Once the circuit
   is open, that cost is gone."
5. "API back." (chaos off) "After 30 s the breaker lets one trial call through; it succeeds,
   the breaker closes, and the data is LIVE again. Nobody had to restart anything."

In the page, open `/?demo=1` for the Demo controls panel (buttons, breaker state, seconds left).
