"""A resource the run uses up is reported, not dumped as a traceback.

Grounding is unbounded — clingo's own API offers no clock and no size limit on it — so a program
small enough to write in one line can run out of memory. clingo raises that as ``MemoryError``,
which
is not a ``RuntimeError`` and so was named by no ``except`` clause in the package: it escaped every
register and reached the user as a stack trace, past the bar the rest of the CLI holds to.

Being unable to *bound* the resource does not excuse being unable to *report* it.
"""

from pathlib import Path
from typing import NoReturn

import pytest

from elenctic import cli
from elenctic.checks import CheckReport
from elenctic.cli import ExitStatus, main
from elenctic.discovery import Case
from elenctic.harness import run_case
from elenctic.outcome import ErrorKind, RunOutcome, Scope
from elenctic.solvers import TIME_BUDGET

_GOOD = "% @expect sat\n% @count  1\n\na.\n#show a/0.\n"


def _corpus(root: Path, *names: str) -> None:
    for name in names:
        (root / f"{name}.lp").write_text(_GOOD, encoding="utf-8")


def test_running_out_of_memory_is_reported_as_an_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Raised where clingo raises it — from the solve path, during a case. A real grounding bomb
    # would take minutes and gigabytes to provoke; the condition under test is what elenctic does
    # when it arrives, not that clingo can be made to produce it.
    (tmp_path / "case.lp").write_text(_GOOD, encoding="utf-8")

    def out_of_memory(*_args: object, **_kwargs: object) -> None:
        raise MemoryError("std::bad_alloc")

    monkeypatch.setattr(cli, "run_case", out_of_memory)
    status = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT, (
        "a resource run out of is the error register, never a verdict"
    )
    assert "Traceback" not in captured.err
    assert "memory" in captured.err.lower()


def test_a_case_that_runs_out_of_memory_costs_only_its_own_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every other way a case can fail to run is reported against its own file while the rest of the
    # corpus still runs — a guarantee the CLI states in its own documentation. Exhausting memory
    # was the one register that abandoned it, and it abandoned it for the failure most likely to
    # arrive in a large corpus, where the results it discards are worth the most.
    _corpus(tmp_path, "first", "greedy", "last")

    def greedy(case: Case, budget: float = TIME_BUDGET) -> tuple[CheckReport, ...]:
        if case.contract_source.name == "greedy.lp":
            raise MemoryError("std::bad_alloc")
        return run_case(case, budget=budget)  # the other two cases run for real

    monkeypatch.setattr(cli, "run_case", greedy)
    status = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT, (
        "a resource the run used up is the error register, never a verdict"
    )
    assert "greedy.lp" in captured.err, "the reader has to be told which case it was"
    assert "2/3 passed, 1 could not be run" in captured.out, (
        "the other two cases keep their results, and the one that did not run is accounted for"
    )


def test_memory_run_out_of_outside_a_case_is_still_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The outermost handler stays the backstop it was meant to be: an allocation that fails where
    # no case owns it — walking the corpus, here — has no case to be reported against, and still
    # must not reach the user as a stack trace.
    _corpus(tmp_path, "case")

    def out_of_memory(*_args: object, **_kwargs: object) -> NoReturn:
        raise MemoryError("std::bad_alloc")

    monkeypatch.setattr(cli, "inspect_corpus", out_of_memory)
    status = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT
    assert "Traceback" not in captured.err
    assert "memory" in captured.err.lower()


def test_an_unexpected_fault_is_framed_as_an_elenctic_bug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The complement. Anything not anticipated is elenctic's fault by definition, and saying so is
    # what tells a user it is not their corpus to fix. The traceback is kept — it is the report —
    # but it is introduced rather than dumped, and the status says the same thing the prose does.
    (tmp_path / "case.lp").write_text(_GOOD, encoding="utf-8")

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise ZeroDivisionError("an elenctic bug")

    monkeypatch.setattr(cli, "run_case", unexpected)
    status = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert status == ExitStatus.HARNESS_FAULT, (
        "elenctic's own register, apart from the faults a user can fix"
    )
    assert "elenctic" in captured.err.lower(), "the user must be told whose fault this is"
    assert "ZeroDivisionError" in captured.err, "the cause is still reported, not swallowed"


def test_the_outermost_handler_files_the_fault_it_met_rather_than_picking_a_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The status is read off a record, which puts the weight on the record being right: its locus
    # is what decides whose fault the run reports, and its message is the whole of what a consumer
    # has once the traceback has scrolled past. Watched where the outcome is consumed, because a
    # frame that hands back an integer has thrown away everything else it knew.
    (tmp_path / "case.lp").write_text(_GOOD, encoding="utf-8")

    def unexpected(*_args: object, **_kwargs: object) -> NoReturn:
        raise ZeroDivisionError("an elenctic bug")

    filed: list[RunOutcome] = []
    decide = cli.exit_status

    def watched(outcome: RunOutcome) -> int:
        filed.append(outcome)
        return decide(outcome)

    monkeypatch.setattr(cli, "run_case", unexpected)
    monkeypatch.setattr(cli, "exit_status", watched)
    assert main([str(tmp_path)]) == ExitStatus.HARNESS_FAULT
    capsys.readouterr()
    (outcome,) = filed
    (record,) = outcome.errors
    assert record.kind is ErrorKind.HARNESS, "the locus the status was read off"
    assert record.scope is Scope.CORPUS, "no case owned it, so it belongs to the run"
    assert "ZeroDivisionError" in record.message, (
        "a record whose reason was dropped is not a report, and the traceback is not in it"
    )
