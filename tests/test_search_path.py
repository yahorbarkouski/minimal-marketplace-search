"""The query path and the server on the real catalogue's shape, with stand-ins for Jev and the model provider."""

import json
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from typesafe_sdk import TypeSafeError

from curated.catalog import about_text, article_titles, json_ld, parse_product, react_payload, site_dataset, spec_rows
from curated.cli import _settings
from curated.domain import Product, Spec
from curated.scrape import page_path, photo_path, sitemap_urls
from curated.search.searcher import Searcher, SearchIndex
from curated.server import create_app
from curated.settings import Settings
from tests.stubbed_index import build_stubbed_root, stubbed_demo
from tests.stubs import StubJev, StubModels


def product(
    product_id: str, name: str, category: str, price: float | None, about: str, *, lists: tuple[str, ...] = ()
) -> Product:
    return Product(
        product_id=product_id,
        url=f"https://www.curated.supply/products/{product_id}",
        name=name,
        brand="Acme",
        brand_slug="acme",
        category=category,
        category_slug=category.lower(),
        lists=lists,
        articles=(),
        price=price,
        staff_pick=False,
        rank=1,
        added="2026-01-01",
        about=about,
        designed_in="Japan",
        specs=(Spec(name="Weight", value="100 g"),),
        alternatives=(),
        photo_url="https://assets.curated.supply/x.webp",
    )


