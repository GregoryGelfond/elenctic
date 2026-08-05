"""Every contract claim carries the line it was written on.

A consumer that places a diagnostic needs the coordinate, and the tokenizer already knows it: the
line was computed for error provenance and then dropped. These pin it from the contract text to the
check that reads it.
"""

import pytest

from elenctic.checks import CheckReport
from elenctic.expectation import Claimed, Sat, Unsat, parse
from elenctic.result import (
    Conclusion,
    ConsistentCautious,
    ConsistentEnumeration,
    Observable,
    SolveOutcome,
    Verdict,
)
from elenctic.run import runs_for
from elenctic.terms import parse_litset

_CONTRACT = """\
% a leading comment that is not a contract line
% @expect sat
% @count 2
% @cautious { a }
% @model { a, b }
p(1).
"""


def test_the_expect_line_is_the_line_expect_was_written_on() -> None:
    expectation = parse(_CONTRACT)
    assert isinstance(expectation, Sat)
    assert expectation.expect_line == 2


def test_each_cell_carries_its_own_line() -> None:
    expectation = parse(_CONTRACT)
    assert isinstance(expectation, Sat)
    assert expectation.count is not None
    assert expectation.count.line == 3
    assert expectation.count.value == 2
    assert expectation.model is not None
    assert expectation.model.line == 5


def test_a_brace_continuation_reports_the_line_the_tag_opened_on() -> None:
    # One claim spread over lines is the continuation mechanism, and it is one claim: the tag's own
    # line is where a reader looks for it.
    expectation = parse("% @expect sat\n% @model { a,\n%   b }\n")
    assert isinstance(expectation, Sat)
    assert expectation.model is not None
    assert expectation.model.line == 2


def test_the_line_reaches_the_check_that_reads_the_cell() -> None:
    expectation = parse(_CONTRACT)
    lines = {
        (check.label, check.subject): check.line
        for run in runs_for(expectation)
        for check in run.checks
    }
    assert lines[("@count", "")] == 3
    assert lines[("@model", "")] == 5
    assert lines[("@expect sat", "")] == 2


def test_an_unsat_contract_reports_the_line_too() -> None:
    # The unsat arm derives its one check by a different path from the sat arm, so it needs its own
    # coordinate rather than inheriting the sat arm's coverage.
    expectation = parse("% a note about the encoding\n% @expect unsat\n")
    assert isinstance(expectation, Unsat)
    assert expectation.expect_line == 2
    ((check,),) = (run.checks for run in runs_for(expectation))
    assert check.label == "@expect unsat"
    assert check.line == 2


def test_two_consequence_lines_are_two_claims_with_two_lines() -> None:
    expectation = parse("% @expect sat\n% @cautious { a }\n% @cautious { b }\n")
    assert isinstance(expectation, Sat)
    assert [claim.line for claim in expectation.cautious] == [2, 3]


def test_each_consequence_claim_gets_its_own_check() -> None:
    expectation = parse("% @expect sat\n% @cautious { a }\n% @cautious { b }\n")
    lines = sorted(
        check.line
        for run in runs_for(expectation)
        for check in run.checks
        if check.label == "@cautious"
    )
    assert lines == [2, 3]


def test_splitting_the_consequence_tags_preserves_the_case_verdict() -> None:
    # L1 ⊆ ⋂ and L2 ⊆ ⋂ hold exactly when (L1 ∪ L2) ⊆ ⋂ does, so the case verdict is the same
    # whether the claims are checked together or apart. What changes is which line a failure names.
    from elenctic.harness import case_verdict
    from elenctic.result import Conclusion, ConsistentEnumeration, Observable, SolveOutcome, Verdict
    from elenctic.terms import parse_litset

    census = ConsistentEnumeration((Observable(frozenset(parse_litset("a"))),))
    outcome = SolveOutcome(census, Conclusion.EXHAUSTED)
    expectation = parse("% @expect sat\n% @cautious { a }\n% @cautious { b }\n")
    checks = [check for run in runs_for(expectation) for check in run.checks]
    reports = tuple(check(outcome) for check in checks)
    failing = [
        (check, report)
        for check, report in zip(checks, reports, strict=True)
        if report.verdict is Verdict.FAIL
    ]
    assert case_verdict(reports) is Verdict.FAIL
    assert len(failing) == 1, "only the claim that was false fails"
    check, report = failing[0]
    assert check.line == 3, "the failure names the line whose claim was false, not the union's"
    assert "b" in report.message


