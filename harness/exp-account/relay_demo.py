#!/usr/bin/env python3
"""App-relay controller integration: no free transit after valid PAY.

Uses synthetic test amounts and a structural verifier, not real ecash. The
lock-policy and persistence are the production-side primitives under test.
For the real-mint P2PK/DLEQ path see exp-twokey / exp-outage.
"""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sidecar"))

from tollgate_fips.account import AccountState, PrepaidAccountStore
from tollgate_fips.appendlog import CrcNullifierJournal
from tollgate_fips.exposure import ExposureLedger
from tollgate_fips.nut11 import check_offline_condition
from tollgate_fips.payment import PaymentProof
from tollgate_fips.relay import AppRelayController

SELLER = "02" + "ab" * 32


def lock():
    return ["P2PK", {"data": SELLER, "nonce": "00" * 16,
                      "tags": [["sigflag", "SIG_INPUTS"]]}]


class StructuralVerifier:
    def verify(self, proof, seller_npub, msg1_ephemeral):
        check_offline_condition(proof.token, SELLER, proof.final_expiry)
        return True


def proof(nullifier, payer, amount=1000):
    return PaymentProof(mint_url="http://mint", unit="sat", keyset_id="k1",
                        nullifier=nullifier, amount_msat=Decimal(amount),
                        payer_npub=payer, token=lock())


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="relay-demo-", dir="/tmp/opencode")
    accounts = PrepaidAccountStore(str(Path(tmp) / "accounts.sqlite3"))
    relay = AppRelayController(CrcNullifierJournal(str(Path(tmp) / "proofs.fjnl")),
                               ExposureLedger(str(Path(tmp) / "exposure.sqlite3")),
                               accounts, StructuralVerifier(), "npub1seller",
                               cap_msat=100000, rate_bytes_per_msat=Decimal(10))
    report = {}
    unpaid = relay.forward_frame("npub1a", "l1", 100)
    report["unpaid"] = {"allowed": unpaid.allowed, "state": unpaid.state.value}

    relay.accept_payment("npub1a", "l1", [proof("payment-1", "npub1a")], "msg1a")
    accepted = relay.forward_frame("npub1a", "l1", 100)
    report["after_valid_payment"] = {"allowed": accepted.allowed,
                                     "charged_msat": str(accepted.charged_msat),
                                     "remaining_msat": str(accepted.remaining_msat)}
    try:
        relay.accept_payment("npub1b", "l1",
                             [proof("payment-1", "npub1b")], "msg1b")
        report["cross_peer_replay"] = "accepted (unexpected)"
    except Exception as exc:
        report["cross_peer_replay"] = type(exc).__name__

    exhaust = relay.forward_frame("npub1a", "l1", 9900)
    report["exhausted"] = {"allowed": exhaust.allowed,
                           "state": exhaust.state.value,
                           "remaining_msat": str(exhaust.remaining_msat)}
    next_frame = relay.forward_frame("npub1a", "l1", 100)
    report["after_exhaustion"] = {"allowed": next_frame.allowed,
                                  "charged_msat": str(next_frame.charged_msat)}

    relay.accept_payment("npub1a", "l2",
                         [proof("payment-2", "npub1a", amount=2000)], "msg2")
    relay.mark_link_down("npub1a")
    # The saved account is closed and reopened, as after a process restart.
    relay.accounts.close()
    accounts2 = PrepaidAccountStore(str(Path(tmp) / "accounts.sqlite3"))
    reopened = accounts2.get_or_create("npub1a", Decimal(10))
    report["after_reopen"] = {"state": reopened.state.value,
                              "remaining_msat": str(reopened.remaining_msat),
                              "used_msat": str(reopened.used_msat)}
    relay.accounts = accounts2
    resumed = relay.forward_frame("npub1a", "l3", 100)
    report["resumed_new_link"] = {"allowed": resumed.allowed,
                                  "state": resumed.state.value,
                                  "remaining_msat": str(resumed.remaining_msat)}
    report["pending_before_settlement"] = len(relay.gate.journal.pending())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
