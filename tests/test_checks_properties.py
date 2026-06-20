"""Hypothesis property tests for the check layer's load-bearing invariants (spec §3, §7a).

These pin the structural guarantees the example tests only sample: consequence-soundness (an
incomplete solve is *always* UNDECIDED, never FAIL/raise — the ``Inconclusive`` arm), the variadic
optimal aggregation (⋂/⋃ over the whole class equals the pairwise fold, singleton included), the
single-source label, and containment soundness (PASS iff ⊆).
"""

import functools
import operator

from clingo import Function, Symbol
from hypothesis import given
from hypothesis import strategies as st

from elenctic.checks import (
    Check,
    brave_contains,
    brave_optimal_contains,
    cautious_contains,
    cautious_optimal_contains,
    cost_is,
    count_is,
    count_optimal_is,
    expect_sat,
    expect_unsat,
    has_model,
    has_optimal_model,
    query_matches,
)
from elenctic.query import Answer, GroundQuery
from elenctic.result import (
    ConsistentCautious,
    ConsistentOptimalEnumeration,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    Verdict,
)

_atoms = st.builds(Function, st.sampled_from(["a", "b", "c", "d", "e"]))
_atom_sets = st.frozensets(_atoms, max_size=5)


def _every_check(litset: frozenset[Symbol]) -> list[Check]:
    """One instance of each public check, built from ``litset`` where a litset is needed."""
    return [
        expect_sat(),
        expect_unsat(),
        has_model(litset),
        count_is(len(litset)),
        cautious_contains(litset),
        brave_contains(litset),
        cost_is((1,)),
        has_optimal_model(litset),
        cautious_optimal_contains(litset),
        brave_optimal_contains(litset),
        count_optimal_is(1),
        query_matches(GroundQuery(Answer.yes, (Function("a"),))),
    ]


@given(_atom_sets)
def test_every_check_is_undecided_on_inconclusive(litset: frozenset[Symbol]) -> None:
    for check in _every_check(litset):
        assert check(Inconclusive()).verdict is Verdict.UNDECIDED  # §7a — never FAIL, never raises


@given(st.lists(_atom_sets, min_size=1, max_size=4))
def test_optimal_aggregation_equals_the_pairwise_fold(family: list[frozenset[Symbol]]) -> None:
    # The check's variadic ⋂/⋃ over Opt(P) must equal the pairwise fold for every family size —
    # singleton included (the ``family[0].intersection(*family[1:])`` edge).
    result = ConsistentOptimalEnumeration(tuple(Observable(s) for s in family), Optimum((0,)))
    meet: frozenset[Symbol] = functools.reduce(operator.and_, family)
    join: frozenset[Symbol] = functools.reduce(operator.or_, family)
    assert cautious_optimal_contains(meet)(result).verdict is Verdict.PASS
    assert brave_optimal_contains(join)(result).verdict is Verdict.PASS


@given(_atom_sets)
def test_static_label_equals_reported_label(litset: frozenset[Symbol]) -> None:
    # option C / single source: every check carries its label statically, and it is the SAME label
    # its CheckReport carries on every (field-free) arm — one source, no divergence.
    for check in _every_check(litset):
        assert check.label  # statically readable, non-empty
        assert check.label == check(Inconclusive()).label
        assert check.label == check(Inconsistent()).label


@given(_atom_sets, _atom_sets)
def test_cautious_passes_iff_subset(
    litset: frozenset[Symbol], aggregate: frozenset[Symbol]
) -> None:
    result = ConsistentCautious(aggregate)
    expected = Verdict.PASS if litset <= aggregate else Verdict.FAIL
    assert cautious_contains(litset)(result).verdict is expected
