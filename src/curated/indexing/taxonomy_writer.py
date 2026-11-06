"""A model writes the taxonomy from what the readings found: the categories and facets Jev tags products with and
reads searches into. Nobody edits it by hand, so a new catalogue gets its own."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

import yaml

from curated.domain import Product, ProductId, Reading
from curated.providers.protocols import JsonCompleter
from curated.settings import Settings
from curated.taxonomy import Category, FacetFamily, FacetValue, Taxonomy

REASONING_EFFORT = "medium"
OBJECT_TYPES_SHOWN = 250
VALUES_SHOWN = 80

_DEFINED = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "definition": {"type": "string"}},
    "required": ["name", "definition"],
    "additionalProperties": False,
}
TAXONOMY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "categories": {"type": "array", "items": _DEFINED},
        "facet_families": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "values": {"type": "array", "items": _DEFINED}},
                "required": ["name", "values"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["categories", "facet_families"],
    "additionalProperties": False,
}

PROMPT = """\
You design the taxonomy of a search engine over Curated Supply, a directory of {count} well-designed products. A \
decision model will use it two ways. It picks exactly one category for each product and answers one yes-or-no \
question per facet value, from the product's text. It also reads each buyer's search into the same categories and \
facet values, and the search then matches products by those answers. Below is what an earlier pass read from every \
product, with how many products carry each value.

Write:
- categories: 25 to 40 kinds of product, mutually exclusive, which together cover every product below. A category is \
what the product is ("Headphones and earbuds"), never who it is for or what it feels like. Size them so that none \
holds more than about a tenth of the products.
- facet_families: 4 to 6 families of attributes that cut across the categories, holding 80 to 120 values in all: \
materials, colors and finishes, and styles or aesthetics at least, plus any other family that buyers would search \
by, such as use, setting or feature. Each value should hold at least about ten products and should be something a \
buyer would actually type.

Every category and value has a name and a definition. Write each definition so that a reader who sees only that \
definition can decide a borderline product: one sentence on what it covers, and when a neighbouring value is easily \
confused with it, where the line between them runs. Use the plain names buyers use, and merge near-duplicates in \
the lists below.

The site's own categories: {categories}
The editor's lists: {lists}

Object types, with counts:
{object_types}

Materials, with counts:
{materials}

Colors, with counts:
{colors}

Aesthetics, with counts:
{aesthetics}

Moods, with counts:
{moods}

Settings, with counts:
{settings}
"""


def _counted(values: Iterable[str], shown: int) -> str:
    counts = Counter(value.strip().lower() for value in values)
    return ", ".join(f"{value} ({count})" for value, count in counts.most_common(shown))


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def taxonomy_prompt(products: Mapping[ProductId, Product], readings: Mapping[ProductId, Reading]) -> str:
    read = list(readings.values())
    return PROMPT.format(
        count=len(products),
        categories=", ".join(sorted({product.category for product in products.values()})),
        lists=", ".join(sorted({name for product in products.values() for name in product.lists})),
        object_types=_counted((reading.object_type for reading in read), OBJECT_TYPES_SHOWN),
        materials=_counted((value for reading in read for value in reading.materials), VALUES_SHOWN),
        colors=_counted((value for reading in read for value in reading.colors), VALUES_SHOWN),
        aesthetics=_counted((value for reading in read for value in reading.aesthetics), VALUES_SHOWN),
        moods=_counted((value for reading in read for value in reading.moods), VALUES_SHOWN),
        settings=_counted((value for reading in read for value in reading.settings), VALUES_SHOWN),
    )


def taxonomy_from_answer(answer: Mapping[str, Any]) -> Taxonomy:
    """The model's answer with ids derived from its names; raises when two names share an id."""
    families = []
    for family in answer["facet_families"]:
        family_id = _slug(family["name"])
        values = tuple(
            FacetValue(id=f"{family_id}.{_slug(value['name'])}", name=value["name"], definition=value["definition"])
            for value in family["values"]
        )
        families.append(FacetFamily(id=family_id, name=family["name"], values=values))
    categories = tuple(
        Category(id=f"category.{_slug(category['name'])}", name=category["name"], definition=category["definition"])
        for category in answer["categories"]
    )
    return Taxonomy(categories=categories, facet_families=tuple(families))


async def write_taxonomy(
    products: Mapping[ProductId, Product],
    readings: Mapping[ProductId, Reading],
    *,
    settings: Settings,
    client: JsonCompleter,
) -> Taxonomy:
    answer = await client.complete_json(
        model=settings.models.taxonomy,
        messages=[{"role": "user", "content": taxonomy_prompt(products, readings)}],
        schema_name="taxonomy",
        schema=TAXONOMY_SCHEMA,
        purpose="write taxonomy",
        reasoning_effort=REASONING_EFFORT,
    )
    taxonomy = taxonomy_from_answer(answer)
    settings.taxonomy_path.parent.mkdir(parents=True, exist_ok=True)
    settings.taxonomy_path.write_text(
        yaml.safe_dump(taxonomy.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=110),
        encoding="utf-8",
    )
    return taxonomy
