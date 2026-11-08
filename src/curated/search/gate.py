"""The relevance gate: Jev reads each fused candidate and answers whether it is a convincing answer to the search.

Jev reads each product's gate card, its catalogue card followed by its style description, and its photo, and, when
the search has one, the search's interpretation beside the buyer's words. Its probability alone decides what reaches
the page and in what order. A call that fails costs only its own products, which count as not matching: TypeSafe has
answered 7 to 18% of image calls with 503 on bad days, and one of them should not cost the whole page.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from typesafe_sdk import Asset, Image, JSONContent, Noul, TypeSafeError

from curated.domain import ProductId
from curated.ledger import BudgetExceededError
from curated.providers.jev import JevAsker
from curated.providers.openrouter import OpenRouterError
from curated.providers.protocols import Decider

GATE_STATEMENT = "Product {key} is a convincing answer to buyer_search."
PHOTO_LABEL = "Photo of {key}:"
GATE_DEFINITIONS = {
    "central point": (
        "what defines the purchase: the kind of product, and whichever of these the search names: brand or model, "
        "material, colour, finish, feature, budget, exclusions. For a taste, mood, room or reference search, that "
        "specific look, mood or world."
    ),
    "limit": (
        "a budget or an exclusion. Compare a stated budget with the card's Price, inclusive. A product meets an "
        "exclusion unless its card or photo shows the excluded thing."
    ),
    "specific fit": (
        "something about this product's own form, palette, texture or use that belongs to the searched mood, room, "
        "occasion, person or world, and would set it apart from well-made products in general."
    ),
    "Aesthetics, Mood, Suits, Appeals to, Evokes, Look": (
        "automatic labels that lean generous. They never establish a fit on their own."
    ),
    "what_the_search_refers_to": (
        "a fast model's broad reading of the search. Being named in it does not make a product a match; the buyer's "
        "own words decide."
    ),
}
"""Sent once per call. Sending them with every question costs 21% more tokens and moves no more answers across the
line than asking the same question again."""
GATE_TRUE = (
    "A person who typed buyer_search would single this product out as a convincing answer. Everything the search "
    "names is shown by the card or photo. For a taste, mood, room or reference search, the product has a specific fit."
)
GATE_FALSE = (
    "The fit is generic or tenuous: the product is well designed, premium, minimal or useful, and could suit almost "
    "any tasteful home, desk or person. Or it could merely be used there or carried along without belonging to what "
    "was asked. Or it is a different kind of product from the one named, or breaks a limit. A famous brand, a style "
    "label, a shared material or the absence of a contradiction is not enough."
)


async def gate_candidates(
    text: str,
    product_ids: Sequence[ProductId],
    cards: Mapping[ProductId, str],
    *,
    jev: JevAsker,
    products_per_call: int,
    photos: Callable[[ProductId], Path],
    interpretation: str | None = None,
    fallback: Decider | None = None,
) -> dict[ProductId, float]:
    """Returns each product's probability of satisfying the search. Calls run in parallel, a few products each.
    A call that fails goes to `fallback` when there is one."""
    chunks = [product_ids[start : start + products_per_call] for start in range(0, len(product_ids), products_per_call)]
    answers = await asyncio.gather(
        *(
            _gate_chunk(text, interpretation, chunk, cards, jev=jev, photos=photos, fallback=fallback)
            for chunk in chunks
        )
    )
    return {product_id: probability for answer in answers for product_id, probability in answer.items()}


async def _gate_chunk(
    text: str,
    interpretation: str | None,
    product_ids: Sequence[ProductId],
    cards: Mapping[ProductId, str],
    *,
    jev: JevAsker,
    photos: Callable[[ProductId], Path],
    fallback: Decider | None = None,
) -> dict[ProductId, float]:
    keys = {f"P{position}": product_id for position, product_id in enumerate(product_ids, start=1)}
    state: dict[str, JSONContent] = {"buyer_search": text}
    if interpretation is not None:
        state["what_the_search_refers_to"] = interpretation
    state["definitions"] = GATE_DEFINITIONS
    state["products"] = {key: {"card": cards[product_id], "photo": f"photo-{key}"} for key, product_id in keys.items()}
    assets: dict[str, Asset] = {f"photo-{key}": Image(photos(product_id)) for key, product_id in keys.items()}
    questions = {
        key: Noul(instructions=GATE_STATEMENT.format(key=key), criteria={"true": GATE_TRUE, "false": GATE_FALSE})
        for key in keys
    }
    try:
        response = await jev.ask(state, questions, purpose="gate candidates", assets=assets)
    except TypeSafeError as error:
        print(f"[search] gate call failed for {len(keys)} products: {error!r}", file=sys.stderr)
        if fallback is None:
            return dict.fromkeys(product_ids, 0.0)
        return await _ask_fallback(fallback, state, questions, keys=keys, cards=cards, photos=photos)
    return {product_id: response.nouls[key].noul for key, product_id in keys.items()}


async def _ask_fallback(
    fallback: Decider,
    state: dict[str, JSONContent],
    questions: Mapping[str, Noul],
    *,
    keys: Mapping[str, ProductId],
    cards: Mapping[ProductId, str],
    photos: Callable[[ProductId], Path],
) -> dict[ProductId, float]:
    """Asks the fallback decision model the same questions. It reads images only as top-level items of a list, so the
    state comes first and each photo follows the label its product's card points to."""
    products = {
        key: {"card": cards[product_id], "photo": f"the image after {PHOTO_LABEL.format(key=key)!r}"}
        for key, product_id in keys.items()
    }
    listed: list[JSONContent] = [{**state, "products": products}]
    for key, product_id in keys.items():
        listed += [PHOTO_LABEL.format(key=key), _image_part(photos(product_id))]
    asked = {
        key: {"type": "noul", "instructions": question.instructions, "criteria": question.criteria}
        for key, question in questions.items()
    }
    try:
        answers = await fallback.decide(listed, asked, purpose="gate candidates (fallback)")
    except (OpenRouterError, BudgetExceededError, OSError) as error:
        print(f"[search] fallback gate call failed for {len(keys)} products: {error!r}", file=sys.stderr)
        return dict.fromkeys(keys.values(), 0.0)
    return {product_id: answers[key] for key, product_id in keys.items()}


def _image_part(path: Path) -> dict[str, JSONContent]:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
