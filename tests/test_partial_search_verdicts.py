"""Which readings survive a search that did not finish.

A search that stops early leaves an arbitrary part of the collection unseen, so every reading that
ranges over the whole of one becomes a claim about a part. A reading that ranges over nothing — that
an answer set exists at all — is settled by the first model whatever the rest of the search holds.

The requirement therefore belongs to what a check reads, not to the mode of the run it rides: one
run carries several checks, and they do not all range over the same thing.
"""

from pathlib import Path

import pytest

from elenctic import checks
from elenctic.discovery import discover
from elenctic.expectation import parse
from elenctic.harness import case_verdict, run_case
from elenctic.result import (
    Conclusion,
    ConsistentEnumeration,
    Observable,
    SolveOutcome,
    Verdict,
    collection_of,
)
from elenctic.run import runs_for
from elenctic.terms import parse_litset

_UNFINISHED = [Conclusion.STOPPED, Conclusion.INTERRUPTED]


def _census(*models: str) -> ConsistentEnumeration:
    return ConsistentEnumeration(
        tuple(Observable(frozenset(parse_litset(model))) for model in models)
    )


@pytest.mark.parametrize("conclusion", _UNFINISHED)
def test_expect_sat_is_decided_by_a_search_that_did_not_finish(conclusion: Conclusion) -> None:
    report = checks.expect_sat()(SolveOutcome(_census("a"), conclusion))
    assert report.verdict is Verdict.PASS, (
        "@expect sat reads nothing from the collection, so one model settles it"
    )


@pytest.mark.parametrize("conclusion", _UNFINISHED)
def test_a_census_reading_is_undecided_by_a_search_that_did_not_finish(
    conclusion: Conclusion,
) -> None:
    report = checks.count_is(1)(SolveOutcome(_census("a"), conclusion))
    assert report.verdict is Verdict.UNDECIDED, (
        "a census over part of the collection is not the census"
    )


@pytest.mark.parametrize("conclusion", _UNFINISHED)
def test_a_consequence_reading_over_a_partial_search_never_passes_a_claim(
    conclusion: Conclusion,
) -> None:
    # The dangerous direction: clingo refines cautious consequences downwards, so a cut-short run
    # holds a SUPERSET of the true ⋂. A claim naming a surplus atom would be "verified" by a search
    # that never established it.
    report = checks.cautious_contains(frozenset(parse_litset("a")))(
        SolveOutcome(_census("a"), conclusion)
    )
    assert report.verdict is Verdict.UNDECIDED


def test_a_finished_search_decides_both() -> None:
    outcome = SolveOutcome(_census("a"), Conclusion.EXHAUSTED)
    assert checks.expect_sat()(outcome).verdict is Verdict.PASS
    assert checks.count_is(1)(outcome).verdict is Verdict.PASS


def test_the_undecided_message_says_which_way_the_search_ended() -> None:
    stopped = checks.count_is(1)(SolveOutcome(_census("a"), Conclusion.STOPPED))
    interrupted = checks.count_is(1)(SolveOutcome(_census("a"), Conclusion.INTERRUPTED))
    assert stopped.message != interrupted.message, (
        "a report that cannot say why it could not decide leaves the reader nothing to act on"
    )
    assert "bound" in stopped.message
    assert "budget" in interrupted.message


def test_a_check_needs_an_exhausted_search_exactly_when_it_reads_a_collection() -> None:
    # Derived, not declared: a check is exempt exactly when nothing it reads is a reading of a
    # collection. Stated over the fields, not over "reads anything at all" — those differ, because
    # `@expect unsat` reads the witness, which is not a collection, so it is exempt while reading
    # something. Both contract shapes appear, since one exempt check lives in each.
    contracts = (
        "% @expect sat\n% @count 2\n% @cautious { a }\n% @brave { a }\n% @model { a }\n"
        "% @query yes { a }\n",
        "% @expect unsat\n",
    )
    seen = set()
    for text in contracts:
        for run in runs_for(parse(text)):
            for check in run.checks:
                seen.add(check.label)
                reads_a_collection = any(
                    collection_of(frozenset({field})).needs_exhausted_search
                    for field in check.reads
                )
                assert check.needs_exhausted_search == reads_a_collection, (
                    f"{check.label} reads {sorted(f.value for f in check.reads)} but requires "
                    f"exhaustion={check.needs_exhausted_search}"
                )
    assert {"@expect sat", "@expect unsat"} <= seen, "both exempt checks must be covered"


def test_the_exempt_checks_are_exactly_the_two_that_read_no_collection() -> None:
    # The closed companion to the derivation above, which is otherwise a tautology: if a future
    # check joins the exempt set, this names it and a reader has to justify it.
    exempt = {
        check.label
        for text in ("% @expect sat\n% @count 2\n% @cautious { a }\n", "% @expect unsat\n")
        for run in runs_for(parse(text))
        for check in run.checks
        if not check.needs_exhausted_search
    }
    assert exempt == {"@expect sat", "@expect unsat"}


def test_a_case_under_a_hit_budget_still_reports_the_satisfiability_it_settled(
    tmp_path: Path,
) -> None:
    # The reachable form of the defect, end to end through the ordinary path: 2^20 answer sets and
    # a budget no machine meets. The solve decides satisfiable and is then cut short, so the census
    # reading is a claim about a part while the satisfiability reading is settled.
    case_file = tmp_path / "wide.lp"
    case_file.write_text(
        "% @expect sat\n% @count 1048576\n{ p(1..20) }.\n#show p/1.\n", encoding="utf-8"
    )
    (case,) = discover(case_file)
    reports = run_case(case, budget=0.05)
    by_label = {report.label: report.verdict for report in reports}
    assert by_label["@expect sat"] is Verdict.PASS, (
        "the search found models, so satisfiability was settled"
    )
    assert by_label["@count"] is Verdict.UNDECIDED
    assert case_verdict(reports) is Verdict.UNDECIDED
