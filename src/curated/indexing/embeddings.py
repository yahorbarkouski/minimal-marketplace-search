"""Embeddings of product cards, product photos and queries, cached per item and kept as L2-normalized matrices."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from curated.cache import JsonCache, JsonValue
from curated.domain import ProductId
from curated.indexing.photos import model_photo
from curated.providers.openrouter import OpenRouterClient
from curated.providers.protocols import TextEmbedder

TEXT_NAMESPACE = "embedding-text"
PHOTO_NAMESPACE = "embedding-photo"
QUERY_PURPOSE = "embedding-query"
INTERPRETATION_PURPOSE = "embedding-interpretation"
EMBEDDING_CONCURRENCY = 8


def document_text(title: str, card: str) -> str:
    return f"title: {title} | text: {card}"


def query_text(text: str) -> str:
    return f"task: search result | query: {text}"


def l2_normalize(vectors: NDArray[np.float32]) -> NDArray[np.float32]:
    """Scales each vector (each row of a matrix) to unit length."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("cannot normalize a zero vector")
    return (vectors / norms).astype(np.float32)


@dataclass(frozen=True)
class EmbeddingMatrix:
    """One L2-normalized row per product, in the order of `ids`."""

    ids: tuple[ProductId, ...]
    vectors: NDArray[np.float32]

    def __post_init__(self) -> None:
        shape = self.vectors.shape
        if self.vectors.dtype != np.float32 or len(shape) != 2 or shape[0] != len(self.ids):
            raise ValueError(
                f"expected a float32 matrix with one row per id ({len(self.ids)}), "
                f"got {self.vectors.dtype} of shape {shape}"
            )

    def save(self, directory: Path, name: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / f"{name}.npy", self.vectors)
        (directory / f"{name}.ids.json").write_text(json.dumps(list(self.ids)), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path, name: str) -> EmbeddingMatrix:
        ids = json.loads((directory / f"{name}.ids.json").read_text(encoding="utf-8"))
        return cls(ids=tuple(ids), vectors=np.load(directory / f"{name}.npy"))


async def embed_documents(
    texts: Mapping[ProductId, str],
    *,
    client: OpenRouterClient,
    cache: JsonCache,
    model: str,
    dimensions: int,
    batch_size: int = 32,
) -> EmbeddingMatrix:
    keys = {product_id: {"model": model, "dimensions": dimensions, "text": text} for product_id, text in texts.items()}

    async def embed(batch: Sequence[ProductId]) -> NDArray[np.float32]:
        inputs = [texts[product_id] for product_id in batch]
        return await client.embed_texts(inputs, model=model, dimensions=dimensions, purpose=TEXT_NAMESPACE)

    return await _embed_uncached(
        keys, embed, namespace=TEXT_NAMESPACE, cache=cache, dimensions=dimensions, batch_size=batch_size
    )


async def embed_photo_sets(
    photos: Mapping[ProductId, Path],
    *,
    client: OpenRouterClient,
    cache: JsonCache,
    model: str,
    dimensions: int,
    batch_size: int = 8,
) -> EmbeddingMatrix:
    """Embeds each product's photo."""
    keys = {
        product_id: {"model": model, "dimensions": dimensions, "photo": hashlib.sha256(model_photo(path)).hexdigest()}
        for product_id, path in photos.items()
    }

    async def embed(batch: Sequence[ProductId]) -> NDArray[np.float32]:
        images = [model_photo(photos[product_id]) for product_id in batch]
        return await client.embed_images(images, model=model, dimensions=dimensions, purpose=PHOTO_NAMESPACE)

    return await _embed_uncached(
        keys, embed, namespace=PHOTO_NAMESPACE, cache=cache, dimensions=dimensions, batch_size=batch_size
    )


async def embed_query(text: str, *, client: TextEmbedder, model: str, dimensions: int) -> NDArray[np.float32]:
    """Embeds the user's query with the query prefix added. Never cached, so its latency is measured live."""
    vectors = await client.embed_texts([query_text(text)], model=model, dimensions=dimensions, purpose=QUERY_PURPOSE)
    return l2_normalize(vectors)[0]


async def embed_interpretation(
    text: str, interpretation: str, *, client: TextEmbedder, model: str, dimensions: int
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Two vectors in one call: the interpretation as a document titled by the search, which the style
    arm matches against the products' style descriptions, and as a query, for the text and photo arms."""
    vectors = await client.embed_texts(
        [document_text(text, interpretation), query_text(interpretation)],
        model=model,
        dimensions=dimensions,
        purpose=INTERPRETATION_PURPOSE,
    )
    as_document, as_query = l2_normalize(vectors)
    return as_document, as_query


async def _embed_uncached(
    keys: Mapping[ProductId, JsonValue],
    embed: Callable[[Sequence[ProductId]], Awaitable[NDArray[np.float32]]],
    *,
    namespace: str,
    cache: JsonCache,
    dimensions: int,
    batch_size: int,
) -> EmbeddingMatrix:
    """Sends only the items missing from the cache, in batches, and caches each raw vector as it arrives."""
    vectors = {product_id: cache.get(namespace, key) for product_id, key in keys.items()}
    missing = [product_id for product_id, vector in vectors.items() if vector is None]
    slots = asyncio.Semaphore(EMBEDDING_CONCURRENCY)
    done = 0

    async def embed_batch(batch: Sequence[ProductId]) -> None:
        nonlocal done
        async with slots:
            for product_id, vector in zip(batch, await embed(batch), strict=True):
                vectors[product_id] = vector.tolist()
                cache.put(namespace, keys[product_id], vectors[product_id])
            done += len(batch)
            print(f"[{namespace}] {done}/{len(missing)}", file=sys.stderr, flush=True)

    await asyncio.gather(
        *(embed_batch(missing[start : start + batch_size]) for start in range(0, len(missing), batch_size))
    )
    ids = tuple(keys)
    matrix = np.asarray([vectors[product_id] for product_id in ids], dtype=np.float32).reshape(len(ids), dimensions)
    return EmbeddingMatrix(ids=ids, vectors=l2_normalize(matrix))
