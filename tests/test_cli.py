"""The ``elenctic`` console entry: exit status separates pass / fail / error, and ``--explain``
narrates the derived run plan without solving."""

from pathlib import Path

import pytest

from elenctic import corpus
from elenctic.cli import main
from elenctic.outcome import ExitStatus
from elenctic.run import RoutingError
from elenctic.run import runs_for as real_runs_for


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_cli_passes_a_satisfied_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")
    status = main([str(tmp_path / "encodings")])
    assert status == ExitStatus.OK
    assert "1/1 passed" in capsys.readouterr().out


def test_cli_fails_a_violated_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # b is shown but never derived, so @cautious { b } FAILs (b ∉ ⋂).
    write(
        tmp_path / "encodings/g/e.lp",
        "a. #show a/0. #show b/0.\n% @expect sat\n% @cautious { b }\n",
    )
    status = main([str(tmp_path / "encodings")])
    assert status == ExitStatus.NOT_PASSED
    assert "FAIL" in capsys.readouterr().out


def test_cli_reports_a_malformed_contract_against_its_own_file_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A walked file that cannot be turned into a case is that file's problem, not the corpus's:
    # it is named and the other cases still run. Still the error register (2), never a verdict.
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @model { a }\n")  # no @expect
    status = main([str(tmp_path / "encodings")])
    assert status == ExitStatus.USER_FAULT
    err = capsys.readouterr().err
    assert "CASE ERROR" in err
    assert "e.lp" in err


def test_cli_reports_a_corpus_error_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The register above is per file; this one is genuinely about the corpus. A named target that
    # does not exist tests nothing, and there is no file to attribute it to.
    status = main([str(tmp_path / "no_such_directory")])
    assert status == ExitStatus.USER_FAULT
    assert "corpus error" in capsys.readouterr().err


