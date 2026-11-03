# PROGRESS

Living status file. Read it first every session; update it after every task (protocol in CLAUDE.md).
If this file and the repo disagree, the repo wins. No keys, tokens, personal data or raw API responses here.

## Snapshot

- Date: 2026-11-03 (W6). Deadline: 2026-12-16.
- Branch: `main`
- Last commit: the `docs(progress)` commit for N2; before it `4ed0dd6 feat(scripts): bench_contracts and first measurements [W6]`
- Origin: `origin/main` = `7adc347`; local is ahead by 5 (not pushed)
- Tests: 249 passed (`uv run pytest -q`, 2026-11-03)
- Working tree: clean after the progress commit (local-only files are gitignored: `.env`, `em_fallback.db`, `.idea/`)
- Provider default: `EM_PROVIDER=mock` (`mcp_server/providers.py`); `live` reads data.go.kr (Chungju)

## Contracts (RT-101..105)

Limits live in `backend/app/core/config.py`; timings are recorded per request and summarised by `GET /metrics` (`docs/metrics.md`).
Measured 2026-11-03 with `scripts/bench_contracts.py` on a local server (loopback, sequential requests, no load, not deployed):
mock n=30 (`docs/measurements/2026-11-03-mock.md`), live n=10 (`docs/measurements/2026-11-03-live.md`). Values are server-side p50/p95/max.

| Contract | Requirement | Status | Enforced / measured in | Last measured value |
|---|---|---|---|---|
| RT-101 | TTFT <= 1.50 s | measured end to end (local) | `services/triage_stream_service.py` (rules-only `triage` event first); `tests/test_triage_stream.py::test_first_event_long_before_a_slow_upstream` | mock 1/2/3 ms, **live** 1/3/3 ms (client side: mock 2/3/9, live 2/9/9); 100% ok |
| RT-102 | tool call <= 2.00 s | measured end to end (local) | `clients/mcp_client.py` (one deadline: connect, call, reconnect), timed in `services/fallback_service.py`; `tests/test_mcp_client.py::test_default_timeout_is_rt102` | mock er 739/1077/1093, pharmacy 858/1089/1095 ms; **live** er 3/201/201 (mostly provider cache hits, max = cold call), pharmacy 152/198/198 ms; 100% ok |
| RT-103 | fallback <= 200 ms | implemented; measured in tests only, not measured end to end (no failure in the bench runs) | `services/fallback_service.py` (`wait_for(..., FALLBACK_BUDGET_S)`, timed from the failure); `tests/test_fallback.py::test_hang_served_from_cache_within_rt103`, `tests/test_metrics_api.py::test_fallback_is_counted_when_upstream_fails` | none (0 samples in both runs; N3 chaos will produce them) |
| RT-104 | data > 180 min = UNCERTAIN | implemented (rule, not latency) | `services/freshness.py`, `models/domain.py`; `tests/test_models.py::test_uncertain_after_180_min`, `tests/test_fallback.py::test_old_cache_is_uncertain` | n/a |
| RT-105 | end-to-end <= 6.00 s | measured end to end (local) | `services/triage_stream_service.py` (cap at 6 s), `graph/triage_graph.py` (`total_ms`); `tests/test_triage_graph.py::test_rt105_end_to_end_with_default_mock_latency` | mock 910/1100/1116 ms, **live** 156/221/221 ms (client side: mock 911/1101/1122, live 157/227/227); 100% ok |

Not yet measured: concurrent load, a deployed server over a real network (N6), and RT-103 outside tests (N3).

## Done

### W1-W3 (plan, prototype, research)
- Project context and latency contracts: `cc14d75`, tag `v0.2-research-plan`
- Repo skeleton and requirements: `137ea3c`
- Multilingual HTML prototype with mock data: `9340644`, tag `v0.3-ui-prototype`
- Benchmark: fake LLM and mock tools `2c2c08f`; ReAct and Plan-Execute agents `8b222e8` (in `eval/`)

### W4 (architecture)
- Domain models and RT-104 freshness rule: `df7ef8e`
- Data provider layer with MockProvider: `bc16d03`
- Layered backend (controllers/services/clients/schemas/models/core): `c389c0b`; endpoint map + health service `ecfc480`
- uv project files `642b67c`; data access rule and build order doc `567cbf0`

### W5 (core system)
- mcp SDK `79e5c2c`; em-mcp-server with ER, pharmacy, OTC tools `44e9d14`
- MCP client with RT-102 timeout `0478379`; arch test backend never imports mcp_server `4373a37` (tags `v0.6-mcp-integrated`, `midterm-demo-v0.6`)
- App-wide MCP client and error mapping (503/504/502) `8887e5b`; connect bounded by RT-102 `71eaab8`; reconnect closes only the failed connection `b97ff1f`
- GET /facilities/er `f906d50`, /facilities/ph `39fb57e`, /otc/{cat} `5c065c8`
- Language detection + rule classifier (EN/RU/ZH/KO) `95b3515`; location, time, advice templates `52d73c3`
- LangGraph supervisor, parallel ER + pharmacy workers `394cf52`; POST /api/triage `05a4937`
- data.go.kr samples for Chungju `01e5098`; LiveProvider `4e9ff8a`; data sources doc `b92ea0b`
- Circuit breaker + SQLite fallback cache `d3fe5c5`, doc `d8d8c37`
- POST /api/triage/stream (SSE) `86d794d`, doc `67ba050`; frontend on the stream `af03fb4`
- `scripts/run_dev.sh` and README run guide `ed5dade`

