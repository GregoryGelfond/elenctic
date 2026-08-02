"""A search that stopped early is not a complete enumeration.

clingo reports exhaustiveness separately from satisfiability: a solve can decide *satisfiable* and
still have stopped before covering the collection. Every reading that ranges over a collection — a
census, the consequences, the optimal class — is sound only over a complete enumeration, so a
partial one is never presented as the whole.

The guarantee is enforced in two places, because the requirement belongs to what is *read* and one
solve carries several readings. Here: the solve keeps the satisfiability it settled and reports how
its search ended, so nothing is discarded and nothing is dressed up. At the check
(``test_partial_search_verdicts.py``): a reading over a collection that met an unfinished search is
UNDECIDED, never FAIL and never a PASS it did not earn.

A mode reading a single witness is exempt. The exemption is load-bearing rather than an
optimization: a witness search *may* legitimately not finish — with nothing else driving it, it
stops at the first answer set — so requiring exhaustion of it would report satisfiable programs as
UNDECIDED. It is not that such a search never finishes: an objective puts clingo's default
optimization in force and proving an optimum does exhaust, which is why the exemption is stated as
"not required" rather than "never happens".

The partial state is produced by capping the search — a **conflict limit** or a **model cap** —
never a wall-clock budget, so it does not depend on how fast the machine is. Each test asserts the
state it is exercising, because the failure that matters is silent: a solve that came back *unknown*
instead would reach ``Inconclusive`` down the pre-existing path and pass the assertion while
covering none of this.
"""

from collections.abc import Callable

import pytest
from clingo import Control
from clingo.solving import Model, SolveResult

from elenctic import solvers
from elenctic.checks import cautious_contains, count_optimal_is
from elenctic.result import (
    Conclusion,
    Consistent,
    ConsistentWitness,
    Inconclusive,
    SolveOutcome,
    Verdict,
)
from elenctic.run import Mode
from elenctic.solvers import (
    _Collector,
    _drive,
    _optimal_enum_two_phase,
    _solve_under_budget,
)

# Decided in a handful of conflicts, expensive to enumerate: 8-queens has 92 answer sets, so a
# search cut short still answers "satisfiable" while covering a fraction of them. The #minimize
# gives the optimization modes an objective over the same program.
_WIDE = """
#const n=8.
row(1..n). col(1..n).
1 { queen(R,C) : col(C) } 1 :- row(R).
:- queen(R1,C), queen(R2,C), R1 < R2.
:- queen(R1,C1), queen(R2,C2), R1 < R2, R2-R1 == |C2-C1|.
#minimize { R*C,R,C : queen(R,C) }.
#show queen/2.
"""

# The same program with no objective. Whether a witness solve exhausts depends on this: an
# objective puts clingo's default optimization in force, and proving an optimum exhausts the search,
# whereas without one the solve stops at the first answer set. The exemption has to hold in the
# second case, which is the ordinary shape of a satisfiability contract.
_PLAIN = """
#const n=8.
row(1..n). col(1..n).
1 { queen(R,C) : col(C) } 1 :- row(R).
:- queen(R1,C), queen(R2,C), R1 < R2.
:- queen(R1,C1), queen(R2,C2), R1 < R2, R2-R1 == |C2-C1|.
#show queen/2.
"""

# A colouring whose first node is pinned, so ⋂ over all answer sets is exactly {assign(1,r)} and is
# reached only after many strengthening steps. Every earlier step of the cautious enumeration is a
# strict superset of it — which is what makes a truncated cautious search dangerous rather than
# merely incomplete.
_PINNED = """
#const n=9.
node(1..n). colour(r;g;b).
edge(N,N+1) :- node(N), node(N+1).
1 { assign(N,C) : colour(C) } 1 :- node(N).
:- assign(N1,C), assign(N2,C), edge(N1,N2).
assign(1,r).
#show assign/2.
"""

# Enough search to decide satisfiable, not enough to exhaust — the state this fix exists for.
_PARTIAL = "16,-1"


def _quiet(_code: object, _message: str) -> None:
    """Keep clingo's own diagnostics out of the test output."""


def _control(
    mode: Mode, limit: str | None = None, program: str = _WIDE, models: str | None = None
) -> Control:
    """A grounded control for ``mode``. Under ``limit`` its search gives up after that many
    conflicts; under ``models`` it stops after that many models. Either caps the search without
    ending the solve, so it decides satisfiability without covering the collection."""
    control = Control(list(mode.args), logger=_quiet)
    control.add("base", [], program)
    control.ground([("base", [])])
    if limit is not None:
        control.configuration.solve.solve_limit = limit  # type: ignore[union-attr]
    if models is not None:
        control.configuration.solve.models = models  # type: ignore[union-attr]
    return control


def _on_model_for(collector: _Collector) -> Callable[[Model], bool]:
    """The plain (non-theory) callback factory the optimal driver takes."""
    return collector.on_model


