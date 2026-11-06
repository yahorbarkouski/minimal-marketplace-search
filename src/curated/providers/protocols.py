"""What the query path needs from a model provider, so tests can stand in for OpenRouter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray


class JsonCompleter(Protocol):
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
    ) -> dict[str, Any]: ...


class TextEmbedder(Protocol):
    async def embed_texts(
        self, texts: Sequence[str], *, model: str, dimensions: int, purpose: str
    ) -> NDArray[np.float32]: ...


class QueryModels(JsonCompleter, TextEmbedder, Protocol):
    """A provider that both parses queries and embeds them."""
