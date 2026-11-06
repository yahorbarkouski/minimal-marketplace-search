"""Measures the search on fixed searches that its question and thresholds were never tuned on.

`curated benchmark run` runs each search in `benchmark/searches.jsonl` once, one at a time, and saves what it showed,
what the gate said, what it cost and how long it took. `curated benchmark pool` lists the pairs of search and product
that have no grade yet. `curated benchmark score` compares a run with `benchmark/grades.jsonl`, which holds what blind
judges said of each pair, and costs nothing.

A product counts as good when its judges' mean grade is at least 2 of 3. Only graded products count: the scores say
how much of the first ten was graded, and recall means the share of the graded good products the page showed.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from curated.cache import cache_key
from curated.ledger import SpendLedger
from curated.providers.jev import JevClient
from curated.providers.openrouter import OpenRouterClient
from curated.runlog import Run
from curated.search.searcher import Searcher, SearchIndex
from curated.settings import Settings

GOOD_GRADE = 2
MAX_GRADE = 3
TOP = 10
POOL_REST = 5
POOL_UNDER = 5
POOL_SEED = 17
BENCHMARK_CAP_USD = 0.5
"""Dollars one benchmark run may spend before it stops itself: about 100 searches."""

Pair = tuple[str, str]


@dataclass(frozen=True)
class SearchRun:
    """One search as a benchmark run saved it."""

    search: str
    kind: str
    shown: tuple[str, ...]
    gate: Mapping[str, float]
    first_ms: float | None
    total_ms: float
    cost: float


def load_searches(path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_grades(path: Path) -> dict[Pair, dict[str, int]]:
    """Each pair of search and product, with each judge's grade."""
    grades: defaultdict[Pair, dict[str, int]] = defaultdict(dict)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                grades[row["search"], row["product_id"]][row["judge"]] = row["grade"]
    return dict(grades)


def load_run(results: Path) -> list[SearchRun]:
    saved = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [
        SearchRun(
            search=row["id"],
            kind=row["kind"],
            shown=tuple(row["shown"]),
            gate=row["gate"],
            first_ms=row["first_ms"],
            total_ms=row["total_ms"],
            cost=row["cost"],
        )
        for row in saved
    ]


def run_directory(settings: Settings, name: str) -> Path:
    return settings.runs_dir / f"benchmark-{name}"


def run_config(settings: Settings) -> dict[str, Any]:
    """What a run's results depend on; a run directory refuses to continue under a different one."""
    return {"sizes": cache_key("sizes", repr(settings.sizes)), "models": cache_key("models", repr(settings.models))}


async def run_benchmark(settings: Settings, *, searches: Path, name: str, limit: int | None) -> Path:
    """Runs the searches not yet saved under `name`, one at a time, so each time is the time of one search."""
    directory = run_directory(settings, name)
    index = SearchIndex.load(settings)
    ledger = SpendLedger.open(settings.ledger_path, settings.budget_usd)
    wanted = load_searches(searches)
    async with OpenRouterClient.connect(ledger) as openrouter, JevClient.connect(ledger, settings.models) as jev:
        with Run(str(directory), config=run_config(settings), max_cost=BENCHMARK_CAP_USD) as run:
            for item in run.todo(wanted, id_of=lambda row: row["search"], limit=limit):
                before = ledger.total_usd
                # A searcher of its own, so no search finds its interpretation cached.
                searcher = Searcher(index, settings=settings, openrouter=openrouter, jev=jev)
                try:
                    trace, _ = await searcher.begin(item["search"], on_first_results=lambda _: None)
                except Exception as error:
                    run.fail(item["search"], error, cost=ledger.total_usd - before)
                    continue
                first = trace.timings_ms.get("first_results") if trace.first_results else None
                run.save(
                    item["search"],
                    {
                        "kind": item["kind"],
                        "shown": list(trace.shown),
                        "gate": trace.gate,
                        "first_ms": first,
                        "total_ms": trace.timings_ms["total"],
                        "interpretation": trace.interpretation,
                    },
                    cost=ledger.total_usd - before,
                )
    return directory / "results.jsonl"


def pool(runs: Iterable[SearchRun], graded: Mapping[Pair, Any]) -> list[Pair]:
    """The pairs worth grading that have no grade: each page's first ten, a few from the rest of it, and the products
    just under its line, which is where the page may have lost good ones."""
    pairs: list[Pair] = []
    chooser = random.Random(POOL_SEED)
    for run in runs:
        rest = list(run.shown[TOP:])
        sampled = chooser.sample(rest, min(POOL_REST, len(rest)))
        shown = set(run.shown)
        under = sorted((i for i in run.gate if i not in shown), key=lambda i: -run.gate[i])[:POOL_UNDER]
        pairs += [(run.search, i) for i in [*run.shown[:TOP], *sampled, *under] if (run.search, i) not in graded]
    return pairs


def mean_grade(judges: Mapping[str, int]) -> float:
    return sum(judges.values()) / len(judges)


def ndcg(shown: Sequence[str], grades: Mapping[str, float], *, top: int = TOP) -> float | None:
    """How well the first `top` graded products are ordered against the best order of everything graded for this
    search, from 0 to 1. Ungraded products are skipped; None when nothing graded is good."""
    gains = [grades[i] for i in shown if i in grades][:top]
    ideal = sorted(grades.values(), reverse=True)[:top]

    def discounted(values: Sequence[float]) -> float:
        return sum((2**value - 1) / math.log2(place + 2) for place, value in enumerate(values))

    best = discounted(ideal)
    return discounted(gains) / best if best else None


