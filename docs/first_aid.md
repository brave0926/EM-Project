# First-aid support agent (N6)

A third worker in the supervisor graph tells the user **what to do now** and which over-the-counter
product **types** may help. Medical safety comes first: every sentence comes from a curated knowledge
base, never from model memory. Not medical advice; not clinically validated.

```
START -> triage -> extract -+- red:   er_worker || first_aid_worker ---------------------+-> advise -> END
                            +- other: er_worker || pharmacy_worker || first_aid_worker ---+
first_aid_worker -> first_aid_service -> MCP client -> em-mcp-server get_first_aid -> mcp_server/data/first_aid.json
```

## Knowledge base (`mcp_server/data/first_aid.json`)

One entry per category, plus `generic`. Each entry has stable item ids (`burn.cool`), `steps` (in order),
`do_not`, `warning_signs` (each with match terms per language), `otc_types`, `sources` and
`reviewed` per language.

| Kind | Entries | Products |
|---|---|---|
| standard | burn, cut, fever, minor | product types only (`otc_types`), always with the line "use as labelled; ask a pharmacist; tell them about allergies, age, pregnancy" |
| minimal | critical, and the high-risk entries below | none: 119 or the ER first, no home-treatment instructions, no CPR instructions |
| generic | `generic` (category `other`, or any category without an entry) | none: stay with the person, no food or drink, watch breathing and response, ER/119 if worse or unsure, ask a pharmacist before any product. Shown with "No specific guide for this case" |

High-risk categories are rule-based (`services/classifier_service.py`, EN/RU/ZH/KO with RU stems, ё read as е,
and Chinese/Korean matched with spaces removed). None of them is ever GREEN:

| Category | Severity |
|---|---|
| head_injury, eye_injury, fracture | AMBER |
| bite | AMBER; a snake bite is RED |
| allergy | AMBER; swelling of the lips, mouth, tongue or throat, or anaphylaxis, is RED |
| choking, electric_shock, drowning, heavy_bleeding | RED (119) |

High-risk categories are checked before `critical` so the guide is specific. Critical words anywhere
in the text (unconscious, not breathing, ...) still make any case RED.

### Sources

All 16 sources were opened and checked on 2026-11-03 (NHS, British Red Cross, St John Ambulance).
None is marked `UNVERIFIED`. They are UK pages, so 999 is given as 119 (Korea). The NHS pages
"When to go to A&E" and "Anaphylaxis" are past their own review dates. A source the team cannot
verify must be written with `"verified": false, "url": "UNVERIFIED"`; the validator enforces this.

### Translations

Every text exists in EN/RU/ZH/KO. **All are drafts (`reviewed: false`)**: EN was written from the
sources, and RU/ZH/KO are machine-translated drafts that a human must review. The card says
"Draft text, not yet reviewed by a medical professional" while `reviewed` is false.

## Safety rules (enforced by tests)

- `services/content_safety.py`: no number followed by a dose unit or tablet/pill word (any language),
  no diagnosis phrases, no brand names (small blocklist), no drug names, no prescription drugs.
  `tests/test_first_aid_kb.py` checks every text of every entry in every language. The same patterns
  validate LLM advice rewrites.
- Every entry has sources and warning signs; minimal and generic entries have no products.
- A warning sign named in the user's text (`match` terms) sets the escalation line "go to the ER now
  or call 119" at the top of the card. Severity is never changed by the first-aid worker: it comes
  from the rules only, so a GREEN case can carry an escalation line (for example "acid burn").
- RED always gets a minimal entry: a RED burn/cut/fever/minor case gets the `critical` entry.
- Failure (MCP error, timeout, bad data) never breaks the request: notice `FIRST_AID_UNAVAILABLE`, no
  card, and the advice template as before. Under the RT-105 cut the same notice is added.

## What the LLM may and may not do

Only with `EM_LLM=anthropic` (see `docs/llm.md`). The job `select_items(query, language, items)`
gets the ids and texts of the entry's steps and products and returns JSON ids only:

- Allowed: pick 1-8 ids from the given list, at least one of them a step. The card then shows only
  those steps/products, in knowledge-base order. `do_not` and `warning_signs` are always shown in full.
- Rejected (full entry kept, `LLM_FALLBACK`): non-JSON, empty, duplicates, unknown or made-up ids,
  more than 8, products only, timeout (`LLM_TIMEOUT_S`) or any error.
- Never: write medical text, change severity or the 119 prompt, or select anything for a minimal
  or generic entry (no call is made). It cannot answer outside the knowledge base.

## API

- SSE event `first_aid` (any order with `er` and `pharmacy`): `entry`, `kind`, `language`, `steps`,
  `do_not`, `warning_signs`, `otc_types`, `otc_note`, `escalate`, `matched_warning_signs`,
  `no_specific`, `not_medical_advice`, `sources`, `reviewed`, `selected_by`, `t_ms`.
  Match terms are never sent to the client.
- `POST /api/triage`: the same card in `first_aid` (null when unavailable).
- `GET /metrics`: `first_aid.worker_ms` (limit = RT-102 budget), `outcomes` (ok/unavailable/none),
  `by_category`, `uncovered` (generic entry), `escalated`, `llm_selected`; `llm.select_ms`.
  No user text is stored.
- Frontend: a "What to do now" card under the severity / 119 banner (4 languages).

## Evaluation

`eval/scenarios/first_aid.yaml`: 30 cases covering all 15 entries, all 4 languages, warning signs,
RED, high-risk and 8 out-of-base phrases (insect in the ear, tooth, hiccups, foreign object, splinter).
The file is YAML in JSON flow style, so it is read with `json` and needs no YAML dependency.

```bash
uv run pytest -q tests/test_first_aid_scenarios.py
```

Each case runs through the graph with rules only and with a fake LLM that returns invalid ids,
valid ids, garbage, a made-up id and a timeout (6 modes, 180 runs). Checked: the entry, the severity
(and that the LLM never changes it), the must / must_not items, and the global safety patterns.

## Limits

- Not clinically validated; all texts are unreviewed drafts. Keyword rules miss phrasings that are not
  in the tables. Those cases fall to `other` (AMBER, generic entry) or, for burn/cut/fever/minor
  words, to the normal path.
- Some keywords are broad on purpose (cautious): for example Korean «부러졌» ("broke") puts a broken
  tooth into `fracture` (AMBER) instead of `generic`.
- The escalation line does not raise severity (see above).
- The real LLM selection has not been run against the Anthropic API (no key, see `docs/llm.md`).
