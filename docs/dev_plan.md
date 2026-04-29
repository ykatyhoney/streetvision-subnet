# Subnet Validator Refactor — Dev Plan

_Last updated: 2026-04-29_

---

## Context

The `natix-application-server` (proxy API) has been redesigned. Two communication patterns that used to exist between the validator and the proxy API are being replaced, and a new challenge source is being added to the validator's forward loop.

---

## Goals

### 1. Replace credential-based authentication with hotkey signing

**Old:** Validator calls `/credentials` to fetch a signed message, then uses it to verify inbound requests (Ed25519 challenge/response).

**New:** For every outbound API call, the validator signs the current Unix timestamp (seconds) using its **hotkey** (sr25519 / bittensor wallet) and injects three headers:

| Header | Value |
|---|---|
| `x-hotkey` | validator's SS58 hotkey address |
| `x-signature` | hex signature of the timestamp string |
| `x-timestamp` | Unix timestamp as a string (seconds) |

**Files to change:** `neurons/validator_proxy.py` — remove `get_credentials()`, `authenticate_token()`, `verify_credentials`, and the `healthcheck` endpoint. Add a shared helper `build_auth_headers(wallet)` used by all outbound HTTP calls.

---

### 2. Remove the inbound proxy server; replace with periodic outbound polling

**Old:** Validator ran a FastAPI server (`/validator_proxy`, `/health/liveness`). The proxy API pushed organic (consensus) tasks to this server. This required `proxy.port` config, `OrganicTaskDistributor`, `ProxyCounter`, `start_server()`, and the entire `forward()` request-handler.

**New:** The validator **polls** the API for consensus tasks on a timer. No inbound server. No port required.

- Endpoint: `POST /tasks/request` with `{ "scoring_method": 1 }` (label omitted → any label)
- Response: `{ task_id, s3_url, category, scoring_method, label }`
- Validator downloads the image from the presigned S3 URL, distributes it to miners as a normal challenge
- Reports assignment + responses via `POST /tasks/statistics/assign` and `POST /tasks/statistics/report`

**Rate:** configurable via `validator.env` as `ORGANIC_POLL_INTERVAL_SECONDS`, default `360` (6 minutes).

_Rationale:_ 1 140 consensus tasks/day ÷ 5 validators = 228 tasks/validator/day ≈ 1 every 6 min 20 s. Rounding down to 360 s keeps us safely under the API rate limit.

**Files to change:** `neurons/validator_proxy.py` — gut the server scaffolding; replace with a polling loop.

---

### 3. Update statistics API calls

Old paths pointed at `/organic_tasks/statistics/*`. New paths are:

| Old | New |
|---|---|
| `POST /organic_tasks/statistics/assign` | `POST /tasks/statistics/assign` |
| `POST /organic_tasks/statistics/report` | `POST /tasks/statistics/report` |

Payload schema also changed — the field `type` is now `scoring_method` (int: 0 = Benchmark, 1 = Consensus), and `category` must be included.

**Files to change:** `natix/validator/forward.py` — `statistics_assign_task()`, `statistics_report_task()`.

---

### 4. Add API as a third challenge source in `forward.py`

**Old:** `determine_challenge_type()` picks 50/50 between:
- Synthetic (i2i or t2i from `synthetic_media_cache`)
- Real (calls `/dataset/download` on proxy URL)

**New:** Three-way random selection (equal probability, ~33 % each):
- Synthetic (unchanged)
- Real/dataset (unchanged)
- **API** — call `POST /tasks/request` with `{ "category": <category>, "scoring_method": 0, "label": <label> }`, receive a presigned S3 URL, download the image, use it as the challenge.

The label is still determined before the source is selected (as today). If the API source is chosen, the label from the response overrides the randomly chosen one (since the API returns the ground-truth label).

**Files to change:** `natix/validator/forward.py` — `determine_challenge_type()` and `forward()`.

---

## Implementation Steps

