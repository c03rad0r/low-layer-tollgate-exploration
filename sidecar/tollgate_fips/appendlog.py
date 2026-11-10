"""CRC-framed, append-only proof journal for an embedded receiver prototype.

One committed record is `magic | version | state | uint16 length | JSON | crc32`.
The final record per key wins. Fsync precedes the in-memory/returned commit;
a truncated tail is removed during recovery, while corruption elsewhere fails
closed. This is a reference implementation, not an ESP32 wear/power-loss proof.
"""

from __future__ import annotations

import json
import os
import struct
import time
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from .journal import AlreadySettled, AlreadySpent, Reservation, ReservationInFlight

MAGIC = b"FJNL"
VERSION = 1
HEADER = struct.Struct(">4sBBH")  # magic, version, state, JSON length (big endian)
MAX_PAYLOAD = 4096
STATES = {"RESERVED": 1, "SETTLED": 2, "SPENT": 3}


class CorruptJournal(ValueError):
    pass


def _validate_payload_state(payload: dict, state: str) -> None:
    required = {"mint_url", "unit", "keyset_id", "nullifier", "amount_msat"}
    if set(payload) - {"mint_url", "unit", "keyset_id", "nullifier",
                        "amount_msat", "final_expiry", "at", "state"}:
        raise CorruptJournal("unknown record fields")
    if payload.get("state") != state:
        raise CorruptJournal("record state does not match its framing")
    if not set(payload) >= required:
        raise CorruptJournal("incomplete record")
    if not all(isinstance(payload[key], str) for key in ("mint_url", "unit",
            "keyset_id", "nullifier", "amount_msat")):
        raise CorruptJournal("record keys and amount must be strings")
    if any(not payload[key] for key in required - {"final_expiry"}):
        raise CorruptJournal("empty reservation key part")
    try:
        if Decimal(payload["amount_msat"]) <= 0:
            raise CorruptJournal("reservation amount must be positive")
    except InvalidOperation as exc:
        raise CorruptJournal("invalid reservation amount") from exc