def test_cli_explain_narrates_the_plan_without_solving(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @cautious { a }\n")
    status = main([str(tmp_path / "encodings"), "--explain"])
    out = capsys.readouterr().out
    assert status == ExitStatus.OK
    assert "CAUTIOUS_ALL (projects: no):" in out  # the run, its projection decision
    # the check, the claim it judges, and the fields it reads. The claim is named because a
    # contract may repeat the tag, and two claims a reader cannot tell apart explain nothing.
    assert "@cautious ({ a }) — reads {cautious}" in out


def test_cli_runs_the_krbook_dogfood_corpus(capsys: pytest.CaptureFixture[str]) -> None:
    # the vendored Gelfond programs pass end-to-end through the real console entry.
    krbook = Path(__file__).parent / "krbook" / "encodings"
    status = main([str(krbook)])
    assert status == ExitStatus.OK
    assert "4/4 passed" in capsys.readouterr().out


def test_cli_reports_a_misroute_as_a_harness_error_and_keeps_going(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A misroute is a harness error (exit 3 — elenctic's own, not a fault a user could fix),
    # reported distinctly, while the other cases still run. runs_for is correct-by-construction, so
    # inject the failure on one case.
    write(tmp_path / "encodings/good/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")
    write(tmp_path / "encodings/bad/e.lp", "a. #show a/0.\n% @expect sat\n% @note BOOM\n")

    def selectively_misroute(expectation: object, theory_in_force: bool = False) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(expectation, theory_in_force)  # type: ignore[arg-type]

    monkeypatch.setattr(corpus, "runs_for", selectively_misroute)
    status = main([str(tmp_path / "encodings")])
    captured = capsys.readouterr()
    assert (
        status == ExitStatus.HARNESS_FAULT
    )  # a harness error, not a verdict and not a corpus to fix
    assert "HARNESS ERROR" in captured.err and "bad" in captured.err  # the misrouted case named
    assert "1/2 passed" in captured.out  # the good case still ran and passed
    assert "1 harness error" in captured.out


def test_cli_explain_narrates_reads_and_the_projection_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --explain prints each check's reads and a per-run projects: line, so the reads/populates
    # surface is dogfooded. A shown-only clingcon enumeration projects (yes); a @count one does not
    # (no). The dry-run does not solve, so clingcon need not be installed.
    write(
        tmp_path / "encodings/shown/e.lp",
        "&dom {1..3} = v(x). ok. #show ok/0.\n"
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingcon\n",
    )
    write(
        tmp_path / "encodings/full/e.lp",
        "&dom {1..3} = v(x). ok. #show ok/0.\n"
        "% @expect sat\n% @count 3\n% @elenctic solver clingcon\n",
    )
    status = main([str(tmp_path / "encodings"), "--explain"])
    out = capsys.readouterr().out
    assert status == ExitStatus.OK
    assert "reads {shown census}" in out  # @model narrates its read token
    assert "projects: yes" in out  # the shown-only run projects
    assert "reads {full census}" in out  # @count narrates the full token
    assert "projects: no" in out  # the full-census run suppresses projection


def test_cli_explain_leads_with_the_note_gloss(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # @note is the headline of the --explain narration — the author's what/why *above* the
    # harness's how (the run plan, the reads). Multiple notes render in author order. A doc adjunct,
    # never a verdict (no semantic change). The position asserts pin the headline property (a note
    # loop moved below the run narration would still pass a mere substring-presence check).
    case = write(
        tmp_path / "c.lp",
        "% @expect sat\n% @model { ok }\n"
        "% @note feasible within budget\n% @note and within the deadline\n"
        "ok.\n#show ok/0.\n",
    )
    status = main([str(case), "--explain"])
    out = capsys.readouterr().out
    assert status == ExitStatus.OK
    first = out.index("note: feasible within budget")
    second = out.index("note: and within the deadline")
    assert first < second  # author order preserved
    assert second < out.index("(projects:")  # the notes lead, above the harness's "how"


def test_cli_explain_glosses_an_unsat_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The gloss reads case.expectation.notes uniformly over the Sat | Unsat union — an @unsat case
    # carries its note too (both bases carry notes).
    case = write(
        tmp_path / "u.lp", "% @expect unsat\n% @note no schedule fits the budget\na :- not a.\n"
    )
    status = main([str(case), "--explain"])
    assert status == ExitStatus.OK
    assert "no schedule fits the budget" in capsys.readouterr().out


def test_the_dry_run_reports_a_misroute_it_meets_and_names_the_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Surfacing a plan that cannot be built is what the dry run is for, so it is the mode where a
    # misroute matters most — and the one where it went untested. The diagnostic goes to standard
    # error, so it names the case there rather than relying on the narration beside it. The status
    # is the one a run would give the same fault: which mode met it says nothing about whose it is.
    write(tmp_path / "encodings/good/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")
    write(tmp_path / "encodings/bad/e.lp", "a. #show a/0.\n% @expect sat\n% @note BOOM\n")

    def selectively_misroute(expectation: object, theory_in_force: bool = False) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(expectation, theory_in_force)  # type: ignore[arg-type]

    monkeypatch.setattr(corpus, "runs_for", selectively_misroute)
    status = main([str(tmp_path / "encodings"), "--explain"])
    captured = capsys.readouterr()
    assert status == ExitStatus.HARNESS_FAULT, (
        "a plan that cannot be built is a harness error, never a clean dry run"
    )
    assert "HARNESS ERROR" in captured.err
    assert "bad" in captured.err, "standard error names the case on its own"


def test_the_dry_run_reports_a_file_it_could_not_use_and_still_narrates_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The guarantee a run gives — one unusable file costs its own result and no other's — is the
    # same guarantee in the mode whose whole purpose is inspection, where losing the narration of
    # every other case would defeat the point of asking. The file is reported, it moves the status,
    # and the healthy case is still narrated.
    write(tmp_path / "encodings/good/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")
    write(tmp_path / "encodings/bad/e.lp", '% @expect sat\n#include "no_such_library.lp".\n')
    status = main([str(tmp_path / "encodings"), "--explain"])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT, (
        "a file that will produce no verdict is a fault the author can fix"
    )
    assert "CASE ERROR" in captured.err and "no_such_library.lp" in captured.err
    assert "@model" in captured.out, "the case that could be planned is still planned"


@pytest.mark.parametrize(
    "flags", [["--explain"], ["--explain", "--strict"]], ids=["plain", "strict"]
)
def test_the_dry_run_reports_no_tally_because_it_decides_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    # The dry run narrates a plan; it produces no verdicts, so it has no cases to count. A tally
    # here could only be read as a result, and the honest number would be zero passed out of a
    # corpus of several — which is worse than saying nothing.
    # The solver is declared so that --strict has no hygiene to escalate: what is under test here
    # is that the dial grades observations without deciding whether to solve at all.
    write(
        tmp_path / "encodings/good/e.lp",
        "a. #show a/0.\n% @elenctic solver clingo\n% @expect sat\n% @model { a }\n",
    )
    write(
        tmp_path / "encodings/more/e.lp",
        "b. #show b/0.\n% @elenctic solver clingo\n% @expect sat\n% @model { b }\n",
    )
    status = main([str(tmp_path / "encodings"), *flags])
    captured = capsys.readouterr()
    assert status == ExitStatus.OK
    assert "passed" not in captured.out, "a dry run reports a plan, never a score"


@pytest.mark.parametrize(
    ("flag", "value", "echoed"),
    [
        ("--budget", "0", "0.0"),
        ("--budget", "-1", "-1.0"),
        ("--budget", "inf", "inf"),
        ("--budget", "nan", "nan"),
        ("--deadline", "0", "0.0"),
        ("--deadline", "-1", "-1.0"),
        ("--deadline", "inf", "inf"),
        ("--deadline", "nan", "nan"),
    ],
    ids=[
        "budget-zero",
        "budget-negative",
        "budget-infinite",
        "budget-not-a-number",
        "deadline-zero",
        "deadline-negative",
        "deadline-infinite",
        "deadline-not-a-number",
    ],
)
def test_a_duration_that_is_not_a_positive_finite_number_of_seconds_is_refused(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], flag: str, value: str, echoed: str
) -> None:
    # Converting the text is as far as the parser goes: it takes a zero, a negative, and both
    # spellings of a number that is not one. Two of the four have no JSON form, so a report
    # carrying one is a report no consumer can parse; the other two are simply not durations. All
    # four are refused where the parser refuses a flag it cannot read — before the run — so the
    # answer is a sentence about what was typed rather than a fault reported against a corpus.
    #
    # What the diagnostic has to contain is asserted rather than that it is non-empty: the flag, the
    # domain, the value that was rejected, and what to do instead. A message missing any of those
    # sends the reader back to guess at the one thing they came to be told.
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")

    status = main([str(tmp_path / "encodings"), flag, value])

    captured = capfd.readouterr()
    assert status == ExitStatus.USER_FAULT, (
        "a command line that cannot be run is a fault its author can fix"
    )
    assert captured.out == "", "and it produced no run, so there is nothing to report about one"
    assert captured.err.startswith("usage error: "), "filed where the reader's own mistakes are"
    assert flag in captured.err, "the diagnostic names the flag that was wrong"
    assert "positive finite number of seconds" in captured.err, "and the domain it wanted"
    assert echoed in captured.err, "and the value it refused, so the reader can see what was read"


@pytest.mark.parametrize(
    ("flag", "remedy"),
    [
        ("--budget", "large finite number"),
        ("--deadline", "leaves --deadline off"),
    ],
    ids=["budget", "deadline"],
)
def test_the_remedy_a_refused_duration_offers_is_the_one_that_flag_has(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], flag: str, remedy: str
) -> None:
    # The two flags answer "I want no limit" differently, so one sentence cannot serve both. There
    # is no way to ask for an unbounded per-solve budget, so the answer there is a large number;
    # a run with no deadline is the default, so the answer there is to leave the flag off. A reader
    # arriving here is most likely carrying over a convention in which zero means unbounded, which
    # is exactly the reader for whom the wrong remedy is worse than none.
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")

    assert main([str(tmp_path / "encodings"), flag, "0"]) == ExitStatus.USER_FAULT

    assert remedy in capfd.readouterr().err


def test_a_large_finite_duration_is_the_remedy_and_is_accepted(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # The other side of the refusal above, and the remedy its diagnostic offers: a run that wants
    # no practical limit asks for a large finite number, so that number must run the corpus.
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")

    status = main([str(tmp_path / "encodings"), "--budget", "1e9", "--deadline", "1e9"])

    assert status == ExitStatus.OK
    assert "1/1 passed" in capfd.readouterr().out
