# Streaming triage (SSE)

`POST /api/triage/stream` takes the same body as `POST /api/triage` and answers with
`text/event-stream`, so the critical part arrives first (RT-101: first event <= 1.5 s) and the
facilities follow as each worker finishes. `POST /api/triage` is unchanged.

Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no` (stops Nginx from buffering the stream).

## Events

Each message is `event: <name>\ndata: <one-line JSON>\n\n`; `data.event` repeats the name.
The payloads are the `StreamEvent` models in `backend/app/models/stream.py` (in Swagger under the 200 response).

| Event | When | Payload |
|---|---|---|
| `triage` | first, from the rule classifier (no network) | `severity`, `category`, `call_119`, `language`, `location` {name, lat, lon, source}, `at_time`, `prompt_119` (RED only), `t_ms` |
| `er` | ER worker finished | `facilities` (status LIVE / CACHED / UNCERTAIN, `fetched_at`, `distance_km`, ...), `t_ms` |
| `pharmacy` | pharmacy worker finished; never for RED | `facilities`, `otc`, `at_time`, `t_ms` |
| `notice` | as soon as a notice is known, once each | `notice` (LOCATION_DEFAULT, FALLBACK_CACHE, NO_DATA, ER_UNAVAILABLE, ...), `t_ms` |
| `advice` | after the workers | `language`, `advice` (same text as `/api/triage`), `t_ms` |
| `done` | last, then the stream closes | `total_ms`, `stages` {triage, er, pharmacy, advice in ms}, `notices`, `timed_out`, `rt101_ok`, `rt105_ok` |

`er` and `pharmacy` run in parallel and may come in either order. `t_ms` is measured from the start of the stream.

## Guarantees

- **RT-105 cap (6 s):** if the run is not finished by then, the running workers are cancelled, a missing
  worker gets `ER_UNAVAILABLE` / `PHARMACY_UNAVAILABLE`, `advice` is built from the template with what
  is known (the 119 line is always in it), and `done` has `timed_out=true, rt105_ok=false`. The stream never hangs.
- **Failing worker:** the breaker and fallback cache answer first (`FALLBACK_CACHE`); with nothing saved the
  worker sends an empty list plus `*_UNAVAILABLE` and `NO_DATA`. The stream goes on to `done`.
- **Client disconnect:** closing the connection cancels the graph and its running workers.

How it works: the controller opens the LangGraph node-update stream (`graph/triage_graph.stream_updates`,
`astream(stream_mode="updates")`) and hands it to `services/triage_stream_service.stream_triage`, which turns
each node update into events. The same graph serves `/api/triage`; there is no second copy of the logic.

## Example (local run, mock provider)

```bash
python -m mcp_server.server &                     # em-mcp-server on :8001 (EM_PROVIDER=mock)
uvicorn backend.app.main:app --port 8000 &
curl -N -X POST http://127.0.0.1:8000/api/triage/stream \
  -H 'Content-Type: application/json' \
  -d '{"query": "Severe burn on my hand, near Chungju Station, 2 AM"}'
```

Arrival times on the left (data lines shortened):

```
[     3 ms] event: triage
[     3 ms] data: {"event": "triage", "severity": "amber", "category": "burn", "call_119": false, "language": "en", "location": {"name": "Chungju Station (approx.)", "lat": 36.972, "lon": 127.9, "source": "text"}, "at_time": "02:00", "prompt_119": null, "t_ms": 3}
[   940 ms] event: er
[   940 ms] data: {"event": "er", "facilities": [{"name": "Chungju Medical Center ER (mock)", ..., "status": "LIVE", "distance_km": 3.35}, ...], "t_ms": 940}
[   990 ms] event: pharmacy
[   990 ms] data: {"event": "pharmacy", "facilities": [{"name": "Station Night Pharmacy (mock)", ...}], "otc": ["Sterile non-adherent dressing", ...], "at_time": "02:00", "t_ms": 990}
[   991 ms] event: advice
[   991 ms] data: {"event": "advice", "language": "en", "advice": "Get medical care soon: go to an ER or clinic.\n...", "t_ms": 991}
[   991 ms] event: done
[   991 ms] data: {"event": "done", "total_ms": 991, "stages": {"triage": 3, "er": 940, "pharmacy": 990, "advice": 991}, "notices": [], "timed_out": false, "rt101_ok": true, "rt105_ok": true}
```

A RED query (`아버지가 의식이 없어요, 충주역`) starts with `"severity": "red", "prompt_119": "생명이 위험할 수 있습니다. 지금 바로 119에 전화하세요."`
at 0-1 ms, then `er`, `advice`, `done`, and no `pharmacy`.

## Reading it in the browser

`EventSource` only does GET, so use `fetch` and read the body stream:

```js
async function streamTriage(body, onEvent) {
  const resp = await fetch("/api/triage/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {        // one SSE message per blank line
      const message = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const name = message.match(/^event: (.*)$/m)?.[1];
      const data = message.match(/^data: (.*)$/m)?.[1];
      if (name && data) onEvent(name, JSON.parse(data));
    }
  }
}

// Show the 119 prompt the moment it arrives; fill in facilities as they come.
streamTriage({ query: "He is unconscious" }, (name, data) => {
  if (name === "triage" && data.prompt_119) showBanner(data.prompt_119);
  if (name === "er") renderErs(data.facilities);
  if (name === "pharmacy") renderPharmacies(data.facilities);
  if (name === "notice") addNotice(data.notice);
  if (name === "advice") renderAdvice(data.advice);
});
```

Cancelling the request (an `AbortController` passed to `fetch`) closes the stream and cancels the workers on the server.
