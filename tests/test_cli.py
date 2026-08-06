"""The ``elenctic`` console entry: exit status separates pass / fail / error, and ``--explain``
narrates the derived run plan without solving."""

import io
from contextlib import redirect_stderr, redirect_stdout
from itertools import product
from pathlib import Path

import pytest

from elenctic import corpus
from elenctic.cli import (
    _hand_over_standard_output,
    _heading,
    _render_tail,
    _summary_line,
    _TerminalPlan,
    _TerminalRun,
    main,
)
from elenctic.outcome import ErrorKind, ErrorRecord, ExitStatus, Invocation, RunOutcome, Scope
from elenctic.run import RoutingError, runs_for as real_runs_for


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
    # Capitals and a dash say it cost this file and not the run; the word says a contract is what
    # is wrong with it, which is the one thing a reader needs before opening the file.
    assert "CONTRACT ERROR — " in err
    assert "e.lp" in err


def test_cli_reports_a_fault_that_cost_the_whole_run_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The register above is per file; this one is genuinely about the corpus. A named target that
    # does not exist tests nothing, and there is no file to attribute it to.
    status = main([str(tmp_path / "no_such_directory")])
    assert status == ExitStatus.USER_FAULT
    # Lower case and a colon are what say the run ended here: no tally follows, because nothing ran.
    assert "discovery error: " in capsys.readouterr().err


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

    def selectively_misroute(
        expectation: object, theory_in_force: bool = False, *, has_projection: bool = False
    ) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(
            expectation,  # type: ignore[arg-type]
            theory_in_force,
            has_projection=has_projection,
        )

    monkeypatch.setattr(corpus, "runs_for", selectively_misroute)
    status = main([str(tmp_path / "encodings")])
    captured = capsys.readouterr()
    assert (
        status == ExitStatus.HARNESS_FAULT
    )  # a harness error, not a verdict and not a corpus to fix
    assert "HARNESS ERROR" in captured.err
    assert "bad" in captured.err, "and the misrouted case is named"
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

    def selectively_misroute(
        expectation: object, theory_in_force: bool = False, *, has_projection: bool = False
    ) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(
            expectation,  # type: ignore[arg-type]
            theory_in_force,
            has_projection=has_projection,
        )

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
    # The worked example of the collapse: an #include that will not resolve is a fault in the
    # program, and it is announced as one here — where discovery met it — exactly as it is when the
    # runner meets one. It used to be announced as a CASE ERROR here and a PROGRAM ERROR there.
    assert "PROGRAM ERROR — " in captured.err
    assert "no_such_library.lp" in captured.err
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


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_every_locus_a_case_can_fail_under_is_accounted_for_to_a_reader(
    kind: ErrorKind, capsys: pytest.CaptureFixture[str]
) -> None:
    # A case that produced no verdict must not disappear. The register accounts for it either way,
    # but a reader watching the run sees only what is written, so a locus the renderer has no
    # sentence for is a case that ran and then went missing from the reader's view of the corpus.
    #
    # Over the whole vocabulary rather than over the loci a run files today, because that is the
    # list that grows: adding a locus is a deliberate act, and this is what makes giving it a
    # sentence part of the act rather than something to be noticed later.
    record = ErrorRecord(
        kind=kind, scope=Scope.CASE, source=Path("case.lp"), message="the reason it produced none"
    )

    _TerminalRun().case_unjudged(record)

    said = capsys.readouterr().err

    # The whole line, not a substring of it. A substring assertion is satisfied by the *message*,
    # which every arm passes through unchanged — so the labels, the separator, and whether the arm
    # names the file were all free, and swapping two labels passed the entire suite. Measured, not
    # supposed: the mutation that swapped SOLVER and PROGRAM was proposed by a reviewer and run.
    assert said == _SAID_ABOUT[kind], f"what a reader is told about a {kind.value} fault"


