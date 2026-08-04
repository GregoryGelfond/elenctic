"""What a user sees when a case cannot be run: an error, not a traceback.

An error is not a verdict, so it must not borrow a verdict's exit status, and it must not cost the
run the results of the cases that did complete. These drive the CLI end to end.
"""

from pathlib import Path

import pytest

from elenctic import cli, discovery
from elenctic.checks import CheckReport
from elenctic.cli import ExitStatus, main
from elenctic.discovery import Case
from elenctic.harness import run_case
from elenctic.result import SeamError
from elenctic.solvers import TIME_BUDGET

_GOOD = "% @expect sat\n% @count  2\n\n1 { tea; coffee } 1.\n#show tea/0.\n#show coffee/0.\n"
_UNSAFE = "% @expect sat\n% @count  1\n\nq(1).\np(X) :- q(Y).\n"
# Fails while the corpus is being *discovered* rather than while it is being solved: clingo cannot
# resolve the include, so the case never gets built.
_BAD_INCLUDE = '% @expect sat\n% @count  1\n\n#include "no_such_library.lp".\n'
_THEORY = "% @elenctic solver clingcon\n% @expect sat\n% @assign { x=1 }\n\n&sum { x } = 1.\n"


def _corpus(root: Path, **cases: str) -> str:
    """Write each named case into ``root`` and return the target to run."""
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return str(root)


def test_an_ungroundable_case_exits_as_an_error_not_a_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main([_corpus(tmp_path, broken=_UNSAFE)])
    captured = capsys.readouterr()
    # An error register, not a verdict: 1 would claim the case was tested and decided wrong.
    # 2 rather than 3 because the program under test is the author's to fix, not elenctic's.
    assert status == ExitStatus.USER_FAULT
    assert "Traceback" not in captured.err
    # The author needs the offending line and the cause, not a summary that grounding stopped.
    assert "unsafe" in captured.err
    assert "broken.lp:5" in captured.err


def test_an_ungroundable_case_does_not_cost_the_other_cases_their_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The sharp end of the defect: the run used to abort on the broken case, so the healthy cases'
    # results went with it — including the summary line — and stdout came back empty.
    status = main([_corpus(tmp_path, aaa_good=_GOOD, zzz_broken=_UNSAFE)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT
    assert "passed" in captured.out, "the summary of the cases that ran must survive"
    assert "1/2 passed" in captured.out


def test_an_undiscoverable_case_does_not_cost_the_other_cases_their_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same guarantee one stage earlier. The runner isolates a case that fails to *ground*, but a
    # case that fails while the corpus is being *walked* — an unresolvable #include, an undecodable
    # byte, a malformed contract — aborted discovery itself, so no case ran at all and every other
    # result was lost. Whether a case can be run is a fact about that case, at either stage.
    status = main([_corpus(tmp_path, aaa_good=_GOOD, zzz_bad=_BAD_INCLUDE)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT
    assert "Traceback" not in captured.err
    assert "1/2 passed" in captured.out, "the healthy case's result must survive the bad one"
    assert "could not be run" in captured.out
    assert "zzz_bad.lp" in captured.err, "the offending file must be named"


def test_an_explicitly_named_undiscoverable_file_is_still_loud(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Tolerance belongs to the walk, not to a file the user pointed at. Naming one file and getting
    # a summary saying nothing ran would bury the only thing that was asked about.
    (tmp_path / "named.lp").write_text(_BAD_INCLUDE, encoding="utf-8")
    status = main([str(tmp_path / "named.lp")])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT
    assert "Traceback" not in captured.err
    assert "no_such_library.lp" in captured.err


def test_a_missing_declared_solver_exits_as_an_error_with_a_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    status = main([_corpus(tmp_path, theory=_THEORY)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT
    assert 'pip install "elenctic[theory]"' in captured.err


def test_a_missing_declared_solver_costs_only_the_cases_that_declare_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An absent optional backend is an environment problem with one case's name on it. The cases
    # that do not declare it are unaffected and still report — one missing package must not zero
    # a whole corpus.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    status = main([_corpus(tmp_path, aaa_good=_GOOD, zzz_theory=_THEORY)])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT
    assert "1/2 passed" in captured.out


def test_a_dry_run_does_not_require_the_declared_solver(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # --explain narrates the derived run plan without solving, so requiring the backend to be
    # installed for it would be gating a command on something it never uses.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    status = main([_corpus(tmp_path, theory=_THEORY), "--explain"])
    captured = capsys.readouterr()
    assert status == ExitStatus.OK
    assert "clingcon" in captured.out, "the plan still names the declared solver"


def test_a_harness_fault_at_solve_time_costs_only_the_case_that_met_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reason elenctic's own invariants raise elenctic's own root rather than a bare ValueError:
    # HarnessError is a family the per-case region catches, so a result that cannot be right costs
    # one case its verdict. An exception outside the taxonomy reaches the outermost frame instead
    # and ends the run, discarding every case still to come — including ones that had already
    # passed. Raised from the solve path, which is where those invariants live.
    def broken(case: Case, budget: float = TIME_BUDGET) -> tuple[CheckReport, ...]:
        if case.contract_source.name == "mmm_broken.lp":
            raise SeamError("narrowing seam: a shape that does not populate what a check reads")
        return run_case(case, budget=budget)

    monkeypatch.setattr(cli, "run_case", broken)
    status = main([_corpus(tmp_path, aaa_good=_GOOD, mmm_broken=_GOOD, zzz_good=_GOOD)])
    captured = capsys.readouterr()
    assert status == ExitStatus.HARNESS_FAULT, (
        "a harness fault is elenctic's own error register — never a verdict, and never filed with "
        "the faults a user can fix"
    )
    assert "mmm_broken.lp" in captured.err, "the reader has to be told which case it was"
    assert "2/3 passed, 1 harness error(s)" in captured.out, (
        "the cases either side of it keep their results, and the one that broke is accounted for"
    )
