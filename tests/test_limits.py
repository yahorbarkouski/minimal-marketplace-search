"""The limits a public deployment relies on, through the real API with stand-ins for the models."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from curated.ledger import BudgetExceededError
from curated.limits import RateLimit, visitor_address, wait_message
from curated.server import create_app
from curated.settings import Settings
from tests.stubbed_index import stubbed_demo


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_visitor_waits_only_until_their_oldest_request_is_an_hour_old() -> None:
    clock = Clock()
    limit = RateLimit(2, clock=clock)
    assert limit.retry_after("a") is None
    clock.now += 600
    assert limit.retry_after("a") is None
    assert limit.retry_after("a") == 3000
    assert limit.retry_after("b") is None
    clock.now += 3001
    assert limit.retry_after("a") is None


def test_a_refused_request_does_not_extend_the_wait() -> None:
    clock = Clock()
    limit = RateLimit(1, clock=clock)
    limit.retry_after("a")
    for _ in range(5):
        limit.retry_after("a")
    clock.now += 3600
    assert limit.retry_after("a") is None


def request_from(host: str, *headers: tuple[bytes, bytes]) -> Request:
    return Request({"type": "http", "headers": list(headers), "client": (host, 1)})


def test_a_forged_header_counts_only_where_vercel_sets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    forged = (b"x-vercel-forwarded-for", b"6.6.6.6")
    monkeypatch.delenv("VERCEL", raising=False)
    assert visitor_address(request_from("1.1.1.1", forged)) == "1.1.1.1"
    monkeypatch.setenv("VERCEL", "1")
    assert visitor_address(request_from("1.1.1.1", forged)) == "6.6.6.6"
    assert visitor_address(request_from("1.1.1.1", (b"x-forwarded-for", b"6.6.6.6"))) == "1.1.1.1"


def test_a_wait_reads_in_whole_minutes() -> None:
    assert "1 minute." in wait_message(10)
    assert "3 minutes." in wait_message(121)


def test_the_search_stops_at_the_visitors_limit_with_a_message_the_page_can_show(settings: Settings) -> None:
    limited = replace(settings, searches_per_hour=1)
    with TestClient(create_app(stubbed_demo(limited))) as client:
        first = client.get("/api/search", params={"q": "lamp"}).text
        second = client.get("/api/search", params={"q": "lamp"}).text
    assert "event: result" in first
    assert "event: error" in second
    assert "try again" in second
    assert "event: result" not in second


def test_failures_tell_the_page_nothing_internal(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(stubbed_demo(settings))) as client:

        async def fail(*_: object, **__: object) -> None:
            raise RuntimeError("secret-provider-detail")

        monkeypatch.setattr("curated.search.searcher.Searcher.begin", fail)
        failed = client.get("/api/search", params={"q": "lamp"}).text

        async def spent(*_: object, **__: object) -> None:
            raise BudgetExceededError("spent $5.0000 of the $5.00 budget")

        monkeypatch.setattr("curated.search.searcher.Searcher.begin", spent)
        capped = client.get("/api/search", params={"q": "lamp"}).text
    assert "secret-provider-detail" not in failed
    assert "The search failed" in failed
    assert "spending limit" in capped
    assert "$5" not in capped
