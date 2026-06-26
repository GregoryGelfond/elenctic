"""The solver registry is the single source of truth for valid solver names."""

from typing import get_args

from elenctic.registry import SOLVERS, THEORY_SOLVERS, Solver, provides_theory


def test_solvers_are_clingo_and_clingcon() -> None:
    assert frozenset({"clingo", "clingcon"}) == SOLVERS


def test_facades_cover_exactly_the_registry() -> None:
    # solvers._FACADES must implement exactly the registered names — no drift.
    from elenctic.solvers import _FACADES

    assert frozenset(_FACADES) == SOLVERS


def test_solver_type_alias_matches_registry() -> None:
    # The Literal's args are the same set (the static type tracks the runtime registry).
    assert frozenset(get_args(Solver.__value__)) == SOLVERS


def test_theory_solvers_is_a_subset_of_the_registry() -> None:
    # THEORY_SOLVERS is the single source for theory *capability* (the companion to SOLVERS); every
    # theory solver must be a registered solver, so a future entry cannot drift out of the registry.
    assert frozenset({"clingcon"}) == THEORY_SOLVERS
    assert THEORY_SOLVERS <= SOLVERS


def test_provides_theory_reads_the_theory_solver_set() -> None:
    # The one predicate the four theory_in_force sites (discovery gates, cli/harness plans) call,
    # so `solver == "clingcon"` is never re-hardcoded and drift-prone.
    assert provides_theory("clingcon") is True
    assert provides_theory("clingo") is False
