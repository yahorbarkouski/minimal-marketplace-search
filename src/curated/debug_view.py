"""The query debug panel's account of one search, read from its trace: each stage on one time axis, how
the decision model and the interpretation read the search, the counts from the whole corpus down to the page, the gate's
decisions, and one row per product the search judged with every ranking that found it.

Everything here is derived from the trace and the index; nothing calls a model or changes what the search
returns. The server adds each product's display fields to the rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, Literal

from curated.domain import ProductId, SearchTrace
from curated.search.searcher import SearchIndex
from curated.settings import Settings

StepKind = Literal["decision", "llm", "embedding", "code"]

STEPS: Mapping[str, tuple[str, StepKind]] = {
    "understand": ("Understanding", "decision"),
    "embed": ("Search embedding", "embedding"),
    "parse": ("Price parse", "llm"),
    "interpret": ("Interpretation", "llm"),
    "arms": ("Arms on the buyer's words", "code"),
    "fuse_early": ("Early fusion", "code"),
    "expand_early": ("Early expansion", "code"),
    "gate_early": ("Early gate", "decision"),
    "embed_interpretation": ("Interpretation embedding", "embedding"),
    "arms_interpretation": ("Arms on the interpretation", "code"),
    "fuse": ("Fusion", "code"),
    "expand": ("Tag expansion", "code"),
    "gate": ("Gate", "decision"),
}
"""Each timed stage, in the order the search starts them, with its label and the kind of work it is."""

MOMENTS = ("first_results", "first_product", "total")
CATEGORIES_SHOWN = 8
FACETS_SHOWN = 14


def describe_search(trace: SearchTrace, index: SearchIndex, settings: Settings) -> dict[str, Any]:
    """Everything the query debug panel shows of one search's first batch."""
    return {
        "steps": _steps(trace, settings),
        "moments": {moment: round(trace.timings_ms[moment]) for moment in MOMENTS if moment in trace.timings_ms},
        "reading": _reading(trace, index, settings),
        "arms": [{"name": arm.value, "count": len(ranking)} for arm, ranking in trace.arm_rankings.items()],
        "funnel": _funnel(trace, index, settings),
        "gate": _gate(trace, settings),
        "rows": _rows(trace),
        "settings": {
            "sizes": asdict(settings.sizes),
            "models": {name: value for name, value in asdict(settings.models).items() if isinstance(value, str)},
        },
    }


def _steps(trace: SearchTrace, settings: Settings) -> list[dict[str, Any]]:
    models = settings.models
    detail = {
        "understand": "Decision model: query type, stated limit, categories and facets in one call",
        "embed": models.embedding,
        "parse": models.query_parse,
        "interpret": "cached" if trace.timings_ms.get("interpret") == 0 else models.interpretation,
        "embed_interpretation": models.embedding,
        "gate_early": "Decision model with photos, on the buyer's words alone",
        "gate": "Decision model with photos, on the search and its interpretation",
    }
    return [
        {
            "key": key,
            "label": label,
            "kind": kind,
            "start": round(trace.stage_starts_ms[key], 1),
            "ms": round(trace.timings_ms[key], 1),
            "detail": detail.get(key),
        }
        for key, (label, kind) in STEPS.items()
        if key in trace.timings_ms and key in trace.stage_starts_ms
    ]


def _reading(trace: SearchTrace, index: SearchIndex, settings: Settings) -> dict[str, Any]:
    categories = {category.id: category.name for category in index.taxonomy.categories}
    facets = {
        facet.id: f"{family.name}: {facet.name}" for family in index.taxonomy.facet_families for facet in family.values
    }
    sizes = settings.sizes

    def ranked(probabilities: Mapping[str, float], names: Mapping[str, str], shown: int) -> list[dict[str, Any]]:
        best = sorted(probabilities.items(), key=lambda item: -item[1])[:shown]
        return [{"id": key, "name": names.get(key, key), "p": p} for key, p in best]

    return {
        "query_type": None if trace.query_type is None else trace.query_type.value,
        "query_type_confidence": trace.query_type_confidence,
        "states_limit": trace.limit_probability,
        "limit_threshold": sizes.limit_route_threshold,
        "filters": trace.parsed_filters.model_dump(exclude_none=True) or None,
        "interpretation": trace.interpretation,
        "interpretation_cached": trace.timings_ms.get("interpret") == 0,
        "categories": ranked(trace.category_probs, categories, CATEGORIES_SHOWN),
        "facets": ranked(trace.facet_probs, facets, FACETS_SHOWN),
        "category_floor": sizes.expansion_category_floor,
        "facet_floor": sizes.expansion_facet_floor,
    }


def _first_batch(trace: SearchTrace) -> list[ProductId]:
    """The first batch's products, in the order shown; later batches come after them."""
    later = {product_id for batch in trace.further for product_id in batch.shown}
    return [product_id for product_id in trace.shown if product_id not in later]


def _funnel(trace: SearchTrace, index: SearchIndex, settings: Settings) -> list[dict[str, Any]]:
    sizes = settings.sizes
    found = {hit.product_id for ranking in trace.arm_rankings.values() for hit in ranking}
    shown = _first_batch(trace)

    def stage(key: str, label: str, count: int, detail: str | None = None) -> dict[str, Any]:
        return {"key": key, "label": label, "count": count, "detail": detail}

    stages = [stage("catalogue", "Catalogue", len(index.products), "every product in the index")]
    if not trace.parsed_filters.is_empty:
        allowed = int(index.table.mask(trace.parsed_filters).sum())
        stages.append(stage("limits", "Within limits", allowed, "products inside the parsed price limits"))
    stages += [
        stage("found", "Found", len(found), f"distinct products in the arms' top {sizes.arm_k}"),
        stage("fused", "Fused", len(trace.fused), f"top {sizes.fused_k} by reciprocal rank fusion"),
        stage("gated", "Gated", len(trace.gate), f"{len(trace.expansion) or 'none'} from the tag expansion"),
        stage("shown", "Shown", len(shown), f"gate ≥ {sizes.gate_line}, or shown early"),
        stage("dropped", "Not shown", len(trace.gate) - len(shown), f"gate < {sizes.gate_line}"),
    ]
    return stages


def _gate(trace: SearchTrace, settings: Settings) -> dict[str, Any]:
    sizes = settings.sizes
    return {
        "values": [round(p, 3) for p in trace.gate.values()],
        "line": sizes.gate_line,
        "first_line": sizes.first_line,
        "early": len(trace.first_results),
    }


def _rows(trace: SearchTrace) -> list[dict[str, Any]]:
    """One row per product the first batch judged, in the order the gate read them: where each ranking put it, its
    fused score, and how it was decided."""
    position = {product_id: place for place, product_id in enumerate(_first_batch(trace), start=1)}
    fused = {hit.product_id: (rank, hit.score) for rank, hit in enumerate(trace.fused, start=1)}
    expanded = {hit.product_id for hit in trace.expansion}
    ranks: dict[ProductId, dict[str, int]] = {}
    for arm, ranking in trace.arm_rankings.items():
        for rank, hit in enumerate(ranking, start=1):
            ranks.setdefault(hit.product_id, {})[arm.value] = rank
    early = set(trace.first_results)
    return [
        {
            "id": product_id,
            "shown": position.get(product_id),
            "fused": fused[product_id][0] if product_id in fused else None,
            "rrf": round(fused[product_id][1], 5) if product_id in fused else None,
            "arms": ranks.get(product_id, {}),
            "expansion": product_id in expanded,
            "early": product_id in early,
            "gate": round(trace.gate[product_id], 3),
        }
        for product_id in trace.gate
    ]
