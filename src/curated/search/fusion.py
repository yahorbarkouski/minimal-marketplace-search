"""Reciprocal rank fusion of the arms' rankings into one ranking, optionally weighting each arm."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping

from curated.domain import ArmName, Hit, ProductId, Ranking


def reciprocal_rank_fusion(
    rankings: Mapping[ArmName, Ranking],
    *,
    rrf_k: int,
    top_k: int,
    weights: Mapping[ArmName, float] | None = None,
) -> Ranking:
    """Score each product by the sum over arms of weight / (rrf_k + rank), from rank 1; keep the best top_k.

    An arm missing from `weights` weighs 1.0, and an arm weighing 0 is left out, so its products score nothing.
    """
    contributions: defaultdict[ProductId, list[float]] = defaultdict(list)
    for arm, ranking in rankings.items():
        weight = 1.0 if weights is None else weights.get(arm, 1.0)
        if weight < 0:
            raise ValueError(f"fusion weight for {arm} is negative: {weight}")
        if weight == 0:
            continue
        for rank, hit in enumerate(ranking, start=1):
            contributions[hit.product_id].append(weight / (rrf_k + rank))
    # fsum is exactly rounded, so products holding the same ranks in equally weighted arms tie exactly.
    fused = sorted(
        ((product_id, math.fsum(parts)) for product_id, parts in contributions.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return tuple(Hit(product_id=product_id, score=score) for product_id, score in fused[:top_k])
