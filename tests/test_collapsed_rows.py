"""One fact, stated once: the collapsed row in the human render.

Splitting a repeated consequence tag into one check per contract line made every arm whose message
does *not* depend on the claim state the same sentence once per claim. Three ``@cautious`` lines on
an unsatisfiable program gave three identical failures, each longer than the single line the merged
cell used to produce. Carrying the coordinate makes them distinguishable; it does not make them
fewer, and these pin the part that does.

Reports that differ only in *which claim* they judged collapse to one row, with what differs
carried on a continuation line — each subject paired with its own line, so nothing has to be
zipped. When the message turns on the claim, which is the informative case and the reason the split
happened at all, nothing collapses and each claim keeps its own diagnostic.

The collapse is display only. It cannot move a verdict, and it changes nothing a consumer reads.
"""

from pathlib import Path

import pytest

from elenctic.checks import CheckReport
from elenctic.discovery import Case
from elenctic.expectation import Sat
from elenctic.harness import case_verdict, render
from elenctic.result import Conclusion, Verdict

_UNSAT_CAUTIOUS = "no cautious consequences — AS(P) = ∅"


def _case(*notes: str) -> Case:
    return Case(Path("tests/cases/x.lp"), "clingo", Sat(expect_line=1, notes=notes), frozenset())


def _report(
    label: str,
    message: str,
    *,
    subject: str = "",
    line: int = 1,
    verdict: Verdict = Verdict.FAIL,
) -> CheckReport:
    return CheckReport(
        verdict=verdict,
        label=label,
        message=message,
        subject=subject,
        line=line,
        conclusion=Conclusion.EXHAUSTED,
    )


def _cautious_on(*lines: int) -> tuple[CheckReport, ...]:
    """One ``@cautious`` failure per line, all saying the one thing an empty AS(P) makes true."""
    return tuple(
        _report("@cautious", _UNSAT_CAUTIOUS, subject=f"{{ a{line} }}", line=line) for line in lines
    )


# --- the collapse itself ---


def test_claims_that_differ_only_in_their_coordinate_state_the_fact_once() -> None:
    out = render(_case(), _cautious_on(2, 3, 4))
    assert f"  [FAIL] @cautious: {_UNSAT_CAUTIOUS}" in out
    assert "         applied to { a2 } (line 2), { a3 } (line 3), { a4 } (line 4)" in out
    assert out.count(_UNSAT_CAUTIOUS) == 1, "the fact is stated once, not once per claim"


def test_a_collapsed_row_costs_two_lines_however_many_claims_it_carries() -> None:
    # The point of the task: the row count stops growing with the claim count. Without this, ten
    # `@cautious` lines on an unsatisfiable program produce ten copies of one sentence.
    body = len(render(_case(), _cautious_on(*range(2, 12))).splitlines()) - 1  # less the header
    assert body == 2, "a header line and its continuation, whatever the claim count"


def test_nothing_collapses_when_the_message_turns_on_the_claim() -> None:
    # The informative case, and the reason the split happened: each claim failed for its own
    # reason, so each keeps its own diagnostic and its own coordinate.
    reports = (
        _report("@cautious", "{ a } ⊄ ⋂ AS(P) = { c }", subject="{ a }", line=2),
        _report("@cautious", "{ b } ⊄ ⋂ AS(P) = { c }", subject="{ b }", line=3),
    )
    out = render(_case(), reports)
    assert "  [FAIL] @cautious { a } (line 2): { a } ⊄ ⋂ AS(P) = { c }" in out
    assert "  [FAIL] @cautious { b } (line 3): { b } ⊄ ⋂ AS(P) = { c }" in out
    assert "applied to" not in out


def test_a_single_claim_keeps_the_one_line_form() -> None:
    out = render(_case(), _cautious_on(2))
    assert f"  [FAIL] @cautious {{ a2 }} (line 2): {_UNSAT_CAUTIOUS}" in out
    assert "applied to" not in out, "there is nothing to disambiguate against"


def test_a_tag_that_can_occur_once_carries_its_line_and_no_subject() -> None:
    out = render(_case(), (_report("@count", "expected 2 models, got 0 — AS(P) = ∅", line=5),))
    assert "  [FAIL] @count (line 5): expected 2 models, got 0 — AS(P) = ∅" in out
    assert "()" not in out


def test_only_reports_that_agree_on_the_message_collapse() -> None:
    # Same label, same verdict, different message: two facts, so two rows. Collapsing on the label
    # alone would merge diagnostics that say different things and hide one of them.
    reports = (
        *_cautious_on(2, 3),
        _report("@cautious", "{ z } ⊄ ⋂ AS(P) = { }", subject="{ z }", line=4),
    )
    out = render(_case(), reports)
    assert "applied to { a2 } (line 2), { a3 } (line 3)" in out
    assert "  [FAIL] @cautious { z } (line 4): { z } ⊄ ⋂ AS(P) = { }" in out


def test_a_shared_message_under_different_labels_does_not_collapse() -> None:
    # `@cautious` and `@brave` both report an empty AS(P) in the same words on some programs; they
    # are still two claims about two different readings, and merging them would say one was made.
    reports = (
        _report("@cautious", "no consequences — AS(P) = ∅", subject="{ a }", line=2),
        _report("@brave", "no consequences — AS(P) = ∅", subject="{ a }", line=3),
    )
    out = render(_case(), reports)
    assert "  [FAIL] @cautious { a } (line 2): no consequences — AS(P) = ∅" in out
    assert "  [FAIL] @brave { a } (line 3): no consequences — AS(P) = ∅" in out


