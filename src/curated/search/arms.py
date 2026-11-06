"""The retrieval arms: BM25 over the keyword fields, cosine over product vectors, and Jev facet matching.

Each arm keeps its products in ascending id order and knows each product's row in the product table, so a filter's
mask over table rows restricts what the arm returns. Rankings break score ties by ascending product_id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

import bm25s
import numpy as np
import Stemmer
from numpy.typing import NDArray

from curated.domain import ArmName, Hit, KeywordFields, ProductId, Ranking
from curated.search.product_table import ProductTable

DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {"title": 3.0, "names": 2.0, "attributes": 2.0, "description": 1.0, "queries": 1.0}
)


class KeywordArm:
    """BM25 over each keyword field separately; a product scores the weighted sum of its per-field scores."""

    def __init__(
        self,
        table: ProductTable,
        fields: Mapping[ProductId, KeywordFields],
        weights: Mapping[str, float] = DEFAULT_WEIGHTS,
        name_boost: float = 5.0,
    ) -> None:
        texts = {product_id: value.model_dump() for product_id, value in fields.items()}
        field_names = tuple(next(iter(texts.values()))) if texts else tuple(KeywordFields.model_fields)
        if set(weights) != set(field_names):
            raise ValueError(f"weights must name exactly {field_names}, got {tuple(weights)}")
        if any(set(value) != set(field_names) for value in texts.values()):
            raise ValueError(f"every product must have exactly the fields {field_names}")
        self._ids = tuple(sorted(texts))
        self._rows = _TableRows(table, self._ids)
        self._weights = dict(weights)
        self._name_boost = name_boost
        self._stemmer = Stemmer.Stemmer("english")
        self._names = tuple(texts[product_id].get("names", "").casefold() for product_id in self._ids)
        self._indexes: dict[str, bm25s.BM25] = {}
        for field_name in field_names:
            corpus = self._tokenize([texts[product_id][field_name] for product_id in self._ids])
            # bm25s cannot index a field in which no product has a token; such a field can never match.
            if any(corpus):
                index = bm25s.BM25()
                index.index(corpus, show_progress=False)
                self._indexes[field_name] = index

    def search(self, text: str, brands: Sequence[str], k: int, *, allowed: NDArray[np.bool_] | None) -> Ranking:
        """Rank products for `text`. `brands` holds the brands found in the query; a product of one of them gains
        `name_boost`. `allowed`, a mask over product table rows, restricts the ranking to the products it marks."""
        (query_tokens,) = self._tokenize([text])
        scores = np.zeros(len(self._ids))
        for field_name, index in self._indexes.items():
            token_ids = index.get_tokens_ids(query_tokens)
            if token_ids:
                scores += self._weights[field_name] * index.get_scores_from_ids(token_ids)
        for brand in brands:
            scores += self._name_boost * np.array([names == brand.casefold() for names in self._names])
        return _top_hits(self._ids, scores, self._rows.positive_and_allowed(scores, allowed), k)

    def _tokenize(self, texts: list[str]) -> list[list[str]]:
        tokenized = bm25s.tokenize(texts, stopwords="en", stemmer=self._stemmer, return_ids=False, show_progress=False)
        # With return_ids=False bm25s returns token strings, though its annotation also allows Tokenized.
        return cast(list[list[str]], tokenized)


class VectorArm:
    """Cosine similarity between a query vector and one L2-normalized vector per product."""

    def __init__(
        self, table: ProductTable, name: ArmName, ids: Sequence[ProductId], vectors: NDArray[np.float32]
    ) -> None:
        if vectors.ndim != 2 or vectors.shape[0] != len(ids):
            raise ValueError(f"{name} arm: expected one row per product ({len(ids)}), got shape {vectors.shape}")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3):
            raise ValueError(f"{name} arm: vector rows must be L2-normalized")
        self.name = name
        self._ids, order = _sorted_ids(ids)
        self._rows = _TableRows(table, self._ids)
        self._vectors = vectors[order]
        self._vectors.setflags(write=False)
        identity = json.dumps(
            {
                "name": name,
                "ids": self._ids,
                "dtype": self._vectors.dtype.str,
                "shape": self._vectors.shape,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(identity.encode("utf-8"))
        digest.update(self._vectors.tobytes())
        self.fingerprint = digest.hexdigest()

    def search(self, query_vector: NDArray[np.float32], k: int, *, allowed: NDArray[np.bool_] | None) -> Ranking:
        """The k products most similar to the query, among those `allowed` marks when it is given."""
        norm = np.linalg.norm(query_vector)
        if norm == 0:
            raise ValueError(f"{self.name} arm: the query vector is all zeros")
        return _top_hits(self._ids, self._vectors @ (query_vector / norm), self._rows.restrict(allowed), k)


class FacetArm:
    """Matches a query's Jev probabilities against each product's.

    For product i the score is

        score_i = Σ_c q_c · L_ic  +  Σ_f q'_f · P_if / Σ_f q'_f

    where q is the query's category distribution, L_ic the product's category distribution (a Jev Choice,
    rows sum to 1), P_if the product's independent facet probabilities, and q' the query's facet
    probabilities with every value below `query_floor` set to 0. The facet term is 0 when Σ_f q'_f is 0.
    """

    def __init__(
        self,
        table: ProductTable,
        ids: Sequence[ProductId],
        category_probs: NDArray[np.float64],
        facet_probs: NDArray[np.float64],
        query_floor: float = 0.3,
    ) -> None:
        for label, matrix in (("category_probs", category_probs), ("facet_probs", facet_probs)):
            if matrix.ndim != 2 or matrix.shape[0] != len(ids):
                raise ValueError(f"{label}: expected one row per product ({len(ids)}), got shape {matrix.shape}")
        self._ids, order = _sorted_ids(ids)
        self._rows = _TableRows(table, self._ids)
        self._category_probs = category_probs[order]
        self._facet_probs = facet_probs[order]
        self._query_floor = query_floor

    def search(
        self,
        query_category_probs: NDArray[np.float64],
        query_facet_probs: NDArray[np.float64],
        k: int,
        *,
        allowed: NDArray[np.bool_] | None,
    ) -> Ranking:
        """The k best-matching products with a positive score, among those `allowed` marks when it is given."""
        category_match = self._category_probs @ query_category_probs
        kept_facets = np.where(query_facet_probs >= self._query_floor, query_facet_probs, 0.0)
        kept_total = kept_facets.sum()
        scores = category_match + self._facet_probs @ kept_facets / kept_total if kept_total > 0 else category_match
        return _top_hits(self._ids, scores, self._rows.positive_and_allowed(scores, allowed), k)


def _sorted_ids(ids: Sequence[ProductId]) -> tuple[tuple[ProductId, ...], NDArray[np.intp]]:
    """The ids in ascending order, and the row order that puts per-product rows in that order."""
    if len(set(ids)) != len(ids):
        raise ValueError("product ids must be unique")
    order = sorted(range(len(ids)), key=ids.__getitem__)
    return tuple(ids[row] for row in order), np.array(order, dtype=np.intp)


class _TableRows:
    """Where an arm's products sit in the product table, to read a mask over table rows in the arm's own order."""

    def __init__(self, table: ProductTable, sorted_ids: tuple[ProductId, ...]) -> None:
        self._table_size = len(table)
        self._table_rows = table.rows(sorted_ids)

    def restrict(self, allowed: NDArray[np.bool_] | None) -> NDArray[np.bool_] | None:
        """The arm's rows that `allowed` marks, or None when there is no mask."""
        if allowed is None:
            return None
        if allowed.shape != (self._table_size,):
            raise ValueError(f"allowed must mask the {self._table_size} product table rows, got shape {allowed.shape}")
        return allowed[self._table_rows]

    def positive_and_allowed(
        self, scores: NDArray[np.floating], allowed: NDArray[np.bool_] | None
    ) -> NDArray[np.bool_]:
        """The arm's rows that score above 0 and that `allowed` marks."""
        restricted = self.restrict(allowed)
        return scores > 0 if restricted is None else (scores > 0) & restricted


