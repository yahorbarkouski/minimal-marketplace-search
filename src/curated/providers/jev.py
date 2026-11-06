"""Jev, TypeSafe's decision model, with each call charged to the spend ledger."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Protocol

from typesafe_sdk import Asset, AsyncTypeSafeClient, JSONContent, Question, RetryPolicy, SystemOneResponse

from curated.ledger import SpendLedger
from curated.settings import Models, require_env

PROVIDER = "typesafe"
IMAGES_HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
"""Jev reads images only on requests that carry this header, which TypeSafe labels experimental."""


class JevAsker(Protocol):
    """What callers need from Jev: one call with a state, named questions and any images the state refers to."""

    async def ask(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        assets: Mapping[str, Asset] | None = None,
    ) -> SystemOneResponse: ...


class JevClient:
    def __init__(
        self, *, client: AsyncTypeSafeClient, ledger: SpendLedger, model: str | None, usd_per_million: float
    ) -> None:
        self._client = client
        self._ledger = ledger
        self._model = model
        self._usd_per_million = usd_per_million

    @classmethod
    @asynccontextmanager
    async def connect(cls, ledger: SpendLedger, models: Models) -> AsyncIterator[JevClient]:
        # One transport retry covers a dropped connection or a 429/5xx; the SDK never retries a 4xx.
        retry = RetryPolicy(max_retries=1)
        async with AsyncTypeSafeClient(api_key=require_env("TYPESAFE_API_KEY"), retry=retry) as client:
            yield cls(
                client=client,
                ledger=ledger,
                model=models.jev,
                usd_per_million=models.jev_usd_per_million_input_tokens,
            )

    async def ask(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        assets: Mapping[str, Asset] | None = None,
    ) -> SystemOneResponse:
        self._ledger.ensure_room()
        response = await self._client.system_one(
            state=state,
            questions=questions,
            model=self._model,
            assets=assets,
            extra_headers=IMAGES_HEADERS if assets else None,
        )
        self._ledger.record(provider=PROVIDER, model=response.model, purpose=purpose, cost_usd=self.cost_of(response))
        return response

    def cost_of(self, response: SystemOneResponse) -> float:
        """What one call costs, from its input tokens; Jev does not report a price."""
        return (response.usage.input_tokens or 0) * self._usd_per_million / 1_000_000
