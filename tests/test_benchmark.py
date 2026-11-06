"""The benchmark's arithmetic, on grades small enough to check by hand."""

import pytest

from curated.benchmark import SearchRun, agreement, ndcg, pool, score_run, score_search


def run(shown: tuple[str, ...], *, gate: dict[str, float] | None = None, search: str = "lamp") -> SearchRun:
    scores = gate if gate is not None else dict.fromkeys(shown, 0.9)
    return SearchRun(search=search, kind="mood", shown=shown, gate=scores, first_ms=None, total_ms=1000.0, cost=0.005)


GRADES = {
    ("lamp", "good"): {"a": 3, "b": 3},
    ("lamp", "fine"): {"a": 2, "b": 2},
    ("lamp", "bad"): {"a": 0, "b": 1},
    ("lamp", "missed"): {"a": 3, "b": 2},
    ("other", "good"): {"a": 0, "b": 0},
}


def test_a_search_scores_only_what_was_graded_and_only_its_own_grades() -> None:
    scores = score_search(run(("good", "bad", "ungraded")), GRADES)
    assert scores["precision_top"] == pytest.approx(1 / 2)
    assert scores["graded_top"] == pytest.approx(2 / 3)
    assert scores["recall"] == pytest.approx(1 / 3)


def test_judges_who_split_on_a_product_count_as_their_mean() -> None:
    split = {("lamp", "x"): {"a": 3, "b": 1}, ("lamp", "y"): {"a": 2, "b": 1}}
    scores = score_search(run(("x", "y")), split)
    assert scores["precision_top"] == pytest.approx(1 / 2)


def test_an_empty_page_loses_recall_and_measures_no_precision() -> None:
    scores = score_search(run(()), GRADES)
    assert scores["precision_top"] is None
    assert scores["recall"] == 0
    assert score_run([run(())], GRADES)["overall"]["empty_pages"] == 1


def test_ndcg_is_one_for_the_best_order_and_lower_for_a_worse_one() -> None:
    grades = {"a": 3.0, "b": 2.0, "c": 0.0}
    assert ndcg(("a", "b", "c"), grades) == pytest.approx(1.0)
    worst, middle = ndcg(("c", "b", "a"), grades), ndcg(("b", "a", "c"), grades)
    assert worst is not None
    assert middle is not None
    assert worst < middle < 1.0
    assert ndcg(("a",), {"a": 0.0}) is None


def test_agreement_corrects_for_chance() -> None:
    together = agreement({("s", "a"): {"x": 3, "y": 3}, ("s", "b"): {"x": 0, "y": 1}, ("s", "c"): {"x": 2, "y": 1}})
    assert together is not None
    assert together["pairs"] == 3
    assert together["same_grade"] == pytest.approx(1 / 3)
    assert together["within_one"] == 1.0
    assert together["same_good_or_not"] == pytest.approx(2 / 3)
    assert together["kappa"] == pytest.approx(0.4)
    assert agreement({("s", "a"): {"x": 3}}) is None


def test_the_pool_takes_the_first_ten_some_of_the_rest_and_the_nearest_misses() -> None:
    shown = tuple(f"p{i:02}" for i in range(30))
    gate = dict.fromkeys(shown, 0.9) | {"under-1": 0.34, "under-2": 0.2, "far": 0.01}
    pairs = pool([run(shown, gate=gate)], {("lamp", "p00"): {"a": 3}})
    ids = [product_id for _, product_id in pairs]
    assert "p00" not in ids
    assert set(shown[1:10]) <= set(ids)
    assert {"under-1", "under-2", "far"} <= set(ids)
    assert len(ids) == 9 + 5 + 3
    assert ids == [product_id for _, product_id in pool([run(shown, gate=gate)], {("lamp", "p00"): {"a": 3}})]
