"""World views range over full answer sets by default."""

from elenctic.determination import (
    Consistent,
    Optimum,
    WorldView,
    optimal_view,
    world_view,
)
from elenctic.engine import ground, solve
from elenctic.grounded import Grounded
from elenctic.literals import Literal
from elenctic.program import Program
from elenctic.query import Answer, answer


def test_world_view_includes_atoms_that_are_not_shown() -> None:
    found = solve(Program("-b. #show b/0.\n"))
    assert isinstance(found, Consistent)
    view = world_view(found)
    assert isinstance(view, WorldView)
    assert answer(Literal("b", positive=False), view) is Answer.YES
    shown_only = world_view(found, shown=True)
    assert isinstance(shown_only, WorldView)
    assert answer(Literal("b", positive=False), shown_only) is Answer.UNKNOWN


def test_optimal_view_includes_atoms_that_are_not_shown() -> None:
    grounded = ground(Program("a. -b. #minimize {1:a}. #show b/0.\n"))
    assert isinstance(grounded, Grounded)
    found = grounded.optimize()
    assert isinstance(found, Consistent)
    assert isinstance(found.evidence, Optimum)
    view = optimal_view(found)
    assert isinstance(view, WorldView)
    assert answer(Literal("b", positive=False), view) is Answer.YES