def score_search(run: SearchRun, graded: Mapping[Pair, Mapping[str, int]]) -> dict[str, Any]:
    """One search's numbers; a number is None when its search gives it nothing to measure."""
    grades = {i: mean_grade(judges) for (search, i), judges in graded.items() if search == run.search}
    top = [i for i in run.shown[:TOP] if i in grades]
    shown = [i for i in run.shown if i in grades]
    good = {i for i, grade in grades.items() if grade >= GOOD_GRADE}
    return {
        "search": run.search,
        "kind": run.kind,
        "shown": len(run.shown),
        "precision_top": sum(i in good for i in top) / len(top) if top else None,
        "graded_top": len(top) / min(TOP, len(run.shown)) if run.shown else None,
        "good_share": sum(i in good for i in shown) / len(shown) if shown else None,
        "recall": sum(i in good for i in shown) / len(good) if good else None,
        "ndcg": ndcg(run.shown, grades),
    }


def agreement(graded: Mapping[Pair, Mapping[str, int]]) -> dict[str, float] | None:
    """How often two judges agree on the pairs both graded, and the chance-corrected kappa on good or not."""
    pairs = [tuple(judges.values())[:2] for judges in graded.values() if len(judges) >= 2]
    if not pairs:
        return None
    same = sum(a == b for a, b in pairs) / len(pairs)
    close = sum(abs(a - b) <= 1 for a, b in pairs) / len(pairs)
    together = sum((a >= GOOD_GRADE) == (b >= GOOD_GRADE) for a, b in pairs) / len(pairs)
    first = sum(a >= GOOD_GRADE for a, _ in pairs) / len(pairs)
    second = sum(b >= GOOD_GRADE for _, b in pairs) / len(pairs)
    chance = first * second + (1 - first) * (1 - second)
    return {
        "pairs": len(pairs),
        "same_grade": same,
        "within_one": close,
        "same_good_or_not": together,
        "kappa": (together - chance) / (1 - chance) if chance < 1 else 1.0,
    }


def _mean(values: Iterable[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) / len(known) if known else None


def score_run(runs: Sequence[SearchRun], graded: Mapping[Pair, Mapping[str, int]]) -> dict[str, Any]:
    """The run's numbers overall and by kind of search, each search counting the same."""
    searches = [score_search(run, graded) for run in runs]

    def summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        keys = ("precision_top", "graded_top", "good_share", "recall", "ndcg")
        return {
            "searches": len(rows),
            "empty_pages": sum(row["shown"] == 0 for row in rows),
            "median_shown": statistics.median(row["shown"] for row in rows),
        } | {key: _mean(row[key] for row in rows) for key in keys}

    kinds: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in searches:
        kinds[row["kind"]].append(row)
    firsts = [run.first_ms for run in runs if run.first_ms is not None]
    return {
        "overall": summary(searches),
        "by_kind": {kind: summary(rows) for kind, rows in kinds.items()},
        "searches": searches,
        "agreement": agreement(graded),
        "mean_cost": sum(run.cost for run in runs) / len(runs),
        "max_cost": max(run.cost for run in runs),
        "median_page_ms": statistics.median(run.total_ms for run in runs),
        "max_page_ms": max(run.total_ms for run in runs),
        "median_first_ms": statistics.median(firsts) if firsts else None,
        "with_early_product": len(firsts),
    }


def report(scores: Mapping[str, Any]) -> str:
    """The numbers as text; `-` where a number has nothing to measure."""

    def number(value: float | None, percent: bool = False) -> str:
        if value is None:
            return "-"
        return f"{value:.0%}" if percent else f"{value:.2f}"

    header = (
        f"{'':16}{'searches':>9}{'P@10':>7}{'graded':>8}{'nDCG@10':>9}{'recall':>8}{'median shown':>14}{'empty':>7}"
    )
    lines = [header]

    def row(name: str, values: Mapping[str, Any]) -> str:
        return (
            f"{name:16}{values['searches']:>9}{number(values['precision_top'], True):>7}"
            f"{number(values['graded_top'], True):>8}{number(values['ndcg']):>9}"
            f"{number(values['recall'], True):>8}{values['median_shown']:>14g}{values['empty_pages']:>7}"
        )

    lines.append(row("all", scores["overall"]))
    lines += [row(kind, values) for kind, values in sorted(scores["by_kind"].items())]
    lines.append("")
    lines.append(f"cost per search: ${scores['mean_cost']:.4f} mean, ${scores['max_cost']:.4f} max")
    lines.append(f"full page: {scores['median_page_ms'] / 1000:.2f} s median, {scores['max_page_ms'] / 1000:.2f} s max")
    if scores["median_first_ms"] is not None:
        lines.append(
            f"first product: {scores['median_first_ms'] / 1000:.2f} s median, "
            f"on the {scores['with_early_product']} searches with an early product"
        )
    together = scores["agreement"]
    if together:
        lines.append(
            f"judges on {together['pairs']} pairs: same grade {together['same_grade']:.0%}, "
            f"within one {together['within_one']:.0%}, same good or not {together['same_good_or_not']:.0%}, "
            f"kappa {together['kappa']:.2f}"
        )
    return "\n".join(lines)
