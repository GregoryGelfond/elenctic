"""How a search ended, reported apart from what it determined.

A solver settles two independent things: whether an answer set exists, and whether the search that
looked covered the space. These pin the second to its own value, over each way a search can end.

Each test asserts its premise, so a clingo change that decides one of these programs — or fails to
— fails loudly rather than passing vacuously.
"""

import pytest
from clingo import Control
from clingo.solving import SolveResult

from elenctic.checks import expect_unsat
from elenctic.result import (
    Conclusion,
    Consistent,
    ConsistentWitness,
    Determination,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    SolveOutcome,
    Verdict,
)
from elenctic.run import Mode
from elenctic.solvers import (
    _Collector,
    _conclusion,
    _consistent_shape,
    _cut_short,
    _drive,
    _outcome_unless_satisfiable,
    run_clingo,
)

# 2^20 answer sets: far more than a fraction of a second can enumerate, and trivial to ground.
_WIDE = "{ p(1..20) }.\n#show p/1.\n"

# clingo's own solve-result bitset: the flags are independent, so a result can carry several.
_SATISFIABLE = 1
_UNSATISFIABLE = 2
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


def test_a_search_that_hit_the_model_cap_is_consistent_and_incomplete() -> None:
    # The cap is a constructor argument, not a module lookup: the collector's default binds it once
    # at definition, so rebinding the module attribute would not reach this run.
    control = Control(list(Mode.ENUM_ALL.args), logger=_quiet)
    control.add("base", [], _WIDE)
    control.ground([("base", [])])
    collector = _Collector(4)
    outcome = _drive(control, Mode.ENUM_ALL, collector, collector.on_model, 30.0)
    assert collector.models_seen == 4, "the search stops at the cap, it does not merely truncate"
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.INCOMPLETE, (
        "a search that stopped short is neither an external interruption nor exhaustion"
    )


def test_an_undecided_search_still_reports_how_it_ended() -> None:
    # A solve that settles nothing has run all the same, and how it ended is the only thing it has
    # to say. Dropping it left every check on this arm reciting one sentence, so the reading most
    # likely to be short of time was the one that could not name the remedy.
    control = Control(list(Mode.ENUM_ALL.args), logger=_quiet)
    control.add("base", [], _HARD)
    control.ground([("base", [])])
    control.configuration.solve.solve_limit = "1,1"  # type: ignore[union-attr]
    collector = _Collector()
    outcome = _drive(control, Mode.ENUM_ALL, collector, collector.on_model, 30.0)
    assert isinstance(outcome.determination, Inconclusive), (
        "the conflict limit should end the search before it decides anything"
    )
    assert outcome.conclusion is Conclusion.INCOMPLETE, (
        "a conflict limit is a bound the search ran into, not an interruption from outside it"
    )


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
    # The conclusion passed is EXHAUSTED, so the refusal is attributable to the missing set alone
    # and not to how the search ended.
    for mode in (Mode.CAUTIOUS_ALL, Mode.BRAVE_ALL):
        shape = _consistent_shape(mode, _Collector(), False, Conclusion.EXHAUSTED)
        assert shape is None, f"{mode.name} has no consequence set to build from"


def test_a_consequence_run_that_reached_its_fixpoint_reports_it() -> None:
    # The other side, and the premise of the test above: an ordinary consequence run does emit one,
    # so the None branch describes a cut-short search rather than the normal path.
    outcome = run_clingo(Mode.CAUTIOUS_ALL, program="a.\nb.\n#show a/0.\n#show b/0.\n")
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.EXHAUSTED


def test_a_cut_short_search_never_reports_that_it_closed_the_space() -> None:
    # A search that carries both bits is one this side cannot read. It may have closed the space in
    # the window between the budget poll missing and the cancellation landing — or it may be
    # reporting coverage it never had, which a cancelled solve demonstrably does: the sibling test
    # below is built from the same two bits, and there the claim is false about a program with 2^30
    # answer sets. Nothing in the result distinguishes them, so the coverage claim is refused.
    #
    # Refusing it is close to free. Sweeping the budget across the completion window of a
    # 65,536-answer-set program, 480 solves produced 80 exhausted results and every one of them was
    # uninterrupted and completed — the state this test describes never arose, and no exhausted
    # result ever carried a census shorter than the program's true model count. What the refusal
    # costs when it does arise is one reading going UNDECIDED; what it buys is that a partial
    # census is never read as a whole one, which is a wrong verdict rather than a missing one.
    both = SolveResult(_SATISFIABLE | _EXHAUSTED | _INTERRUPTED)  # type: ignore[no-untyped-call]
    assert both.exhausted and both.interrupted, "the constructed result carries both bits"
    assert _conclusion(completed=False, result=both) is Conclusion.INTERRUPTED


def test_a_budget_this_side_missed_counts_as_cut_short_without_clingo_s_bit() -> None:
    # The predicate has two halves and the interrupted bit is only one of them: a solve whose budget
    # this side missed is cut short whether or not the solver noticed. Every other test here reaches
    # the cut-short state through clingo's bit, so without this one that half is never exercised and
    # dropping it from the predicate would pass the suite.
    unnoticed = SolveResult(_UNSATISFIABLE | _EXHAUSTED)  # type: ignore[no-untyped-call]
    assert not unnoticed.interrupted, "the solver did not record the cancellation"
    assert _cut_short(completed=False, result=unnoticed)
    outcome = _outcome_unless_satisfiable(completed=False, result=unnoticed)
    assert outcome is not None
    assert isinstance(outcome.determination, Inconclusive), "AS(P) = ∅ was never established"
    assert outcome.conclusion is Conclusion.INTERRUPTED


