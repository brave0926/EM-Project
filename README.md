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

## Run tests

```bash
pytest
```
