# Data sources

`EM_PROVIDER` picks the provider in em-mcp-server: `mock` (default) or `live`.
Mock data is labelled `MOCK`, data.go.kr data `LIVE`. Raw samples of every response are in `docs/samples/`
(captured with `scripts/capture_samples.py`); `scripts/live_smoke.py` runs LiveProvider once for Chungju.

## Keys

| Variable | Used for |
|---|---|
| `EM_DATA_GO_KR_KEY` | ER service (`ErmctInfoInqireService`) |
| `EM_DATA_GO_KR_KEY_PHARMACY` | Pharmacy service (`ErmctInsttInfoInqireService`); falls back to `EM_DATA_GO_KR_KEY` |

Keys live in `.env` (gitignored, loaded when em-mcp-server starts; the shell environment wins).
`serviceKey` is sent as a normal query parameter; an already URL-encoded key is decoded first.
Keys never appear in errors, logs, samples or tests.

## Operations used

| Tool | Operation | Parameters |
|---|---|---|
| `get_er_beds` | `ErmctInfoInqireService/getEmrrmRltmUsefulSckbdInfoInqire` (real-time beds) | `STAGE1`, `STAGE2` (default 충청북도 / 충주시), `numOfRows=30` |
| `get_er_beds` | `ErmctInfoInqireService/getEgytBassInfoInqire` (basic info, one per hospital) | `HPID` |
| `get_pharmacies` | `ErmctInsttInfoInqireService/getParmacyLcinfoInqire` (by location) | `WGS84_LON`, `WGS84_LAT`, `numOfRows=30` |

The bed list has no coordinates, so each hospital is joined with its basic info on `hpid`.
Region: `Chungju` (or empty) maps to 충청북도 / 충주시; `"<STAGE1> <STAGE2>"` in Korean is passed through;
anything else is `UNKNOWN_REGION`, so a typo never silently returns Chungju data.

## Field mapping

ER (`ERFacility`)

| Field | Source | Notes |
|---|---|---|
| `name` | beds `dutyName` | |
| `tel` | beds `dutyTel3` (ER line), else `dutyTel1`, else basic `dutyTel1` | `""` if none |
| `hvec` | beds `hvec` | free ER beds; negative (overcrowded) -> 0; no `hvec` -> hospital skipped |
| `hvicc` | beds `hvicc` | free ICU beds; absent -> `None` (unknown, never 0) |
| `fetched_at` | beds `hvidate` | `YYYYMMDDHHMMSS`, KST (no zone in the string) -> aware datetime |
| `location.lat/lon` | basic `wgs84Lat` / `wgs84Lon` | no coordinates -> hospital skipped |
| `location.name` | basic `dutyAddr` | |
| `distance_km` | haversine from the patient | sorted nearest first |

Pharmacy (`PharmacyFacility`)

| Field | Source | Notes |
|---|---|---|
| `name`, `tel` | `dutyName`, `dutyTel1` | |
| `location` | `latitude`, `longitude`, `dutyAddr` | |
| `distance_km` | `distance` (km, from the API) | haversine if absent; sorted nearest first |
| `is_open` | `startTime` / `endTime` (today, HHMM) | `is_open()` with midnight crossover; `2400`+ means past midnight; equal start/end = 24 h; missing hours -> `None` |
| `open_until` | `endTime` as `HH:MM` | `None` when open status is unknown |

Closed pharmacies are dropped; open and unknown ones are returned. Advice only names a pharmacy known to be open.

## Limits

- Quota: 1000 calls per day per operation. One cold ER request costs 1 + (number of hospitals) calls
  (3 for Chungju), a warm one 0-1; a pharmacy request costs 1.
- Pharmacy hours: the location operation only returns **today's** `startTime`/`endTime`. `at_time` is a time of day
  and is read as today (KST). Hours for another day, and late-night hours carried over from yesterday
  (e.g. yesterday until 02:00 when you ask at 01:00), are not visible; open status is unknown when the hours
  are missing. The week schedule (`dutyTime1s/1c` ... `dutyTime8s/8c`) is in `getParmacyListInfoInqire`, which has
  no distance; not used yet.
- Timeouts: 1.5 s per upstream call, 1.8 s for the whole tool call (RT-102 is 2.0 s including MCP).
  Timeouts, HTTP errors, non-XML and `resultCode != 00` raise `ProviderError` with a code and message only.
- `getOtc` has no data.go.kr source; LiveProvider returns the same static generic first-aid lists.

## Caching (in memory, per server process)

| Data | TTL | Why |
|---|---|---|
| Beds per region | 60 s | NMC updates beds every few minutes; absorbs bursts |
| Basic info per `hpid` | 24 h | coordinates and address rarely change; saves quota |

Failed calls are not cached.

## UNCERTAIN for live data

RT-104 marks a facility `UNCERTAIN` when its data is older than 180 minutes. For live ERs the age is measured from
`hvidate` (when the hospital last reported beds), not from when we fetched it, so a hospital that stopped reporting
turns UNCERTAIN even though the call just succeeded. An ER without `hvidate` is UNCERTAIN (age unknown).
Live pharmacy data carries no update time, so `fetched_at` is the fetch time.
