"""Read per-peer FMP frame counters and price them.

Boundary (Exp A): the FIPS per-link counters are FMP frame bytes at the
transport API. They exclude medium encapsulation and include control frames.
Until a per-class counter exists, every reading is labelled `all_frames`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

LABEL_ALL_FRAMES = "all_frames"


class MeterError(ValueError):
    pass


@dataclass(frozen=True)
class LinkCounters:
    npub: str
    link_id: int
    transport_id: Optional[int]
    transport_type: Optional[str]
    remote_addr: Optional[str]
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int


@dataclass(frozen=True)
class MeterReading:
    npub: str
    link_ids: Tuple[int, ...]
    bytes_in: int
    bytes_out: int
    packets_in: int
    packets_out: int
    billable_bytes: int
    direction: str
    rate_bytes_per_msat: Optional[Decimal]
    cost_msat: Optional[Decimal]
    # Raw FMP bytes the link counters saw, before policy subtraction.
    wire_bytes: int = 0
    # Bytes the seller refused to forward for this peer in the same window.
    # They increment the link counters (the drop is after the counter) but are
    # not transit, so they are never revenue.
    policy_dropped_bytes: int = 0
    label: str = LABEL_ALL_FRAMES


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def snapshot(
    peers: Iterable[Dict[str, Any]],
    links: Iterable[Dict[str, Any]] = (),
) -> Dict[Tuple[str, int], LinkCounters]:
    """Index the seller's per-link counters by (npub, link_id).

    `show peers` carries the npub and the counters. `show links` carries the
    transport metadata and is merged on link_id when present.
    """
    link_meta: Dict[int, Dict[str, Any]] = {}
    for link in links:
        try:
            link_meta[_int(link.get("link_id"))] = link
        except (TypeError, ValueError):
            continue

    out: Dict[Tuple[str, int], LinkCounters] = {}
    for peer in peers:
        npub = peer.get("npub")
        if not npub:
            continue
        link_id = _int(peer.get("link_id"))
        stats = peer.get("stats") or {}
        meta = link_meta.get(link_id, {})
        key = (str(npub), link_id)
        out[key] = LinkCounters(
            npub=str(npub),
            link_id=link_id,
            transport_id=meta.get("transport_id",
                                 peer.get("transport_id")),
            transport_type=peer.get("transport_type", meta.get("transport_type")),
            remote_addr=meta.get("remote_addr", peer.get("transport_addr")),
            bytes_sent=_int(stats.get("bytes_sent")),
            bytes_recv=_int(stats.get("bytes_recv")),
            packets_sent=_int(stats.get("packets_sent")),
            packets_recv=_int(stats.get("packets_recv")),
        )
    return out


def counter_delta(previous: int, current: int) -> int:
    """Monotonic delta with a reset rule.

    A link re-created under the same key starts its counter at a smaller value.
    Treat the new value as the delta for the new epoch; do not refund and do not
    carry the old value forward.
    """
    if current >= previous:
        return current - previous
    return current


def delta(
    previous: Dict[Tuple[str, int], LinkCounters],
    current: Dict[Tuple[str, int], LinkCounters],
    rate_bytes_per_msat: Optional[Decimal] = None,
    direction: str = "both",
    policy_previous: Optional[Dict[str, int]] = None,
    policy_current: Optional[Dict[str, int]] = None,
) -> List[MeterReading]:
    """Price the link-counter delta, subtracting policy-dropped bytes.

    `policy_previous` / `policy_current` map npub to the cumulative
    `drop_policy_blocked_bytes` for that peer. Supplying them makes a paused
    peer's refused transit free: the wire bytes are still reported in
    `wire_bytes`, but `billable_bytes` never includes them. Omit both for the
    old all-frames behaviour.
    """
    if direction not in ("both", "in", "out"):
        raise MeterError(f"direction must be both|in|out, got {direction!r}")
    rate = _rate(rate_bytes_per_msat) if rate_bytes_per_msat is not None else None

    per_npub: Dict[str, Dict[str, Any]] = {}
    for key, cur in current.items():
        prev = previous.get(key)
        prev_in = prev.bytes_recv if prev else 0
        prev_out = prev.bytes_sent if prev else 0
        prev_pin = prev.packets_recv if prev else 0
        prev_pout = prev.packets_sent if prev else 0

        d_in = counter_delta(prev_in, cur.bytes_recv)
        d_out = counter_delta(prev_out, cur.bytes_sent)
        d_pin = counter_delta(prev_pin, cur.packets_recv)
        d_pout = counter_delta(prev_pout, cur.packets_sent)

        agg = per_npub.setdefault(cur.npub, {
            "link_ids": set(), "bytes_in": 0, "bytes_out": 0,
            "packets_in": 0, "packets_out": 0,
        })
        agg["link_ids"].add(cur.link_id)
        agg["bytes_in"] += d_in
        agg["bytes_out"] += d_out
        agg["packets_in"] += d_pin
        agg["packets_out"] += d_pout

    readings: List[MeterReading] = []
    for npub, agg in sorted(per_npub.items()):
        dropped = 0
        if policy_previous is not None or policy_current is not None:
            dropped = counter_delta(
                _int((policy_previous or {}).get(npub)),
                _int((policy_current or {}).get(npub)),
            )

        # Policy drops are inbound transit only (datagrams this peer sent to a
        # third party). Subtract them from the inbound component, never from
        # the outbound side, which carries heartbeats and acks for the peer's
        # own link and is not transit.
        if direction == "in":
            wire = agg["bytes_in"]
            billable = max(0, agg["bytes_in"] - dropped)
        elif direction == "out":
            wire = agg["bytes_out"]
            billable = agg["bytes_out"]
        else:
            wire = agg["bytes_in"] + agg["bytes_out"]
            billable = max(0, agg["bytes_in"] - dropped) + agg["bytes_out"]
        cost = (Decimal(billable) / rate) if rate else None
        readings.append(MeterReading(
            npub=npub,
            link_ids=tuple(sorted(agg["link_ids"])),
            bytes_in=agg["bytes_in"],
            bytes_out=agg["bytes_out"],
            packets_in=agg["packets_in"],
            packets_out=agg["packets_out"],
            billable_bytes=billable,
            direction=direction,
            rate_bytes_per_msat=rate,
            cost_msat=cost,
            wire_bytes=wire,
            policy_dropped_bytes=dropped,
        ))
    return readings


def _rate(value: Any) -> Decimal:
    try:
        rate = Decimal(str(value))
    except InvalidOperation as exc:
        raise MeterError(f"invalid rate {value!r}") from exc
    if rate <= 0:
        raise MeterError("rate must be positive")
    return rate


def format_msat(value: Optional[Decimal], places: int = 6) -> str:
    if value is None:
        return "-"
    quant = Decimal(1).scaleb(-places)
    return str(value.quantize(quant))
