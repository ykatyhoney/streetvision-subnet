# Development Workflow

How to set up, run, and test the subnet during and after the migration. Written for an AI assistant that needs to verify changes work.

---

## Repository layout

- `main` — production-ready code
- `development` — active development branch, all migration PRs target here

---

## Local setup

Python 3.11 is required (bittensor 9.9.0 constraint). Use pyenv or asdf to manage versions.

```bash
# Pre-migration (Poetry still in place)
poetry install

# Post-migration (Step 2+): plain pip + venv
python3.11 -m venv venv
source venv/bin/activate

pip install -e ".[miner]"                          # miner only
pip install -e ".[validator]"                      # validator core (no DL)
pip install -e ".[validator,validator-synthetic]"  # full validator
```

---

## Running components

**Miner:**
```bash
bash start_miner.sh
# or directly:
venv/bin/python neurons/miner.py \
  --neuron.image_detector RoadworkDetector \
  --neuron.image_detector_config roadwork \
  --wallet.name <wallet> --wallet.hotkey <hotkey>
```

**Validator:**
```bash
bash start_validator.sh
```
This launches three processes:
1. `neurons/validator.py` — main forward loop
2. `natix/validator/scripts/run_cache_updater.py` — downloads parquets from HuggingFace
3. `natix/validator/scripts/run_data_generator.py` — generates synthetic images

**Individual background processes:**
```bash
bash start_cache_updater.sh
bash start_synthetic_generator.sh
```

---

## Environment variables

Loaded from `miner.env` or `validator.env`. Key ones:
- `WALLET_NAME`, `WALLET_HOTKEY` — Bittensor wallet
- `NETUID` — subnet UID (e.g., 14 for mainnet)
- `SUBTENSOR_NETWORK` — `finney` (mainnet) or `test` (testnet)
- `PROXY_CLIENT_URL` — URL of the NATIX proxy API
- `HF_TOKEN` — HuggingFace token for dataset downloads
- `WANDB_API_KEY` — Weights & Biases API key (validator only)

---

## Running tests

```bash
pytest tests/                    # all tests
pytest tests/test_forward.py    # specific file
pytest -x                        # stop on first failure
```

Test layout:
- `tests/` — shared/integration tests
- `tests/validator/` — validator-specific tests
- `neurons/unit_tests/` — miner unit tests (separate from main test suite)

---

## Verifying a migration step

After each step, run this checklist:

```bash
# 1. Imports still resolve
python -c "from natix.protocol import ImageSynapse"
python -c "from natix.miner.registry import DETECTOR_REGISTRY"  # after step 4
python -c "from natix.validator.proxy import ValidatorProxy"      # after step 6

# 2. Entry points show --help without error
python neurons/miner.py --help
python neurons/validator.py --help

# 3. Full test suite
pytest tests/

# 4. Linting
flake8 natix/ neurons/
```

---

## Verifying dependency isolation (Step 2)

After Step 2, test that each extras group installs only what it should:

```bash
# Isolated venv — validator core only
python3.11 -m venv /tmp/test_validator
/tmp/test_validator/bin/pip install -e ".[validator]"

# Should fail — torch must not be present
/tmp/test_validator/bin/python -c "import torch" && echo "FAIL: torch leaked" || echo "OK"

# Should succeed — protocol importable without torch
/tmp/test_validator/bin/python -c "from natix.protocol import ImageSynapse; print('OK')"
```

---

## Making a migration PR

1. Work on `development` branch
2. Each step = one PR (or one commit series on development)
3. PR title format: `refactor(step-N): <description>` (e.g., `refactor(step-4): move base_miner to natix/miner`)
4. Update `PROJECT_STATUS.md` in the same PR to mark the step done
5. Run the verification checklist above before marking PR ready

---

## Git strategy for moves

Use `git mv` for directory renames to preserve file history:

```bash
git mv base_miner natix/miner
git mv natix/synthetic_data_generation natix/validator/synthetic
git mv neurons/validator_proxy.py natix/validator/proxy/proxy.py
```

After moving, update imports. Run tests. Commit as one atomic change.

---

## Docker builds (verification in Step 10)

```bash
docker build -f Dockerfile.miner -t natix-miner:test .
docker build -f Dockerfile.validator -t natix-validator:test .

# Smoke test
docker run --rm natix-miner:test python neurons/miner.py --help
docker run --rm natix-validator:test python neurons/validator.py --help
```
