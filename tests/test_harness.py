"""``harness`` — run a discovered case end-to-end and render its outcome.

``run_case(case)`` is the impure orchestrator (derive runs → solve → check), ``case_verdict`` folds
the per-check reports to a case verdict (FAIL dominates UNDECIDED dominates PASS), and ``render`` is
the pure human diagnostic that keeps FAIL and UNDECIDED distinct and surfaces the case's
``@note`` prose and its ``contract_source`` provenance, taken from the case rather than the reports.
"""

from pathlib import Path

import pytest

from elenctic.checks import CheckReport
from elenctic.discovery import Case, discover
from elenctic.expectation import Sat, Unsat
from elenctic.harness import case_verdict, render, run_case
from elenctic.program import Unrestricted
from elenctic.registry import Solver
from elenctic.result import Conclusion, Verdict
from elenctic.run import RoutingError


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def self_contained(tmp_path: Path, body: str) -> Case:
    """Discover a single contract-bearing case file (issue #3, single-file invocation)."""
    (case,) = discover(write(tmp_path / "case.lp", body))
    return case


# --- run_case: the end-to-end PASS/FAIL/UNDECIDED outcomes over real clingo ---


def test_run_case_passes_a_satisfied_contract(tmp_path: Path) -> None:
    case = self_contained(
        tmp_path,
        "1 {a; b} 1. c. #show a/0. #show b/0. #show c/0.\n% @expect sat\n% @cautious { c }\n",
    )
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.PASS
    assert all(report.verdict is Verdict.PASS for report in reports)


def test_run_case_fails_a_violated_contract(tmp_path: Path) -> None:
    # a is only bravely true (in one answer set), so the cautious claim @cautious { a } FAILs.
    case = self_contained(
        tmp_path, "1 {a; b} 1. #show a/0. #show b/0.\n% @expect sat\n% @cautious { a }\n"
    )
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.FAIL


def test_run_case_fails_unsat_expected_sat(tmp_path: Path) -> None:
    case = self_contained(tmp_path, ":- a. a.\n% @expect sat\n")  # UNSAT, but sat expected
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.FAIL


def test_run_case_passes_expected_unsat(tmp_path: Path) -> None:
    case = self_contained(tmp_path, ":- a. a.\n% @expect unsat\n")  # UNSAT, as expected
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.PASS


def test_the_claims_an_unsat_contract_restates_are_each_answered(tmp_path: Path) -> None:
    # `@count 0` and `@count optimal 0` are the two tags an unsat contract may write beside
    # `@expect`, and each is a claim on a line of its own. They reached no report at all before:
    # the freeze dropped them, so a consumer placing a diagnostic by line found nothing at either.
    case = self_contained(tmp_path, ":- a. a.\n% @expect unsat\n% @count 0\n% @count optimal 0\n")
    reports = run_case(case)
    assert [(report.label, report.line, report.verdict) for report in reports] == [
        ("@expect unsat", 2, Verdict.PASS),
        ("@count", 3, Verdict.PASS),
        ("@count optimal", 4, Verdict.PASS),
    ]


def test_the_claims_an_unsat_contract_restates_fail_with_it(tmp_path: Path) -> None:
    # The direction that proves they are *checked* rather than merely carried: on a satisfiable
    # program all three are false, and each says so against its own line. A claim carried into the
    # report and never decided would sit at PASS here, and the test above could not tell.
    case = self_contained(
        tmp_path, "p(x). #show p/1.\n% @expect unsat\n% @count 0\n% @count optimal 0\n"
    )
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.FAIL
    assert [(report.label, report.line, report.verdict) for report in reports] == [
        ("@expect unsat", 2, Verdict.FAIL),
        ("@count", 3, Verdict.FAIL),
        ("@count optimal", 4, Verdict.FAIL),
    ]


def test_run_case_is_undecided_on_a_hit_budget(tmp_path: Path) -> None:
    # a huge enumeration with a zero budget times out → UNDECIDED, never FAIL/UNSAT.
    case = self_contained(tmp_path, "{ p(1..30) }. #show p/1.\n% @expect sat\n% @count 5\n")
    reports = run_case(case, budget=0.0)
    assert case_verdict(reports) is Verdict.UNDECIDED