### W6 (packaging)
- Pharmacy: nearest closed pharmacies with closing time `27c2702`
- Docker compose (mcp + api containers, fallback-db volume) `7adc347`
- N1 docker-compose v1 fix: env vars read directly instead of `env_file: required` `67e986b`
- PROGRESS.md, session protocol, `/progress` command `ac424e0`
- N2 GET /metrics: per-request records (no user text), ring buffer 1000, nearest-rank p50/p95/max + ok_rate per contract, counters, breakers `8d35a48`; 13 tests (`tests/test_metrics_service.py`, `tests/test_metrics_api.py`)
- N2 `scripts/bench_contracts.py`, `docs/metrics.md`, first measurements mock n=30 + live n=10 `4ed0dd6`

## In progress / uncommitted

- Nothing half done. `docs/progress_archive.md` does not exist yet (created when the log passes 10 lines).

## Next steps

1. **N3 POST /demo/chaos.** Turn failure/delay injection on and off through an MCP tool (backend still never imports mcp_server).
   Done when: test shows chaos on -> `FALLBACK_CACHE` notice and CACHED data within RT-103, chaos off -> LIVE/MOCK again; a bench run with chaos on fills the RT-103 row with real samples.
2. **N4 LangGraph SQLite checkpointer and GET /sessions/{id}.** Persist each triage run; return its state.
   Done when: test runs a triage, then GET /sessions/{id} returns the same severity and facilities; unknown id -> 404. Ask before adding `langgraph-checkpoint-sqlite`.
3. **N5 Real LLM client (`EM_LLM`).** Rewrite advice and extract context (location, time); rules stay the fallback and keep severity.
   Done when: `EM_LLM` unset behaves exactly as today (tests unchanged); tests prove a slow/failing LLM falls back to the template within `LLM_TIMEOUT_S` and never changes severity. Ask before adding an SDK.
4. **N6 Docker/Nginx deployment.** Public URL behind Nginx with SSE buffering off.
   Done when: `/health` returns 200 on the public URL and the stream arrives event by event (curl -N output). Tag `v1.2-online-service` after asking.
5. **N7 Benchmark ReAct vs Plan-Execute on live data.** Reuse `eval/` agents against em-mcp-server with `EM_PROVIDER=live`.
   Done when: a results table (latency, tool calls, RT pass rate) is in `docs/` with the command that produced it.
6. **N8 Final report and release.** Report, demo script, tag `v1.3-final-release` (ask first). Due 2026-12-16.
   Done when: report committed, all tests pass, tag plan approved.

## Endpoints

| Endpoint | Status | Controller |
|---|---|---|
| GET /health | built | `health_controller.py` |
| POST /api/triage | built | `triage_controller.py` (graph `graph/triage_graph.py`) |
| POST /api/triage/stream (SSE) | built | `triage_stream_controller.py` |
| GET /facilities/er | built | `facilities_er_controller.py` |
| GET /facilities/ph | built | `facilities_pharmacy_controller.py` |
| GET /otc/{cat} | built | `otc_controller.py` |
| GET / (frontend, static) | built | mounted in `main.py` |
| GET /metrics | built (N2) | `metrics_controller.py` |
| POST /demo/chaos | planned (N3) | - |
| GET /sessions/{id} | planned (N4) | - |

## Known gaps and decisions

- Missing milestone tags: `v0.4-arch-study`, `v0.5-framework-agent`, `v0.7-multi-agent` (work exists; tag plan proposed, not created; tags need approval).
- LLM not wired: `clients/llm_client.py` has only `NoLlm` (returns the template). Triage is keyword rules only (N5).
- Metrics are in memory only (lost on restart); a stream abandoned before `done` is not recorded.
- No LangGraph checkpointer yet; SQLite is used only for the fallback cache (`clients/fallback_store.py`).
- Pharmacy radius API returns only today's hours: open status for other days is unknown (`docs/data_sources.md`).
- `docs/samples/*.xml` are pinned by `tests/test_live_provider.py`: never re-capture them without updating the tests.
- Keys: `EM_DATA_GO_KR_KEY` (and optional `EM_DATA_GO_KR_KEY_PHARMACY`) live only in `.env` (gitignored). Never print, log or commit them.
- Decision: RT-103 is measured from the moment of failure (after the RT-102 timeout fires), not from request start.
- Decision: severity stays rule-based; an LLM may only rewrite text or extract context.
- Decision: mock is the default provider; mock data is always labelled MOCK, live data LIVE.

## Session log

Newest first. One line per session; lines beyond the last 10 go to `docs/progress_archive.md`.

- 2026-11-03: N2 done: GET /metrics `8d35a48`, bench_contracts + measurements mock n=30 / live n=10 `4ed0dd6`; all contracts measured OK except RT-103 (no samples yet); 249 tests pass. Next: N3 /demo/chaos.
- 2026-11-03: status review; committed docker-compose v1 fix `67e986b`; added PROGRESS.md, session protocol in CLAUDE.md, `/progress` command `ac424e0`; 236 tests pass. Next: N2 /metrics.