def _assert_partial(completed: bool, result: SolveResult) -> None:
    """Assert the solve reached the state under test: decided satisfiable, search not finished.

    Without this a solve that came back *unknown* would still reduce to ``Inconclusive``, down the
    path that existed before the exhaustion requirement — so the test would pass while exercising
    none of it."""
    assert completed, "the cap should end the search, not the time budget"
    assert not result.unknown, "a partial enumeration is a decided solve, not an undecided one"
    assert result.satisfiable, "the program is satisfiable"
    assert not result.exhausted, "the cap is expected to stop the search before it finishes"


def test_a_capped_solve_can_decide_satisfiable_without_finishing() -> None:
    # The state that separates this from an undecided solve: the search answered the satisfiability
    # question, and stopped anyway.
    completed, result = _solve_under_budget(
        _control(Mode.ENUM_ALL, _PARTIAL), _Collector().on_model, 30.0
    )
    _assert_partial(completed, result)


def _drive_partial(
    mode: Mode, monkeypatch: pytest.MonkeyPatch
) -> tuple[SolveOutcome, list[tuple[bool, SolveResult]]]:
    """Drive ``mode`` over a capped search, returning its outcome and what the solve reported.

    The spy is what keeps these tests honest: without it a solve that came back *unknown* would
    reach the undecided arm down a path that has nothing to do with a partial search, and the
    assertion would pass while covering none of it."""
    real = solvers._solve_under_budget
    seen: list[tuple[bool, SolveResult]] = []

    def spy(
        control: Control, on_model: Callable[[Model], bool], budget: float
    ) -> tuple[bool, SolveResult]:
        reported = real(control, on_model, budget)
        seen.append(reported)
        return reported

    monkeypatch.setattr(solvers, "_solve_under_budget", spy)
    collector = _Collector()
    outcome = _drive(_control(mode, _PARTIAL), mode, collector, collector.on_model, 30.0)
    assert len(seen) == 1, "the single-solve driver is expected to solve exactly once"
    _assert_partial(*seen[0])
    return outcome, seen


