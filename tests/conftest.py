"""A small catalogue built into a real index with stand-ins for the models, which the tests share."""

from pathlib import Path

import pytest

from curated.domain import Product, Spec
from curated.settings import Settings
from tests.stubbed_index import build_stubbed_root


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
