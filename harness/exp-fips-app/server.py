#!/usr/bin/env python3
"""Live FIPS-local UDP application service for the app-relay integration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/sidecar")

from tollgate_fips.appendlog import CrcNullifierJournal
from tollgate_fips.application import RelayApplicationHandler
from tollgate_fips.exposure import ExposureLedger
from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.identity import FipsIdentityResolver
from tollgate_fips.nut11 import check_offline_condition
from tollgate_fips.account import PrepaidAccountStore
from tollgate_fips.relay import AppRelayController

SELLER = "02" + "ab" * 32
PORT = 2122


class Verifier:
    def verify(self, proof, seller_npub, msg1_ephemeral):
        check_offline_condition(proof.token, SELLER, proof.final_expiry)
        return True


def main() -> int:
    expected = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    import socket
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("::", PORT))
    sock.settimeout(60)
    fips = Fipsctl()
    seller_npub = fips.status()["npub"]
    controller = AppRelayController(
        CrcNullifierJournal("/out/proofs.fjnl"),
        ExposureLedger("/out/exposure.sqlite3"),
        PrepaidAccountStore("/out/accounts.sqlite3"),
        Verifier(), seller_npub, cap_msat=100000,
        rate_bytes_per_msat=10)
    handler = RelayApplicationHandler(controller, FipsIdentityResolver(fips))
    records = []
    while len(records) < expected:
        try:
            payload, address = sock.recvfrom(65535)
        except socket.timeout:
            break
        source = address[0]
        try:
            response = handler.handle(source, payload)
            record = {"source_ipv6": source, "response": response}
        except Exception as exc:
            record = {"source_ipv6": source,
                      "response": {"t": "nack", "code": type(exc).__name__,
                                   "message": str(exc)}}
        records.append(record)
        sock.sendto(json.dumps(response).encode(), address)
        Path("/out/service-result.json").write_text(json.dumps(records, indent=2))
        print(json.dumps(record), flush=True)
    return 0 if len(records) == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