def test_run_case_runs_multiple_coalesced_checks_in_deterministic_order(tmp_path: Path) -> None:
    case = self_contained(
        tmp_path,
        "1 {a; b} 1. c. #show a/0. #show b/0. #show c/0.\n"
        "% @expect sat\n% @cautious { c }\n% @brave { a }\n",
    )
    reports = run_case(case)
    # the runs_for order: CAUTIOUS_ALL, BRAVE_ALL, then DEFAULT-ridden @expect sat (deterministic).
    assert tuple(report.label for report in reports) == ("@cautious", "@brave", "@expect sat")
    assert case_verdict(reports) is Verdict.PASS


def test_run_case_propagates_a_misrouted_plan_as_a_harness_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a misroute is a HarnessError, never a verdict — run_case re-raises it
    # (it does NOT swallow it as a CheckReport). runs_for is correct-by-construction, so inject it.
    case = self_contained(tmp_path, "a. #show a/0.\n% @expect sat\n")

    def misrouted(
        _expectation: object, _theory_in_force: bool = False, *, has_projection: bool = False
    ) -> tuple[object, ...]:
        raise RoutingError("a stale route")

    monkeypatch.setattr("elenctic.harness.runs_for", misrouted)
    with pytest.raises(RoutingError, match=r"stale route"):
        run_case(case)


def test_run_case_projects_a_shown_only_clingcon_contract(tmp_path: Path) -> None:
    # End-to-end: a clingcon contract whose only census rider is shown-base (@model) projects —
    # distinctness lives in the CSP assignment, which no rider reads, so projection is safe and the
    # enumeration terminates on the small shown class. The plan is well-routed and the case passes.
    pytest.importorskip("clingcon")
    case = self_contained(
        tmp_path,
        "&dom {1..3} = v(x). ok. #show ok/0.\n"
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingcon\n",
    )
    assert case.solver == "clingcon"  # declared, not read from a filename
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.PASS


# --- case_verdict: FAIL dominates UNDECIDED dominates PASS (a definite failure sinks the case) ---


def report(
    verdict: Verdict,
    label: str = "@cautious",
    message: str = "message",
    *,
    subject: str = "",
    line: int = 1,
) -> CheckReport:
    return CheckReport(
        verdict=verdict,
        label=label,
        message=message,
        subject=subject,
        line=line,
        conclusion=Conclusion.EXHAUSTED,
    )


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        pytest.param([Verdict.PASS, Verdict.PASS], Verdict.PASS, id="all-pass"),
        pytest.param([Verdict.PASS, Verdict.FAIL], Verdict.FAIL, id="one-fail"),
        pytest.param([Verdict.PASS, Verdict.UNDECIDED], Verdict.UNDECIDED, id="one-undecided"),
        pytest.param([Verdict.FAIL, Verdict.UNDECIDED], Verdict.FAIL, id="fail-over-undecided"),
    ],
)
def test_case_verdict_folds_with_fail_dominating(
    verdicts: list[Verdict], expected: Verdict
) -> None:
    assert case_verdict(tuple(report(v) for v in verdicts)) is expected


# --- render: the pure human diagnostic (FAIL vs UNDECIDED distinct; @note + provenance) ---


def synthetic(expectation: Sat | Unsat, solver: Solver = "clingo") -> Case:
    return Case(Path("tests/cases/x.lp"), solver, expectation, Unrestricted())


def test_render_pass_case_is_a_terse_header() -> None:
    out = render(synthetic(Sat(expect_line=1)), (report(Verdict.PASS, "@expect sat"),))
    assert out == "tests/cases/x.lp [clingo] — PASS"


def test_render_fail_shows_the_failing_check_and_the_note() -> None:
    case = synthetic(Sat(expect_line=1, notes=("the budget forces a detour",)))
    reports = (
        report(Verdict.PASS, "@expect sat"),
        report(
            Verdict.FAIL,
            "@cautious",
            "{ c } ⊄ ⋂ AS(P) = { } (missing: { c })",
            subject="{ c }",
            line=4,
        ),
    )
    out = render(case, reports)
    assert "— FAIL" in out
    assert "[FAIL] @cautious { c } (line 4): { c } ⊄ ⋂ AS(P)" in out
    assert "note: the budget forces a detour" in out
    assert "@expect sat" not in out  # the passing check is not dumped


