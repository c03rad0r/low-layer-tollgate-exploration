"""Durable receiver-side nullifier journal.

The payment proof is verified outside this module. The journal answers one
question, durably: **has this receiver already accepted this nullifier?**

States:

    RESERVED --settle()--> SETTLED
    RESERVED --mark_spent()--> SPENT
    SETTLED  --mark_spent()--> SPENT

A reservation is committed (SQLite WAL + synchronous=FULL) **before** the seller
grants credit. A crash between the commit and the credit therefore loses a small
amount of revenue, never a replay. A crash after credit but before settlement
leaves a RESERVED row; `recover_stale_reservations` treats it as SPENT, which is
the conservative choice.

Key: `(mint_url, unit, keyset_id, nullifier)`. The keyset is part of the key
because NUT-02 nullifiers are keyset-scoped, and `final_expiry` is a settlement
deadline, not a session clock.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS nullifiers (
    mint_url     TEXT NOT NULL,
    unit         TEXT NOT NULL,
    keyset_id    TEXT NOT NULL,
    nullifier    TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('RESERVED', 'SETTLED', 'SPENT')),
    amount_msat  TEXT NOT NULL,
    final_expiry INTEGER,
    reserved_at  REAL NOT NULL,
    settled_at   REAL,
    note         TEXT,
    PRIMARY KEY (mint_url, unit, keyset_id, nullifier)
);
CREATE INDEX IF NOT EXISTS nullifiers_state
    ON nullifiers (state, reserved_at);
"""


class JournalError(RuntimeError):
    pass


class NullifierConflict(JournalError):
    def __init__(self, state: str, key: tuple):
        self.state = state
        self.key = key
        super().__init__(f"nullifier already in state {state}: {key}")


class ReservationInFlight(NullifierConflict):
    pass


class AlreadySettled(NullifierConflict):
    pass


class AlreadySpent(NullifierConflict):
    pass


@dataclass(frozen=True)
class Reservation:
    mint_url: str
    unit: str
    keyset_id: str
    nullifier: str
    amount_msat: Decimal
    final_expiry: Optional[int]
    reserved_at: float

    @property
    def key(self) -> tuple:
        return (self.mint_url, self.unit, self.keyset_id, self.nullifier)


def keyset_admissible(final_expiry: Optional[int], settlement_window_secs: int,
                      now: Optional[float] = None) -> bool:
    """May a proof from this keyset be admitted?

    After `final_expiry` the mint may irrevocably remove nullifiers (NUT-02), so
    a proof whose keyset expires inside the settlement window cannot be safely
    settled. Reject it at admission; do not use this as the session deadline.
    """
    if final_expiry is None:
        return True
    now = time.time() if now is None else now
    return final_expiry >= now + settlement_window_secs


class NullifierJournal:
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

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # -- writes ----------------------------------------------------------

    def reserve(self, mint_url: str, unit: str, keyset_id: str, nullifier: str,
                amount_msat, final_expiry: Optional[int] = None,
                now: Optional[float] = None) -> Reservation:
        """Durably reserve a nullifier before granting credit.

        Raises `ReservationInFlight`, `AlreadySettled` or `AlreadySpent` if the
        key is already present. The INSERT commits before this returns.
        """
        key = (mint_url, unit, keyset_id, nullifier)
        stamp = time.time() if now is None else now
        amount = Decimal(str(amount_msat))
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self._conn.execute(
                "SELECT state FROM nullifiers WHERE mint_url=? AND unit=? "
                "AND keyset_id=? AND nullifier=?",
                key,
            ).fetchone()
            if existing is not None:
                self._raise_conflict(existing["state"], key)
            self._conn.execute(
                "INSERT INTO nullifiers (mint_url, unit, keyset_id, nullifier, "
                "state, amount_msat, final_expiry, reserved_at) "
                "VALUES (?, ?, ?, ?, 'RESERVED', ?, ?, ?)",
                (*key, str(amount), final_expiry, stamp),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return Reservation(
            mint_url=mint_url,
            unit=unit,
            keyset_id=keyset_id,
            nullifier=nullifier,
            amount_msat=amount,
            final_expiry=final_expiry,
            reserved_at=stamp,
        )

    def settle(self, reservation: Reservation, now: Optional[float] = None) -> None:
        """Mark a reservation settled after the mint accepted the proof."""
        stamp = time.time() if now is None else now
        self._transition(reservation.key, "RESERVED", "SETTLED", stamp,
                         note="settled")

    def mark_spent(self, reservation: Reservation, note: str = "double spend",
                   now: Optional[float] = None) -> None:
        """Mark a nullifier spent after a detected double-spend."""
        stamp = time.time() if now is None else now
        self._transition(reservation.key, ("RESERVED", "SETTLED"), "SPENT",
                         stamp, note=note)

    def recover_stale_reservations(self, older_than_seconds: float,
                                   now: Optional[float] = None) -> int:
        """Treat old RESERVED rows as SPENT.

        A crash can leave a reservation with no settlement result. The seller
        may already have granted credit, so re-crediting is unsafe. Conservative
        recovery refuses the nullifier forever; the operator can reconcile the
        row later.
        """
        now = time.time() if now is None else now
        cutoff = now - older_than_seconds
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE nullifiers SET state='SPENT', settled_at=?, "
                "note='stale reservation' "
                "WHERE state='RESERVED' AND reserved_at < ?",
                (now, cutoff),
            )
        return cursor.rowcount

    # -- reads -----------------------------------------------------------

    def state(self, mint_url: str, unit: str, keyset_id: str,
              nullifier: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT state FROM nullifiers WHERE mint_url=? AND unit=? "
            "AND keyset_id=? AND nullifier=?",
            (mint_url, unit, keyset_id, nullifier),
        ).fetchone()
        return row["state"] if row else None

    def pending(self, limit: int = 100) -> List[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM nullifiers WHERE state='RESERVED' "
            "ORDER BY reserved_at LIMIT ?",
            (limit,),
        ).fetchall()

    def rows(self) -> Iterable[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM nullifiers ORDER BY reserved_at"
        ).fetchall()

    # -- internals -------------------------------------------------------

    def _transition(self, key: tuple, from_states, to_state: str, stamp: float,
                    note: str) -> None:
        if isinstance(from_states, str):
            from_states = (from_states,)
        placeholders = ",".join("?" for _ in from_states)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                f"UPDATE nullifiers SET state=?, settled_at=?, note=? "
                f"WHERE mint_url=? AND unit=? AND keyset_id=? AND nullifier=? "
                f"AND state IN ({placeholders})",
                (to_state, stamp, note, *key, *from_states),
            )
            if cursor.rowcount != 1:
                row = self._conn.execute(
                    "SELECT state FROM nullifiers WHERE mint_url=? AND unit=? "
                    "AND keyset_id=? AND nullifier=?",
                    key,
                ).fetchone()
                if row is None:
                    raise JournalError(f"nullifier not found: {key}")
                self._raise_conflict(row["state"], key)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    @staticmethod
    def _raise_conflict(state: str, key: tuple):
        if state == "RESERVED":
            raise ReservationInFlight(state, key)
        if state == "SETTLED":
            raise AlreadySettled(state, key)
        if state == "SPENT":
            raise AlreadySpent(state, key)
        raise JournalError(f"unknown journal state {state!r} for {key}")
