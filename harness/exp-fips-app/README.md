# Live FIPS application-relay lab

A three-node Docker bridge: A and C each dial B as authenticated FIPS peers;
B runs a real UDP payment/relay handler on 2122. It maps each source FIPS IPv6
to its current peer-table `npub` and `link_id`, then calls the same
`AppRelayController` used by the unit tests.

## Run

Supply real throwaway FIPS seeds in `configs/a.yaml`, `b.yaml` and `c.yaml`.
Launch the mint only if also testing the separate real-token adapter; this
scenario uses synthetic nullifiers and a structural P2PK lock verifier.

```sh
docker compose -f harness/exp-fips-app/docker-compose.yaml down -v --remove-orphans
docker compose -f harness/exp-fips-app/docker-compose.yaml up -d --remove-orphans
PYTHONPATH=./sidecar python3 harness/exp-fips-app/run.py
```

`run.py` clears `/tmp/opencode/fips-app-out` first in a disposable Alpine
container, because the controller's SQLite/log files intentionally live in a
bind mount rather than a compose-managed volume. Data outside this directory
is not removed.

## Scenario and remit

1. A pays proof 1.
2. C replays proof 1 → `reservation_in_flight`.
3. C pays proof 2 successfully; C has independent credit.
4. Both are charged 10 msat for a 100-byte request.
5. A crosses the exhaustion boundary → grace, then blocked at zero.
6. A presents another proof: the account resumes with renewed balance.
7. `link_down` → dormant with retained credit; next authenticated FIPS
   association resumes at updated balance.

The verifier in this specific launcher does not verify Cashu DLEQ signatures.
For real offline proof/DLEQ behavior use `exp-twokey`, `exp-outage` or a real
adapter; this test validates live FIPS source binding and request accounting.

Do not publish seed-bearing files, token bearer values or a production seller
private key. `results/FIPS-APPLICATION-2026-11-11-account-payment-binding.md`
records the run, limitations and test coverage.

The suite's Python and shell checks cover `server.py`, `client.py`, and `run.py`.
Stop with:

```sh
docker compose -f harness/exp-fips-app/docker-compose.yaml down -v --remove-orphans
```
