"""The search's parts on small inputs, each with what would go wrong for a buyer if it broke."""

import asyncio
import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from curated.cache import JsonCache
from curated.domain import ArmName, Filters, Hit, Product, Reading, Spec
from curated.indexing.card import keyword_fields, price_line, render_gate_card, shorten
from curated.indexing.embeddings import l2_normalize
from curated.indexing.photos import GATE_PHOTO_SHORT_SIDE, gate_photo, gate_photo_path, model_photo
from curated.indexing.reading import sample_per_category
from curated.indexing.tagging import ProductTags
from curated.ledger import BudgetExceededError, SpendLedger, spend_by_purpose
from curated.search.expansion import expand
from curated.search.fusion import reciprocal_rank_fusion
from curated.search.gate import gate_candidates
from curated.search.interpretation import InterpretationCache, interpret
from curated.search.product_table import ProductTable
from curated.search.understanding import parse_filters
from curated.settings import Models
from tests.stubs import StubJev


def ranking(*ids: str) -> tuple[Hit, ...]:
    return tuple(Hit(product_id=product_id, score=1.0) for product_id in ids)


def product(product_id: str = "lamp", *, category: str = "Home", price: float | None = 120.0) -> Product:
    return Product(
        product_id=product_id,
        url=f"https://example.com/{product_id}",
        name="Lamp",
        brand="Acme",
        brand_slug="acme",
        category=category,
        category_slug=category.lower(),
        lists=("Black Only",),
        articles=("Good lamps",),
        price=price,
        staff_pick=False,
        rank=1,
        added="2026-01-01",
        about="A lamp.",
        designed_in="Japan",
        specs=(Spec(name="Weight", value="100 g"),),
        alternatives=(),
        photo_url="https://example.com/lamp.webp",
    )


def reading() -> Reading:
    return Reading(
        product_id="lamp",
        object_type="lamp",
        materials=("Steel", "steel"),
        colors=("black",),
        visual_description="A black lamp.",
        buyer_queries=("desk lamp",),
        vibe="Quiet and exact.",
        aesthetics=("minimal",),
        moods=("calm",),
        settings=("desk",),
        appeals_to=("designers",),
        references=(),
    )


# Fusion


def test_fusion_ranks_a_product_two_arms_found_above_one_only_one_found() -> None:
    fused = reciprocal_rank_fusion(
        {ArmName.KEYWORD: ranking("both", "keyword-only"), ArmName.TEXT: ranking("text-only", "both")},
        rrf_k=60,
        top_k=3,
    )
    assert fused[0].product_id == "both"
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 62)


def test_fusion_keeps_top_k_and_breaks_ties_by_id() -> None:
    fused = reciprocal_rank_fusion({ArmName.KEYWORD: ranking("b"), ArmName.TEXT: ranking("a")}, rrf_k=60, top_k=1)
    assert [hit.product_id for hit in fused] == ["a"]


def test_fusion_leaves_out_an_arm_weighing_nothing_and_refuses_a_negative_weight() -> None:
    rankings = {ArmName.KEYWORD: ranking("a"), ArmName.TEXT: ranking("b")}
    fused = reciprocal_rank_fusion(rankings, rrf_k=60, top_k=5, weights={ArmName.TEXT: 0.0})
    assert [hit.product_id for hit in fused] == ["a"]
    with pytest.raises(ValueError, match="negative"):
        reciprocal_rank_fusion(rankings, rrf_k=60, top_k=5, weights={ArmName.TEXT: -1.0})


# Price limits


def test_price_limits_are_inclusive_and_never_exclude_an_unknown_price() -> None:
    table = ProductTable(
        {
            "cheap": product("cheap", price=50),
            "edge": product("edge", price=200),
            "costly": product("costly", price=900),
            "unknown": product("unknown", price=None),
        }
    )
    allowed = table.mask(Filters(price_max=200))
    kept = {product_id for product_id, keep in zip(table.ids, allowed.tolist(), strict=True) if keep}
    assert kept == {"cheap", "edge", "unknown"}
    allowed = table.mask(Filters(price_min=200))
    kept = {product_id for product_id, keep in zip(table.ids, allowed.tolist(), strict=True) if keep}
    assert kept == {"edge", "costly", "unknown"}


