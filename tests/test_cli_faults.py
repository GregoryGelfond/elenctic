"""What a user sees when a case cannot be run: an error, not a traceback.

An error is not a verdict, so it must not borrow a verdict's exit status, and it must not cost the
run the results of the cases that did complete. These drive the CLI end to end.
"""

from collections.abc import Iterable
from pathlib import Path

import pytest

from elenctic import corpus, discovery
from elenctic.checks import CheckReport
from elenctic.cli import main
from elenctic.discovery import Case
from elenctic.harness import run_plan
from elenctic.outcome import ExitStatus
from elenctic.result import SeamError
from elenctic.run import Run
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
    def broken(
        case: Case, runs: Iterable[Run], budget: float = TIME_BUDGET
    ) -> tuple[CheckReport, ...]:
        if case.contract_source.name == "mmm_broken.lp":
            raise SeamError("narrowing seam: a shape that does not populate what a check reads")
        return run_plan(case, runs, budget=budget)

    monkeypatch.setattr(corpus, "run_plan", broken)
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


# An escape a terminal acts on rather than displays: erase-in-line. Written into a corpus by an
# author, and reaching a reader through a diagnostic — which is the whole point. A diagnostic that
# reproduces it can erase the line above it, so a report saying a case FAILed can be made to say
# nothing at all, or something else.
_ERASES_THE_LINE = "\x1b[2K"


def test_a_corpus_cannot_write_a_terminal_escape_into_a_diagnostic_it_causes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The frame that reports a file discovery could not use. This is the guarantee `_Terminal`
    # states in its own docstring and the one nothing held: a reviewer's mutation dropping
    # `legible` here passed the entire suite, because every test reaching this frame used text with
    # nothing in it to sanitize.
    #
    # The input is chosen so that it can fail. A malformed *contract* cannot: `expectation.parse`
    # sanitizes the payload it quotes back, so the escape is already neutral by the time it gets
    # here and dropping the call changes nothing. The first draft of this test used exactly that,
    # and the mutation walked through it — the test was green and measuring nothing. What does
    # reach this frame raw is a program fault met while the corpus is walked: the message is
    # clingo's, quoting a path this corpus chose.
    (tmp_path / f"ev{_ERASES_THE_LINE}il.lp").write_text(
        '% @expect sat\n% @count 1\n#include "nowhere.lp".\na.\n', encoding="utf-8"
    )

    assert main([str(tmp_path)]) == ExitStatus.USER_FAULT

    said = capsys.readouterr().err
    assert _ERASES_THE_LINE not in said, "the escape reached the reader's terminal intact"
    assert "ev\\x1b[2Kil.lp" in said, (
        "and it is shown rather than dropped: a reader has to be able to see that the corpus "
        "tried something, not find text quietly missing"
    )


def test_a_path_the_corpus_chose_is_sanitized_before_a_reader_sees_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The other half, and the one an author is least likely to have thought about: the file's own
    # name. A fault met while the case is *run* is reported against its path, so a corpus that names
    # a file with an escape writes into every diagnostic about it.
    (tmp_path / f"ev{_ERASES_THE_LINE}il.lp").write_text(
        "% @expect sat\n% @count 1\np(X) :- q(Y).\n#show p/1.\n", encoding="utf-8"
    )

    assert main([str(tmp_path)]) == ExitStatus.USER_FAULT

    said = capsys.readouterr().err
    assert _ERASES_THE_LINE not in said, "the escape reached the reader's terminal intact"
    assert "ev\\x1b[2Kil.lp" in said, "and the name is still legible enough to find the file by"


def test_no_string_the_corpus_chose_reaches_a_reader_as_a_terminal_escape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One sweep over every frame that prints, rather than one test per frame.

    The guarantee is stated per module — "every string a corpus had a hand in passes through the
    sanitizer" — and was held per call site, which is why three frames were reachable with hostile
    text and unsanitized while two were pinned. A frame added later inherits this test; it would not
    have inherited a fourth per-frame one.

    The corpus is built so that every string a corpus can choose is hostile at once: a case file's
    name, a library's name, a note's prose, and the payload a contract error quotes back. Run in
    both modes, because the dry run prints through a renderer of its own.
    """

    def put(name: str, text: str) -> None:
        (tmp_path / name).write_text(text, encoding="utf-8")

    put(f"ev{_ERASES_THE_LINE}il.lp", '% @expect sat\n% @count 1\n#include "nowhere.lp".\n')
    put(
        f"no{_ERASES_THE_LINE}te.lp",
        f"% @expect sat\n% @model {{ a }}\n% @note a{_ERASES_THE_LINE}side\na.\n#show a/0.\n",
    )
    put(f"bad{_ERASES_THE_LINE}.lp", f"% @expect ban{_ERASES_THE_LINE}ana\na.\n")
    put(f"orphan{_ERASES_THE_LINE}.lp", "% nothing includes this.\nhelper(1).\n")

    # Both target shapes, because they reach different frames: a directory sends an unusable file
    # to `case_unusable`, while naming that same file makes its fault the whole run's and sends it
    # to `corpus_unreadable`. Only the first was covered, so the second was reachable with hostile
    # text and unsanitized.
    targets = [str(tmp_path), str(tmp_path / f"ev{_ERASES_THE_LINE}il.lp")]
    for target, flags in [(t, f) for t in targets for f in ([], ["--strict"], ["--explain"])]:
        main([target, *flags])
        seen = capsys.readouterr()
        shown = seen.out + seen.err
        where = f"{Path(target).name} {flags or ''}".strip()
        assert _ERASES_THE_LINE not in shown, f"an escape reached the reader under {where}"
        assert "\\x1b" in shown, f"and nothing was silently dropped under {where}"


def test_the_deadline_notice_is_not_printed_for_a_case_that_simply_could_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The notice is rendered from the register by filtering it to the deadline locus, and every test
    # that asserted the notice whole handed it a register holding nothing else — so filtering on the
    # scope instead of the locus agreed with them, and a corpus with one ungroundable case and no
    # --deadline at all announced that a deadline it never had was passed.
    (tmp_path / "broken.lp").write_text(_UNSAFE, encoding="utf-8")

    assert main([str(tmp_path)]) == ExitStatus.USER_FAULT

    said = capsys.readouterr().err
    assert "DEADLINE" not in said, "no deadline was given, so none can have been passed"


def test_a_corpus_that_could_not_be_read_reports_no_tally(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `0/0 passed` under a corpus-scoped fault answers a question nobody asked: it reads as a corpus
    # that was looked at and found to hold nothing, which is a different thing from one that could
    # not be read at all. The suppression was reasoned about in a docstring and held by nothing —
    # every test of this path read standard error and none read standard output.
    assert main([str(tmp_path / "no_such_directory")]) == ExitStatus.USER_FAULT

    seen = capsys.readouterr()
    assert seen.out == "", "nothing ran, so there is nothing to tally"
    assert "passed" not in seen.out
