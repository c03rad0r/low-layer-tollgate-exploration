"""Durable, npub-bound prepaid accounts for intermittent relays.

A FIPS link id is a transport incident, not an account. `PrepaidAccountStore`
pins credit, usage and deadlines to the authenticated npub; a new link id on
the same authenticated npub resumes that account.

This module is deliberately independent of a specific seller controller. It is
the account contract the balloon controller can port to embedded firmware; it
does not by itself verify Cashu or mutate the forwarding dataplane.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional


class AccountState(str, Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    GRACE = "grace"
    DORMANT = "dormant"
    EVICTED = "evicted"


class AccountError(RuntimeError):
    pass


class IdentityMismatch(AccountError):
    pass


@dataclass
class PrepaidAccount:
    npub: str
    rate_bytes_per_msat: Decimal
    state: AccountState = AccountState.UNPAID
    credit_msat: Decimal = Decimal(0)
    used_msat: Decimal = Decimal(0)
    issued_at_mono: float = 0.0
    max_session_seconds: Optional[float] = 7 * 24 * 3600
    grace_seconds: float = 24 * 3600
    grace_deadline_mono: Optional[float] = None
    link_id: Optional[str] = None
    evicted_reason: Optional[str] = None
    _resume_state: Optional[AccountState] = None

    def __post_init__(self) -> None:
        if not self.npub:
            raise AccountError("npub is required")
        self.rate_bytes_per_msat = Decimal(self.rate_bytes_per_msat)
        self.credit_msat = Decimal(self.credit_msat)
        self.used_msat = Decimal(self.used_msat)
        if self.rate_bytes_per_msat <= 0:
            raise AccountError("rate must be positive")
        if self.credit_msat < 0 or self.used_msat < 0:
            raise AccountError("credit and usage cannot be negative")

    @property
    def remaining_msat(self) -> Decimal:
        return max(Decimal(0), self.credit_msat - self.used_msat)

    @property
    def forwarding_allowed(self) -> bool:
        return self.state is AccountState.PAID and self.link_id is not None

    @property
    def deadline_mono(self) -> Optional[float]:
        if self.max_session_seconds is None:
            return None
        return self.issued_at_mono + self.max_session_seconds

    def top_up(self, amount_msat, now: Optional[float] = None) -> None:
        """Add value without resetting usage; never silently re-enable eviction."""
        amount = Decimal(str(amount_msat))
        if amount <= 0:
            raise AccountError("top-up must be positive")
        if self.state is AccountState.EVICTED:
            raise AccountError("an evicted account requires explicit re-admission")
        self.credit_msat += amount
        if self.state is AccountState.DORMANT:
            self._resume_state = AccountState.PAID
        else:
            self.state = AccountState.PAID
        self.grace_deadline_mono = None

    def charge(self, frame_bytes: int, now: Optional[float] = None) -> Decimal:
        """Bill whole FMP frames, not payload estimates, when forwarding."""
        if frame_bytes < 0:
            raise AccountError("negative frame length")
        if not self.forwarding_allowed:
            return Decimal(0)
        now = time.monotonic() if now is None else now
        cost = Decimal(frame_bytes) / self.rate_bytes_per_msat
        self.used_msat += cost
        if self.credit_msat > 0 and self.used_msat >= self.credit_msat:
            self._enter_grace(now)
        return cost

    def link_down(self) -> None:
        """Become dormant; do not delete credit or treat silence as non-payment."""
        if self.state is AccountState.EVICTED:
            return
        if self.state is not AccountState.DORMANT:
            self._resume_state = self.state
        self.link_id = None
        self.state = AccountState.DORMANT

    def link_up(self, npub: str, link_id: str) -> None:
        if npub != self.npub:
            raise IdentityMismatch("presenting peer does not own this account")
        if not link_id:
            raise AccountError("a new authenticated link_id is required")
        self.link_id = str(link_id)
        if self.state is AccountState.DORMANT:
            self.state = self._resume_state or AccountState.UNPAID
            self._resume_state = None

    def tick(self, now: Optional[float] = None) -> AccountState:
        """Apply expiry only as policy, never as link-loss detection."""
        now = time.monotonic() if now is None else now
        if self.state is AccountState.EVICTED:
            return self.state
        deadline = self.deadline_mono
        if deadline is not None and now >= deadline:
            if self.state is AccountState.DORMANT:
                self._resume_state = AccountState.GRACE
            elif self.state in (AccountState.PAID, AccountState.UNPAID):
                self._enter_grace(now)
        if self.state is AccountState.GRACE and self.grace_deadline_mono is not None:
            if now >= self.grace_deadline_mono:
                self.evict("grace expired")
        return self.state

    def evict(self, reason: str) -> None:
        """Explicit seller action; a contact gap alone must not call this."""
        self.state = AccountState.EVICTED
        self.evicted_reason = reason
        self.link_id = None
        self._resume_state = None

    def _enter_grace(self, now: float) -> None:
        if self.state in (AccountState.DORMANT, AccountState.EVICTED):
            return
        self.state = AccountState.GRACE
        self.grace_deadline_mono = now + self.grace_seconds


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    npub TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    account_json TEXT NOT NULL
);
"""


class PrepaidAccountStore:
    """Persistent account records using SQLite WAL and FULL synchronous writes.

    Call `save()` after a state transition that grants or spends credit.
    Link-id changes alone need not force a flash write in the embedded port.
    """

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def get_or_create(self, npub: str, rate_bytes_per_msat: Decimal) -> PrepaidAccount:
        row = self._conn.execute(
            "SELECT account_json FROM accounts WHERE npub=?", (npub,)
        ).fetchone()
        if row is None:
            return PrepaidAccount(npub=npub, rate_bytes_per_msat=rate_bytes_per_msat,
                                  issued_at_mono=time.monotonic())
        payload = json.loads(row["account_json"])
        payload["state"] = AccountState(payload["state"])
        if payload.get("_resume_state"):
            payload["_resume_state"] = AccountState(payload["_resume_state"])
        # Every persisted Decimal is restored as Decimal, never float arithmetic.
        for field in ("rate_bytes_per_msat", "credit_msat", "used_msat"):
            payload[field] = Decimal(payload[field])
        return PrepaidAccount(**payload)

    def save(self, account: PrepaidAccount) -> None:
        payload = dict(account.__dict__)
        payload["state"] = account.state.value
        if account._resume_state:
            payload["_resume_state"] = account._resume_state.value
        for field in ("rate_bytes_per_msat", "credit_msat", "used_msat"):
            payload[field] = str(getattr(account, field))
        self._conn.execute(
            "INSERT INTO accounts(npub,state,account_json) VALUES (?,?,?) "
            "ON CONFLICT(npub) DO UPDATE SET state=excluded.state, "
            "account_json=excluded.account_json",
            (account.npub, account.state.value, json.dumps(payload, sort_keys=True)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
