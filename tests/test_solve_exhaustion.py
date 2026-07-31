"""A search that stopped early is not a complete enumeration.

clingo reports exhaustiveness separately from satisfiability: a solve can decide *satisfiable* and
still have stopped before covering the collection. Every mode whose reading ranges over a collection
— a census, the consequences, the optimal class — is sound only over a complete enumeration, so a
partial one is reported as UNDECIDED rather than presented as the whole.

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
from elenctic.result import Consistent, ConsistentWitness, Inconclusive
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


def _on_model_for(collector: _Collector) -> Callable[[Model], None]:
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


@pytest.mark.parametrize("mode", [Mode.ENUM_ALL, Mode.BRAVE_ALL, Mode.OPTIMAL])
def test_a_partial_search_over_a_collection_is_inconclusive(
    mode: Mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The census, the consequences and the optimum are all readings of a collection. Over a search
    # that stopped early each is a reading of an arbitrary prefix, so none of them is reported. The
    # spy asserts this mode really reached the partial state rather than an undecided one.
    real = solvers._solve_under_budget
    seen: list[tuple[bool, SolveResult]] = []

    def spy(
        control: Control, on_model: Callable[[Model], None], budget: float
    ) -> tuple[bool, SolveResult]:
        outcome = real(control, on_model, budget)
        seen.append(outcome)
        return outcome

    monkeypatch.setattr(solvers, "_solve_under_budget", spy)

    collector = _Collector()
    determination = _drive(_control(mode, _PARTIAL), mode, collector, collector.on_model, 30.0)
    assert len(seen) == 1, "the single-solve driver is expected to solve exactly once"
    _assert_partial(*seen[0])
    assert isinstance(determination, Inconclusive)


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
    assert capped.cautious() > truth, (
        "a truncated cautious enumeration is expected to over-report ⋂, not under-report it"
    )

    # So the mode is held to the same rule as its siblings, and the surplus never reaches a check.
    # Driving it end to end also settles that a truncated consequence run still reports its ⋂ to the
    # collector: the shape is formed before the exhaustion question is asked, so a run that reached
    # here without one would raise instead of reporting UNDECIDED.
    driven = _Collector()
    determination = _drive(
        _control(Mode.CAUTIOUS_ALL, program=_PINNED, models="1"),
        Mode.CAUTIOUS_ALL,
        driven,
        driven.on_model,
        30.0,
    )
    assert isinstance(determination, Inconclusive)


def test_a_partial_first_phase_of_the_optimal_driver_is_inconclusive() -> None:
    # Phase 1 proves the optimum. A search that stopped early holds a best-so-far, not a proven
    # optimum, so there is no bound to enumerate the optimal class at.
    determination = _optimal_enum_two_phase(
        _control(Mode.OPTIMAL_ENUM, _PARTIAL), _on_model_for, 30.0, False
    )
    assert isinstance(determination, Inconclusive)


def test_a_partial_second_phase_of_the_optimal_driver_is_inconclusive(
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
        control: Control, on_model: Callable[[Model], None], budget: float
    ) -> tuple[bool, SolveResult]:
        nonlocal calls
        calls += 1
        outcome = real(control, on_model, budget)
        # Both phases solve for real, so the collector holds models exactly as a truncated phase 2
        # would leave it; only the reported result is swapped for one whose search did not finish.
        return outcome if calls == 1 else (True, partial[1])

    monkeypatch.setattr(solvers, "_solve_under_budget", one_good_then_partial)

    determination = _optimal_enum_two_phase(_control(Mode.OPTIMAL_ENUM), _on_model_for, 30.0, False)
    assert calls == 2, "phase 1 must have proven an optimum, so that phase 2 ran"
    assert isinstance(determination, Inconclusive)


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
    determination = _drive(
        _control(Mode.DEFAULT, program=_PLAIN), Mode.DEFAULT, collector, collector.on_model, 30.0
    )
    assert isinstance(determination, ConsistentWitness)


@pytest.mark.parametrize("mode", [Mode.ENUM_ALL, Mode.BRAVE_ALL, Mode.CAUTIOUS_ALL, Mode.OPTIMAL])
def test_a_complete_search_over_a_collection_is_consistent(mode: Mode) -> None:
    # The other side of the requirement: an unlimited search over this program does finish, so the
    # reading stands. Without this a fix that reported every collection as UNDECIDED would pass.
    collector = _Collector()
    determination = _drive(_control(mode), mode, collector, collector.on_model, 30.0)
    assert isinstance(determination, Consistent)


def test_a_complete_optimal_class_is_consistent() -> None:
    # Both phases of the optimal driver finish when nothing caps them.
    determination = _optimal_enum_two_phase(_control(Mode.OPTIMAL_ENUM), _on_model_for, 30.0, False)
    assert isinstance(determination, Consistent)
