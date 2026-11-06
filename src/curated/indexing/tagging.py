"""Jev tags every product with a category distribution and facet probabilities from the taxonomy."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from curated.cache import cache_key
from curated.domain import ProductId
from curated.jobs import gather_stopping
from curated.providers.jev import JevClient
from curated.runlog import Run
from curated.settings import Settings
from curated.taxonomy import Taxonomy, product_category_question, product_facet_questions

CATEGORY_KEY = "category"
CONCURRENCY = 6
"""TypeSafe answers 429 above about six calls at once."""


@dataclass(frozen=True)
class ProductTags:
    """Row i belongs to ids[i]; columns follow the taxonomy's category and facet order."""

    ids: tuple[ProductId, ...]
    category_probs: NDArray[np.float64]
    facet_probs: NDArray[np.float64]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "category_probs.npy", self.category_probs)
        np.save(directory / "facet_probs.npy", self.facet_probs)
        (directory / "tag_ids.json").write_text(json.dumps(list(self.ids)), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> ProductTags:
        return cls(
            ids=tuple(json.loads((directory / "tag_ids.json").read_text(encoding="utf-8"))),
            category_probs=np.load(directory / "category_probs.npy"),
            facet_probs=np.load(directory / "facet_probs.npy"),
        )


def taxonomy_fingerprint(taxonomy: Taxonomy) -> str:
    return cache_key("taxonomy", taxonomy.model_dump(mode="json"))


async def tag_products(
    cards: Mapping[ProductId, str],
    taxonomy: Taxonomy,
    *,
    settings: Settings,
    jev: JevClient,
    max_cost: float,
) -> ProductTags:
    """Tags the products not tagged before, saving each answer as it arrives, and returns every product's tags. A
    new taxonomy starts a new run; a rerun under the same one continues where this stopped."""
    if CATEGORY_KEY in {facet.id for facet in taxonomy.facets}:
        raise ValueError(f"facet id {CATEGORY_KEY!r} collides with the category question")
    questions = {CATEGORY_KEY: product_category_question(taxonomy), **product_facet_questions(taxonomy)}
    fingerprint = taxonomy_fingerprint(taxonomy)
    run_dir = settings.runs_dir / f"tagging-{fingerprint[:12]}"
    slots = asyncio.Semaphore(CONCURRENCY)
    with Run(str(run_dir), config={"taxonomy": fingerprint}, max_cost=max_cost) as run:

        async def tag(product_id: ProductId) -> None:
            async with slots:
                try:
                    response = await jev.ask(cards[product_id], questions, purpose="tag product")
                except Exception as error:
                    run.fail(product_id, error)
                    return
                run.save(
                    product_id,
                    {
                        "categories": response.choices[CATEGORY_KEY].probabilities,
                        "facets": {facet_id: answer.noul for facet_id, answer in response.nouls.items()},
                    },
                    cost=jev.cost_of(response),
                )

        await gather_stopping(tag(product_id) for product_id in run.todo(list(cards), id_of=lambda i: i))
    return _tags_from_run(run_dir / "results.jsonl", cards, taxonomy)


def _tags_from_run(results: Path, cards: Mapping[ProductId, str], taxonomy: Taxonomy) -> ProductTags:
    with results.open(encoding="utf-8") as lines:
        answers = {saved["id"]: saved for line in lines if line.strip() for saved in [json.loads(line)]}
    missing = sorted(set(cards) - set(answers))
    if missing:
        raise RuntimeError(f"{len(missing)} products have no tags, such as {missing[:3]}; run `curated index` again")
    ids = tuple(cards)
    category_ids = [category.id for category in taxonomy.categories]
    facet_ids = [facet.id for facet in taxonomy.facets]
    return ProductTags(
        ids=ids,
        category_probs=np.array(
            [[answers[i]["categories"][category] for category in category_ids] for i in ids], dtype=np.float64
        ),
        facet_probs=np.array([[answers[i]["facets"][facet] for facet in facet_ids] for i in ids], dtype=np.float64),
    )
