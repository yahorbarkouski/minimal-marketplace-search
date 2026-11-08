"""The search server: the real search behind a small HTTP API, for the site in web/.

`GET /api/search?q=...` streams Server-Sent Events while one search runs:
- `first`: the early products, as soon as the gate on the buyer's words is confident about them;
- `result`: the page's products in order, the search's interpretation, and the account the query debug panel draws
  (`curated.debug_view`): each stage on one time axis, how Jev read the search, the counts from the catalogue to the
  page, and every judged product with the rankings that found it; with the id that asks for the further batches and
  whether one may still hold matches;
- `error`: the search failed, or the visitor or the site has reached a limit.
`GET /api/search/{search_id}/more` judges the search's next batch, while it may still hold matches.
`GET /api/products/{product_id}` describes one product; its photo comes from curated.supply's own CDN.
`GET /api/health` says how many products the server holds, and costs nothing.
Every search is a paid model call charged to the spend ledger like any other.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from curated.debug_view import describe_search
from curated.domain import Product, ProductId, Reading, SearchTrace
from curated.indexing.card import price_line
from curated.indexing.reading import load_readings
from curated.ledger import BudgetExceededError, open_daily
from curated.limits import RateLimit, visitor_address, wait_message
from curated.providers.jev import JevClient
from curated.providers.openrouter import OpenRouterClient
from curated.search.searcher import Continuation, Searcher, SearchIndex
from curated.settings import Settings
from curated.shared_spend import SharedSpend

MAX_QUERY_CHARACTERS = 200
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
STYLE_FIELDS = {"vibe", "aesthetics", "moods", "settings", "appeals_to", "references"}
BLOB_TOKEN = "BLOB_READ_WRITE_TOKEN"
SEARCHES_KEPT = 200
"""Searches whose further batches a page can still ask for; the least recently used is forgotten first."""


@dataclass
class Ongoing:
    """A search a page may ask more of: its trace so far and what judging its next batch needs. The lock
    keeps two requests from judging the same batch."""

    trace: SearchTrace
    more: Continuation
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class Demo:
    """What the API serves from: the searcher, its index, the readings and the searches a page may still ask
    more of."""

    searcher: Searcher
    settings: Settings
    readings: Mapping[ProductId, Reading]
    shared_spend: SharedSpend | None = None
    """Set on a deployment, where the budget has to hold across serverless instances."""
    ongoing: OrderedDict[str, Ongoing] = field(default_factory=OrderedDict)

    async def refresh_spend(self) -> None:
        if self.shared_spend is not None:
            await self.shared_spend.refresh()

    async def share_spend(self) -> None:
        if self.shared_spend is not None:
            await self.shared_spend.share()

    def keep(self, search: Ongoing) -> str:
        search_id = uuid4().hex
        self.ongoing[search_id] = search
        while len(self.ongoing) > SEARCHES_KEPT:
            self.ongoing.popitem(last=False)
        return search_id

    async def judge_further(self, search: Ongoing) -> dict[str, Any] | None:
        """Judges the search's next batch and describes it; None when no batch may hold matches."""
        async with search.lock:
            if not self.searcher.worth_judging(search.more):
                return None
            search.trace = await self.searcher.judge_further(search.trace, search.more)
            return present_batch(self, search)


DemoFactory = Callable[[], AbstractAsyncContextManager[Demo]]


def connect_demo(settings: Settings) -> DemoFactory:
    """Opens the model clients and loads the index once, for the server's lifetime."""

    @asynccontextmanager
    async def open_demo() -> AsyncIterator[Demo]:
        ledger = open_daily(settings.ledger_path, settings.daily_budget_usd)
        async with (
            OpenRouterClient.connect(ledger) as openrouter,
            JevClient.connect(ledger, settings.models) as jev,
        ):
            searcher = Searcher(SearchIndex.load(settings), settings=settings, openrouter=openrouter, jev=jev)
            shared = SharedSpend(ledger) if os.environ.get(BLOB_TOKEN) else None
            yield Demo(searcher=searcher, settings=settings, readings=load_readings(settings), shared_spend=shared)

    return open_demo