def test_a_product_table_refuses_an_unknown_product() -> None:
    with pytest.raises(ValueError, match="not in the product table"):
        ProductTable({"lamp": product()}).rows(["chair"])


# Tag expansion

TAGS = ProductTags(
    ids=("chair", "lamp", "sofa"),
    category_probs=np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.4]]),
    facet_probs=np.array([[0.9], [0.9], [0.2]]),
)


def expanded(categories: list[float], facets: list[float], **overrides: Any) -> list[str]:
    options: dict[str, Any] = {
        "allowed": None,
        "exclude": frozenset(),
        "category_floor": 0.5,
        "facet_floor": 0.7,
        "product_floor": 0.5,
        "cap": 10,
    } | overrides
    hits = expand(np.array(categories), np.array(facets), TAGS, **options)
    return [hit.product_id for hit in hits]


def test_expansion_is_empty_when_the_search_is_confident_about_nothing() -> None:
    assert expanded([0.1, 0.1], [0.1]) == []


def test_expansion_matches_confident_categories_best_first() -> None:
    assert expanded([0.9, 0.0], [0.0]) == ["chair", "sofa"]


def test_expansion_requires_every_confident_facet() -> None:
    assert expanded([0.9, 0.0], [0.9]) == ["chair"]


def test_expansion_drops_a_product_missing_one_of_two_confident_facets() -> None:
    tags = ProductTags(
        ids=("both", "one"), category_probs=np.array([[1.0], [1.0]]), facet_probs=np.array([[0.9, 0.9], [0.9, 0.1]])
    )
    hits = expand(
        np.array([0.0]),
        np.array([0.9, 0.9]),
        tags,
        allowed=None,
        exclude=frozenset(),
        category_floor=0.5,
        facet_floor=0.7,
        product_floor=0.5,
        cap=10,
    )
    assert [hit.product_id for hit in hits] == ["both"]


def test_expansion_honours_the_price_mask_the_exclusions_and_the_cap() -> None:
    assert expanded([0.9, 0.0], [0.0], allowed=np.array([False, True, True])) == ["sofa"]
    assert expanded([0.9, 0.0], [0.0], exclude=frozenset({"chair"})) == ["sofa"]
    assert expanded([0.9, 0.0], [0.0], cap=1) == ["chair"]


# The models' answers


class Answers:
    """A model that gives one fixed answer and remembers what it was asked."""

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def complete_json(self, **call: Any) -> dict[str, Any]:
        self.calls.append(call)
        return self.answer


async def test_the_price_parse_reads_limits_into_filters() -> None:
    filters = await parse_filters(
        "lamp under $150", client=Answers({"price_max": 150, "price_min": None}), models=Models()
    )
    assert filters == Filters(price_max=150)


async def test_an_interpretation_is_tidied_and_an_empty_one_is_an_error() -> None:
    answers = Answers({"interpretation": "  dark   wood\nand brass "})
    assert await interpret("study", client=answers, model="m", provider=None) == "dark wood and brass"
    assert "study" in answers.calls[0]["messages"][0]["content"]
    with pytest.raises(ValueError, match="nothing"):
        await interpret("study", client=Answers({"interpretation": " "}), model="m", provider=None)


def test_the_interpretation_cache_ignores_case_and_spacing_and_forgets_the_oldest() -> None:
    cache = InterpretationCache(capacity=2)
    cache.put("Calm  Bedroom", "first")
    assert cache.get("calm bedroom") == "first"
    cache.put("second", "2")
    cache.put("third", "3")
    assert cache.get("second") == "2"
    assert cache.get("calm bedroom") is None
    assert InterpretationCache(capacity=0).get("anything") is None


# The gate