def test_undecided_claims_collapse_the_same_way_a_failing_one_does() -> None:
    # The commoner shape, and the one every other fixture here misses: a repeated tag whose run hit
    # the budget gives one partial-reading message per claim, identical in every word. Nothing
    # about the collapse is specific to FAIL, and a rule that read the verdict rather than grouping
    # on it would state this fact three times over.
    partial = "the search was cut short before covering the collection this reads"
    reports = tuple(
        _report("@cautious", partial, subject=f"{{ a{n} }}", line=n, verdict=Verdict.UNDECIDED)
        for n in (2, 3, 4)
    )
    out = render(_case(), reports)
    assert f"  [UNDECIDED] @cautious: {partial}" in out
    assert "         applied to { a2 } (line 2), { a3 } (line 3), { a4 } (line 4)" in out
    assert out.count(partial) == 1


def test_a_fail_never_collapses_into_an_undecided() -> None:
    # FAIL and UNDECIDED are kept distinct everywhere else in this renderer, and a row carrying one
    # tag would have to claim a verdict for claims that did not earn it.
    reports = (
        _report("@cautious", _UNSAT_CAUTIOUS, subject="{ a }", line=2),
        _report("@cautious", _UNSAT_CAUTIOUS, subject="{ b }", line=3, verdict=Verdict.UNDECIDED),
    )
    out = render(_case(), reports)
    assert "  [FAIL] @cautious { a } (line 2)" in out
    assert "  [UNDECIDED] @cautious { b } (line 3)" in out


# --- the constraints the collapse must not violate ---


@pytest.mark.parametrize(
    "reports",
    [
        pytest.param(_cautious_on(2, 3, 4), id="collapsing"),
        pytest.param(
            (
                _report("@cautious", _UNSAT_CAUTIOUS, subject="{ a }", line=2),
                _report("@count", "expected 2 models, got 0", line=3, verdict=Verdict.UNDECIDED),
            ),
            id="not-collapsing",
        ),
        pytest.param(
            (
                _report("@count", "budget hit", line=2, verdict=Verdict.UNDECIDED),
                _report("@cautious", _UNSAT_CAUTIOUS, subject="{ a }", line=3),
            ),
            id="undecided-group-first",
        ),
    ],
)
def test_the_header_reports_the_case_verdict_however_the_rows_were_grouped(
    reports: tuple[CheckReport, ...],
) -> None:
    # Asserted through `render`, because that is where a display change could become a correctness
    # change: the verdict folds a *set* of every report, and a header derived instead from the
    # grouped rows would take the first group's verdict — which, with groups in first-appearance
    # order, is UNDECIDED for a case the exit code calls FAIL. Reading `case_verdict` twice would
    # prove only that `case_verdict` is a function of its argument.
    header = render(_case(), reports).splitlines()[0]
    assert header.endswith(f"— {case_verdict(reports).name}")
    assert header.endswith("— FAIL"), "a definite failure sinks the case whatever else it holds"


def test_every_collapsed_claim_appears_in_the_continuation() -> None:
    # Nothing is silently dropped. A row that says one thing about four claims but names three has
    # hidden a claim the author wrote and the run judged.
    reports = _cautious_on(*range(2, 20))
    out = render(_case(), reports)
    for report in reports:
        assert f"{report.subject} (line {report.line})" in out


def test_the_continuation_orders_claims_by_line() -> None:
    # Deterministic bytes for the same input, and ascending because that is the order the reader
    # will meet them in when they open the file. Lines 2, 10 and 11 rather than 2, 3 and 4: single
    # digits sort the same way lexicographically, so any fixture using them is also passed by an
    # implementation that orders on the subject text — or on nothing at all.
    out = render(_case(), tuple(reversed(_cautious_on(2, 10, 11))))
    assert "applied to { a2 } (line 2), { a10 } (line 10), { a11 } (line 11)" in out


def test_a_collapsed_subject_is_made_legible() -> None:
    # A subject is corpus text wherever it is shown, and the continuation line is another place it
    # is shown. Text that could rewrite the verdict must not survive being moved there.
    reports = (
        _report("@query", "computed no", subject="yes \x1b[2J{ a }", line=2),
        _report("@query", "computed no", subject="yes \x1b[2J{ b }", line=3),
    )
    out = render(_case(), reports)
    assert "applied to" in out, "the two reports are expected to collapse"
    assert "\x1b" not in out
    assert "\\x1b" in out


def test_the_note_still_follows_a_collapsed_failure() -> None:
    out = render(_case("this instance is known-slow"), _cautious_on(2, 3))
    assert "applied to" in out
    assert "  note: this instance is known-slow" in out


@pytest.mark.parametrize("count", [1, 2, 5])
def test_a_passing_check_is_never_rendered_collapsed_or_otherwise(count: int) -> None:
    passing = tuple(
        _report("@cautious", "{ a } ⊆ ⋂ AS(P)", subject="{ a }", line=n, verdict=Verdict.PASS)
        for n in range(2, 2 + count)
    )
    assert render(_case(), passing) == "tests/cases/x.lp [clingo] — PASS"
