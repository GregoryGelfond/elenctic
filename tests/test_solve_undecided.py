"""A solve that completes without deciding is UNDECIDED, on every run mode.

clingo's solve result is three-valued — satisfiable, unsatisfiable, or unknown (the search stopped
without deciding). These pin the third value to the ``Inconclusive`` arm across the run modes,
including both phases of the optimal-class driver.

The undecided state is produced with a **conflict limit**, which is deterministic: unlike a
wall-clock budget it does not depend on how fast the machine is. Each test asserts its premise, so a
clingo change that decides the program fails loudly rather than passing vacuously.
"""

from collections.abc import Callable

import pytest
from clingo import Control
from clingo.solving import Model, SolveResult

from elenctic import solvers
from elenctic.result import Inconclusive
from elenctic.run import Mode
from elenctic.solvers import _Collector, _drive, _optimal_enum_two_phase, _solve_under_budget

# Small to ground, expensive to decide: a 60-queens placement whose constraints are only discovered
# by search. The #minimize gives the optimization modes an objective to work on, so a mode that
# reports "this encoding has no objective" is saying something false about this program.
_HARD = """
#const n=60.
1 { p(I,1..n) } 1 :- I=1..n.
:- p(I,V), p(J,V), I<J.
:- p(I,V), p(J,W), I<J, V-W == I-J.
:- p(I,V), p(J,W), I<J, W-V == I-J.
#minimize { V,I : p(I,V) }.
#show p/2.
"""

# Two co-optimal answer sets, decided immediately — for driving the first phase of the optimal
# driver to a real optimum before the second phase is made to give up.
_EASY = "1 {a; b} 1. #minimize { 1,a : a; 1,b : b }. #show a/0. #show b/0."


def _quiet(_code: object, _message: str) -> None:
    """Keep clingo's own diagnostics out of the test output."""


def _limited(mode: Mode, program: str = _HARD) -> Control:
    """A grounded control for ``mode`` whose search gives up after one conflict, so the solve
    completes without deciding anything."""
    control = Control(list(mode.args), logger=_quiet)
    control.add("base", [], program)
    control.ground([("base", [])])
    control.configuration.solve.solve_limit = "1,1"  # type: ignore[union-attr]
    return control


def _on_model_for(collector: _Collector) -> Callable[[Model], None]:
    """The plain (non-theory) callback factory the optimal driver takes."""
    return collector.on_model


def test_a_conflict_limited_solve_completes_without_deciding() -> None:
    # The premise every test below rests on: a *completed* solve that answers nothing.
    completed, result = _solve_under_budget(_limited(Mode.ENUM_ALL), _Collector().on_model, 30.0)
    assert completed, "the conflict limit should end the search, not the time budget"
    assert result.unknown, "the limited solve is expected to decide nothing"
    assert not result.unsatisfiable, "an undecided solve is not a proof of unsatisfiability"


@pytest.mark.parametrize(
    "mode", [Mode.DEFAULT, Mode.ENUM_ALL, Mode.CAUTIOUS_ALL, Mode.BRAVE_ALL, Mode.OPTIMAL]
)
def test_an_undecided_solve_is_inconclusive(mode: Mode) -> None:
    # "The solver did not decide" is what UNDECIDED means. It is never a shape built from an empty
    # search, never a claim that AS(P) is empty, and never a report that the encoding lacks the
    # objective it visibly has.
    collector = _Collector()
    determination = _drive(_limited(mode), mode, collector, collector.on_model, 30.0)
    assert isinstance(determination, Inconclusive)


def test_an_undecided_first_phase_of_the_optimal_driver_is_inconclusive() -> None:
    # Phase 1 proves the optimum. If it does not decide, there is no optimum to enumerate at.
    determination = _optimal_enum_two_phase(_limited(Mode.OPTIMAL_ENUM), _on_model_for, 30.0, False)
    assert isinstance(determination, Inconclusive)


def test_an_undecided_second_phase_of_the_optimal_driver_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Phase 2 enumerates the class at the proven optimum. If that search gives up, the optimal class
    # is unknown — so the driver reports UNDECIDED rather than building a shape from an empty
    # collector. Phase 1 runs for real; only phase 2 is handed an undecided result.
    undecided = _solve_under_budget(_limited(Mode.ENUM_ALL), _Collector().on_model, 30.0)
    assert undecided[1].unknown, "the captured result is expected to decide nothing"

    real = solvers._solve_under_budget
    calls = 0

    def one_good_then_undecided(
        control: Control, on_model: Callable[[Model], None], budget: float
    ) -> tuple[bool, SolveResult]:
        nonlocal calls
        calls += 1
        return real(control, on_model, budget) if calls == 1 else undecided

    monkeypatch.setattr(solvers, "_solve_under_budget", one_good_then_undecided)

    control = Control(list(Mode.OPTIMAL_ENUM.args), logger=_quiet)
    control.add("base", [], _EASY)
    control.ground([("base", [])])
    determination = _optimal_enum_two_phase(control, _on_model_for, 30.0, False)
    assert calls == 2, "phase 1 must have decided, so that phase 2 ran"
    assert isinstance(determination, Inconclusive)
