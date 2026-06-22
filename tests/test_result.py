from collections.abc import Callable

import pytest
from clingo import Function

from elenctic.result import (
    Consistent,
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalEnumeration,
    ConsistentOptimum,
    ConsistentShownCensus,
    ConsistentShownOptimalCensus,
    ConsistentWitness,
    Determination,
    Field,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    SeamError,
    Verdict,
    brave_of,
    brave_optimal_of,
    cautious_of,
    cautious_optimal_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    shown_census_of,
    shown_optimal_census_of,
    witness_of,
)

# --- Observable / Verdict (unchanged) ---


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


def test_consistent_base_is_abstract() -> None:
    # the depth-D invariant: only the six concrete shapes are inhabitable, never a bare Consistent
    with pytest.raises(TypeError, match="abstract"):
        Consistent()


def test_determination_three_arm_match_is_total() -> None:
    # the mandatory trichotomy (aspis §5.1): match the arm before reading any field. That this
    # function type-checks with no fall-through is the proof the 3-arm dispatch is exhaustive.
    def classify(determination: Determination) -> str:
        match determination:
            case Inconsistent():
                return "inconsistent"
            case Inconclusive():
                return "inconclusive"
            case Consistent():
                return "consistent"

    assert classify(Inconsistent()) == "inconsistent"
    assert classify(Inconclusive()) == "inconclusive"
    assert classify(ConsistentWitness(_obs("a"))) == "consistent"


def test_field_vocabulary_is_the_eight_capabilities() -> None:
    # these strings surface in explain/--dry-run output — pin them, not just the count. The census
    # splits into a shown view (projection-invariant) and a full view (multiplicity/assignment).
    assert {field.value for field in Field} == {
        "witness",
        "shown census",
        "full census",
        "cautious",
        "brave",
        "shown optimal census",
        "full optimal census",
        "optimum",
    }


# --- the Optimum proof-token ---


def test_optimum_carries_the_priority_vector() -> None:
    assert Optimum((4, 2)).cost == (4, 2)
    assert ConsistentOptimum(Optimum((7,))).optimum.cost == (7,)


def test_optimum_rejects_an_empty_cost_vector() -> None:
    with pytest.raises(ValueError, match="cost"):
        Optimum(())


# --- accessor seam: success on the shapes that populate the field ---


def test_witness_of_reads_the_default_witness() -> None:
    witness = _obs("a")
    assert witness_of(ConsistentWitness(witness)) == witness


def test_observables_of_reads_the_enumeration_census() -> None:
    census = (_obs("a"), _obs("b"))
    assert observables_of(ConsistentEnumeration(census)) == census


def test_enumeration_derives_cautious_and_brave_from_the_census() -> None:
    a, b = Function("a"), Function("b")
    # census {a,b},{a} → ⋂ = {a} (cautious), ⋃ = {a,b} (brave); single source of truth
    enum = ConsistentEnumeration((Observable(frozenset({a, b})), Observable(frozenset({a}))))
    assert cautious_of(enum) == frozenset({a})
    assert brave_of(enum) == frozenset({a, b})


def test_cautious_of_reads_the_native_cautious_run() -> None:
    a = Function("a")
    assert cautious_of(ConsistentCautious(frozenset({a}))) == frozenset({a})


def test_brave_of_reads_the_native_brave_run() -> None:
    a = Function("a")
    assert brave_of(ConsistentBrave(frozenset({a}))) == frozenset({a})


def test_optimal_observables_of_reads_the_optimal_class() -> None:
    optimal = (_obs("a"),)
    assert optimal_observables_of(ConsistentOptimalEnumeration(optimal, Optimum((1,)))) == optimal


def test_optimal_class_derives_cautious_and_brave_consequences() -> None:
    a, b = Function("a"), Function("b")
    # optimal census {a,b},{a} → ⋂ Opt = {a}, ⋃ Opt = {a,b} (the optimal-base counterparts of ⋂/⋃)
    opt = ConsistentOptimalEnumeration(
        (Observable(frozenset({a, b})), Observable(frozenset({a}))), Optimum((1,))
    )
    assert cautious_optimal_of(opt) == frozenset({a})
    assert brave_optimal_of(opt) == frozenset({a, b})


def test_optimal_consequence_accessors_seam_off_a_non_optimal_shape() -> None:
    # they read the shown optimal census, so a non-optimal shape seams (via shown_optimal_census_of)
    for accessor in (cautious_optimal_of, brave_optimal_of):
        with pytest.raises(SeamError, match="shown optimal census"):
            accessor(ConsistentCautious(frozenset()))


