"""The query path: understand and interpret the query, search every arm inside its price limits, fuse, expand, and
let Jev decide what reaches the page.

Four calls start together: Jev's query questions, the query embedding, the LLM's price parse and the search's
interpretation. The search waits for the parse only when Jev says the query states a price limit; otherwise it
cancels it. The limits restrict every arm through the product table's mask, so a selective limit never empties
the result.

The arms searched with the buyer's words (keyword, text, photo, facets, style) are ready first. While the
interpretation is still on its way, the search gates their best-fused products and hands the confident ones over at
once. When the interpretation arrives, it is embedded and searched through the text, photo and style arms; all
rankings fuse with equal weights. The tag-defined expansion adds products matching the query's confident category and
facets, and Jev gates them all, reading each product's card, style description and photo beside the buyer's words and
the interpretation.

The page holds the products shown early, which stay where they are, then every other product at or above the gate's
line, best first. When the buyer reaches the end of the page, a further batch judges the next best-fused products, each
arm searched deeper for every batch, for as long as the last products judged still held matches.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from curated.catalog import load_products
from curated.domain import ArmName, Filters, FurtherBatch, Product, ProductId, Ranking, SearchTrace
from curated.indexing.build import (
    GATE_CARDS,
    PHOTO_VECTORS,
    STYLE_VECTORS,
    TEXT_VECTORS,
    load_cards,
    load_embeddings,
    load_keyword_fields,
)
from curated.indexing.embeddings import embed_interpretation, embed_query
from curated.indexing.photos import gate_photo_path
from curated.indexing.tagging import ProductTags
from curated.providers.jev import JevAsker
from curated.providers.protocols import Decider, QueryModels
from curated.search.arms import FacetArm, KeywordArm, VectorArm
from curated.search.expansion import expand
from curated.search.fusion import reciprocal_rank_fusion
from curated.search.gate import gate_candidates
from curated.search.interpretation import InterpretationCache, interpret
from curated.search.product_table import ProductTable
from curated.search.understanding import QueryQuestions, QueryUnderstanding, parse_filters, understand_query
from curated.settings import Settings
from curated.taxonomy import BrandNames, Taxonomy

WORD_ARMS = (
    ArmName.KEYWORD,
    ArmName.TEXT,
    ArmName.PHOTO,
    ArmName.FACETS,
    ArmName.STYLE,
)
"""The arms searched with the buyer's own words."""
INTERPRETATION_ARMS = (
    ArmName.TEXT_INTERPRETATION,
    ArmName.PHOTO_INTERPRETATION,
    ArmName.STYLE_INTERPRETATION,
)
"""The arms searched with the search's interpretation."""
PROBABILITY_KEPT = 0.01
"""A trace keeps Jev's reading of a search's categories and facets from this probability up."""


@dataclass(frozen=True)
class SearchIndex:
    products: dict[ProductId, Product]
    cards: dict[ProductId, str]
    """The product's catalogue card, which the debug panel shows."""
    gate_cards: dict[ProductId, str]
    """What the gate reads: the catalogue card followed by the product's style description."""
    taxonomy: Taxonomy
    questions: QueryQuestions
    brands: BrandNames
    table: ProductTable
    keyword: KeywordArm
    text: VectorArm
    photo: VectorArm
    style: VectorArm
    facets: FacetArm
    tags: ProductTags
    tag_rows: NDArray[np.intp]
    """The table row of each row of `tags`, to align a filter mask with the expansion."""

    @classmethod
    def load(cls, settings: Settings) -> SearchIndex:
        directory = settings.index_dir
        products = load_products(settings)
        table = ProductTable(products)
        text = load_embeddings(directory, TEXT_VECTORS)
        photo = load_embeddings(directory, PHOTO_VECTORS)
        style = load_embeddings(directory, STYLE_VECTORS)
        tags = ProductTags.load(directory)
        taxonomy = Taxonomy.load(settings.taxonomy_path)
        return cls(
            products=products,
            cards=load_cards(directory),
            gate_cards=load_cards(directory, GATE_CARDS),
            taxonomy=taxonomy,
            questions=QueryQuestions.build(taxonomy),
            brands=BrandNames.build(sorted({product.brand for product in products.values()})),
            table=table,
            keyword=KeywordArm(table, load_keyword_fields(directory)),
            text=VectorArm(table, ArmName.TEXT, text.ids, text.vectors),
            photo=VectorArm(table, ArmName.PHOTO, photo.ids, photo.vectors),
            style=VectorArm(table, ArmName.STYLE, style.ids, style.vectors),
            facets=FacetArm(table, tags.ids, tags.category_probs, tags.facet_probs),
            tags=tags,
            tag_rows=table.rows(tags.ids),
        )


