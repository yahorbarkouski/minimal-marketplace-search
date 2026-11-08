"""The fallback decision model: the gate asks it when TypeSafe's call fails, and it is charged like any paid call."""

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from typesafe_sdk import TypeSafeError

from curated.ledger import BudgetExceededError, SpendLedger
from curated.providers import openrouter
from curated.providers.openrouter import DECISIONS_URL, OpenRouterClient, OpenRouterError
from curated.search.gate import gate_candidates
from tests.stubs import StubJev


class Failing(StubJev):
    async def ask(self, state, questions, *, purpose, assets=None):
        raise TypeSafeError("503 Image processing is unavailable")


class Recording:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.error = error

    async def decide(self, state: Any, questions: dict[str, Any], *, purpose: str) -> dict[str, float]:
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        return dict.fromkeys(questions, 0.8)


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (300, 300), "white").save(path)
    return path


async def gate(photo: Path, jev: StubJev, fallback: Recording | None) -> dict[str, float]:
    ids = ["lamp", "chair", "sofa"]
    return await gate_candidates(
        "desk lamp",
        ids,
        dict.fromkeys(ids, "A desk lamp."),
        jev=jev,
        products_per_call=2,
        photos=lambda _: photo,
        fallback=fallback,  # type: ignore[arg-type]
    )


async def test_a_failed_call_goes_to_the_fallback_with_the_same_state_questions_and_photos(photo: Path) -> None:
    fallback = Recording()
    scores = await gate(photo, Failing(), fallback)
    assert scores == {"lamp": 0.8, "chair": 0.8, "sofa": 0.8}
    assert [len(questions) for _, questions in fallback.calls] == [2, 1]
    state, questions = fallback.calls[0]
    context, label, image = state[0], state[1], state[2]
    assert context["buyer_search"] == "desk lamp"
    assert "central point" in context["definitions"]
    assert context["products"]["P1"]["card"] == "A desk lamp."
    assert label == "Photo of P1:"
    assert label in context["products"]["P1"]["photo"]
    assert state[3] == "Photo of P2:"
    assert len(state) == 5
    assert base64.b64decode(image["image_url"]["url"].split(",", 1)[1]) == photo.read_bytes()
    assert questions["P1"]["type"] == "noul"
    assert set(questions["P1"]["criteria"]) == {"true", "false"}


async def test_the_fallback_is_untouched_while_the_decision_model_answers(photo: Path) -> None:
    fallback = Recording()
    await gate(photo, StubJev(), fallback)
    assert fallback.calls == []


async def test_a_failed_fallback_costs_only_its_own_products(photo: Path) -> None:
    scores = await gate(photo, Failing(), Recording(OpenRouterError("503")))
    assert scores == {"lamp": 0.0, "chair": 0.0, "sofa": 0.0}


async def test_with_no_fallback_a_failed_call_counts_as_not_matching(photo: Path) -> None:
    assert await gate(photo, Failing(), None) == {"lamp": 0.0, "chair": 0.0, "sofa": 0.0}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def skip(_: float) -> None:
        return None

    monkeypatch.setattr(openrouter, "sleep", skip)


def client(
    tmp_path: Path, answers: list[httpx.Response], cap: float = 1.0, name: str = "ledger.jsonl"
) -> tuple[OpenRouterClient, SpendLedger, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    remaining = iter(answers)

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(remaining)

    ledger = SpendLedger.open(tmp_path / name, cap)
    http = httpx.AsyncClient(base_url=openrouter.BASE_URL, transport=httpx.MockTransport(respond))
    return OpenRouterClient(http=http, ledger=ledger, decider="perplexity/pplx-decider-v1.2"), ledger, seen


ANSWER = {
    "answers": {"P1": {"type": "noul", "noul": 0.9}},
    "usage": {"input_tokens": 500, "output_tokens": 1, "cost": 0.00001},
}
QUESTION = {"P1": {"type": "noul", "instructions": "Is it a lamp?"}}


async def test_the_decider_sends_the_documented_request_and_charges_its_cost(tmp_path: Path) -> None:
    models, ledger, seen = client(tmp_path, [httpx.Response(200, json=ANSWER)])
    scores = await models.decide(["a card", "Photo of P1:"], QUESTION, purpose="test")
    assert scores == {"P1": 0.9}
    assert str(seen[0].url) == DECISIONS_URL
    body = json.loads(seen[0].content)
    assert body["model"] == "perplexity/pplx-decider-v1.2"
    assert body["questions"] == QUESTION
    assert body["state"] == ["a card", "Photo of P1:"]
    assert ledger.total_usd == pytest.approx(0.00001)


async def test_the_decider_retries_a_rate_limit_and_raises_on_an_error(tmp_path: Path) -> None:
    models, _, seen = client(
        tmp_path, [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=ANSWER)]
    )
    assert await models.decide("state", QUESTION, purpose="test") == {"P1": 0.9}
    assert len(seen) == 2
    models, ledger, _ = client(tmp_path, [httpx.Response(400, json={"error": {"message": "bad"}})], name="failed.jsonl")
    with pytest.raises(OpenRouterError, match="400"):
        await models.decide("state", QUESTION, purpose="test")
    assert ledger.total_usd == 0


async def test_a_spent_budget_stops_the_decider_before_it_calls(tmp_path: Path) -> None:
    models, _, seen = client(tmp_path, [], cap=0.0)
    with pytest.raises(BudgetExceededError):
        await models.decide("state", QUESTION, purpose="test")
    assert seen == []
