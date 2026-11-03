#!/usr/bin/env python3
"""Generate a syntactically valid throwaway npub (bech32, secp256k1 x-only).

Used by the ACL latency experiment: the npub must parse, but nobody holds the
private key, so admitting or denying it changes no real peer's access.

Usage: gen-npub.py [hex32]
"""
import os
import sys

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk


def hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def convertbits(data, frombits=8, tobits=5, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def npub_from_hex(h):
    raw = bytes.fromhex(h)
    if len(raw) != 32:
        raise SystemExit("need 32 bytes of hex")
    data = convertbits(raw, 8, 5, True)
    pm = polymod(hrp_expand("npub") + data + [0] * 6) ^ 1
    checksum = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return "npub1" + "".join(CHARSET[d] for d in data + checksum)


if __name__ == "__main__":
    h = sys.argv[1] if len(sys.argv) > 1 else os.urandom(32).hex()
    print(npub_from_hex(h))
