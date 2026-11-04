"""L0 frame gate: per-MAC rate limit and explicit blocks over nftables.

This complements `FipsGate` (L1 admission, L2 transit). The frame gate runs
below FMP, before any npub is proven, so it can only key on the source MAC and
EtherType. It is **rate/abuse control, not authorisation**: a MAC is spoofable,
and no frame-gate verdict may credit a session or stand in for the link gate.

The default policy is rate-limit only: every `0x2121` sender gets an independent
token bucket (E4). `install(default_deny=True)` adds an allow-list for sellers
that have an out-of-band checkout path; without one, that mode locks a new
client out of the handshake it needs to pay (see `spec-drafts/06-frame-gate.md`).

All nft invocations go through `NftControl`, so the command shape is unit-tested
without root and the module can be pointed at a container's netns.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


class FrameGateError(RuntimeError):
    pass


class NftControl(Protocol):
    def run(self, args: List[str], check: bool = True) -> str:
        """Run nft with `args`; return stdout. Raise on non-zero if check."""
        ...


class SubprocessNft:
    def __init__(self, binary: str = "nft"):
        self.binary = binary

    def run(self, args: List[str], check: bool = True) -> str:
        result = subprocess.run(
            [self.binary, *args], text=True, capture_output=True)
        if check and result.returncode != 0:
            raise FrameGateError(
                result.stderr.strip() or f"nft {' '.join(args)} failed")
        return result.stdout


def normalise_mac(mac: str) -> str:
    value = str(mac).strip().lower().replace("-", ":")
    if not MAC_RE.match(value):
        raise FrameGateError(f"invalid MAC address: {mac!r}")
    return value


@dataclass
class FrameGateConfig:
    interface: str = "eth0"
    table: str = "tollgate"
    ethertype: int = 0x2121
    rate_pps: int = 1000
    burst: int = 100
    timeout: str = "10m"
    default_deny: bool = False
    max_entries: int = 65535

    def validate(self) -> None:
        if not IFACE_RE.match(self.interface):
            raise FrameGateError(f"invalid interface: {self.interface!r}")
        if not re.match(r"^[A-Za-z0-9_]{1,32}$", self.table):
            raise FrameGateError(f"invalid table name: {self.table!r}")
        if not 0 < self.ethertype <= 0xFFFF:
            raise FrameGateError(f"invalid ethertype: {self.ethertype}")
        if self.rate_pps <= 0:
            raise FrameGateError("rate_pps must be positive")
        if self.burst < 1:
            raise FrameGateError("burst must be at least 1")
        if self.max_entries < 1:
            raise FrameGateError("max_entries must be positive")
        if not re.match(r"^[0-9]+[smhd]?$", self.timeout):
            raise FrameGateError(f"invalid timeout: {self.timeout!r}")


class FrameGate:
    def __init__(self, control: Optional[NftControl] = None,
                 config: Optional[FrameGateConfig] = None):
        self.control = control or SubprocessNft()
        self.config = config or FrameGateConfig()

    # -- helpers ---------------------------------------------------------

    def _run(self, args: List[str], check: bool = True) -> str:
        return self.control.run(args, check=check)

    @property
    def _table(self) -> List[str]:
        return ["netdev", self.config.table]

    def _set(self, name: str) -> List[str]:
        return [*self._table, name]

    # -- lifecycle -------------------------------------------------------

    def install(self) -> None:
        """Install (or replace) the table, sets, chain and rules.

        Replacing an existing table is intentional: it makes install
        idempotent and clears stale per-MAC state.
        """
        cfg = self.config
        cfg.validate()
        self._run(["delete", "table", *self._table], check=False)
        self._run(["add", "table", *self._table])
        self._run(["add", "set", *self._set("bucket"), "{",
                   "type", "ether_addr", ";",
                   "flags", "dynamic", ";",
                   "size", str(cfg.max_entries), ";",
                   "timeout", cfg.timeout, ";", "}"])
        self._run(["add", "set", *self._set("blocked"), "{",
                   "type", "ether_addr", ";", "}"])
        if cfg.default_deny:
            self._run(["add", "set", *self._set("authorised"), "{",
                       "type", "ether_addr", ";", "}"])
        self._run(["add", "chain", *self._set("ingress"), "{",
                   "type", "filter", "hook", "ingress",
                   "device", cfg.interface, "priority", "0", ";", "}"])

        eth = str(hex(cfg.ethertype))
        # 1. Explicit blocks win over everything.
        self._run(["add", "rule", *self._set("ingress"),
                   "ether", "type", eth, "ether", "saddr", "@blocked",
                   "counter", "drop"])
        # 2. Optional allow-list. Before a handshake there is no npub, so this
        #    is advisory and off by default (it would block first contact).
        if cfg.default_deny:
            self._run(["add", "rule", *self._set("ingress"),
                       "ether", "type", eth, "ether", "saddr", "!=",
                       "@authorised", "counter", "drop"])
        # 3. Per-MAC token bucket. The set creates an element per sender on
        #    first match; whether that sender is dropped is decided by the
        #    limit, not by the element's existence.
        self._run(["add", "rule", *self._set("ingress"),
                   "ether", "type", eth, "update", "@bucket", "{",
                   "ether", "saddr", "limit", "rate", "over",
                   f"{cfg.rate_pps}/second", "burst", str(cfg.burst),
                   "packets", "}", "counter", "drop"])
        # 4. Everything else passes.
        self._run(["add", "rule", *self._set("ingress"),
                   "ether", "type", eth, "counter", "accept"])

    def uninstall(self) -> None:
        self._run(["delete", "table", *self._table], check=False)

    # -- policy ----------------------------------------------------------

    def authorise(self, mac: str) -> None:
        """Allow a MAC through the optional allow-list (default_deny only)."""
        mac = normalise_mac(mac)
        self._run(["add", "element", *self._set("authorised"),
                   "{", mac, "}"])

    def deauthorise(self, mac: str) -> None:
        mac = normalise_mac(mac)
        self._run(["delete", "element", *self._set("authorised"),
                   "{", mac, "}"], check=False)

    def block(self, mac: str) -> None:
        """Drop every 0x2121 frame from this MAC, in any policy."""
        mac = normalise_mac(mac)
        self._run(["add", "element", *self._set("blocked"), "{", mac, "}"])

    def unblock(self, mac: str) -> None:
        mac = normalise_mac(mac)
        self._run(["delete", "element", *self._set("blocked"),
                   "{", mac, "}"], check=False)

    def reset_bucket(self, mac: str) -> None:
        """Forget a MAC's bucket; its next frame gets a full burst."""
        mac = normalise_mac(mac)
        self._run(["delete", "element", *self._set("bucket"),
                   "{", mac, "}"], check=False)

    # -- observation -----------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Parsed `nft -j list table` output (rules, counters, set elements)."""
        out = self._run(["-j", "list", "table", *self._table])
        return json.loads(out)

    def buckets(self) -> List[str]:
        """MACs that currently have a token bucket (over-limit senders)."""
        status = self.status()
        elements: List[str] = []
        for item in status.get("nftables", []):
            entry = item.get("set")
            if isinstance(entry, dict) and entry.get("name") == "bucket":
                for element in entry.get("elem", []):
                    if isinstance(element, str):
                        elements.append(element)
                    elif isinstance(element, dict):
                        inner = element.get("elem")
                        if isinstance(inner, str):
                            elements.append(inner)
                        elif isinstance(inner, dict):
                            elements.append(inner.get("val", ""))
        return [e for e in elements if e]