def test_a_cancelled_search_reporting_no_answer_set_is_not_believed() -> None:
    # The other side of the tie-break, and it does not work the same way. A cancelled solve can come
    # back carrying unsatisfiable AND exhausted together: two occurrences in 1,400 zero-budget
    # solves of a program with 2^30 answer sets, under the plain --models=1 of DEFAULT as well as
    # the enumeration args. Read literally it says the search covered the space and found nothing,
    # about a program whose models are beyond counting.
    #
    # So the rule is not "believe an exhausted search". It is that a search cut short from outside
    # may be believed about what it *found* and never about what it *finished*: a model it produced
    # is evidence that survives the cancel, while covering the space is a claim only a search that
    # ran to its own end can make. The satisfiable case above keeps its exhaustion because a
    # positive finding corroborates it; this one has no finding to corroborate anything.
    cut_short = SolveResult(_UNSATISFIABLE | _EXHAUSTED | _INTERRUPTED)  # type: ignore[no-untyped-call]
    assert cut_short.unsatisfiable and cut_short.exhausted, "the constructed result carries both"
    outcome = _outcome_unless_satisfiable(completed=False, result=cut_short)
    assert outcome is not None, "a solve that did not decide satisfiable is reduced here"
    assert isinstance(outcome.determination, Inconclusive), "AS(P) = ∅ was never established"
    assert outcome.conclusion is Conclusion.INTERRUPTED, "what ended it came from outside it"


def test_a_cancelled_search_cannot_uphold_an_unsat_contract() -> None:
    # Why the reduction above is worth its own rule: `@expect unsat` PASSes on the inconsistent arm,
    # and rides its own DEFAULT run — the mode the row above was measured in. Routing a cancelled
    # search there upholds "this program has no answer set" about a program nothing was learned
    # about, which is the one outcome a testing framework must never produce.
    cut_short = SolveResult(_UNSATISFIABLE | _EXHAUSTED | _INTERRUPTED)  # type: ignore[no-untyped-call]
    outcome = _outcome_unless_satisfiable(completed=False, result=cut_short)
    assert outcome is not None
    report = expect_unsat(line=1)(outcome)
    assert report.verdict is Verdict.UNDECIDED, "never PASS on a search that established nothing"


def test_a_search_that_ran_to_its_end_still_reports_an_unsatisfiable_program() -> None:
    # The premise of both tests above: the refusal is about the cancel, not about the bits. A solve
    # nobody cut short is believed exactly as before, or the rule would trade a false PASS for a
    # whole mode that can no longer decide anything.
    finished = SolveResult(_UNSATISFIABLE | _EXHAUSTED)  # type: ignore[no-untyped-call]
    outcome = _outcome_unless_satisfiable(completed=True, result=finished)
    assert outcome is not None
    assert isinstance(outcome.determination, Inconsistent)
    assert outcome.conclusion is Conclusion.EXHAUSTED


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
    "conclusion",
    # Unsatisfiability is itself a completeness claim: the one pairing rule left once every arm
    # reports its search, and the one the check layer leans on — every check answers this arm from
    # a static verdict without consulting the search, so `@expect unsat` would otherwise PASS on a
    # search that had established nothing of the kind.
    [Conclusion.INCOMPLETE, Conclusion.INTERRUPTED],
)
def test_an_unsatisfiable_result_from_an_unfinished_search_is_refused(
    conclusion: Conclusion,
) -> None:
    with pytest.raises(HarnessError):
        SolveOutcome(Inconsistent(), conclusion)


@pytest.mark.parametrize(
    "determination",
    [Inconclusive(), Inconsistent(), ConsistentWitness(Observable(frozenset()))],
)
def test_no_arm_may_be_built_without_the_search_behind_it(determination: Determination) -> None:
    # Totality is what lets a check read the conclusion on any arm without a missing case, and it
    # is why the diagnostic for a solve that settled nothing can name a remedy at all. Totality is
    # a claim that the value cannot be LEFT OUT, so it is tested by leaving it out — reading back
    # what was just passed in would hold on a field that was still optional.
    #
    # The undecided arm is the one this opened: it used to be refused a conclusion outright. The
    # absence is still refused, because it once meant something here and a caller working from the
    # old shape would otherwise build a result whose failure surfaces as a bare lookup miss inside
    # a check — which the per-case handler does not recognise, so it would cost every case still to
    # come.
    with pytest.raises(TypeError):
        SolveOutcome(determination)  # type: ignore[call-arg]
    with pytest.raises(HarnessError):
        SolveOutcome(determination, None)  # type: ignore[arg-type]
    assert SolveOutcome(determination, Conclusion.EXHAUSTED).conclusion is Conclusion.EXHAUSTED


def test_a_cancelled_theory_solve_also_keeps_what_it_settled() -> None:
    # The "both backends" obligation. clingcon shares the driver but registers a propagator and
    # rewrites the program first, so its cancel path is worth exercising rather than assumed: the
    # clingo side of this is asserted above, and nothing else covers the theory side.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    outcome = run_clingcon(Mode.ENUM_ALL, program=_WIDE, budget=0.05)
    assert isinstance(outcome.determination, Consistent), (
        "a cancelled theory search that found models decided satisfiability"
    )
    assert outcome.conclusion is Conclusion.INTERRUPTED
