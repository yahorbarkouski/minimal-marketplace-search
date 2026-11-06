"""What the paid clients do with money and failures, against a fake server, so no call leaves this machine."""

from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from typesafe_sdk import SystemOneResponse, Usage

from curated.ledger import BudgetExceededError, SpendLedger
from curated.providers import openrouter
from curated.providers.jev import JevClient
from curated.providers.openrouter import OpenRouterClient, OpenRouterError

ANSWER = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"cost": 0.25}}


def client(
    tmp_path: Path, answers: list[httpx.Response], cap_usd: float = 1.0
) -> tuple[OpenRouterClient, SpendLedger, list[Any]]:
    requests: list[Any] = []
    remaining = iter(answers)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return next(remaining)

    http = httpx.AsyncClient(base_url="https://fake.test", transport=httpx.MockTransport(respond))
    ledger = SpendLedger.open(tmp_path / "ledger.jsonl", cap_usd)
    return OpenRouterClient(http=http, ledger=ledger), ledger, requests


async def ask(models: OpenRouterClient) -> dict[str, Any]:
    return await models.complete_json(model="m", messages=[], schema_name="s", schema={}, purpose="test")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def skip(_: float) -> None:
        return None

    monkeypatch.setattr(openrouter, "sleep", skip)


async def test_an_answer_is_parsed_and_its_cost_recorded(tmp_path: Path) -> None:
    models, ledger, _ = client(tmp_path, [httpx.Response(200, json=ANSWER)])
    assert await ask(models) == {"ok": True}
    assert ledger.total_usd == pytest.approx(0.25)


async def test_a_rate_limit_is_retried_and_charged_once(tmp_path: Path) -> None:
    answers = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(503), httpx.Response(200, json=ANSWER)]
    models, ledger, requests = client(tmp_path, answers)
    assert await ask(models) == {"ok": True}
    assert len(requests) == 3
    assert ledger.total_usd == pytest.approx(0.25)


async def test_a_client_error_is_not_retried_and_costs_nothing(tmp_path: Path) -> None:
    models, ledger, requests = client(tmp_path, [httpx.Response(400, text="bad request")])
    with pytest.raises(OpenRouterError, match="400"):
        await ask(models)
    assert len(requests) == 1
    assert ledger.total_usd == 0


async def test_an_outage_gives_up_after_its_retries(tmp_path: Path) -> None:
    models, _, requests = client(tmp_path, [httpx.Response(500) for _ in range(openrouter.MAX_RETRIES + 1)])
    with pytest.raises(OpenRouterError, match="500"):
        await ask(models)
    assert len(requests) == openrouter.MAX_RETRIES + 1


async def test_an_empty_answer_is_an_error(tmp_path: Path) -> None:
    empty = {"choices": [{"message": {"content": None}}]}
    models, _, _ = client(tmp_path, [httpx.Response(200, json=empty)])
    with pytest.raises(OpenRouterError, match="no content"):
        await ask(models)


async def test_a_spent_budget_stops_the_call_before_it_leaves(tmp_path: Path) -> None:
    models, ledger, requests = client(tmp_path, [], cap_usd=0.0)
    with pytest.raises(BudgetExceededError):
        await ask(models)
    assert requests == []
    assert ledger.total_usd == 0


async def test_embeddings_come_back_in_input_order_and_a_short_answer_is_an_error(tmp_path: Path) -> None:
    rows = [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]
    models, _, _ = client(tmp_path, [httpx.Response(200, json={"data": rows})])
    vectors = await models.embed_texts(["a", "b"], model="m", dimensions=2, purpose="test")
    assert np.array_equal(vectors, np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    models, _, _ = client(tmp_path, [httpx.Response(200, json={"data": rows[:1]})])
    with pytest.raises(OpenRouterError, match="1 embeddings for 2"):
        await models.embed_texts(["a", "b"], model="m", dimensions=2, purpose="test")


def test_retry_after_reads_seconds_and_refuses_nonsense() -> None:
    assert openrouter._retry_after_seconds("3") == 3
    assert openrouter._retry_after_seconds("-3") == 0
    with pytest.raises(OpenRouterError, match="unreadable"):
        openrouter._retry_after_seconds("soon")


async def test_jev_charges_each_call_by_its_input_tokens_and_sends_the_image_header_only_with_images(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeTypeSafe:
        async def system_one(self, **call: Any) -> SystemOneResponse:
            calls.append(call)
            return SystemOneResponse(model="jev", usage=Usage(input_tokens=1_000_000, output_tokens=0), answers={})

    ledger = SpendLedger.open(tmp_path / "ledger.jsonl", 1.0)
    jev = JevClient(client=FakeTypeSafe(), ledger=ledger, model=None, usd_per_million=0.042)  # type: ignore[arg-type]
    await jev.ask("state", {}, purpose="test")
    assert calls[-1]["extra_headers"] is None
    assert ledger.total_usd == pytest.approx(0.042)
    await jev.ask("state", {}, purpose="test", assets={"photo": object()})  # type: ignore[dict-item]
    assert calls[-1]["extra_headers"] == {"TypeSafe-Danger-Zone-Images": "true"}
    ledger.cap_usd = 0.0
    with pytest.raises(BudgetExceededError):
        await jev.ask("state", {}, purpose="test")
    assert len(calls) == 2
