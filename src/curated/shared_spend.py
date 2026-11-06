"""A spend total that serverless instances share, so the budget holds across them. Instances share no memory or disk,
so each one adds what it spent as a small blob whose name holds the amount, and the total is the sum of those names.
Adding a new blob instead of rewriting one means two instances can never overwrite each other's spend. A daily ledger's
blobs sit under the day's own prefix, so each search lists only that day's."""

from __future__ import annotations

import sys
from uuid import uuid4

from vercel.blob import BlobError, put_blob, query_blobs

from curated.ledger import SpendLedger, utc_day

PREFIX = "spend/"


def amount_of(pathname: str) -> float:
    """The dollars a spend blob records, from a name such as `spend/1f3a-0.018500.txt`."""
    return float(pathname.removesuffix(".txt").rsplit("-", 1)[1])


class SharedSpend:
    """Keeps the instance's ledger at the total across all instances, on top of what was spent before deploying."""

    def __init__(self, ledger: SpendLedger, *, spent_before_usd: float) -> None:
        self._ledger = ledger
        self._spent_before = spent_before_usd
        self._synced = ledger.total_usd

    def _prefix(self) -> str:
        return PREFIX if self._ledger.day is None else f"{PREFIX}{utc_day()}/"

    async def refresh(self) -> None:
        """Brings the ledger up to the shared total. A failure stops the search, so an outage can't lift the cap."""
        total = self._spent_before
        async for blob in query_blobs(prefix=self._prefix()):
            total += amount_of(blob.pathname)
        # A daily ledger may just have started a new day, which leaves nothing to share.
        unshared = max(0.0, self._ledger.total_usd - self._synced)
        self._synced = total
        self._ledger.total_usd = total + unshared

    async def share(self) -> None:
        """Records what this instance has spent since it last shared."""
        unshared = self._ledger.total_usd - self._synced
        if unshared <= 0:
            return
        self._synced = self._ledger.total_usd
        try:
            await put_blob(f"{self._prefix()}{uuid4().hex}-{unshared:.6f}.txt", b"0", access="private")
        except BlobError as error:
            print(f"[spend] could not record ${unshared:.4f}: {error!r}", file=sys.stderr)
