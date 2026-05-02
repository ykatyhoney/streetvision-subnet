# Migration Tasks

Ten steps to migrate from the current mixed structure to the clean architecture described in ARCHITECTURE.md. Each step is self-contained and should be done in order — later steps depend on earlier ones.

**Current status:** Step 1 complete. Steps 2–10 not started.

---

## Step 1 — Create migration documentation ✅

Create ARCHITECTURE.md, TASKS.md, TECH_DECISIONS.md, PROJECT_STATUS.md, SPECIFICATIONS.md, WORKFLOW.md at project root.

**Why first:** Every subsequent step needs a shared reference point to avoid re-litigating decisions mid-task.

---

## Step 2 — Drop Poetry, switch to pip + venv, and isolate dependencies ✅

**Goal:** Miner and validator can be installed independently using plain pip and a standard venv. Drop Poetry entirely. DL libraries (torch, diffusers, etc.) become optional extras for the validator.

**Why drop Poetry:** The current `pyproject.toml` is already a hybrid — it uses the PEP 621 `[project]` header but puts dependencies in the Poetry-proprietary `[tool.poetry.dependencies]` section. The existing `start_validator.sh` already uses a plain `venv/`, not Poetry. Bittensor subnets standardly use pip. PEP 621 optional dependencies (`[project.optional-dependencies]`) give us the same extras mechanism without the extra toolchain.

**Changes:**

1. Migrate `pyproject.toml` to PEP 621 format:
   - Move deps from `[tool.poetry.dependencies]` to `[project.dependencies]` (core deps only)
   - Add `[project.optional-dependencies]` with four groups:
     - `miner` — torch==2.2.0, torchvision==0.17.0, torchaudio==2.2.0, timm, ultralytics, opencv-python, scikit-image, scikit-learn
     - `validator` — wandb, joblib, tensorboardx (core loop only, no DL, no heavy image processing)
     - `validator-image` — datasets, opencv-python, scikit-image, scikit-learn (HuggingFace cache + augmentation)
     - `validator-synthetic` — torch, torchvision, transformers, diffusers, accelerate, etc. (background synthetic generation process)
   - Add `dev` group for tooling (pytest, black, flake8, etc.)
   - Switch build backend from `poetry-core` to `hatchling`
   - Keep `requires-python = ">=3.10,<3.12"` (Python 3.11 required for bittensor 9.9.0)

2. Replace `requirements.txt` with role-specific files:
   - `requirements.miner.txt` — flat deps for miner Docker image
   - `requirements.validator.txt` — flat deps for validator (core + image pipeline, no DL)
   - `requirements.validator-full.txt` — flat deps for validator with synthetic generation

3. Update `Dockerfile.miner` and `Dockerfile.validator` to use pip + the appropriate requirements file

4. Update `start_miner.sh` and `start_validator.sh` to use `venv/bin/python` (validator already does; align miner)

5. Remove `poetry.lock`

**Install commands after this step:**
```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -e ".[miner]"                             # miner
pip install -e ".[validator]"                         # validator core (no DL)
pip install -e ".[validator,validator-synthetic]"     # full validator
```

**Verification:**
```bash
# Validator core: torch must not be importable
pip install -e ".[validator]"
python -c "import torch" && echo "FAIL" || echo "OK — torch not present"
# Protocol must be importable without torch
python -c "from natix.protocol import ImageSynapse; print('OK')"
```

**Files affected:**
- `pyproject.toml` (rewritten)
- `poetry.lock` (deleted)
- `requirements.txt` → split into `requirements.miner.txt`, `requirements.validator.txt`, `requirements.validator-full.txt`
- `Dockerfile.miner`
- `Dockerfile.validator`
- `start_miner.sh` (minor: align venv usage)

**Depends on:** Step 1

---

## Step 3 — Fix `protocol.py` dependency inversion ✅

