# Project Status

Snapshot of the project state as of 2026-05-02. Update this file after completing each migration step.

---

## Migration progress

| Step | Description | Status |
|------|-------------|--------|
| 1 | Create migration documentation | ✅ Done |
| 2 | Dependency isolation (Poetry extras) | ⬜ Not started |
| 3 | Fix `protocol.py` dependency inversion | ⬜ Not started |
| 4 | Move `base_miner/` → `natix/miner/` | ⬜ Not started |
| 5 | Move `natix/synthetic_data_generation/` → `natix/validator/synthetic/` | ⬜ Not started |
| 6 | Move `neurons/validator_proxy.py` → `natix/validator/proxy/` | ⬜ Not started |
| 7 | Split `natix/validator/forward.py` | ⬜ Not started |
| 8 | Consolidate statistics reporting into `api_client.py` | ⬜ Not started |
| 9 | Thin entry points in `neurons/` | ⬜ Not started |
| 10 | Validation, cleanup, Dockerfile verification | ⬜ Not started |

---

## Current branch

`development` — all migration work happens here before merging to `main`.

---

## Known issues (pre-migration)

### Critical
- `natix/protocol.py` imports `torch` at module level → breaks torch-free validator installs
- `natix/protocol.py` imports `natix/validator/config.py` → layering violation
- Statistics reporting is duplicated in 3 places with inconsistent signatures

### Significant
- `base_miner/` is outside `natix/` — naming inconsistency confuses module layout
- `neurons/validator_proxy.py` contains business logic, not just an entry point
- `natix/synthetic_data_generation/` is in the wrong namespace
- All DL dependencies are installed for both miner and validator (no separation)

### Minor
- `natix/validator/proxy.py` (the old proxy.py) is a thin shell that's barely used
- `natix/validator/api_client.py` only contains `build_auth_headers()` — understaffed
- `forward.py` has two exported functions (`statistics_assign_task`, `statistics_report_task`) that are imported by unrelated modules

---

## Current dependency footprint

All packages in one `pyproject.toml`, everyone installs everything:
- torch 2.2.0
- torchvision 0.17.0
- torchaudio 2.2.0
- transformers ~4.45.0
- diffusers ^0.32.2
- accelerate ^1.2.0
- ultralytics ^8.3.44
- opencv-python ^4.10.0.84
- scikit-image ^0.24.0
- datasets ^3.1.0
- (+ bittensor, wandb, httpx, etc.)

Target after Step 2:
- **Validator core** install: bittensor, httpx, Pillow, numpy, wandb, loguru, pydantic, joblib — no DL
- **Validator + synthetic** install: adds torch, torchvision, diffusers, transformers
- **Miner install**: torch, torchvision, timm, ultralytics, opencv-python

---

## What currently works (as of 2026-05-02)

- Miner starts and serves axon: `start_miner.sh` works
- Validator starts, initializes caches, runs forward loop: `start_validator.sh` works
- Organic task proxy polls API and distributes to miners: `validator_proxy.py` works
- Cache updater runs as background process: `start_cache_updater.sh` works
- Synthetic data generator runs as background process: `start_synthetic_generator.sh` works
- Validator sets weights on-chain via `set_weights()`

---

## Testing state

- `tests/` directory has basic test coverage
- No tests for validator proxy or organic task distributor
- No tests for statistics reporting
- Dockerfiles build and run but have not been tested post-migration
