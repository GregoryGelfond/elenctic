"""The three strictness axes (spec §5): closed vocabulary and the soundness floor are *always*
errors (independent of ``--strict``); hygiene is the ``--strict`` dial — warn with an end-of-run
summary by default (no exit-code effect), escalated to errors that fail the run under ``--strict``
(the CI gate). All hygiene issues are aggregated and reported together."""

from pathlib import Path

import pytest

from elenctic.cli import main

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
    assert status == 0  # the case passes; hygiene does not move the exit code by default
    assert "orphan" in capsys.readouterr().err.lower()  # but it is reported


def test_orphan_library_fails_under_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _DECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")
    status = main([str(tmp_path), "--strict"])
    assert status == 2  # escalated to a corpus error (the CI gate)
    assert "orphan" in capsys.readouterr().err.lower()


def test_undeclared_solver_is_silent_by_default_and_errors_under_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Relying on the stated clingo default is legitimate, so it is silent by default (the Unix rule
    # of silence; the mypy --strict / pytest --strict-markers posture) and an error only under
    # --strict — unlike an orphan library, which is a real smell warned by default.
    write(tmp_path / "case.lp", _UNDECLARED)  # no @elenctic solver → defaulted to clingo
    assert main([str(tmp_path)]) == 0  # passes
    assert "undeclared" not in capsys.readouterr().err.lower()  # silent by default (no nag)
    assert main([str(tmp_path), "--strict"]) == 2  # required explicit under --strict
    assert "undeclared" in capsys.readouterr().err.lower()


def test_a_clean_corpus_emits_no_hygiene_even_under_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _DECLARED)  # declared solver, no orphans
    status = main([str(tmp_path), "--strict"])
    err = capsys.readouterr().err.lower()
    assert status == 0
    assert "orphan" not in err and "hygiene" not in err


def test_hygiene_records_are_aggregated_and_reported_together(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "case.lp", _UNDECLARED)  # undeclared solver
    write(tmp_path / "orphan.lp", "never(included).\n")  # and an orphan library
    status = main([str(tmp_path), "--strict"])
    err = capsys.readouterr().err.lower()
    assert status == 2
    assert "orphan" in err and "undeclared" in err  # both axes in one summary


def test_explain_also_reports_hygiene_and_strict_still_escalates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --explain is a corpus inspection, so hygiene is reported there too; --strict escalates it to
    # exit 2 even in the dry-run (lint a corpus's hygiene without solving it).
    write(tmp_path / "case.lp", _DECLARED)
    write(tmp_path / "orphan.lp", "never(included).\n")
    assert main([str(tmp_path), "--explain"]) == 0  # dry-run passes; hygiene warns only
    assert "orphan" in capsys.readouterr().err.lower()
    assert main([str(tmp_path), "--explain", "--strict"]) == 2  # escalates in --explain too


# --- the exit-code interaction with the verdict register ---


def test_strict_does_not_relax_a_verdict_failure(tmp_path: Path) -> None:
    # A clean-hygiene corpus whose case FAILs is exit 1 with or without --strict (hygiene clean →
    # the verdict register stands). b is shown but never derived, so @cautious { b } FAILs (b ∉ ⋂).
    write(
        tmp_path / "case.lp",
        "a. #show a/0. #show b/0.\n% @expect sat\n% @cautious { b }\n% @elenctic solver clingo\n",
    )
    assert main([str(tmp_path), "--strict"]) == 1


def test_strict_hygiene_error_dominates_a_verdict_failure(tmp_path: Path) -> None:
    # Under --strict a hygiene violation is a corpus error (exit 2), dominating a verdict FAIL (1).
    write(
        tmp_path / "case.lp",  # FAILs (b ∉ ⋂) AND is undeclared (dirty hygiene)
        "a. #show a/0. #show b/0.\n% @expect sat\n% @cautious { b }\n",
    )
    assert main([str(tmp_path), "--strict"]) == 2


# --- the always-error axes (independent of --strict) ---


def test_closed_vocabulary_is_always_an_error(tmp_path: Path) -> None:
    # An unknown contract tag → ContractError → exit 2, with or without --strict (pydantic-style
    # extra='forbid'; mode-independent).
    write(tmp_path / "case.lp", "% @expect sat\n% @bogus xyz\n")
    assert main([str(tmp_path)]) == 2
    assert main([str(tmp_path), "--strict"]) == 2


def test_soundness_floor_is_always_an_error(tmp_path: Path) -> None:
    # R1: a theory atom under default clingo → DiscoveryError → exit 2, with or without --strict.
    write(tmp_path / "case.lp", "% @expect sat\n&dom { 1..3 } = x.\n#show.\n")
    assert main([str(tmp_path)]) == 2
    assert main([str(tmp_path), "--strict"]) == 2
