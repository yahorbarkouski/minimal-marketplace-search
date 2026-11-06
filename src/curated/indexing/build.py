"""Builds every search artifact from the catalogue, the readings and the taxonomy. Vectors are cached per item and
tags are saved per product, so a rerun pays only for what changed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from curated.cache import JsonCache
from curated.catalog import load_products
from curated.domain import KeywordFields, ProductId
from curated.indexing.card import keyword_fields, render_card, render_gate_card, render_style_card
from curated.indexing.embeddings import EmbeddingMatrix, document_text, embed_documents, embed_photo_sets
from curated.indexing.photos import write_gate_photos
from curated.indexing.reading import load_readings
from curated.indexing.tagging import tag_products
from curated.providers.jev import JevClient
from curated.providers.openrouter import OpenRouterClient
from curated.scrape import photo_path
from curated.settings import Settings
from curated.taxonomy import Taxonomy

CARDS = "cards.json"
GATE_CARDS = "gate_cards.json"
KEYWORD_FIELDS = "keyword_fields.json"
TEXT_VECTORS = "text"
PHOTO_VECTORS = "photo"
STYLE_VECTORS = "style"


async def build_index(
    settings: Settings, *, openrouter: OpenRouterClient, jev: JevClient, cache: JsonCache, max_cost: float
) -> None:
    products = load_products(settings)
    readings = load_readings(settings)
    missing = sorted(set(products) - set(readings))
    if missing:
        raise RuntimeError(f"{len(missing)} products have no reading, such as {missing[:3]}; run `curated read`")
    taxonomy = Taxonomy.load(settings.taxonomy_path)
    directory = settings.index_dir

    cards = {i: render_card(product, readings[i]) for i, product in products.items()}
    gate_cards = {i: render_gate_card(product, readings[i]) for i, product in products.items()}
    style_cards = {i: render_style_card(readings[i]) for i in products}
    _write_json(directory / CARDS, cards)
    _write_json(directory / GATE_CARDS, gate_cards)
    _write_json(
        directory / KEYWORD_FIELDS,
        {i: keyword_fields(product, readings[i]).model_dump() for i, product in products.items()},
    )

    model, dimensions = settings.models.embedding, settings.models.embedding_dimensions
    for name, texts in ((TEXT_VECTORS, cards), (STYLE_VECTORS, style_cards)):
        documents = {i: document_text(products[i].name, card) for i, card in texts.items()}
        matrix = await embed_documents(documents, client=openrouter, cache=cache, model=model, dimensions=dimensions)
        matrix.save(directory, name)
    photos = {i: photo_path(settings.photos_dir, i) for i in products}
    write_gate_photos(photos, settings.gate_photos_dir)
    photo = await embed_photo_sets(photos, client=openrouter, cache=cache, model=model, dimensions=dimensions)
    photo.save(directory, PHOTO_VECTORS)
    print(f"embedded {len(cards)} cards two ways and {len(photo.ids)} photos", file=sys.stderr)

    tags = await tag_products(cards, taxonomy, settings=settings, jev=jev, max_cost=max_cost)
    tags.save(directory)
    print(f"tagged {len(tags.ids)} products", file=sys.stderr)


def load_cards(directory: Path, name: str = CARDS) -> dict[ProductId, str]:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def load_keyword_fields(directory: Path) -> dict[ProductId, KeywordFields]:
    raw = json.loads((directory / KEYWORD_FIELDS).read_text(encoding="utf-8"))
    return {product_id: KeywordFields.model_validate(fields) for product_id, fields in raw.items()}


def load_embeddings(directory: Path, name: str) -> EmbeddingMatrix:
    return EmbeddingMatrix.load(directory, name)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
