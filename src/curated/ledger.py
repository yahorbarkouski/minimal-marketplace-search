"""A spend ledger that records every paid call and refuses new ones once the budget is spent."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

WARNING_FRACTIONS = (0.5, 0.8)


class BudgetExceededError(RuntimeError):
    pass


@dataclass
class SpendLedger:
    path: Path
    cap_usd: float
    total_usd: float = 0.0

    @classmethod
    def open(cls, path: Path, cap_usd: float) -> SpendLedger:
        total = 0.0
        if path.exists():
            with path.open(encoding="utf-8") as lines:
                total = sum(json.loads(line)["cost_usd"] for line in lines if line.strip())
        return cls(path=path, cap_usd=cap_usd, total_usd=total)

    def ensure_room(self) -> None:
        if self.total_usd >= self.cap_usd:
            raise BudgetExceededError(f"spent ${self.total_usd:.4f} of the ${self.cap_usd:.2f} budget")

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


def spend_by_purpose(path: Path) -> dict[str, float]:
    totals: dict[str, float] = {}
    if path.exists():
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    entry = json.loads(line)
                    totals[entry["purpose"]] = totals.get(entry["purpose"], 0.0) + entry["cost_usd"]
    return totals
