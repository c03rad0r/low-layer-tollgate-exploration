# Result: SELECTOR — an L0 allow-list cannot learn a rebind

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-SELECTOR (docs/0019, decision D1)
- **Nodes:** `lt-sel-seller`, `lt-sel-buyer`, private Docker bridge
- **FIPS:** 0.6.0-dev (rev `2ba790b221`)
- **Status:** completed, n=3

## Question

Can an L0 allow-list keyed on a transport selector (here IP + UDP source port)
stay bound to one FIPS peer across a rebind? If the answer is no, a bent-pipe
allow-list can pass admitted sessions only while an out-of-band control plane
updates the selector.

## Setup

Seller listens on UDP/2121 and accepts inbound FIPS links; the buyer auto-dials
from UDP/2121. The seller's nft input rule allows exactly one 5-tuple and drops
all other FIPS traffic to its UDP/2121 port:

```text
udp dport 2121 ip saddr <buyer_ip> udp sport 2121 accept
udp dport 2121 drop
```

After the baseline link and ping succeeded, the buyer's bind port was changed to
2222 and its container restarted. The seller's rule was deliberately **not**
updated until after an observation window. Then the rule was updated out of
band and recovery measured.

```sh
docker compose -f harness/exp-selector/docker-compose.yaml up -d --remove-orphans
PYTHONPATH=./sidecar python3 harness/exp-selector/selector.py
```

## Raw measurements

| Run | Baseline ping | After rebind, old rule | Blackout before out-of-band update | Recovery after update |
|---|---:|---:|---:|---:|
| 1 | 0% loss | 100% loss | 14.19 s | 2.61 s |
| 2 | 0% loss | 100% loss | 14.16 s | 2.64 s |
| 3 | 0% loss | 100% loss | 14.17 s | 3.58 s |

The observation windows are from separate fresh stacks (buyer IPs
`172.21.0.2`/`172.21.0.3` across runs, all private).

```text
nft allow: 172.21.0.2 2121
baseline ping: True 0.0
after rebind (old rule): False 100.0
nft allow: 172.21.0.2 2222
recovered: True after_update_s: 2.61 ping: True 0.0
```

## Interpretation

1. **The old 5-tuple is not the identity.** After the port changed, every ping
   failed under the old allow-list. The cryptographic FIPS session is bound to
   the npub, while the L0 allow-list is bound to an ephemeral transport address.
2. **The gate cannot learn the new selector from the traffic it drops.** If the
   control plane drops handshakes from an unknown 5-tuple, it also drops the
   evidence that would identify the new selector. This is a first-contact hole,
   not a latency tuning problem.
3. **An out-of-band update recovers the link.** The 2.61–3.58 s recovery is the
   post-update link re-establishment, not the total blackout. The total blackout
   was 14.16–14.19 s because the experiment deliberately delayed the update.
4. **A default-deny L0 gate needs a checkout/rebind path.** That can be a
   separate control channel, a rate-limited handshake lane, or L2 admission that
   terminates FIPS. It cannot be a claim that source-port matching verifies a
   payer.

## Decision for D1

Do not rely on a transparent bent-pipe allow-list for roaming or rebind-prone
peers. Terminate FIPS where payment is enforced, meter per npub, and let the
allow-list be an advisory optimization for known admitted peers only. Any L0
default-deny gate must retain an out-of-band path for first contact and selector
updates.

## Caveats and follow-ups

- One buyer, one private bridge, UDP only. Rebind was simulated by changing the
    buyer bind port and restarting, not by real NAT or Wi-Fi roaming.
- No Ethernet MAC change or source spoofing in this run. The selector's
  spoofability is independent evidence and remains an L0 security caveat, not a
  measurement made here.
- Follow-up: measure a rebind during a paid session, with a separate checkout
  message updating the allow-list before the new transport address is used.

## Artefacts

- `harness/exp-selector/` — two-node topology, nft manipulation and runner.
