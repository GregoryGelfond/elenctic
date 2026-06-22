"""``harness`` — run a discovered case end-to-end and render its outcome (dx#9).

``run_case(case)`` is the impure orchestrator (derive runs → solve → check), ``case_verdict`` folds
the per-check reports to a case verdict (FAIL dominates UNDECIDED dominates PASS), and ``render`` is
the pure human diagnostic that keeps FAIL and UNDECIDED distinct (§7a) and surfaces the case's
``@note`` prose and its ``contract_source`` provenance (Model A — from the case, not the reports).
"""

from pathlib import Path

import pytest

from elenctic.checks import CheckReport
from elenctic.discovery import Case, Layout, Solver, discover
from elenctic.expectation import Sat, Unsat
from elenctic.harness import case_verdict, render, run_case
from elenctic.result import Verdict
from elenctic.run import RoutingError


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def self_contained(tmp_path: Path, body: str) -> Case:
    """Discover a single self-contained encoding carrying its own contract header."""
    write(tmp_path / "encodings/d/e.lp", body)
    (case,) = discover(Layout(encodings_root=tmp_path / "encodings", cases_root=tmp_path / "none"))
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


def test_run_case_is_undecided_on_a_hit_budget(tmp_path: Path) -> None:
    # a huge enumeration with a zero budget times out → UNDECIDED, never FAIL/UNSAT (§7a).
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
    # Keystone decision 6: a misroute is a HarnessError, never a verdict — run_case re-raises it
    # (it does NOT swallow it as a CheckReport). runs_for is correct-by-construction, so inject it.
    case = self_contained(tmp_path, "a. #show a/0.\n% @expect sat\n")

    def misrouted(_expectation: object, _theory_in_force: bool = False) -> tuple[object, ...]:
        raise RoutingError("a stale route")

    monkeypatch.setattr("elenctic.harness.runs_for", misrouted)
    with pytest.raises(RoutingError, match=r"stale route"):
        run_case(case)


def test_run_case_projects_a_shown_only_clingcon_contract(tmp_path: Path) -> None:
    # End-to-end: a clingcon contract whose only census rider is shown-base (@model) projects —
    # distinctness lives in the CSP assignment, which no rider reads, so projection is safe and the
    # enumeration terminates on the small shown class. The plan is well-routed and the case passes.
    pytest.importorskip("clingcon")
    write(
        tmp_path / "encodings/d/e-clingcon.lp",
        "&dom {1..3} = v(x). ok. #show ok/0.\n% @expect sat\n% @model { ok }\n",
    )
    (case,) = discover(Layout(encodings_root=tmp_path / "encodings", cases_root=tmp_path / "none"))
    assert case.solver == "clingcon"
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.PASS


# --- case_verdict: FAIL dominates UNDECIDED dominates PASS (a definite failure sinks the case) ---


def report(verdict: Verdict, label: str = "@cautious") -> CheckReport:
    return CheckReport(verdict, label, "message")


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
    return Case(Path("tests/cases/x.lp"), None, solver, expectation, frozenset())


def test_render_pass_case_is_a_terse_header() -> None:
    out = render(synthetic(Sat()), (report(Verdict.PASS, "@expect sat"),))
    assert out == "tests/cases/x.lp [clingo] — PASS"


def test_render_fail_shows_the_failing_check_and_the_note() -> None:
    case = synthetic(Sat(notes=("the budget forces a detour",)))
    reports = (
        report(Verdict.PASS, "@expect sat"),
        CheckReport(Verdict.FAIL, "@cautious", "{ c } ⊄ ⋂ AS(P) = { } (missing: { c })"),
    )
    out = render(case, reports)
    assert "— FAIL" in out
    assert "[FAIL] @cautious: { c } ⊄ ⋂ AS(P)" in out
    assert "note: the budget forces a detour" in out
    assert "@expect sat" not in out  # the passing check is not dumped


def test_render_keeps_fail_and_undecided_distinct() -> None:
    reports = (
        CheckReport(Verdict.FAIL, "@cautious", "decided wrong"),
        CheckReport(Verdict.UNDECIDED, "@brave", "the solve did not complete"),
    )
    out = render(synthetic(Sat()), reports)
    assert "[FAIL] @cautious: decided wrong" in out
    assert "[UNDECIDED] @brave: the solve did not complete" in out


def test_render_surfaces_note_on_undecided_too() -> None:
    # A "known-slow" @note is useful on UNDECIDED, not only FAIL.
    case = synthetic(Sat(notes=("this instance is known-slow",)))
    out = render(case, (CheckReport(Verdict.UNDECIDED, "@count", "budget hit"),))
    assert "— UNDECIDED" in out
    assert "note: this instance is known-slow" in out


def test_render_suppresses_the_note_on_a_passing_case() -> None:
    case = synthetic(Sat(notes=("irrelevant on pass",)))
    out = render(case, (report(Verdict.PASS, "@expect sat"),))
    assert out == "tests/cases/x.lp [clingo] — PASS"  # no note line on a passing case


def test_render_surfaces_an_unsat_cases_note_on_failure() -> None:
    case = synthetic(Unsat(notes=("the budget cap excludes every s–t path",)))
    out = render(case, (CheckReport(Verdict.FAIL, "@expect unsat", "a model exists: { a }"),))
    assert "— FAIL" in out
    assert "[FAIL] @expect unsat: a model exists: { a }" in out
    assert "note: the budget cap excludes every s–t path" in out


def test_case_verdict_empty_is_vacuously_pass() -> None:
    # Total-function identity (unreachable via run_case — @expect always yields ≥1 check).
    assert case_verdict(()) is Verdict.PASS


def test_render_empty_reports_is_a_bare_header() -> None:
    assert render(synthetic(Sat()), ()) == "tests/cases/x.lp [clingo] — PASS"
