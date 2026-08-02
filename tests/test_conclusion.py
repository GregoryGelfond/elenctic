"""How a search ended, reported apart from what it determined.

A solver settles two independent things: whether an answer set exists, and whether the search that
looked covered the space. These pin the second to its own value, over each way a search can end.

Each test asserts its premise, so a clingo change that decides one of these programs — or fails to
— fails loudly rather than passing vacuously.
"""

import pytest
from clingo import Control
from clingo.solving import SolveResult

from elenctic.result import (
    Conclusion,
    Consistent,
    HarnessError,
    Inconclusive,
    Inconsistent,
    SolveOutcome,
)
from elenctic.run import Mode
from elenctic.solvers import _Collector, _conclusion, _consistent_shape, _drive, run_clingo

# 2^20 answer sets: far more than a fraction of a second can enumerate, and trivial to ground.
_WIDE = "{ p(1..20) }.\n#show p/1.\n"
# Small to ground, expensive to decide: a 60-queens placement whose constraints are only found by
# search. Paired with a one-conflict limit it produces a solve that completes without deciding.
# clingo's SolveResult bitset, from its own header: the flags are independent.
_SATISFIABLE = 1
_EXHAUSTED = 4
_INTERRUPTED = 8

# An optimizing program whose optimum is expensive to prove, so a conflict limit leaves a
# best-so-far rather than a proven optimum.
_HARD_OPTIMIZING = """
#const n=8.
row(1..n). col(1..n).
1 { queen(R,C) : col(C) } 1 :- row(R).
:- queen(R1,C), queen(R2,C), R1 < R2.
:- queen(R1,C1), queen(R2,C2), R1 < R2, R2-R1 == |C2-C1|.
#minimize { R*C,R,C : queen(R,C) }.
#show queen/2.
"""

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


def test_a_search_that_both_closed_the_space_and_was_interrupted_is_exhausted() -> None:
    # The one case where the tie-break does work: the search closed the space in the window between
    # the budget poll missing and the cancellation landing. What it found is everything, and the
    # interrupt arrived too late to take that away — so exhaustion wins. Built from the bitset
    # directly, because the race cannot be produced on demand.
    both = SolveResult(_SATISFIABLE | _EXHAUSTED | _INTERRUPTED)  # type: ignore[no-untyped-call]
    assert both.exhausted and both.interrupted, "the constructed result carries both bits"
    assert _conclusion(completed=False, result=both) is Conclusion.EXHAUSTED


def test_a_cancelled_solve_really_does_set_clingo_s_interrupted_bit() -> None:
    # The classification leans on this bit, and every other test reaches INTERRUPTED through
    # elenctic's own budget flag instead — so if the bit were never set on the cancel path, the
    # rule would quietly degrade to that flag alone and nothing would notice.
    control = Control(list(Mode.ENUM_ALL.args), logger=_quiet)
    control.add("base", [], _WIDE)
    control.ground([("base", [])])
    collector = _Collector()
    with control.solve(on_model=collector.on_model, async_=True) as handle:
        completed = handle.wait(0.05)
        assert not completed, "the budget is expected to be missed on 2^20 answer sets"
        handle.cancel()
        result = handle.get()
    assert result.interrupted, "cancel() is expected to set the interrupted bit"


def test_an_optimal_solve_closes_its_space() -> None:
    # OPTIMAL is the one collection-reading mode whose args do not state --models=0; it relies on
    # clingo not applying a model bound while proving an optimum. If that were wrong every @cost in
    # a corpus would be UNDECIDED and nothing would say why.
    outcome = run_clingo(
        Mode.OPTIMAL, program="1 { a; b } 1. #minimize { 2,a : a; 1,b : b }.\n#show a/0.\n"
    )
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.EXHAUSTED


def test_an_unproven_optimum_is_never_built() -> None:
    # An Optimum asserts a PROVEN optimum by its own construction, so the best cost a stopped search
    # happened to reach must not be dressed as one. Without this the type's meaning would rest on
    # every reader remembering to consult the conclusion.
    control = Control(list(Mode.OPTIMAL.args), logger=_quiet)
    control.add("base", [], _HARD_OPTIMIZING)
    control.ground([("base", [])])
    control.configuration.solve.solve_limit = "16,-1"  # type: ignore[union-attr]
    collector = _Collector()
    outcome = _drive(control, Mode.OPTIMAL, collector, collector.on_model, 30.0)
    assert isinstance(outcome.determination, Inconclusive), (
        "a best-so-far cost must not be reported as a proven optimum"
    )


@pytest.mark.parametrize(
    ("determination", "conclusion"),
    [
        (Inconclusive(), Conclusion.EXHAUSTED),  # nothing was settled, so no search to describe
        (Inconsistent(), None),  # decided, so it must say how the search ended
        (Inconsistent(), Conclusion.STOPPED),  # unsatisfiable is itself a completeness claim
    ],
)
def test_an_arm_paired_with_the_wrong_search_is_refused(
    determination: object, conclusion: Conclusion | None
) -> None:
    with pytest.raises(HarnessError):
        SolveOutcome(determination, conclusion)  # type: ignore[arg-type]