async def test_the_gate_asks_a_few_products_per_call_and_sends_definitions_once(tmp_path: Path) -> None:
    calls: list[Any] = []

    class Recording(StubJev):
        async def ask(self, state, questions, *, purpose, assets=None):
            calls.append((state, questions, assets))
            return await super().ask(state, questions, purpose=purpose, assets=assets)

    ids = [f"p{i}" for i in range(7)]
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (300, 300), "white").save(photo)
    scores = await gate_candidates(
        "desk lamp",
        ids,
        dict.fromkeys(ids, "A desk lamp."),
        jev=Recording(),
        products_per_call=3,
        photos=lambda _: photo,
        interpretation="task lighting",
    )
    assert set(scores) == set(ids)
    assert [len(questions) for _, questions, _ in calls] == [3, 3, 1]
    for state, questions, assets in calls:
        assert state["buyer_search"] == "desk lamp"
        assert state["what_the_search_refers_to"] == "task lighting"
        assert "central point" in state["definitions"]
        assert set(assets) == {f"photo-{key}" for key in questions}
        assert all("definitions" not in str(question.instructions) for question in questions.values())


# Cards


def test_the_gate_card_carries_the_price_and_the_style_and_skips_what_is_empty() -> None:
    card = render_gate_card(product(), reading())
    assert "Price: $120" in card
    assert "Mood: calm" in card
    assert "Evokes" not in card


def test_a_product_with_no_price_shows_none_on_its_card() -> None:
    assert price_line(product(price=None)) is None
    assert "Price" not in render_gate_card(product(price=None), reading())


def test_keyword_fields_keep_one_spelling_of_each_attribute() -> None:
    fields = keyword_fields(product(), reading())
    assert fields.attributes.casefold().count("steel") == 1
    assert fields.queries == "desk lamp"


def test_shorten_cuts_on_a_word_boundary() -> None:
    assert shorten("short", 10) == "short"
    assert shorten("one two three", 8) == "one two…"


# Indexing


def test_a_sample_takes_the_same_number_from_every_category() -> None:
    products = [product(f"home-{i}", category="Home") for i in range(3)] + [product("carry-0", category="Carry")]
    sample = sample_per_category(products, 2)
    categories = [item.category for item in sample]
    assert categories.count("Home") == 2
    assert categories.count("Carry") == 1


def test_vectors_are_normalized_to_unit_length() -> None:
    vectors = l2_normalize(np.array([[3.0, 4.0]], dtype=np.float32))
    assert np.linalg.norm(vectors[0]) == pytest.approx(1.0)


def test_a_transparent_photo_lands_on_white_at_the_size_jev_accepts(tmp_path: Path) -> None:
    source = tmp_path / "photo.webp"
    Image.new("RGBA", (1000, 600), (0, 0, 0, 0)).save(source)
    with Image.open(io.BytesIO(model_photo(source))) as image:
        assert image.width == 512
        assert min(image.convert("RGB").getpixel((5, 5))) > 250  # type: ignore[arg-type]
    with Image.open(io.BytesIO(gate_photo(source))) as image:
        assert min(image.size) == GATE_PHOTO_SHORT_SIDE


def test_a_gate_photo_name_is_safe_for_any_slug(tmp_path: Path) -> None:
    assert gate_photo_path(tmp_path, "a/b").parent == tmp_path


def test_tags_survive_saving_and_loading(tmp_path: Path) -> None:
    TAGS.save(tmp_path)
    loaded = ProductTags.load(tmp_path)
    assert loaded.ids == TAGS.ids
    assert np.array_equal(loaded.facet_probs, TAGS.facet_probs)


# Money


def test_the_ledger_refuses_new_calls_at_the_budget_and_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = SpendLedger.open(path, cap_usd=1.0)
    ledger.ensure_room()
    ledger.record(provider="p", model="m", purpose="gate", cost_usd=0.6)
    ledger.record(provider="p", model="m", purpose="read", cost_usd=0.4)
    with pytest.raises(BudgetExceededError):
        ledger.ensure_room()
    reopened = SpendLedger.open(path, cap_usd=1.0)
    assert reopened.total_usd == pytest.approx(1.0)
    assert spend_by_purpose(path) == pytest.approx({"gate": 0.6, "read": 0.4})


async def test_the_cache_pays_for_an_answer_once(tmp_path: Path) -> None:
    calls = 0

    async def compute() -> dict[str, int]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"value": 1}

    cache = JsonCache(tmp_path)
    assert await cache.get_or_compute("n", {"text": "a"}, compute) == {"value": 1}
    assert await cache.get_or_compute("n", {"text": "a"}, compute) == {"value": 1}
    assert calls == 1
    await cache.get_or_compute("n", {"text": "b"}, compute)
    assert calls == 2
