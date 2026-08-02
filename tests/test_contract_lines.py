"""Every contract claim carries the line it was written on.

A consumer that places a diagnostic needs the coordinate, and the tokenizer already knows it: the
line was computed for error provenance and then dropped. These pin it from the contract text to the
check that reads it.
"""

from elenctic.expectation import Sat, Unsat, parse
from elenctic.run import runs_for

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
    assert expectation.count is not None and expectation.count.line == 3
    assert expectation.count.value == 2
    assert expectation.model is not None and expectation.model.line == 5


def test_a_brace_continuation_reports_the_line_the_tag_opened_on() -> None:
    # One claim spread over lines is the continuation mechanism, and it is one claim: the tag's own
    # line is where a reader looks for it.
    expectation = parse("% @expect sat\n% @model { a,\n%   b }\n")
    assert isinstance(expectation, Sat)
    assert expectation.model is not None and expectation.model.line == 2


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
