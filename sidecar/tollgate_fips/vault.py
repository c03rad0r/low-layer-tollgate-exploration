"""Durable token vault: keep the bearer token until it is redeemed.

`PaymentGate.accept` reserves a nullifier and takes exposure before the seller
has redeemed anything. If the process dies between acceptance and settlement,
the journal row is RESERVED and the token — the only thing that can settle it —
lives only in the caller's memory.

The vault closes that window: the token is written **before** the journal row is
committed, keyed by the proof's nullifier tuple. A recovery worker can then
redeem every pending token and close the journal, with no re-credit.

This stores bearer tokens, so the database is money. Treat it like a wallet:
file permissions, encryption at rest and a backup policy are the operator's
responsibility.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS token_vault (
    vault_key    TEXT PRIMARY KEY,
    token        TEXT NOT NULL,
    payer_npub   TEXT NOT NULL,
    mint_url     TEXT NOT NULL,
    unit         TEXT NOT NULL,
    keyset_id    TEXT NOT NULL,
    nullifier    TEXT NOT NULL,
    amount_msat  TEXT NOT NULL,
    final_expiry INTEGER,
    created_at   REAL NOT NULL,
    settled_at   REAL
);
CREATE INDEX IF NOT EXISTS token_vault_pending
    ON token_vault (settled_at, created_at);
"""


def vault_key(mint_url: str, unit: str, keyset_id: str, nullifier: str) -> str:
    return json.dumps([mint_url, unit, keyset_id, nullifier], separators=(",", ":"))


@dataclass(frozen=True)
class VaultEntry:
    vault_key: str
    token: str
    payer_npub: str
    mint_url: str
    unit: str
    keyset_id: str
    nullifier: str
    amount_msat: Decimal
    final_expiry: Optional[int]
    created_at: float

    @property
    def reservation_key(self) -> tuple:
        return (self.mint_url, self.unit, self.keyset_id, self.nullifier)


class TokenVault:
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

    # -- writes ----------------------------------------------------------

    def put(self, token: str, payer_npub: str, mint_url: str, unit: str,
            keyset_id: str, nullifier: str, amount_msat,
            final_expiry: Optional[int] = None,
            now: Optional[float] = None) -> VaultEntry:
        stamp = time.time() if now is None else now
        key = vault_key(mint_url, unit, keyset_id, nullifier)
        amount = Decimal(str(amount_msat))
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO token_vault (vault_key, token, payer_npub,"
                " mint_url, unit, keyset_id, nullifier, amount_msat, final_expiry,"
                " created_at, settled_at) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                (key, token, payer_npub, mint_url, unit, keyset_id, nullifier,
                 str(amount), final_expiry, stamp),
            )
        return VaultEntry(key, token, payer_npub, mint_url, unit, keyset_id,
                          nullifier, amount, final_expiry, stamp)

    def remove(self, key: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM token_vault WHERE vault_key=?", (key,))

    def mark_settled(self, key: str, now: Optional[float] = None) -> None:
        stamp = time.time() if now is None else now
        with self._conn:
            self._conn.execute(
                "UPDATE token_vault SET settled_at=? WHERE vault_key=?", (stamp, key))

    # -- reads -----------------------------------------------------------

    def get(self, key: str) -> Optional[VaultEntry]:
        row = self._conn.execute(
            "SELECT * FROM token_vault WHERE vault_key=?", (key,)).fetchone()
        return self._row(row) if row else None

    def pending(self, limit: int = 1000) -> List[VaultEntry]:
        rows = self._conn.execute(
            "SELECT * FROM token_vault WHERE settled_at IS NULL "
            "ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def by_token(self, entries: Iterable[VaultEntry]) -> dict:
        grouped: dict = {}
        for entry in entries:
            grouped.setdefault(entry.token, []).append(entry)
        return grouped

    @staticmethod
    def _row(row: sqlite3.Row) -> VaultEntry:
        return VaultEntry(
            vault_key=row["vault_key"],
            token=row["token"],
            payer_npub=row["payer_npub"],
            mint_url=row["mint_url"],
            unit=row["unit"],
            keyset_id=row["keyset_id"],
            nullifier=row["nullifier"],
            amount_msat=Decimal(row["amount_msat"]),
            final_expiry=row["final_expiry"],
            created_at=row["created_at"],
        )
