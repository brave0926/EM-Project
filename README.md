# EM-Agent: Real-Time Emergency Triage & Facility Dispatch Engine

EM-Agent takes a free-text emergency description (EN/RU/ZH/KO) and finds the nearest ER with free beds and the nearest open pharmacy.
A LangGraph supervisor runs ER and pharmacy workers in parallel and streams guidance over FastAPI + SSE, with strict latency contracts.
Facility data currently comes from a mock provider (labelled MOCK). This is not medical advice; call 119 in a critical emergency.

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

With uv instead: `uv venv && uv pip install -r requirements.txt`.

## Run locally

```bash
scripts/run_dev.sh                    # mock data (default): em-mcp-server + API, Ctrl+C stops both
EM_PROVIDER=live scripts/run_dev.sh   # real data.go.kr data for Chungju
```

Then open http://127.0.0.1:8000/ (Swagger at `/docs`). The page streams `POST /api/triage/stream`
(see `docs/streaming.md`).

- Live mode needs the keys in `.env` (copy `.env.example`): `EM_DATA_GO_KR_KEY`, and optionally
  `EM_DATA_GO_KR_KEY_PHARMACY`. See `docs/data_sources.md`.
- `EM_PROVIDER` from the shell wins over `.env`; without either it is `mock`.
- Ports: `API_PORT` (default 8000) and `EM_MCP_PORT` (default 8001), e.g. `API_PORT=8020 scripts/run_dev.sh`
  if 8000 is taken. The script stops if a port is already in use.
- The last good facility data is kept in `em_fallback.db` (gitignored; `EM_FALLBACK_DB` to move it),
  so the page still answers when the data source is down (`docs/resilience.md`).

## Run tests

```bash
pytest
```
