# LLM: advice rewrite and context extraction (N5)

The LLM is optional. With it off (the default) the app runs on keyword rules and templates
alone, exactly as before N5. With it on, it does two jobs, and it can't change anything that
matters for safety:

| Job | Input | Output | Used only if |
|---|---|---|---|
| `extract` | the user's message | JSON `{"time": "HH:MM" \| null, "place": <known place id> \| null}` | the rules found no place (no request coordinates, no place name in the text) or no time (not for RED) |
| `rewrite` | the template advice | a clearer, calmer text in the same language | it passes validation (below) |

Severity, category and the 119 prompt always come from `services/classifier_service.py`. The
LLM never sees or sets them. The first stream event (`triage`, RT-101) never waits for the LLM.

## Enable

```bash
# .env (gitignored; see .env.example)
EM_LLM=anthropic
ANTHROPIC_API_KEY=...          # never commit, print or log it
EM_LLM_MODEL=                  # optional, default claude-haiku-5-5

scripts/run_dev.sh             # banner shows "LLM anthropic claude-haiku-5-5" or "LLM off"
docker compose up              # passes EM_LLM, EM_LLM_MODEL, ANTHROPIC_API_KEY to the api container
```

`EM_LLM` set to anything other than `anthropic`, or a missing key, means `NoLlm`. The services
then never call it, add no `LLM_FALLBACK` notice and report `"outcome": "off"`.

## Budget (`core/config.py`)

- `LLM_TIMEOUT_S = 1.0`: each job is cut off at this limit. The SDK runs with `max_retries=0`.
- `LLM_RESERVE_S = 0.3`: a job's budget is shortened so it ends at least 0.3 s before the RT-105
  limit of the request, and with less time left no call is started (outcome `timeout`).
- Worst case: extract and rewrite, about 1 s each, run in series with the workers between them. That stays inside RT-105 (6 s).

## Validation and fallback (`services/llm_service.py`)

A rewrite is discarded, and the template shown instead, when it:

- is empty or longer than `LLM_REWRITE_MAX_CHARS` (900);
- drops a facility name or phone number that is in the template (`advice_service.required_in_rewrite`);
- drops the 119 line for RED, or drops "119" when the template has it;
- adds a dose (`_DOSE`: mg, ml, tablets... in EN/RU/ZH/KO) or a diagnosis (`_DIAGNOSIS`:
  "you probably have a ...", "диагноз", "诊断", "진단", ...) that the template doesn't have.

Extraction output must be strict JSON matching `models/llm.LlmContext`: a time as `HH:MM` and a
place from `KNOWN_PLACES` (`chungju_station`, `yeonsu_dong`, `city_hall`), with no extra keys.
The place id is mapped to coordinates by `location_service.known_place`, so the LLM never supplies
coordinates. Anything else is ignored. Rules always win: the LLM fills only the fields the rules left empty.

On a timeout, error or invalid output the request continues on rules and template, and the notice
`LLM_FALLBACK` is added. The notice is technical, so it is not written into the advice text.

## Observability

- Stream: `context` event (only when the LLM filled a place or time); `done.llm` =
  `{"extract_ms", "rewrite_ms", "outcome"}`. Outcome is the worst of the jobs that ran:
  `error > timeout > invalid > ok`, or `off` when no call was made.
- `GET /metrics`: `llm.extract_ms` and `llm.rewrite_ms` (p50/p95/max, ok_rate against
  `LLM_TIMEOUT_S`) and `llm.outcomes` counters, plus `llm_*` per record in `?recent=N`.
- `/demo/chaos` target `llm` (modes `error`, `hang`, `delay`; needs `EM_DEMO_CHAOS=1`)
  makes both jobs fail so the fallback can be shown. `all` still means er + pharmacy only.

## Privacy

Nothing in `/metrics`, the logs or the SQLite fallback cache holds the user's text or the key. The
log line per job is `llm <job> <outcome> <ms> ms`, and errors log only the exception class name
(`tests/test_llm.py::test_logs_hold_no_user_text_and_no_key`). The message itself is sent to the
Anthropic API when `EM_LLM=anthropic`. Don't enable the SDK's own debug logging
(`ANTHROPIC_LOG=debug`), since that would log the request bodies.

## Try it

```bash
python scripts/llm_smoke.py                  # 1 extraction + 1 rewrite (EN), latency and outcome; exit 2 without a key
python scripts/llm_smoke.py --all-langs      # the same in EN, RU, ZH, KO
EM_LLM=anthropic scripts/run_dev.sh          # then, in another shell:
python scripts/llm_smoke.py --chips http://127.0.0.1:8000   # the 16 demo chips: severity, done.llm, notices
```

Only the fixed demo texts are sent. Tests (`tests/test_llm.py`) use a fake client and never call the API.