# What each locus says, whole — including the one that says nothing here, which is why the test
# above is named for a locus being *accounted for* rather than for it saying something. Written
# out per locus rather than derived from the vocabulary,
# because a table that computes the heading agrees with any implementation that computes it the
# same way — including a wrong one. The deadline says nothing here because it is said once at the
# end, from the whole register: one passed deadline is one event costing many cases their result,
# and a line apiece would bury the reason under its own consequences.
_SAID_ABOUT: dict[ErrorKind, str] = {
    ErrorKind.DEADLINE: "",
    ErrorKind.CONTRACT: "CONTRACT ERROR — the reason it produced none\n",
    ErrorKind.DISCOVERY: "DISCOVERY ERROR — the reason it produced none\n",
    ErrorKind.ENVIRONMENT: "ENVIRONMENT ERROR — the reason it produced none\n",
    ErrorKind.PROGRAM: "PROGRAM ERROR — case.lp: the reason it produced none\n",
    ErrorKind.RESOURCE: "RESOURCE ERROR — case.lp: the reason it produced none\n",
    ErrorKind.HARNESS: "HARNESS ERROR — case.lp: the reason it produced none\n",
}


# The same six loci, announced by a frame that met the fault while *reading* the corpus rather than
# while running it. The heading is the same word, because it is the same fault: what a file's
# contract was malformed is not a different thing depending on which part of elenctic noticed.
# Written out here too, so that the two tables agreeing is a fact about the renderer rather than
# about one expression shared between them.
# The deadline row is loud here and silent in the table above, and that is not an oversight: the
# per-case renderer stays quiet because the tail says it once from the whole register, and this
# frame has no tail to defer to. Neither is reachable — discovery files no deadline — so what the
# two rows record is the rule each frame would follow, not a difference a run can produce.
_SAID_ABOUT_AN_UNUSABLE_FILE: dict[ErrorKind, str] = {
    ErrorKind.DEADLINE: "DEADLINE ERROR — the reason it produced none\n",
    ErrorKind.CONTRACT: "CONTRACT ERROR — the reason it produced none\n",
    ErrorKind.DISCOVERY: "DISCOVERY ERROR — the reason it produced none\n",
    ErrorKind.ENVIRONMENT: "ENVIRONMENT ERROR — the reason it produced none\n",
    ErrorKind.PROGRAM: "PROGRAM ERROR — the reason it produced none\n",
    ErrorKind.RESOURCE: "RESOURCE ERROR — the reason it produced none\n",
    ErrorKind.HARNESS: "HARNESS ERROR — the reason it produced none\n",
}


# And the same loci when the fault cost the whole run. Lower case and a colon rather than capitals
# and a dash, which is what tells a reader the run stopped here and produced no report at all.
_SAID_ABOUT_A_WHOLE_RUN: dict[ErrorKind, str] = {
    ErrorKind.DEADLINE: "deadline error: the reason nothing ran\n",
    ErrorKind.CONTRACT: "contract error: the reason nothing ran\n",
    ErrorKind.DISCOVERY: "discovery error: the reason nothing ran\n",
    ErrorKind.ENVIRONMENT: "environment error: the reason nothing ran\n",
    ErrorKind.PROGRAM: "program error: the reason nothing ran\n",
    ErrorKind.RESOURCE: "resource error: the reason nothing ran\n",
    ErrorKind.HARNESS: "harness error: the reason nothing ran\n",
}


# Every heading the vocabulary can produce, whole and written out, over BOTH axes. The three tables
# above each fix one scope and vary the locus, so between them they say nothing about how the scope
# is read — and a renderer that ignored scope entirely would satisfy all three. This is the table
# that holds the other axis, and it is what makes a locus or a scope added later fail here (a
# missing key) as well as under the type checker.
_HEADING: dict[tuple[ErrorKind, Scope], str] = {
    (ErrorKind.CONTRACT, Scope.CASE): "CONTRACT ERROR —",
    (ErrorKind.DISCOVERY, Scope.CASE): "DISCOVERY ERROR —",
    (ErrorKind.ENVIRONMENT, Scope.CASE): "ENVIRONMENT ERROR —",
    (ErrorKind.PROGRAM, Scope.CASE): "PROGRAM ERROR —",
    (ErrorKind.DEADLINE, Scope.CASE): "DEADLINE ERROR —",
    (ErrorKind.RESOURCE, Scope.CASE): "RESOURCE ERROR —",
    (ErrorKind.HARNESS, Scope.CASE): "HARNESS ERROR —",
    (ErrorKind.CONTRACT, Scope.CORPUS): "contract error:",
    (ErrorKind.DISCOVERY, Scope.CORPUS): "discovery error:",
    (ErrorKind.ENVIRONMENT, Scope.CORPUS): "environment error:",
    (ErrorKind.PROGRAM, Scope.CORPUS): "program error:",
    (ErrorKind.DEADLINE, Scope.CORPUS): "deadline error:",
    (ErrorKind.RESOURCE, Scope.CORPUS): "resource error:",
    (ErrorKind.HARNESS, Scope.CORPUS): "harness error:",
}


