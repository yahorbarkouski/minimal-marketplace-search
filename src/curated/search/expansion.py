"""The tag-defined expansion: every product whose Jev tags satisfy the query's confident category and facets."""

from __future__ import annotations

import heapq
from collections.abc import Set as AbstractSet
from itertools import islice

import numpy as np
from numpy.typing import NDArray

from curated.domain import Hit, ProductId, Ranking
from curated.indexing.tagging import ProductTags

# Jev's probabilities come in hundredths; summing them in floating point can land a hair under a floor
# the product meets (0.6 + 0.3 < 0.9).
FLOOR_TOLERANCE = 1e-9


def expand(
    query_category_probs: NDArray[np.float64],
    query_facet_probs: NDArray[np.float64],
    tags: ProductTags,
    *,
    allowed: NDArray[np.bool_] | None,
    exclude: AbstractSet[ProductId],
    category_floor: float,
    facet_floor: float,
    product_floor: float,
    cap: int,
) -> Ranking:
    """The products a broad query defines by its tags, best first, at most `cap` of them.

    The arms each return a top k, so a query that matches thousands of products reaches the gate only
    through the few hundred most similar. This set is defined over every product instead, so its
    completeness does not depend on k; the gate verifies it up to `cap`. When more products match than
    `cap`, the order inside the set decides which are seen, and at scale that is where a taste ranking
    takes over from the tag score.

    The query's confident categories C are those with probability >= `category_floor`, its confident
    facets F those with probability >= `facet_floor`; with neither, the set is empty. A product matches when
    its category mass over C (its probabilities summed over C) reaches `product_floor`, or C is empty, and
    its probability of every facet in F reaches `product_floor`. It scores its category mass over C (1.0
    when C is empty) times the product of its probabilities over F. Ties break by product_id ascending.

    `allowed` is a boolean mask aligned with the order of `tags.ids`; products where it is False are left
    out. Products in `exclude`, such as those already in the fused list, are left out too.
    """
    if cap < 1:
        raise ValueError(f"cap must be at least 1, got {cap}")
    product_count, category_count = tags.category_probs.shape
    facet_count = tags.facet_probs.shape[1]
    if query_category_probs.shape != (category_count,) or query_facet_probs.shape != (facet_count,):
        raise ValueError(
            f"query probabilities have shapes {query_category_probs.shape} and {query_facet_probs.shape}; "
            f"the tags have {category_count} categories and {facet_count} facets"
        )
    if allowed is not None and allowed.shape != (product_count,):
        raise ValueError(f"allowed has shape {allowed.shape}; the tags have {product_count} products")

    confident_categories = query_category_probs >= category_floor
    facets = np.flatnonzero(query_facet_probs >= facet_floor)
    if not confident_categories.any() and facets.size == 0:
        return ()

    floor = product_floor - FLOOR_TOLERANCE
    matches = np.ones(product_count, dtype=np.bool_) if allowed is None else allowed.copy()
    scores = np.ones(product_count)
    if confident_categories.any():
        # A product with the 0/1 indicator streams the matrix once; gathering its columns is ~20x slower.
        scores = tags.category_probs @ confident_categories.astype(np.float64)
        matches &= scores >= floor
    if facets.size:
        facet_probs = tags.facet_probs[:, facets]
        matches &= (facet_probs >= floor).all(axis=1)
        scores = scores * facet_probs.prod(axis=1)
    rows = np.flatnonzero(matches)
    return _best(rows, scores[rows], tags.ids, exclude=exclude, cap=cap)


def _best(
    rows: NDArray[np.intp],
    scores: NDArray[np.float64],
    ids: tuple[ProductId, ...],
    *,
    exclude: AbstractSet[ProductId],
    cap: int,
) -> Ranking:
    """The first `cap` rows not in `exclude`, by descending score then ascending product_id.

    Only the first cap + len(exclude) rows in that order can survive, so the rest are dropped with numpy
    before any product_id is read. Tags come in hundredths, so thousands of products can tie at that boundary;
    only the smallest product_ids among them are kept.
    """
    wanted = cap + len(exclude)
    candidates: list[tuple[float, ProductId]] = []
    if rows.size > wanted:
        boundary = float(np.partition(scores, rows.size - wanted)[rows.size - wanted])
        tied = rows[scores == boundary]
        above = scores > boundary
        rows, scores = rows[above], scores[above]
        tied_ids = heapq.nsmallest(wanted - rows.size, (ids[row] for row in tied.tolist()))
        candidates = [(-boundary, product_id) for product_id in tied_ids]
    candidates += [(-score, ids[row]) for row, score in zip(rows.tolist(), scores.tolist(), strict=True)]
    candidates.sort()
    hits = (
        Hit(product_id=product_id, score=-negated) for negated, product_id in candidates if product_id not in exclude
    )
    return tuple(islice(hits, cap))