def _top_hits(
    sorted_ids: tuple[ProductId, ...], scores: NDArray[np.floating], eligible: NDArray[np.bool_] | None, k: int
) -> Ranking:
    """The k best rows among the eligible ones (every row when `eligible` is None)."""
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if eligible is None:
        best = _best_positions(scores, k)
    else:
        candidates = np.flatnonzero(eligible)
        best = candidates[_best_positions(scores[candidates], k)]
    return tuple(Hit(product_id=sorted_ids[row], score=float(scores[row])) for row in best)


def _best_positions(scores: NDArray[np.floating], k: int) -> NDArray[np.intp]:
    """The positions of the k highest scores, by descending score and then ascending position.

    A partition finds the k-th highest score without sorting every score. Positions scoring above it
    are all kept; positions tied with it are kept lowest first until there are k, so a tie that
    straddles the cut keeps the same products a full stable sort would.
    """
    if len(scores) > k:
        kth_highest = scores[np.argpartition(-scores, k - 1)[:k]].min()
        above = np.flatnonzero(scores > kth_highest)
        tied = np.flatnonzero(scores == kth_highest)[: k - len(above)]
        positions = np.concatenate((above, tied))
    else:
        positions = np.arange(len(scores))
    return positions[np.lexsort((positions, -scores[positions]))]