**Goal:** `natix/protocol.py` must be importable with zero ML dependencies. Currently it imports `torch`, `torchvision`, and `natix/validator/config.TARGET_IMAGE_SIZE` at module level.

**Changes:**
- Create `natix/constants.py` with shared constants (start with `TARGET_IMAGE_SIZE`)
- Update `protocol.py` to import `TARGET_IMAGE_SIZE` from `natix/constants.py`
- Make the torch/torchvision imports inside `prepare_synapse()` lazy (only import when input is actually a tensor)
- Move the module-level `base_transforms = get_base_transforms(...)` call to inside `prepare_image_synapse()`
- Update any file that used `from natix.validator.config import TARGET_IMAGE_SIZE` for this constant specifically

**Files affected:**
- `natix/protocol.py`
- `natix/constants.py` (new)
- `natix/validator/config.py` (keep TARGET_IMAGE_SIZE there too for backward compat, import from constants)

**Depends on:** Step 1

---

## Step 4 — Move `base_miner/` → `natix/miner/` ✅

**Goal:** All miner-specific code lives under `natix/`, mirroring `natix/validator/`. The `base_miner/` directory at project root is eliminated.

**Changes:**
- Move `base_miner/` to `natix/miner/` (git mv to preserve history)
- Update all imports:
  - `neurons/miner.py`: `from base_miner.registry import DETECTOR_REGISTRY` → `from natix.miner.registry import DETECTOR_REGISTRY`
  - `neurons/miner.py`: `import base_miner.detectors` → `import natix.miner.detectors`
  - Any other file importing from `base_miner`
- Verify `neurons/miner.py` starts cleanly after the rename

**Files affected:**
- `base_miner/` → `natix/miner/` (entire directory, git mv)
- `neurons/miner.py`
- Any test files that import from `base_miner`

**Depends on:** Step 1

---

## Step 5 — Move `natix/synthetic_data_generation/` → `natix/validator/synthetic/` ✅

**Goal:** Validator-only code lives under `natix/validator/`. The top-level `natix/synthetic_data_generation/` is eliminated.

**Changes:**
- Move `natix/synthetic_data_generation/` to `natix/validator/synthetic/` (git mv)
- Update all imports referencing `natix.synthetic_data_generation`
- Verify `natix/validator/scripts/run_data_generator.py` still works

**Files affected:**
- `natix/synthetic_data_generation/` → `natix/validator/synthetic/` (git mv)
- `natix/validator/scripts/run_data_generator.py`
- Any imports in `natix/validator/` referencing the old path

**Depends on:** Step 1

---

## Step 6 — Move `neurons/validator_proxy.py` → `natix/validator/proxy/`

**Goal:** Business logic out of the `neurons/` layer. `neurons/` should contain entry points only.

**Changes:**
- Create `natix/validator/proxy/` directory
- Move `neurons/validator_proxy.py` → `natix/validator/proxy/proxy.py` (git mv)
- Move `natix/validator/organic_task_distributor.py` → `natix/validator/proxy/task_distributor.py`
- Create `natix/validator/proxy/__init__.py` exposing `ValidatorProxy`
- Update `neurons/validator.py` import: `from neurons.validator_proxy import ValidatorProxy` → `from natix.validator.proxy import ValidatorProxy`
- The old `natix/validator/proxy.py` (currently a thin shell) gets replaced by the `proxy/` package

**Files affected:**
- `neurons/validator_proxy.py` → `natix/validator/proxy/proxy.py`
- `natix/validator/organic_task_distributor.py` → `natix/validator/proxy/task_distributor.py`
- `natix/validator/proxy.py` → deleted (replaced by `proxy/` package)
- `natix/validator/proxy/__init__.py` (new)
- `neurons/validator.py`

**Depends on:** Step 1

---

## Step 7 — Split `natix/validator/forward.py`

**Goal:** `forward.py` becomes a thin orchestrator. Its four embedded concerns become separate modules.

