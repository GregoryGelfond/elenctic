"""Unit tests for the all-base and scalar checks (spec §3, dx#9).

Each check is a pure ``Check`` mapping a ``Determination`` to a ``CheckReport`` (a three-valued
``Verdict`` plus the dx#9 diagnostic). A check dispatches on the arm — ``Inconclusive`` → UNDECIDED
(§7a), ``Inconsistent`` → the AS(P)=∅ verdict, ``Consistent`` → the per-tag decision read through
the accessor seam. Pure over a ``Determination``; tested with no solver (spec §4).
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
from elenctic.expectation import WitnessClaim
from elenctic.result import (
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimum,
    ConsistentWitness,
    Field,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    Verdict,
)


def obs(*names: str) -> Observable:
    return Observable(frozenset(parse_term(name) for name in names))


def lits(*names: str) -> frozenset[Symbol]:
    return frozenset(parse_term(name) for name in names)


def wm(*names: str) -> WitnessClaim:
    return WitnessClaim(shown=lits(*names))


def enum(*observables: Observable) -> ConsistentEnumeration:
    return ConsistentEnumeration(observables)


def test_check_returns_checkreport_with_verdict_and_label() -> None:
    report = expect_sat()(enum(obs("a")))
    assert isinstance(report, CheckReport)
    assert report.verdict is Verdict.PASS
    assert report.label == "@expect sat"


@pytest.mark.parametrize(
    ("check", "label"),
    [
        pytest.param(expect_sat(), "@expect sat", id="expect-sat"),
        pytest.param(expect_unsat(), "@expect unsat", id="expect-unsat"),
        pytest.param(has_model(wm("a")), "@model", id="model"),
        pytest.param(count_is(1), "@count", id="count"),
        pytest.param(cautious_contains(lits("a")), "@cautious", id="cautious"),
        pytest.param(brave_contains(lits("a")), "@brave", id="brave"),
        pytest.param(cost_is((1,)), "@cost", id="cost"),
        pytest.param(assign_contains(frozenset({(parse_term("x"), 1)})), "@assign", id="assign"),
    ],
)
def test_undecided_when_inconclusive(check: Check, label: str) -> None:
    report = check(Inconclusive())
    assert report.verdict is Verdict.UNDECIDED  # a timeout is never FAIL (§7a)
    assert report.label == label


def test_check_label_is_readable_without_solving() -> None:
    # dx#9 / option C: the contract-tag label is a first-class attribute, readable before any solve.
    assert expect_sat().label == "@expect sat"
    assert has_model(wm("a")).label == "@model"
    assert cautious_contains(lits("a")).label == "@cautious"


def test_check_declares_what_it_reads_statically() -> None:
    # the wiring rule's LHS: reads is statically inspectable, no solve needed.
    assert expect_sat().reads == frozenset()
    assert cautious_contains(lits("a")).reads == frozenset({Field.CAUTIOUS})
    assert brave_contains(lits("a")).reads == frozenset({Field.BRAVE})
    assert has_model(wm("a")).reads == frozenset({Field.SHOWN_CENSUS})
    assert count_is(2).reads == frozenset({Field.FULL_CENSUS})
    assign_reads = assign_contains(frozenset({(parse_term("x"), 1)})).reads
    assert assign_reads == frozenset({Field.FULL_CENSUS})
    assert cost_is((1,)).reads == frozenset({Field.OPTIMUM})
    assert expect_unsat().reads == frozenset({Field.WITNESS})


def test_expect_sat() -> None:
    assert expect_sat()(enum(obs("a"))).verdict is Verdict.PASS
    failed = expect_sat()(Inconsistent())
    assert failed.verdict is Verdict.FAIL  # AS(P) = ∅ is the regression catch
    assert "∅" in failed.message


def test_expect_unsat() -> None:
    assert expect_unsat()(Inconsistent()).verdict is Verdict.PASS
    failed = expect_unsat()(ConsistentWitness(obs("a")))
    assert failed.verdict is Verdict.FAIL
    assert "a" in failed.message  # the witnessing model is surfaced


def test_has_model_is_existential_over_whole_shown_model_and_total() -> None:
    result = enum(obs("a", "b"), obs("c"))
    assert has_model(wm("a", "b"))(result).verdict is Verdict.PASS
    partial = has_model(wm("a"))(result)
    assert partial.verdict is Verdict.FAIL  # the whole shown model, not a subset
    assert "a" in partial.message
    empty = has_model(wm("a"))(Inconsistent())
    assert empty.verdict is Verdict.FAIL  # AS(P) = ∅ arm


def test_count_is_total_at_both_ends() -> None:
    two = enum(obs("a"), obs("b"))
    assert count_is(2)(two).verdict is Verdict.PASS
    missed = count_is(2)(Inconsistent())
    assert missed.verdict is Verdict.FAIL
    assert "2" in missed.message and "0" in missed.message  # expected 2, got 0
    assert count_is(0)(Inconsistent()).verdict is Verdict.PASS  # @count 0 ⟺ unsat
    wrong = count_is(2)(enum(obs("a"), obs("b"), obs("c")))
    assert wrong.verdict is Verdict.FAIL  # wrong count on a Consistent enumeration
    assert "2" in wrong.message and "3" in wrong.message  # expected 2, got 3


def test_cautious_reads_intersection_and_is_total_on_unsat() -> None:
    present = ConsistentCautious(lits("a", "b"))
    assert cautious_contains(lits("a"))(present).verdict is Verdict.PASS
    missing = cautious_contains(lits("c"))(present)
    assert missing.verdict is Verdict.FAIL
    assert "c" in missing.message and "⋂" in missing.message
    unsat = cautious_contains(lits("a"))(Inconsistent())
    assert unsat.verdict is Verdict.FAIL  # AS(P) = ∅ arm; never evaluate L ⊆ (missing)


def test_brave_reads_union_and_is_total_on_unsat() -> None:
    present = ConsistentBrave(lits("a", "b"))
    assert brave_contains(lits("a"))(present).verdict is Verdict.PASS
    missing = brave_contains(lits("c"))(present)
    assert missing.verdict is Verdict.FAIL
    assert "c" in missing.message and "⋃" in missing.message
    unsat = brave_contains(lits("a"))(Inconsistent())
    assert unsat.verdict is Verdict.FAIL


def test_cost_compares_the_vector_by_value() -> None:
    assert cost_is((4, 2))(ConsistentOptimum(Optimum((4, 2)))).verdict is Verdict.PASS
    missed = cost_is((4, 2))(ConsistentOptimum(Optimum((4, 3))))
    assert missed.verdict is Verdict.FAIL
    assert "4" in missed.message
    unsat = cost_is((4, 2))(Inconsistent())
    assert unsat.verdict is Verdict.FAIL  # no optimum — AS(P) = ∅


def test_assign_is_existential_over_observables() -> None:
    target = frozenset({(parse_term("digit(s)"), 9)})
    result = enum(Observable(frozenset(), target))
    assert assign_contains(target)(result).verdict is Verdict.PASS
    missed = assign_contains(frozenset({(parse_term("digit(s)"), 1)}))(result)
    assert missed.verdict is Verdict.FAIL
    assert "digit(s)" in missed.message
    empty = assign_contains(target)(Inconsistent())
    assert empty.verdict is Verdict.FAIL  # AS(P) = ∅ arm


def test_assign_finds_a_match_among_multiple_observables() -> None:
    target = frozenset({(parse_term("x"), 2)})
    result = enum(
        Observable(frozenset(), frozenset({(parse_term("x"), 1)})),
        Observable(frozenset(), frozenset({(parse_term("x"), 2)})),
    )
    assert assign_contains(target)(result).verdict is Verdict.PASS  # matches the 2nd observable


def test_where_witness_couples_shown_and_assignment_on_one_model() -> None:
    # The joint witness binds shown AND assignment to ONE model: shown matching on a different model
    # than the one carrying the assignment is a FAIL (stronger than the two tags separately).
    claim = WitnessClaim(
        shown=frozenset({parse_term("a")}), assign=frozenset({(parse_term("v"), 1)})
    )
    coupled = enum(Observable(frozenset({parse_term("a")}), frozenset({(parse_term("v"), 1)})))
    split = enum(
        Observable(frozenset({parse_term("a")}), frozenset({(parse_term("v"), 9)})),
        Observable(frozenset({parse_term("b")}), frozenset({(parse_term("v"), 1)})),
    )
    assert has_model(claim)(coupled).verdict is Verdict.PASS
    assert has_model(claim)(split).verdict is Verdict.FAIL
