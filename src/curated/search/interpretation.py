"""The search's interpretation: a fast model says, in at most 45 words, what the search refers to and which
kinds of product, styles and settings from this directory belong to it.

It carries the world knowledge the rest of the query path lacks. The search uses it three ways: embedded as a
document against the products' style vectors, embedded as a query through the text and photo arms, and given to
the gate beside the buyer's words.

Interpretations are cached by the search's normalized text, so a repeated search pays neither the call nor
its latency.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from curated.providers.protocols import JsonCompleter

PROMPT = """\
A buyer typed this search into a directory of well-designed products: tech and audio, desk and workspace gear, \
furniture and home objects, bags and everyday carry, watches, design books, coffee gear, personal care, cameras, \
travel gear and cars:

> {query}

In at most 45 words, say what the search refers to and which kinds of product, styles and settings from \
this directory belong to it. Name concrete kinds of product."""
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"interpretation": {"type": "string"}},
    "required": ["interpretation"],
    "additionalProperties": False,
}
MAX_TOKENS = 200
PURPOSE = "interpret search"


async def interpret(text: str, *, client: JsonCompleter, model: str, provider: str | None) -> str:
    """The model's interpretation of one search; raises when the call fails or the answer is empty."""
    answer = await client.complete_json(
        model=model,
        provider=provider,
        reasoning_effort="minimal",
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": PROMPT.format(query=text)}],
        schema_name="search_interpretation",
        schema=SCHEMA,
        purpose=PURPOSE,
    )
    interpretation = " ".join(str(answer.get("interpretation", "")).split())
    if not interpretation:
        raise ValueError(f"{model} interpreted {text!r} as nothing")
    return interpretation


def normalized(text: str) -> str:
    """The cache key of a search: case and runs of whitespace do not change its meaning."""
    return " ".join(text.casefold().split())


class InterpretationCache:
    """The most recently used interpretations, at most `capacity` of them; a capacity of 0 caches nothing."""

    def __init__(self, capacity: int) -> None:
        if capacity < 0:
            raise ValueError(f"capacity must be at least 0, got {capacity}")
        self._capacity = capacity
        self._entries: OrderedDict[str, str] = OrderedDict()

    def get(self, text: str) -> str | None:
        key = normalized(text)
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, text: str, interpretation: str) -> None:
        if self._capacity == 0:
            return
        key = normalized(text)
        self._entries[key] = interpretation
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