@dataclass
class Continuation:
    """What a search needs to judge further batches: its arms, ranked to any depth without new model calls,
    the products it has judged in order, and the share of the last ones it admitted."""

    text: str
    interpretation: str | None
    rank: Callable[[int], Awaitable[dict[ArmName, Ranking]]]
    judged: list[ProductId] = field(default_factory=list)
    tail_share: float = 0.0
    batches: int = 0
    exhausted: bool = False


class Searcher:
    def __init__(
        self,
        index: SearchIndex,
        *,
        settings: Settings,
        openrouter: QueryModels,
        jev: JevAsker,
        fallback: Decider | None = None,
    ) -> None:
        self._index = index
        self._settings = settings
        self._openrouter = openrouter
        self._jev = jev
        self._fallback = fallback
        self._interpretations = InterpretationCache(settings.sizes.interpretation_cache_size)

    @property
    def index(self) -> SearchIndex:
        return self._index

    def worth_judging(self, more: Continuation) -> bool:
        """Whether another batch may still hold matches: products remain, the search has batches left, and
        enough of the last products it judged were admitted."""
        sizes = self._settings.sizes
        return not more.exhausted and more.batches < sizes.further_max and more.tail_share >= sizes.further_share

    async def begin(
        self,
        text: str,
        *,
        on_first_results: Callable[[tuple[ProductId, ...]], None] | None = None,
    ) -> tuple[SearchTrace, Continuation]:
        """Searches one query through its first batch, and returns what judging further batches needs.
        `on_first_results`, if given, receives the products the buyer's words alone make the gate confident about,
        while the interpretation is still on its way."""
        index, sizes, models = self._index, self._settings.sizes, self._settings.models
        clock = _Clock()

        interpretation = asyncio.create_task(self._interpret(text, clock))
        parse = asyncio.create_task(clock.time("parse", parse_filters(text, client=self._openrouter, models=models)))
        understanding = asyncio.create_task(
            clock.time(
                "understand",
                understand_query(text, index.taxonomy, index.questions, jev=self._jev),
            )
        )
        embedding = asyncio.create_task(
            clock.time(
                "embed",
                embed_query(
                    text,
                    client=self._openrouter,
                    model=models.embedding,
                    dimensions=models.embedding_dimensions,
                ),
            )
        )

        understood = await understanding
        if understood.states_limit >= sizes.limit_route_threshold:
            filters = await parse
        else:
            parse.cancel()
            filters = Filters()
        allowed = None if filters.is_empty else index.table.mask(filters)
        query_vector = await embedding
        rankings = await clock.time("arms", self._word_arms(text, query_vector, understood, allowed, sizes.arm_k))

        first_results: tuple[ProductId, ...] = ()
        early_gate: dict[ProductId, float] = {}
        if on_first_results is not None and not interpretation.done():
            # The interpretation is still on its way: show the confident products the buyer's words find now.
            early = self._fuse_and_expand(rankings, understood, allowed, clock, stage="early")[2][: sizes.early_gate_k]
            early_gate = await clock.time("gate_early", self._gate(text, early, interpretation=None))
            first_results = _best_first(early_gate, sizes.first_line)
            clock.mark("first_results")
            if first_results:
                clock.durations["first_product"] = clock.durations["first_results"]
            on_first_results(first_results)

        interpreted = await interpretation
        interpreted_vectors = (
            None
            if interpreted is None
            else await clock.time(
                "embed_interpretation",
                embed_interpretation(
                    text,
                    interpreted,
                    client=self._openrouter,
                    model=models.embedding,
                    dimensions=models.embedding_dimensions,
                ),
            )
        )
        rankings |= await clock.time(
            "arms_interpretation", self._interpretation_arms(interpreted_vectors, allowed, sizes.arm_k)
        )

        fused, expansion, to_gate = self._fuse_and_expand(rankings, understood, allowed, clock)
        final_gate = await clock.time("gate", self._gate(text, to_gate, interpretation=interpreted))
        shown_early = set(first_results)
        rest = [i for i in _best_first(final_gate, sizes.gate_line) if i not in shown_early]
        shown = (*first_results, *rest)
        # A product shown early keeps its score from then if the final gate never read it.
        gate = {i: early_gate[i] for i in first_results} | final_gate
        clock.mark("total")
        if shown:
            clock.durations.setdefault("first_product", clock.durations["total"])

        async def rank(k: int) -> dict[ArmName, Ranking]:
            return await self._word_arms(text, query_vector, understood, allowed, k) | (
                await self._interpretation_arms(interpreted_vectors, allowed, k)
            )

        expanded = {hit.product_id for hit in expansion}
        more = Continuation(
            text=text,
            interpretation=interpreted,
            rank=rank,
            # The early products were gated on the buyer's words, and may be missing from the final fusion.
            judged=list(dict.fromkeys([*first_results, *to_gate])),
            tail_share=self._tail_share([i for i in to_gate if i not in expanded], shown),
        )
        trace = SearchTrace(
            text=text,
            arm_rankings=rankings,
            fused=fused,
            gate=gate,
            parsed_filters=filters,
            shown=shown,
            timings_ms=clock.durations,
            stage_starts_ms=clock.starts,
            query_type=understood.query_type,
            query_type_confidence=understood.query_type_confidence,
            category_probs=_probabilities(
                [category.id for category in index.taxonomy.categories], understood.category_probs
            ),
            facet_probs=_probabilities([facet.id for facet in index.taxonomy.facets], understood.facet_probs),
            limit_probability=understood.states_limit,
            expansion=expansion,
            interpretation=interpreted,
            first_results=first_results,
        )
        return trace, more

    async def judge_further(self, trace: SearchTrace, more: Continuation) -> SearchTrace:
        """Judges the next batch: the best-fused products the search has not judged, its arms searched one
        `arm_k` deeper than for the batch before. Returns the trace with the batch's products after the
        earlier ones, and updates `more`."""
        sizes, index = self._settings.sizes, self._index
        started = time.perf_counter()
        judged = set(more.judged)
        depth = sizes.arm_k * (more.batches + 2)
        while True:
            rankings = await more.rank(depth)
            fused = reciprocal_rank_fusion(rankings, rrf_k=sizes.rrf_k, top_k=len(index.products))
            unjudged = [
                product_id
                for product_id in dict.fromkeys([*more.judged, *(hit.product_id for hit in fused)])
                if product_id not in judged
            ]
            arms_exhausted = all(len(ranking) < depth for ranking in rankings.values())
            if len(unjudged) >= sizes.further_batch or arms_exhausted:
                break
            depth += sizes.arm_k
        products = unjudged[: sizes.further_batch]
        gate = await self._gate(more.text, products, interpretation=more.interpretation) if products else {}
        shown = _best_first(gate, sizes.gate_line)
        more.batches += 1
        more.judged.extend(products)
        more.tail_share = self._tail_share(products, shown)
        more.exhausted = arms_exhausted and len(unjudged) <= len(products)
        batch = FurtherBatch(judged=tuple(products), gate=gate, shown=shown)
        return trace.model_copy(
            update={
                "further": (*trace.further, batch),
                "shown": (*trace.shown, *shown),
                "timings_ms": trace.timings_ms | {f"further_{more.batches}": _elapsed_ms(started)},
            }
        )

    def _tail_share(self, judged: Sequence[ProductId], admitted: Sequence[ProductId]) -> float:
        """The share of the last `further_tail` judged products that were admitted."""
        tail = judged[-self._settings.sizes.further_tail :]
        kept = set(admitted)
        return sum(product_id in kept for product_id in tail) / len(tail) if tail else 0.0

    async def _interpret(self, text: str, clock: _Clock) -> str | None:
        """The search's interpretation, from the cache or the model; None when the call fails or is late,
        so the search goes on with the buyer's words alone."""
        models, begun = self._settings.models, clock.now()
        cached = self._interpretations.get(text)
        if cached is not None:
            clock.record("interpret", begun, took=0.0)
            return cached
        try:
            interpretation = await asyncio.wait_for(
                interpret(
                    text,
                    client=self._openrouter,
                    model=models.interpretation,
                    provider=models.interpretation_provider,
                ),
                timeout=self._settings.sizes.interpretation_timeout_s,
            )
        except Exception as error:  # any failure degrades to the uninterpreted search, never fails it
            print(f"[search] no interpretation for {text!r}: {error!r}", file=sys.stderr)
            return None
        finally:
            clock.record("interpret", begun)
        self._interpretations.put(text, interpretation)
        return interpretation

    async def _word_arms(
        self,
        text: str,
        query_vector: NDArray[np.float32],
        understood: QueryUnderstanding,
        allowed: NDArray[np.bool_] | None,
        k: int,
    ) -> dict[ArmName, Ranking]:
        """The arms searched with the buyer's own words, `k` products each, in parallel threads."""
        index = self._index
        brands = index.brands.find(text)
        searches: dict[ArmName, Callable[[], Ranking]] = {
            ArmName.KEYWORD: lambda: index.keyword.search(text, brands, k, allowed=allowed),
            ArmName.TEXT: lambda: index.text.search(query_vector, k, allowed=allowed),
            ArmName.PHOTO: lambda: index.photo.search(query_vector, k, allowed=allowed),
            ArmName.FACETS: lambda: index.facets.search(
                understood.category_probs, understood.facet_probs, k, allowed=allowed
            ),
            ArmName.STYLE: lambda: index.style.search(query_vector, k, allowed=allowed),
        }
        rankings = await asyncio.gather(*(asyncio.to_thread(run) for run in searches.values()))
        return dict(zip(searches, rankings, strict=True))

    async def _interpretation_arms(
        self,
        vectors: tuple[NDArray[np.float32], NDArray[np.float32]] | None,
        allowed: NDArray[np.bool_] | None,
        k: int,
    ) -> dict[ArmName, Ranking]:
        """The text, photo and style arms searched with the interpretation's embeddings (as a document, as a
        query), `k` products each; empty rankings without an interpretation."""
        if vectors is None:
            return dict.fromkeys(INTERPRETATION_ARMS, ())
        index, (as_document, as_query) = self._index, vectors
        text_hits, photo_hits, style_hits = await asyncio.gather(
            asyncio.to_thread(index.text.search, as_query, k, allowed=allowed),
            asyncio.to_thread(index.photo.search, as_query, k, allowed=allowed),
            asyncio.to_thread(index.style.search, as_document, k, allowed=allowed),
        )
        return {
            ArmName.TEXT_INTERPRETATION: text_hits,
            ArmName.PHOTO_INTERPRETATION: photo_hits,
            ArmName.STYLE_INTERPRETATION: style_hits,
        }

    def _fuse_and_expand(
        self,
        rankings: dict[ArmName, Ranking],
        understood: QueryUnderstanding,
        allowed: NDArray[np.bool_] | None,
        clock: _Clock,
        *,
        stage: str = "",
    ) -> tuple[Ranking, Ranking, tuple[ProductId, ...]]:
        """Fuses the rankings and adds the tag-defined expansion: the fused list, the expansion, and the products
        to gate."""
        index, sizes, suffix = self._index, self._settings.sizes, f"_{stage}" if stage else ""
        fused = clock.time_sync(
            f"fuse{suffix}",
            lambda: reciprocal_rank_fusion(rankings, rrf_k=sizes.rrf_k, top_k=sizes.fused_k),
        )
        fused_ids = [hit.product_id for hit in fused]
        expansion = clock.time_sync(
            f"expand{suffix}",
            lambda: expand(
                understood.category_probs,
                understood.facet_probs,
                index.tags,
                allowed=None if allowed is None else allowed[index.tag_rows],
                exclude=set(fused_ids),
                category_floor=sizes.expansion_category_floor,
                facet_floor=sizes.expansion_facet_floor,
                product_floor=sizes.expansion_product_floor,
                cap=sizes.expansion_cap,
            ),
        )
        return fused, expansion, (*fused_ids, *(hit.product_id for hit in expansion))

    def _gate(
        self, text: str, product_ids: Sequence[ProductId], *, interpretation: str | None
    ) -> Awaitable[dict[ProductId, float]]:
        return gate_candidates(
            text,
            product_ids,
            self._index.gate_cards,
            jev=self._jev,
            products_per_call=self._settings.sizes.gate_products_per_call,
            photos=lambda product_id: gate_photo_path(self._settings.gate_photos_dir, product_id),
            interpretation=interpretation,
            fallback=self._fallback,
        )


