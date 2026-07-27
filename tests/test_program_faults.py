"""The program-fault register: a program that cannot be run is not an elenctic bug.

``ProgramError`` says the program under test cannot be run — a fault its author fixes in the
``.lp``. ``HarnessError`` says elenctic violated one of its own invariants — a fault its author
reports. The two are disjoint roots, so neither can be caught as the other, and neither is ever a
verdict about the program's answer-set behaviour.
"""

from pathlib import Path

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


def test_a_harness_fault_inside_the_callback_stays_a_harness_fault() -> None:
    # The miscostuming an asynchronous solve makes possible: clingo rewraps an exception raised in
    # a model callback as a plain RuntimeError, and the surrounding boundary reads RuntimeError as
    # a fault in the program under test. elenctic's own failure has to survive that intact.
    control = Control(["--models=0"], logger=_quiet)
    control.add("base", [], _CHOICE)
    control.ground([("base", [])])

    def explode(_model: Model) -> None:
        raise HarnessError("seam breach")

    with pytest.raises(HarnessError, match="seam breach"):
        _solve_under_budget(control, explode, 30.0)


def test_the_callback_guard_records_the_original_exception() -> None:
    # Pinning the mechanism directly. A test written against a *synchronous* solve would pass
    # without exercising any of this, because clingo preserves the exception type there.
    def explode(_model: Model) -> None:
        raise HarnessError("seam breach")

    guard = _CallbackGuard(explode)
    with pytest.raises(HarnessError):
        guard(None)  # type: ignore[arg-type]
    assert isinstance(guard.failure, HarnessError)
