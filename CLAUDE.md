# EM-Agent: Real-Time Emergency Triage & Facility Dispatch Engine

Course: Real-Time Agentic AI Systems. Deadline: 2026-12-16. Presenter: Jasurbek.

## Goal

User describes an emergency in free text (EN/RU/ZH/KO). The system finds the nearest ER with free beds and the nearest open pharmacy, and streams guidance.

## Architecture

Supervisor router (LangGraph) -> ER worker + Pharmacy worker in parallel (asyncio) -> em-mcp-server -> data provider. FastAPI + SSE. SQLite for checkpoints and offline fallback.

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
- Ask before adding dependencies beyond fastapi, uvicorn, httpx, pydantic, langgraph, pytest.

## Git workflow

- Remote https://github.com/brave0926/EM-Project.git, branch main.
- Commit format: `type(scope): summary [week]`, e.g. `feat(benchmark): add comparison [W3]`.
- Milestone tags (annotated): v0.2-research-plan, v0.3-ui-prototype, v0.4-arch-study, v0.5-framework-agent, v0.6-mcp-integrated, midterm-demo-v0.6, v0.7-multi-agent, v0.8-distributed, v0.9-realtime-sse, v1.0-reliable-agent, v1.1-observable, v1.2-online-service, v1.3-final-release.
- Never force-push.
- Never commit .env, keys, .venv or *.db.
- Ask me before the first push and before pushing any tag.
