# EM-Agent: Real-Time Emergency Triage & Facility Dispatch Engine

Course: Real-Time Agentic AI Systems. Deadline: 2026-12-16. Presenter: Jasurbek.

## Goal

User describes an emergency in free text (EN/RU/ZH/KO). The system finds the nearest ER with free beds and the nearest open pharmacy, and streams guidance.

## Architecture

Supervisor router (LangGraph) -> ER worker + Pharmacy worker in parallel (asyncio) -> em-mcp-server -> data provider. FastAPI + SSE. SQLite for checkpoints and offline fallback.

## Architecture rules

```
backend/app/
  controllers/  FastAPI routers      -> schemas, services, graph, core
  graph/        LangGraph supervisor -> services, models, core
  services/     pure business logic  -> clients, models, core
  clients/      MCP client (network) -> models, core   (calls em-mcp-server over MCP)
  schemas/      API DTOs             -> models
  models/       domain enums/entities-> core
  core/         config               -> (nothing in app)
mcp_server/     em-mcp-server + data providers -> backend.app.models, backend.app.services
```

Endpoint map: one controller, one service (one use case) and one schema module per endpoint.

```
Endpoint            Controller                          Service                        Schemas
GET  /health        health_controller.py                health_service.py              health.py
POST /api/triage    triage_controller.py                triage_service.py              triage.py
(stream)            triage_stream_controller.py         triage_stream_service.py       triage_stream.py
GET  /facilities/er facilities_er_controller.py         er_facility_service.py         er_facility.py
GET  /facilities/ph facilities_pharmacy_controller.py   pharmacy_facility_service.py   pharmacy_facility.py
GET  /otc/{cat}     otc_controller.py                   otc_service.py                 otc.py
GET  /sessions/{id} sessions_controller.py              session_service.py             session.py
POST /demo/chaos    demo_chaos_controller.py            chaos_service.py               chaos.py
GET  /metrics       metrics_controller.py               metrics_service.py             metrics.py
```

- Services return domain data (models or plain values); controllers map it to schemas.
- main.py is the composition root: it may import clients to own the shared MCP client (lazy, closed on shutdown) and map McpClientError to HTTP (UNAVAILABLE 503, TIMEOUT 504, TOOL_ERROR/BAD_RESPONSE 502). Controllers never touch the client; services get it via clients.get_mcp_client().
- The backend reaches data only through the MCP client. Never import mcp_server or a provider from backend/.
- Build order: B3 builds the MCP server and MCP client first; /facilities/er, /facilities/ph and /otc/{cat} come after, on top of the client.
- /metrics returns a JSON summary (no Prometheus format).
- /sessions/{id} and the triage stream wait until LangGraph and SSE are in place.
- Imports are one-way, top to bottom. No layer imports a layer above it.
- Controllers contain no logic: parse the request, call a service or graph, return a schema.
- Services never import FastAPI (or anything HTTP); they stay testable without a server.
- Models are domain (what the system knows); schemas are API (what clients send and receive).
- Keep package `__init__.py` files empty (no re-exports) to avoid import cycles.
- Single allowed exception: models/domain.py uses services/freshness.py so RT-104 is enforced on every facility object. freshness.py must stay pure and import only core and models/enums.

## Latency contracts

- RT-101 TTFT <= 1.50 s
- RT-102 tool call <= 2.00 s
- RT-103 fallback <= 200 ms
- RT-104 data older than 180 min = UNCERTAIN
- RT-105 end-to-end <= 6.00 s

## Data

data.go.kr is NOT available. Use MockProvider (NMC-like fields: hvec, tel, fetched_at) with delay and failure injection, plus a LiveProvider interface for later. Mock data is always labelled MOCK.

## Rules

- Python 3.11+, type hints, Pydantic, async only.
- Small commits, pytest for new logic, run tests before saying done.
- Not medical advice; 119 prompt for critical cases.
- Ask before adding dependencies beyond fastapi, uvicorn, httpx, pydantic, langgraph, pytest, mcp (v2 SDK: `MCPServer`, not FastMCP).

## Git workflow

- Remote https://github.com/brave0926/EM-Project.git, branch main.
- Commit format: `type(scope): summary [week]`, e.g. `feat(benchmark): add comparison [W3]`.
- Milestone tags (annotated): v0.2-research-plan, v0.3-ui-prototype, v0.4-arch-study, v0.5-framework-agent, v0.6-mcp-integrated, midterm-demo-v0.6, v0.7-multi-agent, v0.8-distributed, v0.9-realtime-sse, v1.0-reliable-agent, v1.1-observable, v1.2-online-service, v1.3-final-release.
- Never force-push.
- Never commit .env, keys, .venv or *.db.
- Ask me before the first push and before pushing any tag.
