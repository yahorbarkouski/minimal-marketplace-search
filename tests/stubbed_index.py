"""Builds an index over the real catalogue and photos with stubbed readings, vectors and tags. It costs nothing and
exists only to exercise the query path and the site without model keys; its results mean nothing about quality."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import uvicorn
import yaml

from curated.catalog import load_products
from curated.domain import Product, Reading
from curated.indexing.build import (
    CARDS,
    GATE_CARDS,
    KEYWORD_FIELDS,
    PHOTO_VECTORS,
    STYLE_VECTORS,
    TEXT_VECTORS,
)
from curated.indexing.card import keyword_fields, render_card, render_gate_card, render_style_card
from curated.indexing.embeddings import EmbeddingMatrix, document_text
from curated.indexing.reading import load_readings
from curated.indexing.tagging import ProductTags
from curated.search.searcher import Searcher, SearchIndex
from curated.server import Demo, create_app
from curated.settings import Settings
from tests.stubs import StubJev, StubModels, embed_words

FACETS = {"Black": "black", "White": "white", "Leather": "leather", "Steel": "steel", "Wood": "wood"}


def stub_reading(product: Product) -> Reading:
    first_sentence = product.about.split(". ")[0]
    return Reading(
        product_id=product.product_id,
        object_type=product.category.lower(),
        materials=(),
        colors=(),
        visual_description=first_sentence,
        buyer_queries=(),
        vibe=first_sentence,
        aesthetics=tuple(product.lists[:3]),
        moods=(),
        settings=(),
        appeals_to=(),
        references=(),
    )


def build_stubbed_root(source: Settings, root: Path) -> Settings:
    """Links the catalogue and photos of `source` under `root` and writes a stubbed index beside them."""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name, target in (("products.jsonl", source.products_path), ("photos", source.photos_dir)):
        if not (data / name).exists():
            (data / name).symlink_to(target)
    settings = Settings(root=root)
    products = load_products(settings)
    readings = {i: stub_reading(product) for i, product in products.items()}
    with settings.readings_path.open("w", encoding="utf-8") as out:
        for reading in readings.values():
            out.write(reading.model_dump_json() + "\n")

    categories = sorted({product.category for product in products.values()})
    taxonomy = {
        "categories": [
            {"id": f"category.{c.lower()}", "name": c, "definition": f"Products in {c}."} for c in categories
        ],
        "facet_families": [
            {
                "id": "attribute",
                "name": "Attribute",
                "values": [{"id": f"attribute.{v}", "name": n, "definition": n} for n, v in FACETS.items()],
            }
        ],
    }
    settings.taxonomy_path.parent.mkdir(parents=True, exist_ok=True)
    settings.taxonomy_path.write_text(yaml.safe_dump(taxonomy), encoding="utf-8")

    directory = settings.index_dir
    directory.mkdir(parents=True, exist_ok=True)
    cards = {i: render_card(product, readings[i]) for i, product in products.items()}
    (directory / CARDS).write_text(json.dumps(cards), encoding="utf-8")
    gate_cards = {i: render_gate_card(product, readings[i]) for i, product in products.items()}
    (directory / GATE_CARDS).write_text(json.dumps(gate_cards), encoding="utf-8")
    fields = {i: keyword_fields(product, readings[i]).model_dump() for i, product in products.items()}
    (directory / KEYWORD_FIELDS).write_text(json.dumps(fields), encoding="utf-8")

    ids = tuple(products)
    texts = {
        TEXT_VECTORS: [document_text(products[i].name, cards[i]) for i in ids],
        STYLE_VECTORS: [render_style_card(readings[i]) for i in ids],
        PHOTO_VECTORS: [products[i].name for i in ids],
    }
    for name, documents in texts.items():
        EmbeddingMatrix(ids=ids, vectors=np.stack([embed_words(text) for text in documents])).save(directory, name)
    category_probs = np.array([[float(p.category == c) for c in categories] for p in products.values()])
    facet_probs = np.array(
        [[float(value in card.lower()) for value in FACETS.values()] for card in (cards[i] for i in ids)]
    )
    ProductTags(ids=ids, category_probs=category_probs, facet_probs=facet_probs).save(directory)
    return settings


def stubbed_demo(settings: Settings, *, jev_delay_s: float = 0.0, model_delay_s: float = 0.0):
    @asynccontextmanager
    async def open_demo() -> AsyncIterator[Demo]:
        searcher = Searcher(
            SearchIndex.load(settings),
            settings=settings,
            openrouter=StubModels(delay_s=model_delay_s),
            jev=StubJev(delay_s=jev_delay_s),
        )
        yield Demo(searcher=searcher, settings=settings, readings=load_readings(settings))

    return open_demo


def main() -> None:
    """Serves the stubbed index, with delays like the real models', at the port the site expects."""
    settings = build_stubbed_root(Settings(), Path(os.environ["CURATED_STUB_ROOT"]))
    app = create_app(stubbed_demo(settings, jev_delay_s=0.3, model_delay_s=0.9))
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("CURATED_STUB_PORT", "8790")))


if __name__ == "__main__":
    main()
