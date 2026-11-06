"""Stand-ins for Jev and OpenRouter that answer from word overlap, so the whole query path runs with no paid call."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from typesafe_sdk import (
    Answer,
    Asset,
    Choice,
    ChoiceAnswer,
    JSONContent,
    Noul,
    NoulAnswer,
    Question,
    SystemOneResponse,
    Usage,
)

STOPWORDS = frozenset({"a", "an", "and", "at", "for", "in", "is", "it", "of", "on", "or", "the", "to", "with"})
WORD = re.compile(r"[a-z0-9]+")
DIMENSIONS = 768


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower())) - STOPWORDS


def overlap(query: str, text: str) -> float:
    """The share of the query's words the text contains."""
    wanted = words(query)
    return len(wanted & words(text)) / len(wanted) if wanted else 0.0


def embed_words(text: str) -> NDArray[np.float32]:
    """A unit vector from the text's words, so texts sharing words lie close together."""
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    for word in words(text) or {"empty"}:
        digest = hashlib.sha256(word.encode()).digest()
        generator = np.random.default_rng(int.from_bytes(digest[:8]))
        vector += generator.standard_normal(DIMENSIONS).astype(np.float32)
    return vector / np.linalg.norm(vector)


@dataclass
class StubJev:
    """Answers gate questions from the overlap between the search and the product's card, and query questions from
    the overlap between the search and the question."""

    delay_s: float = 0.0

    async def ask(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        purpose: str,
        assets: Mapping[str, Asset] | None = None,
    ) -> SystemOneResponse:
        await asyncio.sleep(self.delay_s)
        answers: dict[str, Answer] = {}
        fields = state if isinstance(state, dict) else {}
        search = str(fields.get("buyer_search", ""))
        products = fields.get("products", {})
        for key, question in questions.items():
            if isinstance(question, Noul):
                cards: dict[str, Any] = products if isinstance(products, dict) else {}
                if key in cards:
                    answers[key] = NoulAnswer(noul=overlap(search, str(cards[key])))
                elif key == "states_limit":
                    answers[key] = NoulAnswer(noul=1.0 if "$" in search else 0.0)
                else:
                    answers[key] = NoulAnswer(noul=overlap(search, str(question.instructions)))
            elif isinstance(question, Choice):
                best = next(iter(question.criteria))
                answers[key] = ChoiceAnswer(choice=best, confidence=1.0, probabilities={best: 1.0})
            else:
                raise TypeError(f"StubJev does not answer {type(question).__name__}")
        return SystemOneResponse(model="jev-stub", usage=Usage(input_tokens=1, output_tokens=0), answers=answers)


@dataclass
class StubModels:
    """Answers the interpretation by repeating the search, and the price parse from `under $N`."""

    delay_s: float = 0.0

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
        await asyncio.sleep(self.delay_s)
        prompt = str(messages[0]["content"])
        if schema_name == "search_interpretation":
            found = re.search(r"^> (.*)$", prompt, re.MULTILINE)
            return {"interpretation": f"Things that fit {found.group(1) if found else prompt}."}
        if schema_name == "search_filters":
            search = prompt.rsplit("Search: ", 1)[-1]
            limit = re.search(r"under \$(\d+)", search)
            return {"price_min": None, "price_max": float(limit.group(1)) if limit else None}
        raise ValueError(f"no stub answer for {schema_name}")

    async def embed_texts(
        self, texts: Sequence[str], *, model: str, dimensions: int, purpose: str
    ) -> NDArray[np.float32]:
        await asyncio.sleep(self.delay_s / 4)
        return np.stack([embed_words(text) for text in texts])