@pytest.mark.parametrize(("kind", "scope"), list(product(ErrorKind, Scope)))
def test_a_heading_is_the_locus_and_what_it_cost_and_nothing_else(
    kind: ErrorKind, scope: Scope
) -> None:
    # Both axes at once, against literals. Written out rather than computed from the vocabulary,
    # because a table that builds the heading the way the code builds it agrees with any
    # implementation that builds it that way — including a wrong one. That was the defect in the
    # test this replaces: it asserted `startswith(f"{kind.value.upper()} ERROR —")`, which is the
    # implementation's own expression copied into the assertion, so it could not fail while the
    # implementation was self-consistent.
    assert _heading(kind, scope) == _HEADING[kind, scope]


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_a_file_discovery_could_not_use_is_announced_by_the_locus_of_its_fault(
    kind: ErrorKind, capsys: pytest.CaptureFixture[str]
) -> None:
    # The heading names where the fault lies. It used to name the part of elenctic that met it, so
    # one broken #include read one way when discovery walked into it and another when the runner
    # did — telling a reader that a program which will not load is two different problems.
    record = ErrorRecord(
        kind=kind, scope=Scope.CASE, source=Path("case.lp"), message="the reason it produced none"
    )

    _TerminalRun().case_unusable(record)

    assert capsys.readouterr().err == _SAID_ABOUT_AN_UNUSABLE_FILE[kind]


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_a_fault_that_cost_the_whole_run_is_announced_by_the_locus_of_its_fault(
    kind: ErrorKind, capsys: pytest.CaptureFixture[str]
) -> None:
    # The third frame, and the one that used to say least: every corpus-scoped fault was announced
    # as a corpus error whatever it was about, so a reader whose target held a program that will
    # not load and a reader who named a directory that does not exist were told the same word.
    record = ErrorRecord(
        kind=kind, scope=Scope.CORPUS, source=None, message="the reason nothing ran"
    )

    _TerminalRun().corpus_unreadable(record)

    assert capsys.readouterr().err == _SAID_ABOUT_A_WHOLE_RUN[kind]


@pytest.mark.parametrize("kind", [kind for kind in ErrorKind if kind is not ErrorKind.DEADLINE])
def test_one_locus_is_announced_by_one_word_whichever_frame_met_the_fault(
    kind: ErrorKind, capsys: pytest.CaptureFixture[str]
) -> None:
    # The defect itself, stated directly rather than left to follow from three tables: hand the two
    # per-case frames the same fault and they must call it the same thing. Before this, a program
    # that would not load was a CASE ERROR through the one and a PROGRAM ERROR through the other,
    # and both spellings were pinned by their own tests — each correct about its own frame, and
    # neither able to see that they disagreed.
    #
    # The expectation comes from the table rather than from the implementation's own expression. It
    # asserted `startswith(f"{kind.value.upper()} ERROR —")` when it was first written, which is a
    # copy of the line under test and so could not fail while that line was self-consistent.
    #
    # The deadline is left out because it is the one locus a per-case frame deliberately stays
    # quiet about, and only one of these two frames can ever be handed one.
    record = ErrorRecord(
        kind=kind, scope=Scope.CASE, source=Path("case.lp"), message="the reason it produced none"
    )

    _TerminalRun().case_unusable(record)
    reading = capsys.readouterr().err
    _TerminalRun().case_unjudged(record)
    running = capsys.readouterr().err

    heading = _HEADING[kind, Scope.CASE]
    assert reading.startswith(heading), "the frame that met it while reading the corpus"
    assert running.startswith(heading), "and the frame that met it while running the case"


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_the_dry_run_says_the_same_thing_about_a_fault_indented_under_its_case(
    kind: ErrorKind, capsys: pytest.CaptureFixture[str]
) -> None:
    # A dry run can only meet a misroute today, so it used to label whatever it was handed as
    # elenctic's own fault. That is a fact about what the mode currently does, not a property of a
    # renderer, and answering "harness bug" to an author's broken program is a defect this project
    # has shipped twice. The sentence is now the same one a real run gives, indented under the case
    # the narration has already named.
    record = ErrorRecord(
        kind=kind, scope=Scope.CASE, source=Path("case.lp"), message="the reason it produced none"
    )

    _TerminalPlan().case_unjudged(record)

    expected = _SAID_ABOUT[kind]
    assert capsys.readouterr().err == (f"    {expected}" if expected else "")


