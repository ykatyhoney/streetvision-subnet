# Subnet Halt

This document describes the steps taken to halt subnet 72 and burn all emissions.

## Emission Split During Halt

Bittensor subnet emissions are divided into three independent streams:

| Stream | Share | Mechanism | Halt behaviour |
|--------|-------|-----------|----------------|
| Subnet owner | 18% | `owner_cut` chain parameter | **Unchanged** — owner keeps receiving their cut |
| Validators | ~41% | Yuma consensus dividends (stake/bonds) | **Unchanged** — validators keep receiving dividends |
| Miners | ~41% | Weights set by validators | **Burned** — redirected to owner's UID, which the protocol burns |

## Miner Reward Burn

All miner rewards are burned by directing 100% of validator weights to the **subnet owner's UID**. The Bittensor protocol burns alpha tokens that flow to the owner's UID through this weight-setting mechanism. This is the official burn path — the owner's UID acts as the protocol's burn address for miner incentives.

This is done in `set_weights()` — the validator looks up the owner's hotkey in the metagraph at runtime and unconditionally submits `uids=[owner_uid], weights=[65535]` on every weight-setting interval.

The forward pass is also skipped entirely, so miners receive no challenges and are not queried during the halt.

## Owner and Validator Rewards

These are **not affected by `set_weights`**. The owner's 18% cut and validators' dividend share are chain-level parameters driven independently of which UIDs receive miner weights. No action is needed to preserve them.

## Increasing Minimum Registration Fee

To raise the barrier for new miners registering on the subnet, increase `min_burn`:

```bash
btcli sudo set --param min_burn --value <amount_in_rao> --netuid 72 --wallet.name <owner_wallet>
```

This sets the minimum TAO that must be burned to register a new hotkey on the subnet, making it more expensive (and therefore less attractive) to join during the halt period.
