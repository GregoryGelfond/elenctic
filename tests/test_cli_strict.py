"""The three strictness axes: closed vocabulary and the soundness floor are *always*
errors (independent of ``--strict``); hygiene is the ``--strict`` dial — warn with an end-of-run
summary by default (no exit-code effect), escalated to errors that fail the run under ``--strict``
(the CI gate). All hygiene issues are aggregated and reported together."""

from pathlib import Path

import pytest

from elenctic.cli import main
from elenctic.discovery import ORPHAN_LIBRARY, UNDECLARED_SOLVER
from elenctic.outcome import ExitStatus

_DECLARED = "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\nok.\n#show ok/0.\n"
_UNDECLARED = "% @expect sat\n% @model { ok }\nok.\n#show ok/0.\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- hygiene: the --strict dial (warn by default, error under --strict) ---


def test_orphan_library_warns_by_default_with_no_exit_effect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _DECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")  # contract-free, no case #includes it
    status = main([str(tmp_path)])
    assert (
        status == ExitStatus.OK
    )  # the case passes; hygiene does not move the exit code by default
    assert "orphan" in capsys.readouterr().err.lower()  # but it is reported


def test_orphan_library_fails_under_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _DECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")
    status = main([str(tmp_path), "--strict"])
    assert status == ExitStatus.USER_FAULT  # escalated to a corpus error (the CI gate)
    assert "orphan" in capsys.readouterr().err.lower()


def test_undeclared_solver_is_silent_by_default_and_errors_under_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Relying on the stated clingo default is legitimate, so it is silent by default (the Unix rule
    # of silence; the mypy --strict / pytest --strict-markers posture) and an error only under
    # --strict — unlike an orphan library, which is a real smell warned by default.
    write(tmp_path / "case.lp", _UNDECLARED)  # no @elenctic solver → defaulted to clingo
    assert main([str(tmp_path)]) == ExitStatus.OK  # passes
    assert "undeclared" not in capsys.readouterr().err.lower()  # silent by default (no nag)
    assert (
        main([str(tmp_path), "--strict"]) == ExitStatus.USER_FAULT
    )  # required explicit under --strict
    assert "undeclared" in capsys.readouterr().err.lower()


def test_each_reported_observation_renders_the_sentence_its_own_record_carries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # One home per observation: the sentence a reader is shown and the sentence a consumer reads
    # are one string, so neither can be edited into disagreement with the other. The aggregated
    # line is the one that had to be watched — it states the observation once for a set of files,
    # and stating it from anywhere but the records would leave the records unread.
    write(tmp_path / "case.lp", _UNDECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")
    assert main([str(tmp_path), "--strict"]) == ExitStatus.USER_FAULT
    err = capsys.readouterr().err
    assert ORPHAN_LIBRARY in err
    assert UNDECLARED_SOLVER in err


def test_the_hygiene_heading_says_whether_the_run_failed_on_what_follows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The heading and the exit status are two readings of one grading. A reader shown "warnings"
    # over the same observations a gate has just failed the run on would be looking at the tool
    # contradicting itself about what it thinks of them.
    write(tmp_path / "case.lp", _DECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")
    assert main([str(tmp_path)]) == ExitStatus.OK
    assert "hygiene warnings:" in capsys.readouterr().err
    assert main([str(tmp_path), "--strict"]) == ExitStatus.USER_FAULT
    assert "hygiene errors (--strict):" in capsys.readouterr().err


def test_a_clean_corpus_emits_no_hygiene_even_under_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _DECLARED)  # declared solver, no orphans
    status = main([str(tmp_path), "--strict"])
    err = capsys.readouterr().err.lower()
    assert status == ExitStatus.OK
    assert "orphan" not in err
    assert "hygiene" not in err


def test_hygiene_records_are_aggregated_and_reported_together(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _UNDECLARED)  # undeclared solver
    write(tmp_path / "orphan.lp", "never(included).\n")  # and an orphan library
    status = main([str(tmp_path), "--strict"])
    err = capsys.readouterr().err.lower()
    assert status == ExitStatus.USER_FAULT
    # Both hygiene axes in the one summary, rather than whichever was observed first.
    assert "orphan" in err
    assert "undeclared" in err


def test_explain_also_reports_hygiene_and_strict_still_escalates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --explain is a corpus inspection, so hygiene is reported there too; --strict escalates it to
    # exit 2 even in the dry-run (lint a corpus's hygiene without solving it).
    write(tmp_path / "case.lp", _DECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")
    assert main([str(tmp_path), "--explain"]) == ExitStatus.OK  # dry-run passes; hygiene warns only
    assert "orphan" in capsys.readouterr().err.lower()
    assert (
        main([str(tmp_path), "--explain", "--strict"]) == ExitStatus.USER_FAULT
    )  # escalates in --explain too


# --- the exit-code interaction with the verdict register ---


def test_strict_does_not_relax_a_verdict_failure(tmp_path: Path) -> None:
    # A clean-hygiene corpus whose case FAILs is exit 1 with or without --strict (hygiene clean →
    # the verdict register stands). b is shown but never derived, so @cautious { b } FAILs (b ∉ ⋂).
    write(
        tmp_path / "case.lp",
        "a. #show a/0. #show b/0.\n% @expect sat\n% @cautious { b }\n% @elenctic solver clingo\n",
    )
    assert main([str(tmp_path), "--strict"]) == ExitStatus.NOT_PASSED


def test_strict_hygiene_error_dominates_a_verdict_failure(tmp_path: Path) -> None:
    # Under --strict a hygiene violation is a corpus error (exit 2), dominating a verdict FAIL (1).
    write(
        tmp_path / "case.lp",  # FAILs (b ∉ ⋂) AND is undeclared (dirty hygiene)
        "a. #show a/0. #show b/0.\n% @expect sat\n% @cautious { b }\n",
    )
    assert main([str(tmp_path), "--strict"]) == ExitStatus.USER_FAULT


# --- the always-error axes (independent of --strict) ---


def test_closed_vocabulary_is_always_an_error(tmp_path: Path) -> None:
    # An unknown contract tag → ContractError → exit 2, with or without --strict (pydantic-style
    # extra='forbid'; mode-independent).
    write(tmp_path / "case.lp", "% @expect sat\n% @bogus xyz\n")
    assert main([str(tmp_path)]) == ExitStatus.USER_FAULT
    assert main([str(tmp_path), "--strict"]) == ExitStatus.USER_FAULT


def test_soundness_floor_is_always_an_error(tmp_path: Path) -> None:
    # a theory atom under default clingo → DiscoveryError → exit 2, with or without --strict.
    write(tmp_path / "case.lp", "% @expect sat\n&dom { 1..3 } = x.\n#show.\n")
    assert main([str(tmp_path)]) == ExitStatus.USER_FAULT
    assert main([str(tmp_path), "--strict"]) == ExitStatus.USER_FAULT