@pytest.mark.parametrize("mode", [Mode.ENUM_ALL, Mode.BRAVE_ALL])
def test_a_partial_census_is_kept_and_reported_as_unfinished(
    mode: Mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A census and a union are made of what the search saw, so a partial search yields a partial
    # one — real information, and the solve says so rather than discarding it. Refusing the reading
    # over it is the check's job, since the same solve may carry a reading that needs no more.
    outcome, _ = _drive_partial(mode, monkeypatch)
    assert isinstance(outcome.determination, Consistent)
    assert outcome.conclusion is Conclusion.STOPPED, (
        "a search cut short must never be reported as one that closed the space"
    )


def test_a_partial_optimal_search_yields_no_optimum_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The optimum is different in kind from a census: it is not made of what the search saw, it is
    # a claim that nothing better exists. A search that stopped early has a best-so-far and no such
    # claim, so there is no partial optimum to keep — and constructing one would put an assertion
    # nobody established into a type whose whole meaning is that someone did.
    outcome, _ = _drive_partial(Mode.OPTIMAL, monkeypatch)
    assert isinstance(outcome.determination, Inconclusive)
    assert outcome.conclusion is None


def test_a_partial_cautious_search_would_otherwise_pass_a_false_claim() -> None:
    # The worst case, and the reason a wrong FAIL is not the only risk. Cautious consequences shrink
    # as the enumeration proceeds, so ⋂ over a prefix is a *superset* of ⋂ over the whole
    # collection. A @cautious contract naming one of the surplus atoms would be satisfied by the
    # truncated reading — a false claim reported as verified, which is the worst outcome a testing
    # framework has. A model cap reaches this state where a conflict limit does not.
    whole = _Collector()
    _drive(
        _control(Mode.CAUTIOUS_ALL, program=_PINNED), Mode.CAUTIOUS_ALL, whole, whole.on_model, 30.0
    )
    truth = whole.cautious()
    assert truth, "the pinned node is expected to make ⋂ non-empty"

    capped = _Collector()
    control = _control(Mode.CAUTIOUS_ALL, program=_PINNED, models="1")
    completed, result = _solve_under_budget(control, capped.on_model, 30.0)
    _assert_partial(completed, result)
    partial_meet = capped.cautious()
    assert partial_meet is not None, (
        "the capped run is expected to have reported a consequence model"
    )
    assert partial_meet > truth, (
        "a truncated cautious enumeration is expected to over-report ⋂, not under-report it"
    )

    # So the surplus must never reach a verdict. Driven end to end, and then asserted where it
    # matters: a @cautious contract naming one of the surplus atoms is UNDECIDED, not the PASS the
    # truncated reading would have handed it. Asserting the verdict rather than the arm is the
    # point — a claim "verified" by a search that never established it is the worst outcome a
    # testing framework has, and it is a statement about the verdict, not about the plumbing.
    driven = _Collector()
    outcome = _drive(
        _control(Mode.CAUTIOUS_ALL, program=_PINNED, models="1"),
        Mode.CAUTIOUS_ALL,
        driven,
        driven.on_model,
        30.0,
    )
    surplus = partial_meet - truth
    assert surplus, "the truncated reading is expected to carry atoms the whole one does not"
    false_claim = cautious_contains(frozenset(surplus))
    assert false_claim(outcome).verdict is Verdict.UNDECIDED, (
        "a claim the truncated reading would satisfy must not be reported as verified"
    )

    # And the other direction, so the guarantee is not merely "everything is UNDECIDED": over the
    # complete search the same machinery still decides.
    complete = _Collector()
    whole_outcome = _drive(
        _control(Mode.CAUTIOUS_ALL, program=_PINNED),
        Mode.CAUTIOUS_ALL,
        complete,
        complete.on_model,
        30.0,
    )
    assert false_claim(whole_outcome).verdict is Verdict.FAIL, (
        "the same claim is decidably false once the search has covered the collection"
    )


def test_a_partial_first_phase_of_the_optimal_driver_is_inconclusive() -> None:
    # Phase 1 proves the optimum. A search that stopped early holds a best-so-far, not a proven
    # optimum, so there is no bound to enumerate the optimal class at.
    outcome = _optimal_enum_two_phase(
        _control(Mode.OPTIMAL_ENUM, _PARTIAL), _on_model_for, 30.0, False
    )
    assert isinstance(outcome.determination, Inconclusive)


def test_a_partial_second_phase_of_the_optimal_driver_reports_that_it_did_not_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Phase 2 enumerates the class at the proven optimum. If that search stops early the collector
    # holds part of the optimal class, which is not the optimal class. Phase 1 runs for real, so the
    # optimum is genuinely proven; only phase 2 is handed a partial result. Capping phase 2 directly
    # cannot reach this state — a cap tight enough to truncate phase 2 stops phase 1 first, which
    # returns before phase 2 ever runs.
    partial = _solve_under_budget(_control(Mode.ENUM_ALL, _PARTIAL), _Collector().on_model, 30.0)
    _assert_partial(*partial)

    real = solvers._solve_under_budget
    calls = 0

    def one_good_then_partial(
        control: Control, on_model: Callable[[Model], bool], budget: float
    ) -> tuple[bool, SolveResult]:
        nonlocal calls
        calls += 1
        outcome = real(control, on_model, budget)
        # Both phases solve for real, so the collector holds models exactly as a truncated phase 2
        # would leave it; only the reported result is swapped for one whose search did not finish.
        return outcome if calls == 1 else (True, partial[1])

    monkeypatch.setattr(solvers, "_solve_under_budget", one_good_then_partial)

    outcome = _optimal_enum_two_phase(_control(Mode.OPTIMAL_ENUM), _on_model_for, 30.0, False)
    assert calls == 2, "phase 1 must have proven an optimum, so that phase 2 ran"
    assert outcome.conclusion is Conclusion.STOPPED, (
        "part of the optimal class is not the optimal class, and the outcome says so"
    )
    # And the reading over it is refused, which is the guarantee that matters: an optimal-class
    # census taken from part of the class must not be reported as the census.
    assert count_optimal_is(92)(outcome).verdict is Verdict.UNDECIDED


def test_a_witness_search_is_not_required_to_finish() -> None:
    # The load-bearing exemption. A witness solve over a program with no objective stops at the
    # first answer set and so reports a search that did not finish, with nothing limiting it.
    # Requiring exhaustion here would turn every satisfiable program into UNDECIDED.
    completed, result = _solve_under_budget(
        _control(Mode.DEFAULT, program=_PLAIN), _Collector().on_model, 30.0
    )
    assert completed and result.satisfiable, "the unlimited witness solve is expected to decide"
    assert not result.exhausted, "a witness solve over an objective-free program does not finish"

    collector = _Collector()
    outcome = _drive(
        _control(Mode.DEFAULT, program=_PLAIN), Mode.DEFAULT, collector, collector.on_model, 30.0
    )
    assert isinstance(outcome.determination, ConsistentWitness)


@pytest.mark.parametrize("mode", [Mode.ENUM_ALL, Mode.BRAVE_ALL, Mode.CAUTIOUS_ALL, Mode.OPTIMAL])
def test_a_complete_search_over_a_collection_is_consistent(mode: Mode) -> None:
    # The other side of the requirement: an unlimited search over this program does finish, so the
    # reading stands. Without this a fix that reported every collection as UNDECIDED would pass.
    collector = _Collector()
    outcome = _drive(_control(mode), mode, collector, collector.on_model, 30.0)
    assert isinstance(outcome.determination, Consistent)


def test_a_complete_optimal_class_is_consistent() -> None:
    # Both phases of the optimal driver finish when nothing caps them.
    outcome = _optimal_enum_two_phase(_control(Mode.OPTIMAL_ENUM), _on_model_for, 30.0, False)
    assert isinstance(outcome.determination, Consistent)
