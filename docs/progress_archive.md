# Progress archive

Session log lines moved out of PROGRESS.md (oldest last).

- 2026-11-03: N5 reviewed against its done-criteria: added the diagnosis filter, budget/RED/never-called/log-privacy tests, llm_smoke, env wiring and docs; commits `d01f8a6`, `3544157`, `4bb77d6`; 299 tests pass. Real API run unverified (no key). Next: N6 first-aid agent.
- 2026-11-03: plan change: added N6 first-aid support agent and N9 quality evaluation; renumbered deploy N6->N7, benchmark N7->N8, report N8->N10; N4 /sessions moved last (optional). Older log lines use the old IDs. Next: N5 LLM client.
- 2026-11-03: pushed main (`7adc347..cc08127`) and tags v0.4-arch-study `8b222e8`, v0.5-framework-agent `567cbf0`, v0.7-multi-agent `394cf52`, v0.9-realtime-sse `af03fb4`, v1.0-reliable-agent `d3fe5c5`. Next: N4.
- 2026-11-03: N3 done: /demo/chaos `826f88e`, chaos_demo + RT-103 measured mock 2/2/2 ms, live 1/3/3 ms `2f5caa2`, demo controls `fb8fb71`; 259 tests pass. Next: N4 checkpointer + /sessions (ask about `langgraph-checkpoint-sqlite` first).
- 2026-11-03: N2 done: GET /metrics `8d35a48`, bench_contracts + measurements mock n=30 / live n=10 `4ed0dd6`; all contracts measured OK except RT-103 (no samples yet); 249 tests pass. Next: N3 /demo/chaos.
- 2026-11-03: status review; committed docker-compose v1 fix `67e986b`; added PROGRESS.md, session protocol in CLAUDE.md, `/progress` command `ac424e0`; 236 tests pass. Next: N2 /metrics.