def test_the_deadline_is_said_once_however_many_cases_it_cost(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The other half of the arm above: the one locus the per-case renderer stays quiet about is
    # reported by the tail instead, and reported once, counting the cases off their own records.
    unreached = tuple(
        ErrorRecord(
            kind=ErrorKind.DEADLINE,
            scope=Scope.CASE,
            source=Path(f"case{n}.lp"),
            message="the run passed its 5.0s deadline before reaching this case",
        )
        for n in range(3)
    )

    _render_tail(
        RunOutcome(cases=(), errors=unreached, hygiene=()),
        Invocation(target=Path("tests"), strict=False, budget=30.0, deadline=5.0),
    )

    # The whole line. A substring assertion left the interpolated number free: swapping
    # `invocation.deadline` for `invocation.budget` reported "the run passed its 30.0s deadline"
    # while every record beside it said 5.0s, and the entire suite stayed green. Measured — the
    # mutation was a reviewer's and was run.
    assert capsys.readouterr().err == (
        "DEADLINE ERROR — the run passed its 5.0s deadline; 3 case(s) were not reached\n"
    )


def test_a_tally_counts_the_cases_a_run_actually_accounted_for() -> None:
    # Both counters read case-scoped records, and both have to: `total` counts the cases discovered
    # and counts an unrun one by its case-scoped record, so a corpus-scoped fault counted beside it
    # would produce a line that fails its own arithmetic — "0/0 passed, 1 harness error(s)", which
    # says a case went wrong and that there were no cases. Nothing files such a record into an
    # outcome that also has cases today; this is what keeps that from being the reason it is right.
    corpus_scoped = ErrorRecord(
        kind=ErrorKind.HARNESS, scope=Scope.CORPUS, source=None, message="no case owned it"
    )
    case_scoped = ErrorRecord(
        kind=ErrorKind.HARNESS, scope=Scope.CASE, source=Path("case.lp"), message="this one did"
    )

    assert _summary_line(RunOutcome(cases=(), errors=(corpus_scoped,), hygiene=())) == "0/0 passed"
    assert (
        _summary_line(RunOutcome(cases=(), errors=(case_scoped,), hygiene=()))
        == "0/1 passed, 1 harness error(s)"
    )


def test_a_reader_of_one_merged_stream_is_told_the_deadline_before_the_tally() -> None:
    # The tally is written to standard output and the deadline notice to standard error, so a
    # capture that keeps the two apart cannot see between them — and `2>&1` is what a CI log, a pipe
    # into a pager, and a terminal all are. Both streams are pointed at one buffer here, which is
    # the only way to read the order in process; the fake clock a real deadline needs does not
    # survive a process boundary, so the control harness cannot reach this path at all and says so.
    #
    # The order is the reason, then its consequence: a reader who meets "3 could not be run" first
    # has to hold it until something explains it.
    unreached = tuple(
        ErrorRecord(
            kind=ErrorKind.DEADLINE,
            scope=Scope.CASE,
            source=Path(f"case{n}.lp"),
            message="the run passed its 5.0s deadline before reaching this case",
        )
        for n in range(3)
    )
    merged = io.StringIO()

    # The composition, not one function: the tail no longer writes the tally, it hands it back, so
    # what a reader sees is what the tail wrote followed by what its caller then wrote with the
    # value returned. Asking only the tail would now read the deadline notice and nothing after it,
    # and would go on passing however the two came to be ordered.
    with redirect_stdout(merged), redirect_stderr(merged):
        tally = _render_tail(
            RunOutcome(cases=(), errors=unreached, hygiene=()),
            Invocation(target=Path("tests"), strict=False, budget=30.0, deadline=5.0),
        )
        _hand_over_standard_output(prose=tally)

    assert merged.getvalue() == (
        "DEADLINE ERROR — the run passed its 5.0s deadline; 3 case(s) were not reached\n"
        "\n"
        "0/3 passed, 3 could not be run\n"
    )