# How a row names the claim it judged, and when rows that share a diagnostic become one, are
# pinned in `test_collapsed_rows.py` — this module covers the renderer's other responsibilities.


_ESCAPE = "\x1b[2J"


def _rendered_with_an_escape_in(surface: str) -> str:
    """One render in which exactly ``surface`` carries a terminal escape sequence."""
    case = Case(
        Path(f"tests/cases/{_ESCAPE}x.lp" if surface == "path" else "tests/cases/x.lp"),
        "clingo",
        Sat(
            expect_line=1,
            notes=(f"a note with {_ESCAPE} in it" if surface == "note" else "an ordinary note",),
        ),
        Unrestricted(),
    )
    failure = report(
        Verdict.FAIL,
        "@query",
        f"computed {_ESCAPE} no" if surface == "message" else "computed no",
        subject=f"yes {_ESCAPE}{{ a }}" if surface == "subject" else "yes { a }",
        line=2,
    )
    return render(case, (failure,))


@pytest.mark.parametrize("surface", ["path", "note", "message", "subject"])
def test_render_makes_every_corpus_surface_legible(surface: str) -> None:
    # Four of the strings this render is built from come from the corpus, and a terminal acts on
    # some of that text rather than showing it — so a case could clear the screen or overwrite the
    # verdict just printed. Each surface is asserted rather than assumed: only the subject was
    # covered, and an implementation that dropped the escaping from any of the other three passed.
    out = _rendered_with_an_escape_in(surface)
    assert "\x1b" not in out, f"the {surface} reached the terminal able to act on it"
    assert "\\x1b" in out, f"the {surface} was dropped rather than shown"


def test_render_keeps_fail_and_undecided_distinct() -> None:
    reports = (
        report(Verdict.FAIL, "@cautious", "decided wrong", subject="{ a }", line=2),
        report(Verdict.UNDECIDED, "@brave", "the solve did not complete", subject="{ b }", line=3),
    )
    out = render(synthetic(Sat(expect_line=1)), reports)
    assert "[FAIL] @cautious { a } (line 2): decided wrong" in out
    assert "[UNDECIDED] @brave { b } (line 3): the solve did not complete" in out


def test_render_surfaces_note_on_undecided_too() -> None:
    # A "known-slow" @note is useful on UNDECIDED, not only FAIL.
    case = synthetic(Sat(expect_line=1, notes=("this instance is known-slow",)))
    out = render(case, (report(Verdict.UNDECIDED, "@count", "budget hit", line=3),))
    assert "— UNDECIDED" in out
    assert "note: this instance is known-slow" in out


def test_render_suppresses_the_note_on_a_passing_case() -> None:
    case = synthetic(Sat(expect_line=1, notes=("irrelevant on pass",)))
    out = render(case, (report(Verdict.PASS, "@expect sat"),))
    assert out == "tests/cases/x.lp [clingo] — PASS"  # no note line on a passing case


def test_render_surfaces_an_unsat_cases_note_on_failure() -> None:
    case = synthetic(Unsat(expect_line=1, notes=("the budget cap excludes every s–t path",)))
    out = render(case, (report(Verdict.FAIL, "@expect unsat", "a model exists: { a }"),))
    assert "— FAIL" in out
    assert "[FAIL] @expect unsat (line 1): a model exists: { a }" in out
    assert "note: the budget cap excludes every s–t path" in out


def test_case_verdict_empty_is_vacuously_pass() -> None:
    # Total-function identity (unreachable via run_case — @expect always yields ≥1 check).
    assert case_verdict(()) is Verdict.PASS


def test_render_empty_reports_is_a_bare_header() -> None:
    assert render(synthetic(Sat(expect_line=1)), ()) == "tests/cases/x.lp [clingo] — PASS"
