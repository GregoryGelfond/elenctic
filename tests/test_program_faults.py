"""The program-fault register: a program that cannot be run is not an elenctic bug.

``ProgramError`` says the program under test cannot be run — a fault its author fixes in the
``.lp``. ``HarnessError`` says elenctic violated one of its own invariants — a fault its author
reports. The two are disjoint roots, so neither can be caught as the other, and neither is ever a
verdict about the program's answer-set behaviour.
"""

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import TracebackType
from typing import cast

import pytest
from clingo import Control
from clingo.solving import Model, SolveHandle

from elenctic.outcome import ErrorKind, error_kind
from elenctic.program import ProgramError
from elenctic.result import HarnessError
from elenctic.run import Mode

# Past `solvers.__all__`: `_CallbackGuard` is what carries an exception's own type back across
# clingo's callback boundary, so it is constructed here with a callback that explodes on purpose;
# `_solve_under_budget` is reached for the same reason it is elsewhere — it takes this file's own
# `Control`, where the declared facades build theirs from a `Mode` and a program.
from elenctic.solvers import _CallbackGuard, _solve_under_budget, run_clingcon, run_clingo

_UNSAFE = "q(1).\np(X) :- q(Y).\n"  # parses, but X never binds, so it will not ground
_CHOICE = "1 {a; b} 1. #show a/0. #show b/0."
# 2^20 answer sets: far more than a zero budget can enumerate, so the wait is missed and the
# run takes the cancel path rather than finishing before the guard has anything to do.
_WIDE = "{ p(1..20) }.\n#show p/1.\n"


def _quiet(_code: object, _message: str) -> None:
    """Keep clingo's own diagnostics out of the test output."""


def test_a_program_fault_is_not_a_harness_bug() -> None:
    # The subtype relation would be a false claim: a program that will not ground is its author's
    # to fix, not evidence that elenctic is broken.
    assert not issubclass(ProgramError, HarnessError)
    assert not isinstance(ProgramError("cannot ground"), HarnessError)


def test_a_harness_bug_is_not_a_program_fault() -> None:
    # The other direction of the same disjointness.
    assert not issubclass(HarnessError, ProgramError)
    assert not isinstance(HarnessError("seam breach"), ProgramError)


