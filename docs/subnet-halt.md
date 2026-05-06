# Subnet Halt

This document describes the steps taken to halt subnet 72 and burn all emissions.

## Miner Rewards

All miner rewards are burned by directing 100% of validator weights to UID 0, the network's burn address. This is done in `set_weights()` — instead of computing weights from miner scores, the validator now unconditionally submits `uids=[0], weights=[65535]` on every weight-setting interval. As a result, no TAO flows to any miner; all miner-side emissions are redirected to the burn address.

The forward pass is also skipped entirely, so miners receive no challenges and are not queried during the halt.

## Owner Rewards

Owner rewards are a chain-level parameter and are not controlled by the validator process. To set the subnet owner cut to 0 and stop owner emissions:

```bash
btcli sudo set --param owner_cut --value 0 --netuid 72 --wallet.name <owner_wallet>
```

This sets the owner's share of subnet emissions to 0%, so no TAO accrues to the subnet owner wallet.

## Increasing Minimum Registration Fee

To raise the barrier for new miners registering on the subnet, increase `min_burn`:

```bash
btcli sudo set --param min_burn --value <amount_in_rao> --netuid 72 --wallet.name <owner_wallet>
```

This sets the minimum TAO that must be burned to register a new hotkey on the subnet, making it more expensive (and therefore less attractive) to join during the halt period.
