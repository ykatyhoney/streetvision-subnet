# Project Status

Snapshot of the project state as of 2026-05-02. Update this file after completing each migration step.

---

## Migration progress

| Step | Description | Status |
|------|-------------|--------|
| 1 | Create migration documentation | ✅ Done |
| 2 | Drop Poetry, pip + venv, dependency isolation | ✅ Done |
| 3 | Fix `protocol.py` dependency inversion | ✅ Done |
| 4 | Move `base_miner/` → `natix/miner/` | ✅ Done |
| 5 | Move `natix/synthetic_data_generation/` → `natix/validator/synthetic/` | ✅ Done |
| 6 | Move `neurons/validator_proxy.py` → `natix/validator/proxy/` | ✅ Done |
| 7 | Split `natix/validator/forward.py` | ✅ Done |
| 8 | Consolidate statistics reporting into `api_client.py` | ✅ Done |
| 9 | Thin entry points in `neurons/` | ✅ Done |
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

## Dependency footprint (post Step 2)

Four independently installable extras groups in `pyproject.toml`:

| Install command | Gets |
|----------------|------|
| `pip install -e ".[miner]"` | torch, timm, ultralytics, opencv, scikit-image |
| `pip install -e ".[validator]"` | wandb, joblib — no DL, no heavy image libs |
| `pip install -e ".[validator,validator-image]"` | + datasets, opencv, scikit-image |
| `pip install -e ".[validator,validator-image,validator-synthetic]"` | + torch, diffusers, transformers |

Requirements files for Docker:
- `requirements.miner.txt`
- `requirements.validator.txt` (core + image pipeline)
- `requirements.validator-full.txt` (core + image + synthetic)

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
