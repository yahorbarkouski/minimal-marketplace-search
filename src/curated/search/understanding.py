"""Query understanding: what Jev reads from the query, and the price limits an LLM parses.

Jev answers, in one call, the query's category and facet probabilities (which the facets arm and the tag
expansion match), its type (kept in the trace for diagnosis), and whether it states a price limit (which decides
whether the search waits for the LLM's parse).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from typesafe_sdk import Choice, Noul, Question

from curated.domain import Filters, QueryType
from curated.providers.jev import JevAsker
from curated.providers.protocols import JsonCompleter
from curated.settings import Models
from curated.taxonomy import Taxonomy, query_category_questions, query_facet_questions

STATES_LIMIT_KEY = "states_limit"
QUERY_TYPE_KEY = "query_type"
STATES_LIMIT_QUESTION = Noul(
    instructions=(
        "The buyer's search states a price limit: an amount of money the product must be under, over or within."
    )
)
QUERY_TYPE_QUESTION = Choice(
    instructions="Which kind of search did the buyer type?",
    criteria={
        QueryType.NAME.value: (
            "It asks for a specific brand, designer, author or model by its name, alone or with a plain product "
            'word (such as "leica camera" or "aeron"), and states no exclusion and no price limit.'
        ),
        QueryType.ATTRIBUTES.value: (
            "It names one specific kind of product and what it is made of or how it works, such as its material, "
            'construction or feature (such as "walnut desk shelf" or "mechanical keyboard with a knob"), and '
            "names no brand, states no exclusion and no limit."
        ),
        QueryType.CONSTRAINTS.value: (
            "It names a kind of product, its attributes or its brand and adds a limit the product must meet: "
            'an exclusion or a price (such as "espresso machine under $500", "slim wallet that is not leather").'
        ),
        QueryType.APPEARANCE.value: (
            "It describes how one kind of product looks, by its colors, shapes, patterns or finish "
            '(such as "matte black desk lamp" or "round transparent speaker").'
        ),
        QueryType.MOOD.value: (
            "It describes a feeling, a room or setting to furnish, an occasion or use, or the person the "
            "product is for, rather than one product, even when it also mentions materials or a price limit "
            '(such as "housewarming gift for a coffee lover", "calm bedroom" or "long-haul flight essentials").'
        ),
        QueryType.CROSS_CATEGORY.value: (
            "It asks for a material, finish, color or style wherever it appears, on any kind of product, without "
            'naming one specific kind of product, even when it adds a limit (such as "anything in titanium", '
            '"all things transparent" or "brutalist objects").'
        ),
        QueryType.REFERENCE.value: (
            "It names a person, a fictional character, a film, a show, a place or a present-day aesthetic whose "
            'taste the buyer wants, rather than a kind of product (such as "a Bond villain\'s desk", '
            '"Scandinavian summer house" or "dark academia").'
        ),
    },
)


@dataclass(frozen=True)
class QueryQuestions:
    """Every question Jev is asked about a query, built once per taxonomy."""

    questions: dict[str, Question]

    @classmethod
    def build(cls, taxonomy: Taxonomy) -> QueryQuestions:
        routing: dict[str, Question] = {
            STATES_LIMIT_KEY: STATES_LIMIT_QUESTION,
            QUERY_TYPE_KEY: QUERY_TYPE_QUESTION,
        }
        categories, facets = query_category_questions(taxonomy), query_facet_questions(taxonomy)
        collisions = sorted(routing.keys() & (categories.keys() | facets.keys()))
        if collisions:
            raise ValueError(f"taxonomy ids collide with routing questions: {collisions}")
        return cls(questions={**categories, **facets, **routing})


@dataclass(frozen=True)
class QueryUnderstanding:
    category_probs: NDArray[np.float64]
    facet_probs: NDArray[np.float64]
    query_type: QueryType
    query_type_confidence: float
    states_limit: float
    """Jev's probability that the search states a price limit, which only the parse reads."""


async def understand_query(
    text: str, taxonomy: Taxonomy, questions: QueryQuestions, *, jev: JevAsker
) -> QueryUnderstanding:
    response = await jev.ask({"buyer_search": text}, questions.questions, purpose="understand query")
    nouls = response.nouls
    query_type = response.choices[QUERY_TYPE_KEY]
    return QueryUnderstanding(
        category_probs=np.array([nouls[c.id].noul for c in taxonomy.categories], dtype=np.float64),
        facet_probs=np.array([nouls[f.id].noul for f in taxonomy.facets], dtype=np.float64),
        query_type=QueryType(query_type.choice),
        query_type_confidence=query_type.confidence,
        states_limit=nouls[STATES_LIMIT_KEY].noul,
    )


FILTER_PROMPT = """\
You read one search typed by a buyer on a directory of well-designed products and extract only its explicit \
price limits.

- price_min / price_max: amounts the buyer states as a limit ("under $500", "between 200 and 800", \
"at least $1k"). Plain numbers in USD. A number that is part of a product's name is not a limit.
- Anything not stated is null.

Search: {query}"""

FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "price_min": {"type": ["number", "null"]},
        "price_max": {"type": ["number", "null"]},
    },
    "required": ["price_min", "price_max"],
    "additionalProperties": False,
}


async def parse_filters(text: str, *, client: JsonCompleter, models: Models) -> Filters:
    answer = await client.complete_json(
        model=models.query_parse,
        provider=models.query_parse_provider,
        reasoning_effort="minimal",
        max_tokens=200,
        messages=[{"role": "user", "content": FILTER_PROMPT.format(query=text)}],
        schema_name="search_filters",
        schema=FILTER_SCHEMA,
        purpose="parse query filters",
    )
    return Filters.model_validate(answer)