def _best_first(gate: dict[ProductId, float], line: float) -> tuple[ProductId, ...]:
    """The products at or above the line, the highest probability first."""
    return tuple(sorted((i for i, p in gate.items() if p >= line), key=lambda i: -gate[i]))


@dataclass
class _Clock:
    """One search's timings in milliseconds from its start: how long each stage took (`durations`, which
    also holds the moments `first_results`, `first_product` and `total`), and when each stage began (`starts`),
    so stages that overlap can be drawn on one time axis."""

    started: float = field(default_factory=time.perf_counter)
    durations: dict[str, float] = field(default_factory=dict)
    starts: dict[str, float] = field(default_factory=dict)

    def now(self) -> float:
        return _elapsed_ms(self.started)

    def record(self, stage: str, begun: float, *, took: float | None = None) -> None:
        """Records a stage that began at `begun` and ends now, or took `took` when given."""
        self.starts[stage] = begun
        self.durations[stage] = self.now() - begun if took is None else took

    def mark(self, moment: str) -> None:
        """Records the time since the search's start under `moment`."""
        self.durations[moment] = self.now()

    async def time[T](self, stage: str, awaitable: Awaitable[T]) -> T:
        begun = self.now()
        result = await awaitable
        self.record(stage, begun)
        return result

    def time_sync[T](self, stage: str, compute: Callable[[], T]) -> T:
        begun = self.now()
        result = compute()
        self.record(stage, begun)
        return result


def _probabilities(ids: Sequence[str], probabilities: NDArray[np.float64]) -> dict[str, float]:
    """Each id's probability, rounded, leaving out those under PROBABILITY_KEPT."""
    return {
        identifier: round(float(p), 3)
        for identifier, p in zip(ids, probabilities, strict=True)
        if p >= PROBABILITY_KEPT
    }


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
