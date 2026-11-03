"""Per-payer, per-mint exposure cap.

The journal stops a replay at one receiver. It cannot see a token given to two
sellers. The cap bounds that residual risk: at most `cap_msat` of unsettled face
value per `(payer_npub, mint_url, unit)`.

Ordering is deliberate: reserve exposure **before** the journal row. A crash
between the two overstates exposure (the seller lends less next time), never
understates it (which would let a double spend through).
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS exposure (
    payer_npub       TEXT NOT NULL,
    mint_url         TEXT NOT NULL,
    unit             TEXT NOT NULL,
    outstanding_msat TEXT NOT NULL,
    updated_at       REAL NOT NULL,
    PRIMARY KEY (payer_npub, mint_url, unit)
);
"""


class ExposureError(RuntimeError):
    pass


class ExposureExceeded(ExposureError):
    def __init__(self, current: Decimal, amount: Decimal, cap: Decimal):
        self.current = current
        self.amount = amount
        self.cap = cap
        super().__init__(
            f"exposure {current} + {amount} exceeds cap {cap} msat"
        )


class UnknownExposure(ExposureError):
    pass


@dataclass(frozen=True)
class ExposureKey:
    payer_npub: str
    mint_url: str
    unit: str


class ExposureLedger:
    def __init__(self, path: str, busy_timeout_ms: int = 5000):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=busy_timeout_ms / 1000)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def reserve(self, key: ExposureKey, amount_msat, cap_msat) -> Decimal:
        """Add `amount_msat` to the key's outstanding exposure, or refuse.

        The check and the update are one `BEGIN IMMEDIATE` transaction, so two
        concurrent payments cannot both pass a cap check that only one should.
        """
        amount = Decimal(str(amount_msat))
        cap = Decimal(str(cap_msat))
        if amount <= 0:
            raise ExposureError("amount must be positive")
        if cap < 0:
            raise ExposureError("cap must be non-negative")

        stamp = time.time()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT outstanding_msat FROM exposure "
                "WHERE payer_npub=? AND mint_url=? AND unit=?",
                (key.payer_npub, key.mint_url, key.unit),
            ).fetchone()
            current = Decimal(row["outstanding_msat"]) if row else Decimal(0)
            new = current + amount
            if new > cap:
                raise ExposureExceeded(current, amount, cap)
            self._conn.execute(
                "INSERT INTO exposure (payer_npub, mint_url, unit, "
                "outstanding_msat, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (payer_npub, mint_url, unit) DO UPDATE SET "
                "outstanding_msat=excluded.outstanding_msat, "
                "updated_at=excluded.updated_at",
                (key.payer_npub, key.mint_url, key.unit, str(new), stamp),
            )
            self._conn.commit()
            return new
        except Exception:
            self._conn.rollback()
            raise

    def release(self, key: ExposureKey, amount_msat) -> Decimal:
        """Release settled or refused exposure. Never goes below zero."""
        amount = Decimal(str(amount_msat))
        if amount <= 0:
            raise ExposureError("amount must be positive")

        stamp = time.time()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT outstanding_msat FROM exposure "
                "WHERE payer_npub=? AND mint_url=? AND unit=?",
                (key.payer_npub, key.mint_url, key.unit),
            ).fetchone()
            if row is None:
                raise UnknownExposure(f"no exposure row for {key}")
            current = Decimal(row["outstanding_msat"])
            new = max(Decimal(0), current - amount)
            self._conn.execute(
                "UPDATE exposure SET outstanding_msat=?, updated_at=? "
                "WHERE payer_npub=? AND mint_url=? AND unit=?",
                (str(new), stamp, key.payer_npub, key.mint_url, key.unit),
            )
            self._conn.commit()
            return new
        except Exception:
            self._conn.rollback()
            raise

    def outstanding(self, key: ExposureKey) -> Decimal:
        row = self._conn.execute(
            "SELECT outstanding_msat FROM exposure "
            "WHERE payer_npub=? AND mint_url=? AND unit=?",
            (key.payer_npub, key.mint_url, key.unit),
        ).fetchone()
        return Decimal(row["outstanding_msat"]) if row else Decimal(0)

    def rows(self):
        return self._conn.execute(
            "SELECT * FROM exposure ORDER BY payer_npub, mint_url, unit"
        ).fetchall()
