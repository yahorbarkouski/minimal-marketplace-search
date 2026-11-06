"""The password gate, and the spend total that serverless instances share."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from curated import shared_spend
from curated.gate import COOKIE, PasswordGate, access_token
from curated.ledger import BudgetExceededError, SpendLedger
from curated.shared_spend import SharedSpend, amount_of

PASSWORD = "open sesame"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    login = tmp_path / "login.html"
    login.write_text("<title>the login page</title>")
    app = FastAPI()

    @app.get("/")
    def home() -> dict[str, str]:
        return {"page": "search"}

    @app.get("/api/search")
    def search() -> dict[str, str]:
        return {"results": "secret"}

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(PasswordGate, password=PASSWORD, login_page=login)
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_without_the_cookie_pages_show_the_login_and_the_api_refuses(client: TestClient) -> None:
    assert "the login page" in client.get("/").text
    assert client.get("/api/search").status_code == 401


def test_the_health_check_stays_open(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True}


def test_a_wrong_password_returns_to_the_page_and_sets_no_cookie(client: TestClient) -> None:
    response = client.post("/api/login", data={"password": "nope", "next": "/?q=lamp"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?q=lamp&wrong=1"
    assert COOKIE not in response.cookies


def test_the_right_password_opens_the_site_and_returns_to_the_page(client: TestClient) -> None:
    response = client.post("/api/login", data={"password": PASSWORD, "next": "/?q=lamp"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?q=lamp"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert PASSWORD not in cookie
    assert client.get("/api/search").json() == {"results": "secret"}
    assert client.get("/").json() == {"page": "search"}


def test_signing_in_never_redirects_to_another_site(client: TestClient) -> None:
    response = client.post("/api/login", data={"password": PASSWORD, "next": "//evil.example"})
    assert response.headers["location"] == "/"


def test_a_forged_cookie_is_refused(client: TestClient) -> None:
    client.cookies.set(COOKIE, access_token("another password"))
    assert client.get("/api/search").status_code == 401


def test_spend_blob_names_hold_their_amounts() -> None:
    assert amount_of("spend/1f3a-0.018500.txt") == 0.0185


class FakeBlobs:
    """The two blob calls, over one list of names that every instance sees."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.names: list[str] = []
        monkeypatch.setattr(shared_spend, "put_blob", self.put)
        monkeypatch.setattr(shared_spend, "query_blobs", self.query)

    async def put(self, pathname: str, body: bytes, *, access: str) -> None:
        self.names.append(pathname)

    async def query(self, *, prefix: str) -> AsyncIterator[SimpleNamespace]:
        for name in self.names:
            if name.startswith(prefix):
                yield SimpleNamespace(pathname=name)


def ledger_at(tmp_path: Path, name: str, cap: float = 5.0) -> SpendLedger:
    return SpendLedger.open(tmp_path / name, cap)


async def test_two_instances_share_one_total_and_the_cap_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blobs = FakeBlobs(monkeypatch)
    first, second = ledger_at(tmp_path, "a.jsonl"), ledger_at(tmp_path, "b.jsonl")
    sharing_first = SharedSpend(first, spent_before_usd=4.0)
    sharing_second = SharedSpend(second, spent_before_usd=4.0)

    await sharing_first.refresh()
    assert first.total_usd == pytest.approx(4.0)
    first.record(provider="p", model="m", purpose="search", cost_usd=0.6)
    await sharing_first.share()
    assert len(blobs.names) == 1

    await sharing_second.refresh()
    assert second.total_usd == pytest.approx(4.6)
    second.record(provider="p", model="m", purpose="search", cost_usd=0.5)
    await sharing_second.share()

    await sharing_first.refresh()
    assert first.total_usd == pytest.approx(5.1)
    with pytest.raises(RuntimeError, match="budget"):
        first.ensure_room()


async def test_sharing_twice_counts_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blobs = FakeBlobs(monkeypatch)
    ledger = ledger_at(tmp_path, "a.jsonl")
    sharing = SharedSpend(ledger, spent_before_usd=0.0)
    await sharing.refresh()
    ledger.record(provider="p", model="m", purpose="search", cost_usd=0.25)
    await asyncio.gather(sharing.share(), sharing.share())
    await sharing.refresh()
    assert ledger.total_usd == pytest.approx(0.25)
    assert len(blobs.names) == 1


async def test_a_daily_ledger_counts_one_day_and_its_budget_comes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "daily.jsonl"
    yesterday = time.time() - 86_400
    path.write_text(
        json.dumps({"at": yesterday, "cost_usd": 9.0}) + "\n" + json.dumps({"at": time.time(), "cost_usd": 0.5}) + "\n"
    )
    ledger = SpendLedger.open(path, 1.0, daily=True)
    assert ledger.total_usd == pytest.approx(0.5)
    ledger.record(provider="p", model="m", purpose="search", cost_usd=0.5)
    with pytest.raises(BudgetExceededError, match="today's"):
        ledger.ensure_room()
    ledger.day = "2020-01-01"
    ledger.ensure_room()
    assert ledger.total_usd == 0


async def test_instances_share_only_todays_spend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blobs = FakeBlobs(monkeypatch)
    blobs.names.append("spend/2020-01-01/old-9.000000.txt")
    ledger = SpendLedger.open(tmp_path / "a.jsonl", 5.0, daily=True)
    sharing = SharedSpend(ledger, spent_before_usd=0.0)
    await sharing.refresh()
    assert ledger.total_usd == 0
    ledger.record(provider="p", model="m", purpose="search", cost_usd=0.25)
    await sharing.share()
    assert any(name.startswith(f"spend/{ledger.day}/") for name in blobs.names)
    await sharing.refresh()
    assert ledger.total_usd == pytest.approx(0.25)