def test_optimum_of_reads_single_and_class() -> None:
    assert optimum_of(ConsistentOptimum(Optimum((1,)))).cost == (1,)
    assert optimum_of(ConsistentOptimalEnumeration((_obs("a"),), Optimum((2,)))).cost == (2,)


# --- accessor seam: SeamError off a shape that does not populate the field ---


@pytest.mark.parametrize(
    ("accessor", "shape", "field_word"),
    [
        pytest.param(witness_of, ConsistentCautious(frozenset()), "witness", id="witness"),
        pytest.param(
            shown_census_of, ConsistentCautious(frozenset()), "shown census", id="shown-census"
        ),
        pytest.param(
            observables_of, ConsistentCautious(frozenset()), "full census", id="full-census"
        ),
        pytest.param(cautious_of, ConsistentBrave(frozenset()), "cautious", id="cautious"),
        pytest.param(brave_of, ConsistentCautious(frozenset()), "brave", id="brave"),
        pytest.param(
            shown_optimal_census_of,
            ConsistentCautious(frozenset()),
            "shown optimal census",
            id="shown-optimal-census",
        ),
        pytest.param(
            optimal_observables_of,
            ConsistentOptimum(Optimum((1,))),
            "full optimal census",
            id="full-optimal-census",
        ),
        pytest.param(optimum_of, ConsistentCautious(frozenset()), "optimum", id="optimum"),
    ],
)
def test_accessor_off_wrong_shape_raises_seam_error(
    accessor: Callable[[Consistent], object], shape: Consistent, field_word: str
) -> None:
    with pytest.raises(SeamError, match=field_word):
        accessor(shape)


def test_seam_error_is_a_harness_error_never_a_verdict() -> None:
    # category lock: harness bugs share one root (distinct from any Verdict, which is a CheckReport)
    assert issubclass(SeamError, HarnessError)


# --- the result-shape invariant: Consistent ⟹ ≥1 model ---


def test_consistent_enumeration_requires_a_nonempty_census() -> None:
    with pytest.raises(ValueError, match="observable"):
        ConsistentEnumeration(())


def test_consistent_optimal_enumeration_requires_a_nonempty_class() -> None:
    with pytest.raises(ValueError, match="optimal"):
        ConsistentOptimalEnumeration((), Optimum((1,)))


# --- the projected shapes and the shown-census accessors (the field split) ---


def test_shown_census_accessor_is_total_over_both_enumeration_shapes_and_agrees() -> None:
    # shown_census_of returns the SET of shown projections — derived on the full shape, stored on
    # the projected shape — and the two agree on the same census.
    a, b = Function("a"), Function("b")
    full = ConsistentEnumeration((Observable(frozenset({a})), Observable(frozenset({b}))))
    projected = ConsistentShownCensus(frozenset({frozenset({a}), frozenset({b})}))
    assert shown_census_of(full) == frozenset({frozenset({a}), frozenset({b})})
    assert shown_census_of(projected) == shown_census_of(full)


def test_observables_of_narrows_to_the_full_shape_only() -> None:
    # The full census (with multiplicity/assignment) is readable only off the full shape; reading it
    # off the projected shown-only shape is a SeamError by construction.
    with pytest.raises(SeamError):
        observables_of(ConsistentShownCensus(frozenset({frozenset({Function("a")})})))


def test_consequence_views_derive_from_either_enumeration_shape() -> None:
    # ⋂/⋃ are functions of the shown-census SET, so they read both the full and projected shapes.
    a, b, c = Function("a"), Function("b"), Function("c")
    projected = ConsistentShownCensus(frozenset({frozenset({a, c}), frozenset({b, c})}))
    assert cautious_of(projected) == frozenset({c})  # ⋂ derived from the shown set
    assert brave_of(projected) == frozenset({a, b, c})  # ⋃ derived from the shown set


def test_projected_optimal_shape_carries_optimum_and_withholds_the_full_class() -> None:
    shape = ConsistentShownOptimalCensus(frozenset({frozenset({Function("a")})}), Optimum((1,)))
    assert optimum_of(shape).cost == (1,)
    assert shown_optimal_census_of(shape) == frozenset({frozenset({Function("a")})})
    with pytest.raises(SeamError):
        optimal_observables_of(shape)  # the full optimal class is withheld
