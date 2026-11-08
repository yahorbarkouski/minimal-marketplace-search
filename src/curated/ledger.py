"""A spend ledger that records every paid call and refuses new ones once the budget is spent. A daily ledger counts
only what was spent since midnight UTC, so its budget comes back each day."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

WARNING_FRACTIONS = (0.5, 0.8)


class BudgetExceededError(RuntimeError):
    pass


def utc_day(moment: float | None = None) -> str:
    """The UTC date of a moment, by default now, such as `2026-11-06`."""
    return datetime.fromtimestamp(time.time() if moment is None else moment, UTC).date().isoformat()


@dataclass
class SpendLedger:
    path: Path
    cap_usd: float
    total_usd: float = 0.0
    day: str | None = None
    """The UTC date a daily ledger is counting; None for a ledger that counts everything."""

    @classmethod
    def open(cls, path: Path, cap_usd: float, *, daily: bool = False) -> SpendLedger:
        day = utc_day() if daily else None
        total = 0.0
        if path.exists():
            with path.open(encoding="utf-8") as lines:
                entries = (json.loads(line) for line in lines if line.strip())
                total = sum(entry["cost_usd"] for entry in entries if day is None or utc_day(entry["at"]) == day)
        return cls(path=path, cap_usd=cap_usd, total_usd=total, day=day)

    def ensure_room(self) -> None:
        if self.day is not None and self.day != utc_day():
            self.day = utc_day()
            self.total_usd = 0.0
        if self.total_usd >= self.cap_usd:
            period = "today's" if self.day is not None else "the"
            raise BudgetExceededError(f"spent ${self.total_usd:.4f} of {period} ${self.cap_usd:.2f} budget")

    def record(self, *, provider: str, model: str, purpose: str, cost_usd: float) -> None:
        before = self.total_usd
        self.total_usd += cost_usd
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": time.time(),
            "provider": provider,
            "model": model,
            "purpose": purpose,
            "cost_usd": cost_usd,
        }
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry) + "\n")
        for fraction in WARNING_FRACTIONS:
            threshold = fraction * self.cap_usd
            if before < threshold <= self.total_usd:
                print(f"[ledger] spend passed ${threshold:.2f} of ${self.cap_usd:.2f}", file=sys.stderr)


def open_daily(path: Path, cap_usd: float) -> SpendLedger:
    """The ledger every command and the server use: today's spend against the daily budget."""
    return SpendLedger.open(path, cap_usd, daily=True)


def spend_by_purpose(path: Path) -> dict[str, float]:
    totals: dict[str, float] = {}
    if path.exists():
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    entry = json.loads(line)
                    totals[entry["purpose"]] = totals.get(entry["purpose"], 0.0) + entry["cost_usd"]
    return totals
