from collections.abc import Callable

import pytest
from clingo import Function

from elenctic.result import (
    Consistent,
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalClass,
    ConsistentOptimum,
    ConsistentWitness,
    Field,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    SeamError,
    SolveResult,
    Verdict,
    brave_of,
    cautious_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    witness_of,
)


def test_observable_is_hashable_and_value_equal() -> None:
    a, b = Function("a"), Function("b")
    o1 = Observable(frozenset({a, b}))
    o2 = Observable(frozenset({b, a}))
    assert o1 == o2
    assert hash(o1) == hash(o2)
    assert len({o1, o2}) == 1  # dedups in a set


def test_observable_distinct_by_assignment() -> None:
    a = Function("a")
    o1 = Observable(frozenset({a}), frozenset({(Function("x"), 1)}))
    o2 = Observable(frozenset({a}), frozenset({(Function("x"), 2)}))
    assert o1 != o2  # spec §2.0: equal shown, different assign ⇒ distinct observables


def test_solveresult_defaults() -> None:
    r = SolveResult(completed=True)
    assert r.observables == ()
    assert r.optimal_observables == ()
    assert r.union is None
    assert r.intersection is None
    assert r.optimum_cost is None


def test_verdict_three_valued() -> None:
    assert len({Verdict.PASS, Verdict.FAIL, Verdict.UNDECIDED}) == 3


# --- the Determination arms (depth D) ---


def _obs(*names: str) -> Observable:
    return Observable(frozenset(Function(n) for n in names))


def test_consistent_shapes_are_consistent_others_are_not() -> None:
    assert isinstance(ConsistentWitness(_obs("a")), Consistent)
    assert isinstance(ConsistentCautious(frozenset()), Consistent)
    assert not isinstance(Inconsistent(), Consistent)
    assert not isinstance(Inconclusive(), Consistent)


def test_field_vocabulary_is_six_capabilities() -> None:
    assert len(set(Field)) == 6


# --- the Optimum proof-token ---


def test_optimum_carries_the_priority_vector() -> None:
    assert Optimum((4, 2)).cost == (4, 2)
    assert ConsistentOptimum(Optimum((7,))).optimum.cost == (7,)


# --- accessor seam: success on the shapes that populate the field ---


def test_witness_of_reads_the_default_witness() -> None:
    witness = _obs("a")
    assert witness_of(ConsistentWitness(witness)) == witness


def test_observables_of_reads_the_enumeration_census() -> None:
    census = (_obs("a"), _obs("b"))
    assert observables_of(ConsistentEnumeration(census, frozenset(), frozenset())) == census


def test_cautious_of_reads_native_and_enumeration() -> None:
    a = Function("a")
    assert cautious_of(ConsistentCautious(frozenset({a}))) == frozenset({a})
    enum = ConsistentEnumeration((_obs("a"),), frozenset({a}), frozenset())
    assert cautious_of(enum) == frozenset({a})


def test_brave_of_reads_native_and_enumeration() -> None:
    a = Function("a")
    assert brave_of(ConsistentBrave(frozenset({a}))) == frozenset({a})
    enum = ConsistentEnumeration((_obs("a"),), frozenset(), frozenset({a}))
    assert brave_of(enum) == frozenset({a})


def test_optimal_observables_of_reads_the_optimal_class() -> None:
    optimal = (_obs("a"),)
    assert optimal_observables_of(ConsistentOptimalClass(optimal, Optimum((1,)))) == optimal


def test_optimum_of_reads_single_and_class() -> None:
    assert optimum_of(ConsistentOptimum(Optimum((1,)))).cost == (1,)
    assert optimum_of(ConsistentOptimalClass((_obs("a"),), Optimum((2,)))).cost == (2,)


# --- accessor seam: SeamError off a shape that does not populate the field ---


@pytest.mark.parametrize(
    ("accessor", "shape", "field_word"),
    [
        pytest.param(witness_of, ConsistentCautious(frozenset()), "witness", id="witness"),
        pytest.param(
            observables_of, ConsistentCautious(frozenset()), "observables", id="observables"
        ),
        pytest.param(cautious_of, ConsistentBrave(frozenset()), "cautious", id="cautious"),
        pytest.param(brave_of, ConsistentCautious(frozenset()), "brave", id="brave"),
        pytest.param(
            optimal_observables_of,
            ConsistentOptimum(Optimum((1,))),
            "optimal observables",
            id="optimal-observables",
        ),
        pytest.param(optimum_of, ConsistentCautious(frozenset()), "optimum", id="optimum"),
    ],
)
def test_accessor_off_wrong_shape_raises_seam_error(
    accessor: Callable[[Consistent], object], shape: Consistent, field_word: str
) -> None:
    with pytest.raises(SeamError, match=field_word):
        accessor(shape)


# --- the result-shape invariant: Consistent ⟹ ≥1 model (Task 1 review carry) ---


def test_consistent_enumeration_requires_a_nonempty_census() -> None:
    with pytest.raises(ValueError, match="observable"):
        ConsistentEnumeration((), frozenset(), frozenset())


def test_consistent_optimal_class_requires_a_nonempty_class() -> None:
    with pytest.raises(ValueError, match="optimal"):
        ConsistentOptimalClass((), Optimum((1,)))
