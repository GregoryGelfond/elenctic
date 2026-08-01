"""How a search ended, reported apart from what it determined.

A solver settles two independent things: whether an answer set exists, and whether the search that
looked covered the space. These pin the second to its own value, over each way a search can end.

Each test asserts its premise, so a clingo change that decides one of these programs — or fails to
— fails loudly rather than passing vacuously.
"""

from clingo import Control

from elenctic.result import Conclusion, Consistent, Inconclusive, Inconsistent
from elenctic.run import Mode
from elenctic.solvers import _Collector, _consistent_shape, _drive, run_clingo

# 2^20 answer sets: far more than a fraction of a second can enumerate, and trivial to ground.
_WIDE = "{ p(1..20) }.\n#show p/1.\n"
# Small to ground, expensive to decide: a 60-queens placement whose constraints are only found by
# search. Paired with a one-conflict limit it produces a solve that completes without deciding.
_HARD = """
#const n=60.
1 { p(I,1..n) } 1 :- I=1..n.
:- p(I,V), p(J,V), I<J.
:- p(I,V), p(J,W), I<J, V-W == I-J.
:- p(I,V), p(J,W), I<J, W-V == I-J.
#show p/2.
"""


def _quiet(_code: object, _message: str) -> None:
    """Keep clingo's own diagnostics out of the test output."""


def test_a_finished_search_is_exhausted() -> None:
    outcome = run_clingo(Mode.ENUM_ALL, program="{ p(1..3) }.\n#show p/1.\n")
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.EXHAUSTED


def test_a_cancelled_search_that_found_models_is_consistent_and_interrupted() -> None:
    # The whole point: satisfiability WAS decided, so the arm is not Inconclusive. A budget cut the
    # search short, which is a fact about the search, not about whether the program has a model.
    outcome = run_clingo(Mode.ENUM_ALL, program=_WIDE, budget=0.05)
    assert isinstance(outcome.determination, Consistent), (
        "a cancelled search that found models decided satisfiability"
    )
    assert outcome.conclusion is Conclusion.INTERRUPTED


def test_a_search_stopped_at_a_model_bound_is_consistent_and_stopped() -> None:
    # The cap is a constructor argument, not a module lookup: the collector's default binds it once
    # at definition, so rebinding the module attribute would not reach this run.
    control = Control(list(Mode.ENUM_ALL.args), logger=_quiet)
    control.add("base", [], _WIDE)
    control.ground([("base", [])])
    collector = _Collector(4)
    outcome = _drive(control, Mode.ENUM_ALL, collector, collector.on_model, 30.0)
    assert collector.models_seen == 4, "the search stops at the cap, it does not merely truncate"
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.STOPPED, (
        "a requested bound is not an external interruption and not exhaustion"
    )


def test_an_undecided_search_has_no_conclusion_to_report() -> None:
    control = Control(list(Mode.ENUM_ALL.args), logger=_quiet)
    control.add("base", [], _HARD)
    control.ground([("base", [])])
    control.configuration.solve.solve_limit = "1,1"  # type: ignore[union-attr]
    collector = _Collector()
    outcome = _drive(control, Mode.ENUM_ALL, collector, collector.on_model, 30.0)
    assert isinstance(outcome.determination, Inconclusive), (
        "the conflict limit should end the search before it decides anything"
    )
    assert outcome.conclusion is None, "there is no completed search to describe"


def test_an_unsatisfiable_program_closed_the_space() -> None:
    # No search can report that a program has no answer set without covering the space, so this arm
    # carries the one conclusion it can.
    outcome = run_clingo(Mode.ENUM_ALL, program="a.\n:- a.\n")
    assert isinstance(outcome.determination, Inconsistent)
    assert outcome.conclusion is Conclusion.EXHAUSTED


def test_a_consequence_run_with_no_consequence_model_settles_nothing() -> None:
    # Reachable now that a cut-short search keeps the satisfiability it settled: a cautious solve
    # cancelled before clingo emits its first consequence model has decided satisfiability but has
    # no ⋂ at all — not even a partial one. It used to be unreachable, and so used to be reported
    # as a violated clingo assumption; blaming elenctic for a budget the user chose would be wrong.
    # Driven through the collector rather than through a timing window, so it is decided by the
    # state itself and not by how fast this machine is.
    assert _consistent_shape(Mode.CAUTIOUS_ALL, _Collector()) is None
    assert _consistent_shape(Mode.BRAVE_ALL, _Collector()) is None


def test_a_consequence_run_that_reached_its_fixpoint_reports_it() -> None:
    # The other side, and the premise of the test above: an ordinary consequence run does emit one,
    # so the None branch describes a cut-short search rather than the normal path.
    outcome = run_clingo(Mode.CAUTIOUS_ALL, program="a.\nb.\n#show a/0.\n#show b/0.\n")
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.EXHAUSTED