**Changes:**
- Create `natix/validator/challenge/` with:
  - `selector.py` — `determine_challenge_type()` function
  - `augmentation.py` — thin wrapper over `apply_augmentation_by_level` with challenge-specific logic
  - `api_task.py` — `fetch_api_challenge()` and S3 image download
- Keep `forward.py` as an orchestrator that imports from `challenge/` and calls `get_rewards()`
- The `statistics_assign_task` / `statistics_report_task` functions stay in `forward.py` temporarily (consolidated in Step 8)

**Files affected:**
- `natix/validator/forward.py` (trimmed to orchestrator)
- `natix/validator/challenge/` (new directory, 3 files + `__init__.py`)

**Depends on:** Steps 1, 6

---

## Step 8 — Consolidate statistics reporting into `api_client.py`

**Goal:** Eliminate the three copies of `statistics_assign_task` / `statistics_report_task`. One implementation, one place.

**Current duplication:**
- `natix/validator/forward.py` — batch version (`List[float]`)
- `natix/validator/proxy/task_distributor.py` — single version (`float`)
- `natix/validator/proxy/proxy.py` — calls forward.py version

**Changes:**
- Move both `statistics_assign_task` and `statistics_report_task` into `natix/validator/api_client.py`
- Unify the two signatures (single + batch both supported, or separate functions clearly named)
- Remove duplicates from `forward.py` and `proxy/`
- Update all call sites to import from `api_client`

**Files affected:**
- `natix/validator/api_client.py`
- `natix/validator/forward.py`
- `natix/validator/proxy/proxy.py`
- `natix/validator/proxy/task_distributor.py`

**Depends on:** Steps 6, 7

---

## Step 9 — Thin entry points in `neurons/`

**Goal:** `neurons/miner.py` and `neurons/validator.py` contain no business logic. They only parse arguments, instantiate the main class, and run the loop.

**Changes:**
- Audit `neurons/validator.py`: `init_wandb()` and `store_vali_info()` are business logic — move them into `natix/validator/` (e.g., `natix/validator/monitoring.py`)
- `neurons/miner.py` is already close to thin — review and clean up if needed
- Verify `neurons/` only imports from `natix/` (no cross-imports between neuron files)

**Files affected:**
- `neurons/validator.py`
- `natix/validator/monitoring.py` (new, receives wandb init logic)

**Depends on:** Steps 4, 6, 7, 8

---

## Step 10 — Validation, cleanup, and Dockerfile verification

**Goal:** Confirm the full migration is correct and all install paths work.

**Checklist:**
- [ ] `poetry install --extras miner` — no torch for validator, no DL imports leak
- [ ] `poetry install --extras validator` — no torch installed, validator core runs
- [ ] `poetry install --extras "validator validator-synthetic"` — full validator with synthetic gen
- [ ] `python -c "from natix.protocol import ImageSynapse"` works without torch installed
- [ ] `python neurons/miner.py --help` works
- [ ] `python neurons/validator.py --help` works
- [ ] All tests pass: `pytest tests/`
- [ ] `Dockerfile.miner` builds and runs
- [ ] `Dockerfile.validator` builds and runs
- [ ] Update `ARCHITECTURE.md` to mark migration complete
- [ ] Update `PROJECT_STATUS.md` with final state

**Depends on:** All previous steps

---

## Step ordering summary

```
1 (docs)
├── 2 (deps)        — independent of 3-9, can do in parallel
├── 3 (protocol)    — independent of 4-9, can do in parallel
├── 4 (base_miner)  — independent of 5-9
├── 5 (synthetic)   — independent of 4, 6-9
├── 6 (proxy)
│   └── 7 (forward split)
│       └── 8 (stats consolidation)
│           └── 9 (thin neurons)
│               └── 10 (validation)
```

Steps 2, 3, 4, 5 can be done in any order after Step 1. Step 6 must come before 7, 7 before 8, 8 before 9.
