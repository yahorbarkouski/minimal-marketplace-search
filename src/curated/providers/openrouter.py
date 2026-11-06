"""OpenRouter: structured completions and Gemini embeddings, each call charged to the spend ledger."""

from __future__ import annotations

import base64
import json
import random
import sys
from asyncio import sleep
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import numpy as np
from numpy.typing import NDArray

from curated.ledger import SpendLedger
from curated.settings import require_env

BASE_URL = "https://openrouter.ai/api/v1"
PROVIDER = "openrouter"
MAX_RETRIES = 4
FIRST_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0


class OpenRouterError(RuntimeError):
    pass


def jpeg_data_uri(image: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")


@asynccontextmanager
async def connect_http() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for the OpenRouter API, authenticated with OPENROUTER_API_KEY."""
    # Transport retries re-open failed connections only; a request the server received is resent
    # only by send_with_retries, after a 429 or 5xx answer.
    transport = httpx.AsyncHTTPTransport(retries=2, limits=httpx.Limits(max_connections=64))
    headers = {"Authorization": f"Bearer {require_env('OPENROUTER_API_KEY')}"}
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=timeout, transport=transport) as http:
        yield http


async def send_with_retries(send: Callable[[], Awaitable[httpx.Response]], *, label: str) -> httpx.Response:
    """Sends a request, and resends it after a 429 or 5xx answer up to MAX_RETRIES times; returns the
    last response for the caller to check.

    This is infrastructure for rate limits and provider outages, not a quality fallback: the same
    request goes to the same model, and any other status, including every other 4xx, returns at once.
    Each wait follows `Retry-After` when the answer has one, else exponential backoff with jitter.
    """
    response = await send()
    for retry in range(1, MAX_RETRIES + 1):
        if not _is_transient(response.status_code):
            break
        delay = _retry_delay_seconds(response.headers.get("Retry-After"), retry)
        print(
            f"[openrouter] {label} -> {response.status_code}; retry {retry} of {MAX_RETRIES} in {delay:.1f}s",
            file=sys.stderr,
        )
        await sleep(delay)
        response = await send()
    return response


def _is_transient(status_code: int) -> bool:
    return status_code == httpx.codes.TOO_MANY_REQUESTS or status_code >= httpx.codes.INTERNAL_SERVER_ERROR


def _retry_delay_seconds(retry_after: str | None, retry: int) -> float:
    """Retry n waits between half and all of FIRST_BACKOFF_SECONDS * 2**(n-1), at most
    MAX_BACKOFF_SECONDS, unless the server said how long to wait."""
    if retry_after is not None:
        return _retry_after_seconds(retry_after)
    ceiling = min(MAX_BACKOFF_SECONDS, FIRST_BACKOFF_SECONDS * 2 ** (retry - 1))
    return random.uniform(ceiling / 2, ceiling)


def _retry_after_seconds(value: str) -> float:
    """Reads `Retry-After`, which is either a number of seconds or an HTTP date."""
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise OpenRouterError(f"unreadable Retry-After header: {value!r}") from error
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


class OpenRouterClient:
    def __init__(self, *, http: httpx.AsyncClient, ledger: SpendLedger) -> None:
        self._http = http
        self._ledger = ledger

    @classmethod
    @asynccontextmanager
    async def connect(cls, ledger: SpendLedger) -> AsyncIterator[OpenRouterClient]:
        async with connect_http() as http:
            yield cls(http=http, ledger=ledger)

    async def complete_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
        reasoning_effort: str | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Returns the model's answer parsed as JSON that matches `schema`."""
        answer, _ = await self.complete_json_costed(
            model=model,
            messages=messages,
            schema_name=schema_name,
            schema=schema,
            purpose=purpose,
            reasoning_effort=reasoning_effort,
            provider=provider,
            max_tokens=max_tokens,
        )
        return answer

    async def complete_json_costed(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
        reasoning_effort: str | None = None,
        provider: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], float]:
        """The answer and what the call cost in USD, for jobs that track their own spend."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        if reasoning_effort is not None:
            body["reasoning"] = {"effort": reasoning_effort}
        if provider is not None:
            body["provider"] = {"order": [provider], "allow_fallbacks": False}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        payload = await self._post("/chat/completions", body, model=model, purpose=purpose)
        content = payload["choices"][0]["message"].get("content")
        if not content:
            raise OpenRouterError(f"{model} returned no content: {json.dumps(payload)[:500]}")
        return json.loads(content), float(payload.get("usage", {}).get("cost") or 0.0)

    async def embed_texts(
        self, texts: Sequence[str], *, model: str, dimensions: int, purpose: str
    ) -> NDArray[np.float32]:
        return await self._embed(list(texts), model=model, dimensions=dimensions, purpose=purpose)

    async def embed_images(
        self, images: Sequence[bytes], *, model: str, dimensions: int, purpose: str
    ) -> NDArray[np.float32]:
        """Embeds each JPEG image as one vector."""
        inputs = [{"content": [{"type": "image_url", "image_url": {"url": jpeg_data_uri(image)}}]} for image in images]
        return await self._embed(inputs, model=model, dimensions=dimensions, purpose=purpose)

    async def _embed(self, inputs: list[Any], *, model: str, dimensions: int, purpose: str) -> NDArray[np.float32]:
        body = {"model": model, "input": inputs, "dimensions": dimensions, "encoding_format": "float"}
        payload = await self._post("/embeddings", body, model=model, purpose=purpose)
        rows = sorted(payload["data"], key=lambda row: row["index"])
        if len(rows) != len(inputs):
            raise OpenRouterError(f"{model} returned {len(rows)} embeddings for {len(inputs)} inputs")
        return np.asarray([row["embedding"] for row in rows], dtype=np.float32)

    async def _post(self, path: str, body: dict[str, Any], *, model: str, purpose: str) -> dict[str, Any]:
        self._ledger.ensure_room()
        response = await send_with_retries(lambda: self._http.post(path, json=body), label=f"{path} {model}")
        if response.status_code != httpx.codes.OK:
            raise OpenRouterError(f"{path} {model} -> {response.status_code}: {response.text[:500]}")
        payload: dict[str, Any] = response.json()
        if "error" in payload:
            raise OpenRouterError(f"{path} {model} -> {json.dumps(payload['error'])[:500]}")
        cost = float(payload.get("usage", {}).get("cost") or 0.0)
        self._ledger.record(provider=PROVIDER, model=model, purpose=purpose, cost_usd=cost)
        return payload
