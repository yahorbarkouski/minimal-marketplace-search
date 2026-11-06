"""Types shared by the catalogue, indexing and search."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

ProductId = str
"""A product's slug on curated.supply, such as `sofort-2`."""


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Spec(Frozen):
    """One row of a product's specification table, such as `Lens: 22mm f/9.5`."""

    name: str
    value: str


class Product(Frozen):
    """One product as curated.supply describes it."""

    product_id: ProductId
    url: str
    name: str
    brand: str
    brand_slug: str
    category: str
    category_slug: str
    lists: tuple[str, ...]
    """The names of the site's editorial lists that hold it, such as `Black Only`."""
    articles: tuple[str, ...]
    """The titles of the site's blog posts that write about it."""
    price: float | None
    """In USD, as the site lists it; None when the site lists no price."""
    staff_pick: bool
    rank: int
    """The site's own ordering of its products, lowest first."""
    added: str
    """When the site added it, as an ISO date."""
    about: str
    """The site's editorial text, paragraphs separated by blank lines."""
    designed_in: str | None
    specs: tuple[Spec, ...]
    alternatives: tuple[ProductId, ...]
    photo_url: str


class Reading(Frozen):
    """What the indexing model reads from a product's page and photo: a catalogue record, and how the product
    looks and feels to a stylist, so that searches by taste, mood or reference can meet it in the same vocabulary."""

    product_id: ProductId
    object_type: str
    materials: tuple[str, ...]
    colors: tuple[str, ...]
    visual_description: str
    """Shape, colors, finish and mood as the photo shows them."""
    buyer_queries: tuple[str, ...]
    """Searches a buyer might type to find this product."""
    vibe: str
    """One or two sentences on what the product looks like and the feeling it gives."""
    aesthetics: tuple[str, ...]
    """Named styles, design movements or present-day aesthetics, most specific first."""
    moods: tuple[str, ...]
    settings: tuple[str, ...]
    """Rooms, places, occasions or ways of carrying or using it."""
    appeals_to: tuple[str, ...]
    """Kinds of person, by taste or way of life, who would want it."""
    references: tuple[str, ...]
    """People, characters, films, shows, designers or places whose world it fits; often empty."""


class KeywordFields(Frozen):
    """The text fields keyword search weighs separately."""

    title: str
    names: str
    attributes: str
    description: str
    queries: str


class QueryType(StrEnum):
    NAME = "name"
    ATTRIBUTES = "attributes"
    CONSTRAINTS = "constraints"
    APPEARANCE = "appearance"
    MOOD = "mood"
    CROSS_CATEGORY = "cross_category"
    REFERENCE = "reference"
    """A search by a person, character, film, show, place or aesthetic, such as "Patrick Bateman's apartment"."""


class Filters(Frozen):
    """The price limits a query states, inclusive and optional, in USD."""

    price_min: float | None = None
    price_max: float | None = None

    @property
    def is_empty(self) -> bool:
        return self.price_min is None and self.price_max is None


class ArmName(StrEnum):
    """One ranking that fusion combines: an index searched with the buyer's words or with the search's
    interpretation (the `_interpretation` arms)."""

    KEYWORD = "keyword"
    TEXT = "text"
    PHOTO = "photo"
    FACETS = "facets"
    STYLE = "style"
    TEXT_INTERPRETATION = "text_interpretation"
    PHOTO_INTERPRETATION = "photo_interpretation"
    STYLE_INTERPRETATION = "style_interpretation"


class Hit(Frozen):
    product_id: ProductId
    score: float


Ranking = tuple[Hit, ...]


class FurtherBatch(Frozen):
    """A batch of products a search judged past its first: the best-fused products not judged before, in fused
    order, with the gate's probability for each, and those that reached the page, best first."""

    judged: tuple[ProductId, ...]
    gate: dict[ProductId, float]
    shown: tuple[ProductId, ...] = ()


class SearchTrace(Frozen):
    """Everything one search produced, which the query debug panel draws."""

    text: str
    arm_rankings: dict[ArmName, Ranking]
    fused: Ranking
    gate: dict[ProductId, float]
    parsed_filters: Filters
    shown: tuple[ProductId, ...]
    """The page: the products shown early, then the rest best first, then each further batch's."""
    timings_ms: dict[str, float]
    """How long each stage took, and the moments `first_results`, `first_product` and `total`, in ms."""
    stage_starts_ms: dict[str, float] = {}
    """When each stage in `timings_ms` began, in ms from the search's start."""
    query_type: QueryType | None = None
    """Jev's reading of the query type; kept for diagnosis, nothing routes on it."""
    query_type_confidence: float | None = None
    category_probs: dict[str, float] = {}
    """Jev's probability that the search asks for each taxonomy category, from 0.01 up; the facets arm and
    the tag expansion read them."""
    facet_probs: dict[str, float] = {}
    """Likewise for each facet value."""
    limit_probability: float | None = None
    """Jev's probability that the query states a price limit."""
    expansion: Ranking = ()
    """Products the tag-defined expansion added beyond the fused list, gated with it."""
    interpretation: str | None = None
    """What the search refers to, as the interpretation model read it; None when it failed or timed out."""
    first_results: tuple[ProductId, ...] = ()
    """The products shown before the search finished, best first."""
    further: tuple[FurtherBatch, ...] = ()
    """The batches judged past the first, in order; `gate` holds the first batch only."""
