#!/usr/bin/env python3
import json
import socket
import sys

SELLER = "02" + "ab" * 32


def request(kind, args):
    if kind == "pay":
        name = args[0]
        return {"v": 1, "t": "pay", "req": "live-" + name,
                "msg1_ephemeral": "live-msg1",
                "proofs": [{
                    "mint": "http://mint", "unit": "sat", "keyset": "k1",
                    "secret": name, "amount_msat": str(int(args[1])),
                    "condition": ["P2PK", {"data": SELLER,
                                           "nonce": "00" * 16,
                                           "tags": [["sigflag", "SIG_INPUTS"]]}],
                }]}
    if kind == "frame":
        return {"v": 1, "t": "frame", "req": "frame-" + args[0],
                "frame_bytes": int(args[0])}
    if kind == "link_down":
        return {"v": 1, "t": "link_down", "req": "down-" + args[0]}
    raise ValueError(kind)


def main() -> int:
    destination = sys.argv[1]
    kind = sys.argv[2]
    args = sys.argv[3:]
    message = request(kind, args)
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.settimeout(10)
    sock.sendto(json.dumps(message).encode(), (destination, 2122))
    response, _ = sock.recvfrom(65535)
    print(json.dumps({"kind": kind, "request": message,
                      "response": json.loads(response)}, indent=2))


if __name__ == "__main__":
    main()