class CrcJournal:
    """Single-writer, bounded-record receiver journal.

    `recover_at_open=True` treats previously RESERVED rows as SPENT. It is the
    same conservative restart policy as the SQLite journal. Always fsync a
    record before returning from `reserve`, `settle` or `mark_spent`.
    """

    def __init__(self, path: str, recover_at_open: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        blob = self.path.read_bytes()
        self._records, complete_to = self._read_records(blob)
        if complete_to < len(blob):
            # A torn final header/record is never a committed reservation.
            with self.path.open("r+b") as handle:
                handle.truncate(complete_to)
                handle.flush()
                os.fsync(handle.fileno())
        self._compact()
        if recover_at_open:
            for record in list(self._records):
                if record["state"] == "RESERVED":
                    key = self._key(record)
                    self.mark_spent(key)

    @staticmethod
    def _key_kwargs(record: dict) -> tuple:
        return (record["mint_url"], record["unit"], record["keyset_id"],
                record["nullifier"])

    def _key(self, record_or_kwargs) -> tuple:
        if isinstance(record_or_kwargs, dict):
            return self._key_kwargs(record_or_kwargs)
        return tuple(record_or_kwargs)

    @staticmethod
    def _read_records(blob: bytes) -> tuple[list[dict], int]:
        records = []
        pos = 0
        while pos < len(blob):
            if len(blob) - pos < HEADER.size:
                break
            magic, version, state_id, size = HEADER.unpack_from(blob, pos)
            if magic != MAGIC or version != VERSION or state_id not in STATES.values():
                raise CorruptJournal(f"invalid record header at {pos}")
            if size > MAX_PAYLOAD:
                raise CorruptJournal(f"oversized record at {pos}")
            end = pos + HEADER.size + size
            if end + 4 > len(blob):
                break
            payload_bytes = blob[pos + HEADER.size:end]
            expected = int.from_bytes(blob[end:end + 4], "little")
            if zlib.crc32(payload_bytes) & 0xFFFFFFFF != expected:
                raise CorruptJournal(f"CRC failure at {pos}")
            try:
                record = json.loads(payload_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CorruptJournal(f"invalid JSON record at {pos}") from exc
            record_state = next(k for k, v in STATES.items() if v == state_id)
            _validate_payload_state(record, record_state)
            record["state"] = record_state
            record["_state_id"] = state_id
            records.append(record)
            pos = end + 4
        return records, pos

    def _append(self, state: str, record: dict) -> None:
        record = dict(record)
        record["state"] = state
        state_id = STATES[state]
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_PAYLOAD:
            raise CorruptJournal("record exceeds bounded size")
        blob = bytearray(HEADER.pack(MAGIC, VERSION, state_id, len(encoded)))
        blob += encoded
        blob += (zlib.crc32(encoded) & 0xFFFFFFFF).to_bytes(4, "little")
        with self.path.open("ab") as handle:
            size = handle.write(blob)
            if size != len(blob):
                raise OSError(f"short append: {size} != {len(blob)}")
            handle.flush()
            os.fsync(handle.fileno())
        record["_state_id"] = state_id
        self._records.append(record)

    def reserve(self, *, mint_url: str, unit: str, keyset_id: str, nullifier: str,
                amount_msat, final_expiry: Optional[int] = None,
                now: Optional[float] = None) -> dict:
        key = (mint_url, unit, keyset_id, nullifier)
        if self.state(*key) == "RESERVED":
            raise ReservationInFlight("reservation already in flight", key)
        if self.state(*key) == "SETTLED":
            raise AlreadySettled("already settled", key)
        if self.state(*key) == "SPENT":
            raise AlreadySpent("already spent", key)
        record = {"mint_url": mint_url, "unit": unit, "keyset_id": keyset_id,
                  "nullifier": nullifier, "amount_msat": str(amount_msat),
                  "final_expiry": final_expiry, "at": time.time() if now is None else now}
        record["state"] = "RESERVED"
        _validate_payload_state(record, "RESERVED")
        self._append("RESERVED", record)
        return record

    def _transition(self, key: tuple, expected: str, target: str) -> None:
        if self.state(*key) != expected:
            raise ValueError(f"{key} is not {expected}")
        last = self._last(*key)
        record = {k: v for k, v in last.items() if not k.startswith("_")}
        record["at"] = time.time()
        self._append(target, record)

    def settle(self, mint_url: str, unit: str, keyset_id: str, nullifier: str) -> None:
        self._transition((mint_url, unit, keyset_id, nullifier), "RESERVED", "SETTLED")

    def mark_spent(self, key: tuple) -> None:
        self._transition(key, "RESERVED", "SPENT")

    def _last(self, mint_url: str, unit: str, keyset_id: str, nullifier: str) -> dict:
        key = (mint_url, unit, keyset_id, nullifier)
        for record in reversed(self._records):
            if self._key(record) == key:
                return record
        raise KeyError(key)

    def state(self, mint_url: str, unit: str, keyset_id: str, nullifier: str) -> Optional[str]:
        key = (mint_url, unit, keyset_id, nullifier)
        for record in reversed(self._records):
            if self._key(record) == key:
                return record["state"]
        return None

    def pending(self) -> list[dict]:
        latest = {}
        for record in self._records:
            latest[self._key(record)] = record
        return [record.copy() for record in latest.values()
                if record["state"] == "RESERVED"]

    def records(self) -> list[dict]:
        return [r.copy() for r in self._records]

    def _compact(self) -> None:
        """Retain every key's latest record; validate the result before replacing."""
        latest = {}
        for record in self._records:
            latest[self._key(record)] = record
        records = list(latest.values())
        tmp = self.path.with_suffix(self.path.suffix + ".compact")
        with tmp.open("wb") as handle:
            for record in records:
                encoded = json.dumps({k: v for k, v in record.items()
                                     if not k.startswith("_")},
                                    sort_keys=True, separators=(",", ":")).encode()
                handle.write(HEADER.pack(MAGIC, VERSION, record["_state_id"], len(encoded)))
                handle.write(encoded)
                handle.write((zlib.crc32(encoded) & 0xFFFFFFFF).to_bytes(4, "little"))
            handle.flush()
            os.fsync(handle.fileno())
        self._read_records(tmp.read_bytes())
        os.replace(tmp, self.path)
        self._records, _ = self._read_records(self.path.read_bytes())


class CrcNullifierJournal:
    """Adapt `CrcJournal` to `NullifierJournal`'s controller-facing interface.

    This keeps the same durable-ordering semantics but lets `PaymentGate` and
    `SettlementWorker` use the flight-oriented record format directly.
    """

    def __init__(self, path: str, recover_stale_reservations: bool = False):
        self._log = CrcJournal(path, recover_at_open=False)
        if recover_stale_reservations:
            self.recover_stale_reservations()

    @staticmethod
    def _reservation(record: dict) -> Reservation:
        return Reservation(mint_url=record["mint_url"], unit=record["unit"],
                           keyset_id=record["keyset_id"],
                           nullifier=record["nullifier"],
                           amount_msat=Decimal(record["amount_msat"]),
                           final_expiry=record["final_expiry"],
                           reserved_at=record["at"])

    @staticmethod
    def _kwargs(reservation: Reservation) -> dict:
        return dict(mint_url=reservation.mint_url, unit=reservation.unit,
                    keyset_id=reservation.keyset_id,
                    nullifier=reservation.nullifier)

    def reserve(self, **kwargs) -> Reservation:
        record = self._log.reserve(**kwargs)
        return self._reservation(record)

    def settle(self, reservation: Reservation, now: Optional[float] = None) -> None:
        self._log.settle(**self._kwargs(reservation))

    def mark_spent(self, reservation: Reservation, note: str = "double spend",
                   now: Optional[float] = None) -> None:
        self._log.mark_spent(reservation.key)

    def state(self, *key) -> Optional[str]:
        return self._log.state(*key)

    def pending(self, limit: int = 100) -> list[Reservation]:
        return [self._reservation(record) for record in self._log.pending()[:limit]]

    def recover_stale_reservations(self) -> int:
        count = 0
        for reservation in self.pending():
            self._log.mark_spent(reservation.key)
            count += 1
        return count

    def close(self) -> None:
        # Records and writes are already fsynced individually.
        return None
