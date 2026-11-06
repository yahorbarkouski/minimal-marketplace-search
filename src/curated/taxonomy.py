"""The taxonomy (categories and facet families) a model writes from the catalogue, the Jev questions built from
it, and the brand names a search can name."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml
from pydantic import model_validator
from typesafe_sdk import Choice, Noul

from curated.domain import Frozen

MAX_CHOICE_OPTIONS = 255
WORD = re.compile(r"\w+")


class Category(Frozen):
    id: str
    name: str
    definition: str


class FacetValue(Frozen):
    id: str
    name: str
    definition: str


class FacetFamily(Frozen):
    id: str
    name: str
    values: tuple[FacetValue, ...]


def name_words(text: str) -> tuple[str, ...]:
    """The casefolded words of `text`, the unit brand names are matched in. "&" reads as "and"; every other
    character that is not a letter, digit or underscore separates words."""
    return tuple(WORD.findall(unicodedata.normalize("NFKC", text).casefold().replace("&", " and ")))


@dataclass(frozen=True)
class BrandNames:
    """Each brand's words mapped to its name, so a lookup costs one dictionary probe per word n-gram of the text
    rather than one scan per brand."""

    by_words: dict[tuple[str, ...], str]
    longest: int

    @classmethod
    def build(cls, names: Sequence[str]) -> BrandNames:
        by_words = {words: name for name in names if (words := name_words(name))}
        return cls(by_words=by_words, longest=max((len(words) for words in by_words), default=0))

    def find(self, text: str) -> tuple[str, ...]:
        """The brands whose words occur consecutively in `text`, in the order they occur."""
        words = name_words(text)
        found: dict[str, None] = {}
        for start in range(len(words)):
            for end in range(start + 1, min(start + self.longest, len(words)) + 1):
                name = self.by_words.get(words[start:end])
                if name is not None:
                    found[name] = None
        return tuple(found)


class Taxonomy(Frozen):
    categories: tuple[Category, ...]
    facet_families: tuple[FacetFamily, ...]

    @model_validator(mode="after")
    def _check(self) -> Taxonomy:
        if len(self.categories) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"{len(self.categories)} categories exceed a Jev Choice's {MAX_CHOICE_OPTIONS}")
        counts = Counter([category.id for category in self.categories] + [facet.id for facet in self.facets])
        duplicates = sorted(identifier for identifier, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate taxonomy ids: {duplicates}")
        return self

    @classmethod
    def load(cls, path: Path) -> Taxonomy:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    @cached_property
    def facets(self) -> tuple[FacetValue, ...]:
        return tuple(value for family in self.facet_families for value in family.values)

    @cached_property
    def _family_of(self) -> dict[str, FacetFamily]:
        return {value.id: family for family in self.facet_families for value in family.values}

    def family_of(self, facet: FacetValue) -> FacetFamily:
        return self._family_of[facet.id]


def product_category_question(taxonomy: Taxonomy) -> Choice:
    return Choice(
        instructions="Which category does this product belong to?",
        criteria={category.id: f"{category.name}: {category.definition}" for category in taxonomy.categories},
    )


def product_facet_questions(taxonomy: Taxonomy) -> dict[str, Noul]:
    return {
        facet.id: Noul(
            instructions=f"{taxonomy.family_of(facet).name} of this product: {facet.name}. {facet.definition}"
        )
        for facet in taxonomy.facets
    }


def query_category_questions(taxonomy: Taxonomy) -> dict[str, Noul]:
    return {
        category.id: Noul(
            instructions=(
                f"The buyer's search asks for a product in this category: {category.name}. {category.definition}"
            )
        )
        for category in taxonomy.categories
    }


def query_facet_questions(taxonomy: Taxonomy) -> dict[str, Noul]:
    return {
        facet.id: Noul(
            instructions=(
                f"The buyer's search asks for this {taxonomy.family_of(facet).name.lower()}: "
                f"{facet.name}. {facet.definition}"
            )
        )
        for facet in taxonomy.facets
    }
