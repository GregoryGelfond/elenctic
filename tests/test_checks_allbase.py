"""Unit tests for the all-base and scalar checks (spec §3; plan Task 4 / dx#9).

Each check is a pure ``Check`` — a callable carrying its contract-tag ``label`` — that
maps a ``SolveResult`` to a ``CheckReport``: a three-valued ``Verdict`` plus the diagnostic
the dx#9 layer surfaces (the ``label`` and an expected-vs-actual ``message``). Checks are
pure over ``SolveResult``, so they test with no solver (spec §4).
"""

import pytest
from clingo import Symbol, parse_term

from elenctic.checks import (
    Check,
    CheckReport,
    assign_contains,
    brave_contains,
    cautious_contains,
    cost_is,
    count_is,
    expect_sat,
    expect_unsat,
    has_model,
)
from elenctic.result import Observable, SolveResult, Verdict


def obs(*names: str) -> Observable:
    return Observable(frozenset(parse_term(name) for name in names))


def lits(*names: str) -> frozenset[Symbol]:
    return frozenset(parse_term(name) for name in names)


def test_check_returns_checkreport_with_verdict_and_label() -> None:
    report = expect_sat()(SolveResult(completed=True, observables=(obs("a"),)))
    assert isinstance(report, CheckReport)
    assert report.verdict is Verdict.PASS
    assert report.label == "@expect sat"


@pytest.mark.parametrize(
    ("check", "label"),
    [
        pytest.param(expect_sat(), "@expect sat", id="expect-sat"),
        pytest.param(expect_unsat(), "@expect unsat", id="expect-unsat"),
        pytest.param(has_model(lits("a")), "@model", id="model"),
        pytest.param(count_is(1), "@count", id="count"),
        pytest.param(cautious_contains(lits("a")), "@cautious", id="cautious"),
        pytest.param(brave_contains(lits("a")), "@brave", id="brave"),
        pytest.param(cost_is((1,)), "@cost", id="cost"),
        pytest.param(assign_contains(frozenset({(parse_term("x"), 1)})), "@assign", id="assign"),
    ],
)
def test_undecided_when_not_completed(check: Check, label: str) -> None:
    report = check(SolveResult(completed=False))
    assert report.verdict is Verdict.UNDECIDED  # a timeout is never FAIL (§7a)
    assert report.label == label


def test_check_label_is_readable_without_solving() -> None:
    # dx#9 / C: the contract-tag label is a first-class attribute on the check itself, so a
    # consumer can identify or explain a check before any solve (no SolveResult needed).
    assert expect_sat().label == "@expect sat"
    assert has_model(lits("a")).label == "@model"
    assert cautious_contains(lits("a")).label == "@cautious"


def test_expect_sat() -> None:
    assert expect_sat()(SolveResult(True, observables=(obs("a"),))).verdict is Verdict.PASS
    failed = expect_sat()(SolveResult(True, observables=()))
    assert failed.verdict is Verdict.FAIL  # AS(P) = ∅ is the regression catch
    assert "∅" in failed.message


def test_expect_unsat() -> None:
    assert expect_unsat()(SolveResult(True, observables=())).verdict is Verdict.PASS
    failed = expect_unsat()(SolveResult(True, observables=(obs("a"),)))
    assert failed.verdict is Verdict.FAIL
    assert "a" in failed.message  # the witnessing model is surfaced


def test_expect_unsat_witness_is_canonical_not_enumeration_order() -> None:
    # The surfaced witness is canonical (min by text), independent of solver enumeration order,
    # so the dx#9 message is reproducible (MINOR-7).
    result = SolveResult(True, observables=(obs("b"), obs("a")))
    report = expect_unsat()(result)
    assert report.verdict is Verdict.FAIL
    assert "{ a }" in report.message  # canonical min witness …
    assert "{ b }" not in report.message  # … not observables[0]


def test_has_model_is_existential_over_whole_shown_model_and_total() -> None:
    result = SolveResult(True, observables=(obs("a", "b"), obs("c")))
    assert has_model(lits("a", "b"))(result).verdict is Verdict.PASS
    partial = has_model(lits("a"))(result)
    assert partial.verdict is Verdict.FAIL  # the whole shown model, not a subset
    assert "a" in partial.message
    empty = has_model(lits("a"))(SolveResult(True, observables=()))
    assert empty.verdict is Verdict.FAIL  # total on the empty base


def test_count_is_total_at_both_ends() -> None:
    two = SolveResult(True, observables=(obs("a"), obs("b")))
    assert count_is(2)(two).verdict is Verdict.PASS
    missed = count_is(2)(SolveResult(True, observables=()))
    assert missed.verdict is Verdict.FAIL
    assert "2" in missed.message and "0" in missed.message  # expected 2, got 0
    assert count_is(0)(SolveResult(True, observables=())).verdict is Verdict.PASS  # @count 0 over ∅


def test_cautious_reads_intersection_and_is_total_on_none() -> None:
    present = SolveResult(True, intersection=lits("a", "b"))
    assert cautious_contains(lits("a"))(present).verdict is Verdict.PASS
    missing = cautious_contains(lits("c"))(present)
    assert missing.verdict is Verdict.FAIL
    assert "c" in missing.message and "⋂" in missing.message
    none = cautious_contains(lits("a"))(SolveResult(True, intersection=None))
    assert none.verdict is Verdict.FAIL  # empty base: never evaluate L ⊆ None


def test_brave_reads_union_and_is_total_on_none() -> None:
    present = SolveResult(True, union=lits("a", "b"))
    assert brave_contains(lits("a"))(present).verdict is Verdict.PASS
    missing = brave_contains(lits("c"))(present)
    assert missing.verdict is Verdict.FAIL
    assert "c" in missing.message and "⋃" in missing.message
    none = brave_contains(lits("a"))(SolveResult(True, union=None))
    assert none.verdict is Verdict.FAIL


def test_cost_compares_the_vector_by_value() -> None:
    assert cost_is((4, 2))(SolveResult(True, optimum_cost=(4, 2))).verdict is Verdict.PASS
    missed = cost_is((4, 2))(SolveResult(True, optimum_cost=(4, 3)))
    assert missed.verdict is Verdict.FAIL
    assert "4" in missed.message
    none = cost_is((4, 2))(SolveResult(True, optimum_cost=None))
    assert none.verdict is Verdict.FAIL  # no optimization run populated a cost


def test_assign_is_existential_over_observables() -> None:
    target = frozenset({(parse_term("digit(s)"), 9)})
    result = SolveResult(True, observables=(Observable(frozenset(), target),))
    assert assign_contains(target)(result).verdict is Verdict.PASS
    missed = assign_contains(frozenset({(parse_term("digit(s)"), 1)}))(result)
    assert missed.verdict is Verdict.FAIL
    assert "digit(s)" in missed.message
    empty = assign_contains(target)(SolveResult(True, observables=()))
    assert empty.verdict is Verdict.FAIL  # total on the empty base
