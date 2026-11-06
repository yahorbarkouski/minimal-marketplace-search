"""Reads the downloaded pages into one record per product.

The `/products` page embeds the site's whole dataset in its React payload, which gives every product's brand,
category, lists, price and photo. Each product's own page adds its editorial text, specification table and
alternatives, from its HTML and its JSON-LD.
"""

from __future__ import annotations

import gzip
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from curated.domain import Product, Spec
from curated.settings import Settings

SITE = "https://www.curated.supply"
_PAYLOAD = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.DOTALL)
_DATASET = '"dataset":'
_LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
_ABOUT = re.compile(r'<div data-about="true"[^>]*>(.*?)</div></section>', re.DOTALL)
_PARAGRAPH = re.compile(r"<p>(.*?)</p>", re.DOTALL)
_SPEC_ROW = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.DOTALL)
_ARTICLES = re.compile(r'<a [^>]*href="/blog/[^"]+"[^>]*>.*?<img [^>]*alt="([^"]*)"', re.DOTALL)
_READ_ABOUT = ">Read about it</h2>"
_TAG = re.compile(r"<[^>]+>")
DESIGNED_IN = "Designed in"
NOT_SPECS = frozenset({DESIGNED_IN, "Source"})


def react_payload(page: str) -> str:
    """The page's React payload, the chunks of data Next.js streams into its HTML, joined."""
    return "".join(json.loads(f'"{chunk}"') for chunk in _PAYLOAD.findall(page))


def site_dataset(page: str) -> dict[str, Any]:
    """The site's whole dataset, from the `/products` page's React payload."""
    payload = react_payload(page)
    start = payload.find(_DATASET)
    if start < 0:
        raise ValueError("the /products page holds no dataset; the site's markup has changed")
    dataset, _ = json.JSONDecoder().raw_decode(payload, start + len(_DATASET))
    return dataset


def product_cards(page: str) -> list[dict[str, Any]]:
    return site_dataset(page)["cards"]


def json_ld(page: str, kind: str) -> dict[str, Any] | None:
    """The page's first JSON-LD block of the given @type."""
    for block in _LD_JSON.findall(page):
        parsed = json.loads(block)
        if parsed.get("@type") == kind:
            return parsed
    return None


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def about_text(page: str) -> str:
    """The product's editorial text, paragraphs separated by blank lines; empty when it has none."""
    found = _ABOUT.search(page)
    if found is None:
        return ""
    paragraphs = (_text(paragraph) for paragraph in _PARAGRAPH.findall(found.group(1)))
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def spec_rows(page: str) -> list[tuple[str, str]]:
    return [(_text(name), _text(value)) for name, value in _SPEC_ROW.findall(page)]


def article_titles(page: str) -> tuple[str, ...]:
    """The titles of the blog posts under the page's "Read about it" heading."""
    start = page.find(_READ_ABOUT)
    if start < 0:
        return ()
    section = page[start : page.find("</section>", start)]
    return tuple(html.unescape(title) for title in _ARTICLES.findall(section))


def _slug_of(url: str) -> str:
    return unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])


def parse_product(card: dict[str, Any], page: str, dataset: dict[str, Any]) -> Product:
    """One product, from its entry in the site's dataset and its own page."""
    slug = card["slug"]
    described = json_ld(page, "Product")
    if described is None:
        raise ValueError(f"{slug}: the page has no Product JSON-LD")
    specs = spec_rows(page)
    designed_in = next((value for name, value in specs if name == DESIGNED_IN), None)
    similar = described.get("isSimilarTo") or []
    price = card["price"]
    return Product(
        product_id=slug,
        url=f"{SITE}/products/{quote(slug, safe='')}",
        name=card["name"],
        brand=dataset["brandNames"][card["brandSlug"]],
        brand_slug=card["brandSlug"],
        category=dataset["categoryNames"][card["categorySlug"]],
        category_slug=card["categorySlug"],
        lists=tuple(dataset["listNames"][slug].strip() for slug in card["listSlugs"]),
        articles=article_titles(page),
        price=float(price) if price else None,
        staff_pick=card["staffPick"],
        rank=card["rank"],
        added=card["date"][:10],
        about=about_text(page),
        designed_in=designed_in,
        specs=tuple(Spec(name=name, value=value) for name, value in specs if name not in NOT_SPECS),
        alternatives=tuple(_slug_of(item["url"]) for item in similar),
        photo_url=card["imageUrl"].replace(" ", "%20"),
    )


def _read_page(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode("utf-8")


def build_catalog(settings: Settings) -> list[Product]:
    """Parses every downloaded product, in the site's order, and writes `products.jsonl`."""
    dataset = site_dataset(_read_page(settings.raw_dir / "site" / "products.html.gz"))
    products: list[Product] = []
    missing: list[str] = []
    for card in sorted(dataset["cards"], key=lambda card: card["rank"]):
        path = settings.raw_dir / "products" / f"{quote(card['slug'], safe='')}.html.gz"
        if not path.exists():
            missing.append(card["slug"])
            continue
        products.append(parse_product(card, _read_page(path), dataset))
    if missing:
        raise RuntimeError(f"{len(missing)} products have no downloaded page, such as {missing[:3]}")
    settings.products_path.parent.mkdir(parents=True, exist_ok=True)
    with settings.products_path.open("w", encoding="utf-8") as out:
        for product in products:
            out.write(product.model_dump_json() + "\n")
    return products


def load_products(settings: Settings) -> dict[str, Product]:
    with settings.products_path.open(encoding="utf-8") as lines:
        products = (Product.model_validate_json(line) for line in lines if line.strip())
        return {product.product_id: product for product in products}