# --- totality: EVERY cell, not the handful the examples above happen to reach ---

# One row per cell that can carry a claim, as (tag text, the cell it lands in). Written as a table
# rather than as one test per tag because totality is a claim about the *set* of cells: a cell added
# without a line has to fail something, and a test that ranges over the set is the only thing that
# can notice. `@expect` is absent because it is not a cell — its line is `expect_line`, pinned
# above.
_CELLS: list[tuple[str, str]] = [
    ("@model { a }", "model"),
    ("@optimal { a }", "optimal_model"),
    ("@model optimal { a }", "optimal_model"),
    ("@cautious { a }", "cautious"),
    ("@cautious optimal { a }", "cautious_optimal"),
    ("@brave { a }", "brave"),
    ("@brave optimal { a }", "brave_optimal"),
    ("@count 2", "count"),
    ("@count optimal 1", "count_optimal"),
    ("@cost { 4 }", "cost"),
    ("@assign { v=1 }", "assign"),
    ("@assign optimal { w=2 }", "assign_optimal"),
    ("@query yes { a }", "queries"),
]


def _claims(expectation: Sat, cell: str) -> list[Claimed[object]]:
    """The claims in a cell, however many it holds — one for a single-valued cell, n for a
    repeatable one, so a table row need not know which kind it named."""
    held = getattr(expectation, cell)
    if held is None:
        return []
    return list(held) if isinstance(held, tuple) else [held]


def test_the_cell_table_covers_every_cell_that_can_carry_a_claim() -> None:
    # The table is only as good as its coverage, so it is checked against the shape rather than
    # trusted: a cell added to Sat without a row here fails, and so does a row naming no cell.
    carrying = {
        name
        for name in Sat.__dataclass_fields__
        if name not in {"expect_line", "notes"}  # not cells: the shape's own line, and prose
    }
    assert {cell for _tag, cell in _CELLS} == carrying


@pytest.mark.parametrize(("tag", "cell"), _CELLS, ids=[tag for tag, _ in _CELLS])
def test_every_cell_carries_the_line_its_tag_was_written_on(tag: str, cell: str) -> None:
    # Two leading comments, so a cell that hard-coded 1 or 2 is caught.
    expectation = parse(f"% a comment\n% @expect sat\n% {tag}\n")
    assert isinstance(expectation, Sat)
    assert [claim.line for claim in _claims(expectation, cell)] == [3]


@pytest.mark.parametrize(("tag", "cell"), _CELLS, ids=[tag for tag, _ in _CELLS])
def test_every_cells_line_reaches_the_check_it_derives(tag: str, cell: str) -> None:
    # The cell carrying the line is half of it; a check built without passing it on would leave the
    # coordinate stranded one layer short of the consumer that needs it.
    expectation = parse(f"% a comment\n% @expect sat\n% {tag}\n")
    derived = [
        check
        for run in runs_for(expectation)
        for check in run.checks
        if not check.label.startswith("@expect")
    ]
    assert derived, "the tag derived no check at all"
    assert all(check.line == 3 for check in derived)


def test_a_check_is_identified_by_label_subject_and_line() -> None:
    # (label, subject) names a check but cannot identify one: an author may write the same claim
    # twice. At most one tag occupies a line, so the triple is what a consumer keys on.
    expectation = parse(
        "% @expect sat\n% @cautious { a }\n% @cautious { a }\n% @cautious { b }\n"
        "% @query yes { a }\n% @query yes { a }\n"
    )
    checks = [check for run in runs_for(expectation) for check in run.checks]
    pairs = [(check.label, check.subject) for check in checks]
    triples = [(check.label, check.subject, check.line) for check in checks]
    assert len(set(pairs)) < len(pairs), "identical claims share a (label, subject)"
    assert len(set(triples)) == len(triples), "the line is what tells them apart"