def test_an_ungroundable_program_is_a_program_fault(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.lp"
    source.write_text(_UNSAFE, encoding="utf-8")
    with pytest.raises(ProgramError, match=r"cannot run the program: .*unsafe variables") as caught:
        run_clingo(Mode.ENUM_ALL, files=(source,))
    # The message has to carry what its author needs in order to fix it. clingo reports the
    # offending line and the unsafe variable through its logger; the exception it raises says only
    # that grounding stopped, so a report built from the exception alone would be useless.
    assert "unsafe" in str(caught.value)
    assert "unsafe.lp:2" in str(caught.value)


def test_an_ungroundable_program_is_never_unsatisfiable(tmp_path: Path) -> None:
    # A program that will not ground has no answer sets *defined*, which is not the same as having
    # none. Reporting it as unsatisfiable would silently pass an `@expect unsat` contract written
    # against a broken program — the worst outcome available to a testing framework.
    source = tmp_path / "unsafe.lp"
    source.write_text(_UNSAFE, encoding="utf-8")
    with pytest.raises(ProgramError, match=r"cannot run the program: .*unsafe variables"):
        run_clingo(Mode.DEFAULT, files=(source,))


def _exploding(_model: Model) -> bool:
    """A model callback standing in for an elenctic-internal fault during a solve."""
    raise HarnessError("seam breach")


def _grounded_choice() -> Control:
    control = Control(["--models=0"], logger=_quiet)
    control.add("base", [], _CHOICE)
    control.ground([("base", [])])
    return control


def test_an_async_solve_erases_the_type_of_a_callback_exception() -> None:
    # The premise the guard exists for, pinned against the solver rather than assumed: driving the
    # solve asynchronously, clingo does not re-raise a callback exception unchanged — it surfaces
    # at get() as a plain RuntimeError carrying only the message. If a future clingo stops doing
    # this, this test fails loudly and the guard can be reconsidered.
    control = _grounded_choice()  # bound to a local: the control must outlive the solve handle
    # The solve is driven outside the raises block, so what the block holds is the one call this
    # test is about: `get()` is where the callback's exception is said to surface, and pinning the
    # raise to that call is what makes the claim in the comment above checkable rather than merely
    # true of the pair.
    with control.solve(on_model=_exploding, async_=True) as handle:
        handle.wait(30.0)
        with pytest.raises(RuntimeError) as caught:
            handle.get()
    assert type(caught.value) is RuntimeError, "the original type is expected to be erased here"
    assert "seam breach" in str(caught.value), "only the message survives the rewrap"


def test_an_ungroundable_theory_program_is_a_program_fault(tmp_path: Path) -> None:
    # The clingcon wrap is the wider one — it encloses the theory registration, the rewrite, the
    # ground and the theory's own prepare — so the translation is exercised through it too, not
    # only through the plain clingo path.
    source = tmp_path / "unsafe-theory.lp"
    source.write_text("&sum { x } = 1.\n" + _UNSAFE, encoding="utf-8")
    with pytest.raises(ProgramError, match=r"cannot run the program: .*unsafe variables") as caught:
        run_clingcon(Mode.ENUM_ALL, files=(source,))
    assert "unsafe" in str(caught.value)
    assert "unsafe-theory.lp" in str(caught.value)


def test_a_harness_fault_inside_the_callback_stays_a_harness_fault() -> None:
    # What the guard buys, over the erasure pinned above: the surrounding boundary reads a
    # RuntimeError as a fault in the program under test, so without this an elenctic-internal
    # failure raised during a solve would be reported as its author's fault.
    with pytest.raises(HarnessError, match="seam breach"):
        _solve_under_budget(_grounded_choice(), _exploding, 30.0)


class _CancellingHandle:
    """A solve handle that fires the callback and then reports the budget as missed.

    This is the shape a cancelled solve takes: the cancellation absorbs the callback's exception,
    so ``get()`` returns normally and nothing re-raises on the way out. Faked rather than provoked
    from a real solve, because reaching it for real is a race between the callback firing and the
    budget poll returning — a test built on that would be flaky, and this path is worth pinning
    exactly."""

    def __init__(self, on_model: Callable[[Model], bool]) -> None:
        self._on_model = on_model

    def __enter__(self) -> _CancellingHandle:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def wait(self, _budget: float) -> bool:
        with suppress(Exception):  # the solver absorbs it; the guard has already recorded it
            self._on_model(cast(Model, None))
        return False  # the budget was missed

    def cancel(self) -> None:
        return None

    def get(self) -> None:
        return None  # a cancelled solve returns without raising


class _CancellingControl:
    """A control whose solve always takes the cancelled path above."""

    def solve(self, on_model: Callable[[Model], bool], async_: bool) -> _CancellingHandle:
        assert async_, "the facade always solves asynchronously"
        return _CancellingHandle(on_model)


def test_a_recorded_callback_fault_survives_a_missed_budget() -> None:
    # The failure this guards: a cancelled solve raises nothing, so an elenctic fault recorded by
    # the callback would be dropped and the run would report `completed=False` — which reduces to
    # UNDECIDED. That presents an internal bug as a verdict about the program under test, a
    # sharper version of the miscostuming this module exists to prevent.
    with pytest.raises(HarnessError, match="seam breach"):
        _solve_under_budget(cast(Control, _CancellingControl()), _exploding, 0.0)


def test_the_callback_guard_records_the_original_exception() -> None:
    # The guard's own contract, exercised without a solver: it re-raises on the way out (so the
    # solve still aborts) and keeps the original, which is what the driver reads back afterwards.
    guard = _CallbackGuard(_exploding)
    with pytest.raises(HarnessError, match="seam breach"):
        guard(None)  # type: ignore[arg-type]
    assert isinstance(guard.failure, HarnessError)


def _closing_fails(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """Make clingo's solve handle fail on close, the way a real teardown failure does.

    ``SolveHandle.__exit__`` closes unconditionally — it never reads ``exc_type`` — and routes the
    result through ``_handle_error``, which raises a plain ``RuntimeError`` for anything that is not
    a bad allocation. Simulated rather than provoked for real, because making
    ``clingo_solve_handle_close`` fail takes a solver-level failure no Python caller can force; the
    real close still runs first, so the handle is released exactly as it would be.
    """
    real_exit = SolveHandle.__exit__

    def close_fails(
        self: SolveHandle,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        # The real close first, so the handle is genuinely released and this leaves no solver state
        # behind for the tests that follow. clingo carries no annotations for this method, which is
        # what the ignore is about — not a shape this file is unsure of.
        real_exit(self, exc_type, exc_val, exc_tb)  # type: ignore[no-untyped-call]
        raise RuntimeError(message)

    monkeypatch.setattr(SolveHandle, "__exit__", close_fails)


def test_a_solve_that_answered_and_then_failed_to_close_is_not_the_programs_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The contradiction, not the route to it: elenctic could not close its own solve handle, and the
    # corpus author was told their program cannot be run. `__exit__` runs on the way out of the
    # `with`, which is *after* the `try` that guards `handle.get()`, so the close's RuntimeError
    # sailed past every guard into `_program_faults` — whose whole job is to say the program is at
    # fault. A reader would be sent to fix an `.lp` that is correct.
    #
    # The injected text deliberately avoids the word "close", so that the assertions below can only
    # be satisfied by what *elenctic* says. Matching on the injected words instead is a test that
    # passes on its own input, and this one did until it was provoked.
    _closing_fails(monkeypatch, "teardown exploded")

    with pytest.raises(HarnessError, match="could not close the solve") as caught:
        run_clingo(Mode.ENUM_ALL, program=_CHOICE)

    assert error_kind(caught.value) is ErrorKind.HARNESS, (
        "the locus is elenctic's, so a reader is not sent to a program that is not at fault"
    )
    assert not isinstance(caught.value, ProgramError), "the two roots are disjoint"


def test_a_close_failure_says_the_solve_had_already_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # What the reader is told has to distinguish the close from the solve, or "a harness fault"
    # leaves them looking at a solve that in fact succeeded.
    _closing_fails(monkeypatch, "teardown exploded")

    with pytest.raises(HarnessError, match="could not close the solve") as caught:
        run_clingo(Mode.ENUM_ALL, program=_CHOICE)

    said = str(caught.value)
    assert "the solve ran" in said, "the solve is exonerated in elenctic's own words"
    assert "teardown exploded" in said, "and the solver's own words survive"
    assert "cannot run the program" not in said, "which is what it used to say, and was not true"


def test_a_solve_that_fails_before_it_answers_is_still_the_programs_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The path the fix must NOT touch, and the control on the discriminator itself: a RuntimeError
    # raised while the solver is working is what `_program_faults` exists for, and it must still
    # arrive as a ProgramError. A discriminator that never re-raised would trade one misattribution
    # for its opposite.
    #
    # Through `get()` rather than through an ungroundable program, and the difference is the whole
    # value of the test: a ground failure is refused in a *different* fault region and never reaches
    # the solve at all, so it holds nothing about this code. Written that way first, and breaking
    # the discriminator left it green.
    def get_fails(self: SolveHandle) -> object:
        raise RuntimeError("the solver stopped mid-search")

    monkeypatch.setattr(SolveHandle, "get", get_fails)

    with pytest.raises(ProgramError, match="cannot run the program"):
        run_clingo(Mode.ENUM_ALL, program=_CHOICE)


def test_an_ungroundable_program_is_refused_before_any_solve_begins(tmp_path: Path) -> None:
    # The sibling of the above, kept apart from it because they are two different regions: this one
    # is refused around `ground`, and never reaches `_solve_under_budget`.
    case = tmp_path / "unsafe.lp"
    case.write_text(_UNSAFE, encoding="utf-8")

    with pytest.raises(ProgramError, match="cannot run the program"):
        run_clingo(Mode.ENUM_ALL, files=(case,))


def test_a_cancel_that_fails_is_elenctics_fault_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # The sibling of the close, and the reason the rule is stated over *operations* rather than over
    # the one that was noticed first. Cancelling is the hang guard's normal doing — it is what a
    # missed budget triggers — so a cancel that fails is elenctic's, exactly as a close that fails
    # is. Reported as the program's fault until this, and by the same route: clingo raises a plain
    # RuntimeError and the fault region reads that as the program's.
    def cancel_fails(self: SolveHandle) -> None:
        raise RuntimeError("cancel refused")

    monkeypatch.setattr(SolveHandle, "cancel", cancel_fails)

    # A budget of zero is missed by construction, which is what puts the run on the cancel path.
    with pytest.raises(HarnessError, match="could not cancel the solve") as caught:
        run_clingo(Mode.ENUM_ALL, program=_WIDE, budget=0.0)

    assert error_kind(caught.value) is ErrorKind.HARNESS
    assert "cancel refused" in str(caught.value), "the solver's own words survive"


def test_a_callback_fault_survives_a_close_that_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two faults at once, and the first one is the one the reader needs. A callback failure is
    # recorded and re-raised with its own type; the close then runs on the way out and, under a
    # `with`, its RuntimeError would *replace* that HarnessError outright — leaving the corpus
    # author accused of a broken program by a teardown they cannot see. Closing by hand is what
    # keeps the original in flight.
    _closing_fails(monkeypatch, "teardown exploded")

    with pytest.raises(HarnessError, match="seam breach") as caught:
        _solve_under_budget(_grounded_choice(), _exploding, 30.0)

    assert not isinstance(caught.value, ProgramError), "the callback's fault, not the program's"
