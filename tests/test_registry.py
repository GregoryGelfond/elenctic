"""The solver registry is the single source of truth for valid solver names (R5)."""

from typing import get_args

from elenctic.registry import SOLVERS, Solver


def test_solvers_are_clingo_and_clingcon() -> None:
    assert frozenset({"clingo", "clingcon"}) == SOLVERS


def test_facades_cover_exactly_the_registry() -> None:
    # solvers._FACADES must implement exactly the registered names — no drift (R5).
    from elenctic.solvers import _FACADES

    assert frozenset(_FACADES) == SOLVERS


def test_solver_type_alias_matches_registry() -> None:
    # The Literal's args are the same set (the static type tracks the runtime registry).
    assert frozenset(get_args(Solver.__value__)) == SOLVERS
