"""Resolve transport source addresses to authenticated FIPS peer identity.

The application resolver derives identity only from the daemon's authenticated
peer table. A source IP address, MAC or claimed npub is never sufficient alone.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable


class IdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class FipsPeerIdentity:
    npub: str
    link_id: str
    node_addr: str
    ipv6_addr: str


def canonical_ipv6(address: str) -> str:
    host = address.rsplit("%", 1)[0]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return ipaddress.IPv6Address(host).compressed


def resolve_in_peer_rows(rows: Iterable[dict], ipv6_addr: str) -> FipsPeerIdentity:
    try:
        wanted = canonical_ipv6(ipv6_addr)
    except ipaddress.AddressValueError as exc:
        raise IdentityError("source address is not an IPv6 address") from exc
    for row in rows:
        peer_ip = row.get("ipv6_addr")
        if not peer_ip:
            continue
        if canonical_ipv6(peer_ip) != wanted:
            continue
        if row.get("connectivity") not in (None, "connected"):
            raise IdentityError(f"peer is not connected: {row.get('connectivity')}")
        npub = row.get("npub")
        link_id = row.get("link_id")
        if not npub or link_id is None:
            raise IdentityError("connected FIPS peer has no npub/link identity")
        return FipsPeerIdentity(npub=npub, link_id=str(link_id),
                                node_addr=row.get("node_addr", ""), ipv6_addr=peer_ip)
    raise IdentityError("source address is not present in the authenticated FIPS peer table")


class FipsIdentityResolver:
    """Resolve through an injected Fipsctl-style object with a peers() method."""

    def __init__(self, fipsctl):
        self.fipsctl = fipsctl

    def resolve(self, ipv6_addr: str) -> FipsPeerIdentity:
        return resolve_in_peer_rows(self.fipsctl.peers(), ipv6_addr)