- [x] **Step 1 — Auth helper**
  - Add `build_auth_headers(wallet) -> dict` in `natix/validator/api_client.py` (new small file)
  - Signs `str(int(time.time()))` with `wallet.hotkey.sign()`
  - Returns `{"x-hotkey": ..., "x-signature": ..., "x-timestamp": ...}`

- [ ] **Step 2 — Update statistics calls**
  - In `forward.py`: update `statistics_assign_task` → new path, new payload shape (`scoring_method`, `category`)
  - In `forward.py`: update `statistics_report_task` → new path
  - Inject auth headers into both calls

- [ ] **Step 3 — Add API task helper**
  - Add `fetch_api_challenge(wallet, api_url, category, label) -> dict | None` in `forward.py` or `api_client.py`
  - Calls `POST /tasks/request`, downloads image from S3 URL, returns `{"image": PIL.Image, "label": int, "task_id": str}`

- [ ] **Step 4 — Extend `determine_challenge_type`**
  - Add `"api"` as a third source option (uniform 1/3 probability each)
  - Update `forward()` to handle the new source branch

- [x] **Step 5 — Consensus task poller**
  - Add `poll_consensus_tasks(self)` async loop in `validator_proxy.py` or a new `natix/validator/consensus_poller.py`
  - Reads `ORGANIC_POLL_INTERVAL_SECONDS` (default 360) from env / config
  - Calls `POST /tasks/request` with `scoring_method=1`, distributes to miners, reports stats
  - Launched as a background task from `ValidatorProxy.__init__` (or from `validator.py`)

- [x] **Step 6 — Strip the inbound server**
  - Remove `FastAPI` server, `OrganicTaskDistributor`, `ProxyCounter`, `get_credentials`, `start_server`, `authenticate_token`, `verify_credentials`, inbound `forward()` handler, `healthcheck`
  - Remove `proxy.port` dependency
  - Keep only the outbound organic poller started in `__init__`

- [x] **Step 7 — Config / env**
  - Add `ORGANIC_POLL_INTERVAL_SECONDS=360` to `validator.env.example`
  - Wire it into `validator_config.py` (or wherever env vars are read)

---

## API Reference (Tasks Domain)

### `POST /tasks/request`
Headers: `x-hotkey`, `x-signature`, `x-timestamp`

Request: `{ "category": int, "scoring_method": int, "label": int (optional) }`
Response: `{ "task_id": str, "s3_url": str, "category": int, "scoring_method": int, "label": int }`
Errors: `429` rate-limited, `404` no tasks available

### `POST /tasks/statistics/assign`
Headers: `x-hotkey`, `x-signature`, `x-timestamp`

Request: `{ "validator_uid": int, "miner_uid_list": [int], "scoring_method": int, "category": int, "label": int, "payload_ref": str }`
Response: `{ "id": str, "validator_uid": int, "assigned_miner_uids": [int], "ignored_miner_uids": [int] }`

### `POST /tasks/statistics/report`
Headers: `x-hotkey`, `x-signature`, `x-timestamp`

Request bulk: `{ "task_id": str, "miner_uid_list": [int], "predictions": [float] }`

---

## Task Category / Label Codes

| Field | Code | Meaning |
|---|---|---|
| `scoring_method` | 0 | Benchmark (ground-truth label known) |
| `scoring_method` | 1 | Consensus (miners decide) |
| `category` | 0 | Roadwork |
| `category` | 1 | Weather |
| `category` | 2 | Accident |
| `category` | 3 | Near-collision |
| `label` | 0 | Negative / none |
| `label` | 1 | Positive (event present) |

---

## Status

| Step | Status |
|---|---|
| Step 1 — Auth helper | Not started |
| Step 2 — Statistics calls update | Not started |
| Step 3 — API task helper | Not started |
| Step 4 — `determine_challenge_type` extension | Not started |
| Step 5 — Consensus poller | Not started |
| Step 6 — Strip inbound server | Not started |
| Step 7 — Config / env | Not started |
