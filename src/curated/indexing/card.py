"""Text renderings of a product: the card that embeddings read, the card the gate reads, the style
card, and keyword fields."""

from __future__ import annotations

from collections.abc import Iterable

from curated.domain import KeywordFields, Product, Reading

ABOUT_CHARACTERS = 600
SPECS_CHARACTERS = 300


def render_card(product: Product, reading: Reading) -> str:
    return _render_lines(
        [
            ("Name", product.name),
            ("Brand", product.brand),
            ("Object", reading.object_type),
            ("Category", product.category),
            ("Materials", ", ".join(reading.materials)),
            ("Colors", ", ".join(reading.colors)),
            ("Looks", reading.visual_description),
            ("Designed in", product.designed_in),
            ("Specs", shorten(_specs(product), SPECS_CHARACTERS)),
            ("Price", price_line(product)),
            ("On the lists", ", ".join(product.lists)),
            ("Written about in", "; ".join(product.articles)),
            ("About", shorten(product.about, ABOUT_CHARACTERS)),
        ]
    )


def render_style_card(reading: Reading) -> str:
    """The style description under the product's kind: what the style vector embeds."""
    return _render_lines([("Object", reading.object_type), *_style_lines(reading)])


def render_gate_card(product: Product, reading: Reading) -> str:
    """What the gate reads: the card, followed by the style description."""
    return render_card(product, reading) + "\n" + _render_lines(_style_lines(reading))


def _style_lines(reading: Reading) -> list[tuple[str, str | None]]:
    return [
        ("Aesthetics", ", ".join(reading.aesthetics)),
        ("Mood", ", ".join(reading.moods)),
        ("Suits", ", ".join(reading.settings)),
        ("Appeals to", ", ".join(reading.appeals_to)),
        ("Evokes", ", ".join(reading.references)),
        ("Look", reading.vibe),
    ]


def keyword_fields(product: Product, reading: Reading) -> KeywordFields:
    return KeywordFields(
        title=product.name,
        names=product.brand,
        attributes=_join_unique(
            [
                reading.object_type,
                product.category,
                product.designed_in,
                *reading.materials,
                *reading.colors,
                *product.lists,
            ]
        ),
        description=" ".join([product.about, _specs(product), *product.articles]),
        queries="; ".join(reading.buyer_queries),
    )


def price_line(product: Product) -> str | None:
    return None if product.price is None else f"${product.price:,.0f}"


def _specs(product: Product) -> str:
    return "; ".join(f"{spec.name}: {spec.value}" for spec in product.specs)


def _render_lines(fields: Iterable[tuple[str, str | None]]) -> str:
    lines = ((label, " ".join((value or "").split())) for label, value in fields)
    return "\n".join(f"{label}: {value}" for label, value in lines if value)


def shorten(text: str, limit: int) -> str:
    """Cuts text to about `limit` characters on a word boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    boundary = text.rfind(" ", 0, limit + 1)
    return text[: boundary if boundary > 0 else limit].rstrip(" ,;:") + "…"


def _join_unique(values: Iterable[str | None]) -> str:
    """Joins the non-empty values with "; ", keeping the first of any that differ only in case."""
    unique: dict[str, str] = {}
    for value in values:
        if value and value.strip():
            unique.setdefault(value.strip().casefold(), value.strip())
    return "; ".join(unique.values())