def create_app(open_demo: DemoFactory) -> FastAPI:
    state: dict[str, Demo] = {}
    limits: dict[str, RateLimit] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with open_demo() as demo:
            state["demo"] = demo
            limits["visitor"] = RateLimit(demo.settings.searches_per_hour)
            yield

    app = FastAPI(title="Curated", lifespan=lifespan)

    def demo() -> Demo:
        return state["demo"]

    def wait_for(request: Request) -> int | None:
        """Counts a paid request against the visitor; the seconds to wait when they have reached the limit."""
        limit = limits.get("visitor")
        return None if limit is None else limit.retry_after(visitor_address(request))

    @app.get("/api/health")
    def health() -> dict[str, int]:
        return {"products": len(demo().searcher.index.products)}

    @app.get("/api/search")
    async def search(
        request: Request, q: str = Query(min_length=1, max_length=MAX_QUERY_CHARACTERS)
    ) -> StreamingResponse:
        text = " ".join(q.split())
        if not text:
            raise HTTPException(status_code=422, detail="the search is empty")
        # An error event, because a page's event stream can't read a response's status or body.
        wait = wait_for(request)
        events = _refused(wait_message(wait)) if wait is not None else _search_events(demo(), text)
        return StreamingResponse(events, media_type="text/event-stream", headers=STREAM_HEADERS)

    @app.get("/api/search/{search_id}/more")
    async def more(request: Request, search_id: str) -> dict[str, Any]:
        wait = wait_for(request)
        if wait is not None:
            raise HTTPException(status_code=429, detail=wait_message(wait), headers={"Retry-After": str(wait)})
        current = demo()
        search = current.ongoing.get(search_id)
        if search is None:
            raise HTTPException(status_code=404, detail="this search is no longer kept; search again")
        current.ongoing.move_to_end(search_id)
        batch = await current.judge_further(search)
        await current.share_spend()
        return batch if batch is not None else {"products": [], "judged": 0, "more": False}

    @app.get("/api/products/{product_id}")
    def product(product_id: str) -> dict[str, Any]:
        current = demo()
        index = current.searcher.index
        if product_id not in index.products:
            raise HTTPException(status_code=404, detail=f"no product {product_id}")
        found = index.products[product_id]
        reading = current.readings[product_id]
        return {
            **_product_view(current, product_id),
            "card": index.cards[product_id],
            "about": found.about,
            "specs": [spec.model_dump() for spec in found.specs],
            "designed_in": found.designed_in,
            "lists": list(found.lists),
            "style": reading.model_dump(include=STYLE_FIELDS),
        }

    return app


async def _refused(message: str) -> AsyncIterator[str]:
    yield f"event: error\ndata: {json.dumps({'message': message})}\n\n"


async def _search_events(demo: Demo, text: str) -> AsyncIterator[str]:
    """Runs one search and yields its events: the early products, then the result or an error."""
    events: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
    started = perf_counter()

    def first(product_ids: tuple[ProductId, ...]) -> None:
        products = [_product_view(demo, product_id) for product_id in product_ids]
        events.put_nowait(("first", {"elapsed_ms": round((perf_counter() - started) * 1000), "products": products}))

    async def run() -> None:
        try:
            await demo.refresh_spend()
            trace, more = await demo.searcher.begin(text, on_first_results=first)
            search_id = demo.keep(Ongoing(trace=trace, more=more))
            worth = demo.searcher.worth_judging(more)
            events.put_nowait(("result", present(demo, trace) | {"search_id": search_id, "more": worth}))
        except BudgetExceededError:
            events.put_nowait(
                ("error", {"message": "The search has reached its spending limit. Please try again later."})
            )
        except Exception as error:  # the page shows the failure instead of hanging; the details stay in the log
            print(f"[search] {text!r} failed: {error!r}", file=sys.stderr)
            events.put_nowait(("error", {"message": "The search failed. Please try again."}))
        finally:
            # Shielded, so a visitor who closes the page mid-search still has its spend counted.
            await asyncio.shield(demo.share_spend())
            events.put_nowait(None)

    task = asyncio.create_task(run())
    try:
        while (event := await events.get()) is not None:
            kind, data = event
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
    finally:
        task.cancel()


def present(demo: Demo, trace: SearchTrace) -> dict[str, Any]:
    """What the page shows of one search: its products, and the account the query debug panel draws."""
    debug = describe_search(trace, demo.searcher.index, demo.settings)
    for row in debug["rows"]:
        product = _product_view(demo, row["id"])
        row |= {key: product[key] for key in ("name", "price", "brand", "category", "url", "photo")}
    return {
        "query": trace.text,
        "interpretation": trace.interpretation,
        "query_type": None if trace.query_type is None else trace.query_type.value,
        "filters": trace.parsed_filters.model_dump(exclude_none=True) or None,
        "products": [_product_view(demo, product_id, trace.gate) for product_id in trace.shown],
        "first_results": list(trace.first_results),
        "debug": debug,
    }


def present_batch(demo: Demo, search: Ongoing) -> dict[str, Any]:
    """What the page shows of a search's latest further batch: the products it adds, how many it judged, and whether
    another batch may still hold matches."""
    batch = search.trace.further[-1]
    return {
        "batch": len(search.trace.further),
        "judged": len(batch.judged),
        "products": [_product_view(demo, product_id, batch.gate) for product_id in batch.shown],
        "more": demo.searcher.worth_judging(search.more),
    }


def _product_view(demo: Demo, product_id: ProductId, gate: Mapping[ProductId, float] | None = None) -> dict[str, Any]:
    product: Product = demo.searcher.index.products[product_id]
    return {
        "id": product_id,
        "name": product.name,
        "price": price_line(product) or "",
        "brand": product.brand,
        "category": product.category,
        "url": product.url,
        "photo": product.photo_url,
        "aesthetics": list(demo.readings[product_id].aesthetics[:3]),
        "gate": None if gate is None else gate.get(product_id),
    }