PRODUCTS = (
    product("black-lamp", "Black desk lamp", "Workspace", 120, "A black desk lamp in steel.", lists=("Black Only",)),
    product("costly-lamp", "Marble desk lamp", "Workspace", 900, "A desk lamp in marble."),
    product("no-price-lamp", "Paper desk lamp", "Home", None, "A desk lamp in paper."),
    product("backpack", "Canvas backpack", "Carry", 200, "A canvas backpack for a laptop."),
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    source = Settings(root=tmp_path / "source")
    source.data_dir.mkdir(parents=True)
    source.photos_dir.mkdir()
    with source.products_path.open("w", encoding="utf-8") as out:
        for item in PRODUCTS:
            out.write(item.model_dump_json() + "\n")
    return build_stubbed_root(source, tmp_path / "stubbed")


def searcher(settings: Settings) -> Searcher:
    return Searcher(SearchIndex.load(settings), settings=settings, openrouter=StubModels(), jev=StubJev())


async def test_the_page_holds_what_the_gate_keeps_best_first(settings: Settings) -> None:
    trace, _ = await searcher(settings).begin("black desk lamp")
    assert trace.shown[0] == "black-lamp"
    assert "backpack" not in trace.shown
    assert [trace.gate[i] for i in trace.shown] == sorted((trace.gate[i] for i in trace.shown), reverse=True)
    assert trace.interpretation == "Things that fit black desk lamp."


async def test_a_price_limit_removes_only_products_over_it(settings: Settings) -> None:
    trace, _ = await searcher(settings).begin("desk lamp under $150")
    assert trace.parsed_filters.price_max == 150
    assert "costly-lamp" not in trace.shown
    assert {"black-lamp", "no-price-lamp"} <= set(trace.shown)


async def test_a_failed_gate_call_costs_only_its_own_products(settings: Settings) -> None:
    class FailsOnPaper(StubJev):
        async def ask(self, state, questions, *, purpose, assets=None):
            if "Paper" in str(state):
                raise TypeSafeError("503 Image processing is unavailable")
            return await super().ask(state, questions, purpose=purpose, assets=assets)

    searching = Searcher(
        SearchIndex.load(settings),
        settings=replace(settings, sizes=replace(settings.sizes, gate_products_per_call=1)),
        openrouter=StubModels(),
        jev=FailsOnPaper(),
    )
    trace, _ = await searching.begin("desk lamp")
    assert trace.gate["no-price-lamp"] == 0.0
    assert "black-lamp" in trace.shown
    assert "no-price-lamp" not in trace.shown


async def test_products_shown_early_stay_first_and_the_rest_follow_by_score(settings: Settings) -> None:
    early: list[tuple[str, ...]] = []
    slow = Searcher(SearchIndex.load(settings), settings=settings, openrouter=StubModels(delay_s=0.05), jev=StubJev())
    trace, _ = await slow.begin("black desk lamp", on_first_results=early.append)
    assert early == [trace.first_results]
    assert trace.first_results[0] == "black-lamp"
    assert trace.shown[: len(trace.first_results)] == trace.first_results
    rest = [trace.gate[i] for i in trace.shown[len(trace.first_results) :]]
    assert rest == sorted(rest, reverse=True)
    assert trace.timings_ms["first_product"] < trace.timings_ms["total"]


async def test_a_product_shown_early_stays_when_the_final_gate_fails(settings: Settings) -> None:
    class FailsOnceInterpreted(StubJev):
        async def ask(self, state, questions, *, purpose, assets=None):
            if isinstance(state, dict) and "what_the_search_refers_to" in state:
                raise TypeSafeError("503 Image processing is unavailable")
            return await super().ask(state, questions, purpose=purpose, assets=assets)

    slow = Searcher(
        SearchIndex.load(settings), settings=settings, openrouter=StubModels(delay_s=0.05), jev=FailsOnceInterpreted()
    )
    trace, _ = await slow.begin("black desk lamp", on_first_results=lambda _: None)
    assert trace.first_results
    assert trace.shown == trace.first_results


async def test_a_later_product_with_a_higher_score_stays_below_what_was_shown_early(settings: Settings) -> None:
    class ChangesItsMind(StubJev):
        async def ask(self, state, questions, *, purpose, assets=None):
            if isinstance(state, dict) and "what_the_search_refers_to" in state:
                state = {**state, "buyer_search": "canvas backpack"}
            return await super().ask(state, questions, purpose=purpose, assets=assets)

    slow = Searcher(
        SearchIndex.load(settings), settings=settings, openrouter=StubModels(delay_s=0.05), jev=ChangesItsMind()
    )
    trace, _ = await slow.begin("black desk lamp", on_first_results=lambda _: None)
    assert "black-lamp" in trace.first_results
    assert "backpack" not in trace.first_results
    assert trace.shown[0] == "black-lamp"
    assert trace.shown[-1] == "backpack"
    assert trace.gate["backpack"] > trace.gate["black-lamp"]


async def test_the_early_gate_reads_only_the_best_fused_products(settings: Settings) -> None:
    class Recording(StubJev):
        gated: ClassVar[list[int]] = []

        async def ask(self, state, questions, *, purpose, assets=None):
            if purpose == "gate candidates":
                self.gated.append(len(questions))
            return await super().ask(state, questions, purpose=purpose, assets=assets)

    limited = replace(settings, sizes=replace(settings.sizes, early_gate_k=2, gate_products_per_call=50))
    searching = Searcher(
        SearchIndex.load(limited), settings=limited, openrouter=StubModels(delay_s=0.05), jev=Recording()
    )
    await searching.begin("desk lamp", on_first_results=lambda _products: None)
    assert Recording.gated[0] == 2
    assert Recording.gated[1] > 2


def test_the_server_streams_a_search_and_describes_a_product(settings: Settings) -> None:
    with TestClient(create_app(stubbed_demo(settings))) as client:
        with client.stream("GET", "/api/search", params={"q": "black desk lamp"}) as response:
            body = "".join(response.iter_text())
        blocks = [block.split("\n") for block in body.strip().split("\n\n")]
        events = {kind.removeprefix("event: "): json.loads(data.removeprefix("data: ")) for kind, data in blocks}
        assert "error" not in events
        assert events["result"]["products"][0]["id"] == "black-lamp"
        assert events["result"]["products"][0]["brand"] == "Acme"

        detail = client.get("/api/products/black-lamp").json()
        assert detail["about"] == "A black desk lamp in steel."
        assert detail["specs"] == [{"name": "Weight", "value": "100 g"}]
        assert client.get("/api/products/nothing").status_code == 404


SIMILAR = "https://www.curated.supply/products/pliss%C3%A9-toaster"
PAGE = f"""
<script type="application/ld+json">{{"@type":"Product","isSimilarTo":[{{"url":"{SIMILAR}"}}]}}</script>
<div data-about="true" class="x"><p>First &amp; best.</p>
<p>Kodak&#x27;s second.</p></div></section>
<dl><div><dt class="a">Designed in</dt><dd class="b">Japan<img src="/flags/jp.svg"/></dd></div>
<div><dt>Size</dt><dd>110 x 62 mm</dd></div></dl>
<h2>Read about it</h2><a class="flex" href="/blog/x"><img src="y" alt="Film &amp; instant"/></a></section>
"""


def test_a_product_page_parses_into_its_fields() -> None:
    assert about_text(PAGE) == "First & best.\n\nKodak's second."
    assert spec_rows(PAGE) == [("Designed in", "Japan"), ("Size", "110 x 62 mm")]
    assert article_titles(PAGE) == ("Film & instant",)
    assert json_ld(PAGE, "Product") is not None
    card = {
        "slug": "plissé-blender",
        "name": "Blender",
        "brandSlug": "acme",
        "categorySlug": "home",
        "imageUrl": "https://assets.curated.supply/a b.webp",
        "price": 0,
        "staffPick": True,
        "rank": 3,
        "date": "2026-05-30T00:00:00.000Z",
        "listSlugs": ["black"],
    }
    dataset = {"brandNames": {"acme": "Acme"}, "categoryNames": {"home": "Home"}, "listNames": {"black": "Black Only "}}
    parsed = parse_product(card, PAGE, dataset)
    assert parsed.url == "https://www.curated.supply/products/pliss%C3%A9-blender"
    assert parsed.designed_in == "Japan"
    assert parsed.specs == (Spec(name="Size", value="110 x 62 mm"),)
    assert parsed.alternatives == ("plissé-toaster",)
    assert parsed.lists == ("Black Only",)
    assert parsed.price is None
    assert parsed.photo_url == "https://assets.curated.supply/a%20b.webp"


def test_the_site_dataset_comes_out_of_the_react_payload() -> None:
    chunk = json.dumps('x"dataset":{"cards":[{"slug":"a"}],"total":1},"more":1')[1:-1]
    page = f'<script>self.__next_f.push([1,"{chunk}"])</script>'
    assert react_payload(page).startswith('x"dataset"')
    assert site_dataset(page)["cards"] == [{"slug": "a"}]


def test_files_keep_one_spelling_for_unicode_slugs(tmp_path: Path) -> None:
    url = "https://www.curated.supply/products/pliss%C3%A9-blender"
    assert page_path(tmp_path, url) == tmp_path / "products" / "pliss%C3%A9-blender.html.gz"
    assert page_path(tmp_path, "https://www.curated.supply/products") == tmp_path / "site" / "products.html.gz"
    assert page_path(tmp_path, "https://www.curated.supply") == tmp_path / "site" / "home.html.gz"
    assert photo_path(tmp_path, "plissé-blender") == tmp_path / "pliss%C3%A9-blender.webp"
    assert sitemap_urls("<loc>a</loc><loc>b</loc><loc>a</loc>") == ["a", "b"]


def test_the_env_file_sets_the_budget_and_overrides_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CURATED_ROOT", str(tmp_path))
    monkeypatch.setenv("CURATED_BUDGET_USD", "99")
    (tmp_path / ".env").write_text("# a comment\nCURATED_BUDGET_USD=3\nEMPTY=\n", encoding="utf-8")
    assert _settings().budget_usd == 3
