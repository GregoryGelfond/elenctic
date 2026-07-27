"""The program-fault register: a program that cannot be run is not an elenctic bug.

``ProgramError`` says the program under test cannot be run — a fault its author fixes in the
``.lp``. ``HarnessError`` says elenctic violated one of its own invariants — a fault its author
reports. The two are disjoint roots, so neither can be caught as the other, and neither is ever a
verdict about the program's answer-set behaviour.
"""

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest
from clingo import Control
from clingo.solving import Model

from elenctic.program import ProgramError
from elenctic.result import HarnessError
from elenctic.run import Mode
from elenctic.solvers import _CallbackGuard, _solve_under_budget, run_clingo

_UNSAFE = "q(1).\np(X) :- q(Y).\n"  # parses, but X never binds, so it will not ground
_CHOICE = "1 {a; b} 1. #show a/0. #show b/0."


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
    with pytest.raises(ProgramError) as caught:
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
    with pytest.raises(ProgramError):
        run_clingo(Mode.DEFAULT, files=(source,))


def _exploding(_model: Model) -> None:
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
    with (
        pytest.raises(RuntimeError) as caught,
        control.solve(on_model=_exploding, async_=True) as handle,
    ):
        handle.wait(30.0)
        handle.get()
    assert type(caught.value) is RuntimeError, "the original type is expected to be erased here"
    assert "seam breach" in str(caught.value), "only the message survives the rewrap"


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

    def __init__(self, on_model: Callable[[Model], None]) -> None:
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

    def solve(self, on_model: Callable[[Model], None], async_: bool) -> _CancellingHandle:
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
    with pytest.raises(HarnessError):
        guard(None)  # type: ignore[arg-type]
    assert isinstance(guard.failure, HarnessError)