def test_a_repeatable_tag_carries_its_surface_as_its_subject() -> None:
    # The discriminator the repeatable @query tag already used, extended to the tags that became
    # repeatable: without it two claims are indistinguishable wherever a line is not shown, which
    # is every reader of a Check rather than a report — the dry-run plan among them.
    expectation = parse("% @expect sat\n% @cautious { a }\n% @brave { b }\n")
    subjects = {check.label: check.subject for run in runs_for(expectation) for check in run.checks}
    assert subjects["@cautious"] == "{ a }"
    assert subjects["@brave"] == "{ b }"


# --- the invariant every carrier of a coordinate shares ---


def test_a_line_is_1_based_wherever_one_is_carried() -> None:
    # The same invariant on every carrier. Claimed validated it from the start; the others took a
    # bare int, so a decoder or a hand-built shape could seat a 0 where the contract promises a
    # line — the one value a missing JSON field decodes to. The report is the carrier that leaves
    # the process, which is why it is guarded rather than trusted to the check that built it.
    from elenctic import checks

    with pytest.raises(ValueError, match="1-based"):
        Claimed("a", 0)
    with pytest.raises(ValueError, match="1-based"):
        Sat(expect_line=0)
    with pytest.raises(ValueError, match="1-based"):
        Unsat(expect_line=0)
    with pytest.raises(ValueError, match="1-based"):
        checks.expect_sat(line=0)
    with pytest.raises(ValueError, match="1-based"):
        CheckReport(
            verdict=Verdict.PASS,
            label="@expect sat",
            message="",
            subject="",
            line=0,
            conclusion=Conclusion.EXHAUSTED,
        )


def test_a_line_is_counted_the_way_clingo_counts_one() -> None:
    # A contract line ends at a newline and nowhere else, because that is where clingo's comment
    # ends. Python's splitlines() also breaks on \v, \f, NEL and the Unicode separators, so a
    # consumer resolving this coordinate with splitlines() would highlight the wrong line. The
    # coordinate leaves the module now, so the model it is counted in is part of what is promised.
    text = "% @note a note with a vertical tab \v inside it\n% @expect sat\n"
    expectation = parse(text)
    assert expectation.expect_line == 2
    assert len(text.splitlines()) == 3, "splitlines would have made this line 3"


# --- the coordinate reaches the report, which is where a consumer reads it ---


def test_a_report_carries_the_claim_it_judged() -> None:
    # The last hop. A check knowing its own coordinate is no use to a consumer that only ever sees
    # the report, and the report is what both the human render and the document are built from.
    expectation = parse("% @expect sat\n% @cautious { a }\n")
    census = ConsistentEnumeration((Observable(frozenset(parse_litset("a"))),))
    outcome = SolveOutcome(census, Conclusion.EXHAUSTED)
    reports = {
        report.label: report
        for run in runs_for(expectation)
        for check in run.checks
        for report in [check(outcome)]
    }
    assert reports["@cautious"].line == 2
    assert reports["@cautious"].subject == "{ a }", "a consequence tag is repeatable, so it has one"
    assert reports["@cautious"].conclusion is Conclusion.EXHAUSTED
    assert reports["@expect sat"].subject == "", "a tag that can occur once has nothing to name"


def test_a_query_report_carries_its_subject() -> None:
    expectation = parse("% @expect sat\n% @query yes { a }\n")
    outcome = SolveOutcome(ConsistentCautious(frozenset(parse_litset("a"))), Conclusion.EXHAUSTED)
    (report,) = [
        check(outcome)
        for run in runs_for(expectation)
        for check in run.checks
        if check.label == "@query"
    ]
    assert report.subject, "the repeatable tag is discernible only by its subject"
    assert report.line == 2
