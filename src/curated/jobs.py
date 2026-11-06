"""Running a long job's items together."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable

from curated.runlog import RunStopped


async def gather_stopping(jobs: Iterable[Awaitable[None]]) -> None:
    """Runs the jobs together; the first RunStopped cancels the rest and is raised, so nothing writes to a run that
    has closed."""
    tasks = [asyncio.ensure_future(job) for job in jobs]
    try:
        await asyncio.gather(*tasks)
    except RunStopped:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
