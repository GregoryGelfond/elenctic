"""Hypothesis property tests for the check layer's load-bearing invariants (spec §3, §7a).

These pin the structural guarantees the example tests only sample: consequence-soundness (an
incomplete solve is *always* UNDECIDED, never FAIL/raise — the ``Inconclusive`` arm), the variadic
optimal aggregation (⋂/⋃ over the whole class equals the pairwise fold, singleton included), the
single-source label, containment soundness (PASS iff ⊆), and that the containment builders reject
an empty (vacuous) litset.
"""

import functools
import operator

import pytest
from clingo import Function, Symbol
from hypothesis import given
from hypothesis import strategies as st

from elenctic.checks import (
    Check,
    assign_contains,
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
from elenctic.expectation import WitnessClaim
from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var
from elenctic.result import (
    ConsistentBrave,
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
_litsets = st.frozensets(_atoms, min_size=1, max_size=5)  # a litset is non-empty (§2.1)


def _every_check(litset: frozenset[Symbol]) -> list[Check]:
    """One instance of each public check, built from ``litset`` (non-empty) where one is needed —
    every tag and every ``@query`` form, so §7a holds across the whole check surface."""
    goal = QueryLiteral("p", True, (Var("X"),))
    return [
        expect_sat(),
        expect_unsat(),
        has_model(WitnessClaim(shown=litset)),
        count_is(len(litset)),
        assign_contains(frozenset({(Function("a"), 1)})),
        cautious_contains(litset),
        brave_contains(litset),
        cost_is((1,)),
        has_optimal_model(WitnessClaim(shown=litset)),
        cautious_optimal_contains(litset),
        brave_optimal_contains(litset),
        count_optimal_is(1),
        query_matches(GroundQuery(Answer.yes, (Function("a"),))),  # singleton ground
        query_matches(GroundQuery(Answer.no, (Function("a"), Function("b")))),  # conjunctive
        query_matches(BindingQuery(Answer.yes, goal, frozenset())),  # binding settled
        query_matches(BindingQuery(Answer.unknown, goal, frozenset())),  # binding unknown
    ]


@given(_litsets)
def test_every_check_is_undecided_on_inconclusive(litset: frozenset[Symbol]) -> None:
    for check in _every_check(litset):
        assert check(Inconclusive()).verdict is Verdict.UNDECIDED  # §7a — never FAIL, never raises


@given(st.lists(_atom_sets, min_size=1, max_size=4))
def test_optimal_aggregation_equals_the_pairwise_fold(family: list[frozenset[Symbol]]) -> None:
    # The check's variadic ⋂/⋃ over Opt(P) must equal the pairwise fold for every family size —
    # singleton included. A common atom keeps meet/join non-empty (litsets are non-empty).
    common = Function("z")
    members = [members_set | {common} for members_set in family]
    result = ConsistentOptimalEnumeration(tuple(Observable(s) for s in members), Optimum((0,)))
    meet: frozenset[Symbol] = functools.reduce(operator.and_, members)
    join: frozenset[Symbol] = functools.reduce(operator.or_, members)
    assert cautious_optimal_contains(meet)(result).verdict is Verdict.PASS
    assert brave_optimal_contains(join)(result).verdict is Verdict.PASS


@given(_litsets)
def test_static_label_equals_reported_label(litset: frozenset[Symbol]) -> None:
    # option C / single source: every check carries its label statically, and it is the SAME label
    # its CheckReport carries on every (field-free) arm — one source, no divergence.
    for check in _every_check(litset):
        assert check.label  # statically readable, non-empty
        assert check.label == check(Inconclusive()).label
        assert check.label == check(Inconsistent()).label


@given(_litsets, _atom_sets)
def test_cautious_passes_iff_subset(
    litset: frozenset[Symbol], aggregate: frozenset[Symbol]
) -> None:
    result = ConsistentCautious(aggregate)
    expected = Verdict.PASS if litset <= aggregate else Verdict.FAIL
    assert cautious_contains(litset)(result).verdict is expected


@given(_litsets, _atom_sets)
def test_brave_passes_iff_subset(litset: frozenset[Symbol], aggregate: frozenset[Symbol]) -> None:
    result = ConsistentBrave(aggregate)
    expected = Verdict.PASS if litset <= aggregate else Verdict.FAIL
    assert brave_contains(litset)(result).verdict is expected


def test_query_check_subject_discriminates_instances() -> None:
    # the repeatable @query tag: label groups, subject (the surface) discriminates instances, so a
    # consumer/explain can tell two @query checks apart before any solve (Pass B MAJOR).
    goal = QueryLiteral("p", True, (Var("X"),))
    singleton = query_matches(GroundQuery(Answer.yes, (Function("a"),)))
    conjunctive = query_matches(GroundQuery(Answer.no, (Function("a"), Function("b"))))
    binding = query_matches(BindingQuery(Answer.unknown, goal, frozenset()))
    assert singleton.label == conjunctive.label == binding.label == "@query"  # the tag groups
    assert singleton.subject == "yes { a }"
    assert conjunctive.subject == "no { a, b }"
    assert binding.subject == "unknown p(X)"
    bare = WitnessClaim(shown=frozenset({Function("a")}))
    assert has_model(bare).subject == ""  # non-repeatable tags carry an empty subject


def test_containment_builders_reject_an_empty_litset() -> None:
    # the empty-litset false-PASS (∅ ⊆ A) is rejected at construction, mirroring the parser (§2.1).
    for build in (
        cautious_contains,
        brave_contains,
        cautious_optimal_contains,
        brave_optimal_contains,
        assign_contains,
    ):
        with pytest.raises(ValueError, match="vacuous"):
            build(frozenset())
