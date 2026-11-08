"""Perplexity's decision model, which the gate asks when TypeSafe's fails. It takes the same kind of request: content
as state, named yes-or-no questions with criteria, and images as data URLs inside the state.
https://docs.perplexity.ai/docs/decisions"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx

from curated.ledger import SpendLedger
from curated.providers.openrouter import send_with_retries
from curated.settings import Models

PROVIDER = "perplexity"
URL = "https://api.perplexity.ai/v1/decisions"
KEY = "PERPLEXITY_API_KEY"
TIMEOUT_S = 30.0


class PerplexityError(RuntimeError):
    pass


class PerplexityDecider:
    def __init__(self, *, http: httpx.AsyncClient, ledger: SpendLedger, model: str, usd_per_million: float) -> None:
        self._http = http
        self._ledger = ledger
        self._model = model
        self._usd_per_million = usd_per_million

    @classmethod
    @asynccontextmanager
    async def connect(cls, ledger: SpendLedger, models: Models) -> AsyncIterator[PerplexityDecider | None]:
        """The decider, or None when PERPLEXITY_API_KEY is not set, so the fallback is optional."""
        key = os.environ.get(KEY, "").strip()
        if not key:
            yield None
            return
        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT_S) as http:
            yield cls(
                http=http,
                ledger=ledger,
                model=models.fallback_decider,
                usd_per_million=models.fallback_decider_usd_per_million_input_tokens,
            )

    async def decide(self, state: Any, questions: Mapping[str, dict[str, Any]], *, purpose: str) -> dict[str, float]:
        """The probability of yes for each named question; raises PerplexityError when the call fails."""
        self._ledger.ensure_room()
        body = {"model": self._model, "state": state, "questions": dict(questions)}
        response = await send_with_retries(lambda: self._http.post(URL, json=body), label=f"decisions {self._model}")
        if response.status_code != httpx.codes.OK:
            raise PerplexityError(f"decisions {self._model} -> {response.status_code}: {response.text[:300]}")
        payload = response.json()
        tokens = payload.get("usage", {}).get("input_tokens") or 0
        self._ledger.record(
            provider=PROVIDER, model=self._model, purpose=purpose, cost_usd=tokens * self._usd_per_million / 1_000_000
        )
        return {name: float(payload["answers"][name]["noul"]) for name in questions}
