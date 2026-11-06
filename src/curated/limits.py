"""How many searches one visitor may make. The limit lives in each server instance's memory, so a deployment with
several instances allows a visitor up to that many times the limit, and an attacker with many addresses goes around it.
It stops casual abuse; the daily budget in `curated.ledger` is what bounds the bill."""

from __future__ import annotations

import math
import os
import time
from collections import deque
from collections.abc import Callable

from starlette.requests import Request

HOUR_SECONDS = 3600.0
MAX_VISITORS = 100_000
"""Visitors remembered at once, so that many addresses can't grow the instance's memory without end."""


class RateLimit:
    """At most `per_hour` requests from one visitor in any hour."""

    def __init__(self, per_hour: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if per_hour < 1:
            raise ValueError(f"per_hour must be at least 1, got {per_hour}")
        self._per_hour = per_hour
        self._clock = clock
        self._visitors: dict[str, deque[float]] = {}

    def retry_after(self, visitor: str) -> int | None:
        """Counts a request and returns None, or returns the seconds until this visitor may make one."""
        now = self._clock()
        times = self._visitors.setdefault(visitor, deque())
        while times and now - times[0] >= HOUR_SECONDS:
            times.popleft()
        if len(times) >= self._per_hour:
            return math.ceil(HOUR_SECONDS - (now - times[0]))
        times.append(now)
        if len(self._visitors) > MAX_VISITORS:
            oldest = min(self._visitors, key=lambda key: self._visitors[key][-1] if self._visitors[key] else 0.0)
            del self._visitors[oldest]
        return None


def visitor_address(request: Request) -> str:
    """The visitor's address. Vercel sets this header itself and overwrites any a visitor sends; anywhere else the
    header could be forged, so only the connection counts."""
    if os.environ.get("VERCEL"):
        forwarded = request.headers.get("x-vercel-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def wait_message(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"That's a lot of searches. Please try again in {minutes} minute{'' if minutes == 1 else 's'}."
