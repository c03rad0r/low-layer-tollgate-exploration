# Production account/P2PK/journal demo

This harness checks the host primitives used by the later balloon-relay work.
It does not need Docker, a FIPS process, a mint or hardware access. All amounts
are synthetic test units; no token is redeemed and no account grants real
monetary credit.

```sh
python3 harness/exp-account/account_demo.py
```

The `accept` and `resume` steps run in two **separate child processes**, so the
resumed credit comes from the saved SQLite data rather than a Python object.

It reports:

- an npub account becoming DORMANT and reopening with its exact balance;
- a new link id resuming the same account without resetting usage;
- valid one-of-one compressed P2PK acceptance alongside refusal of refund,
  locktime, grouped signing and unknown extensions;
- same-process replay refusal, reopen-settled replay refusal, pending after
  settle being empty, and no pending credit from a torn append-only final record.

`docs/0020-balloon-production-readiness.md` is the release checklist. Do not
interpret this host success as evidence of flash-power-loss durability or a
running balloon relay controller. It is the reference API/proof for a later
controller integration.
