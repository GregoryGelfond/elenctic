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
from elenctic.checks import _partial_message, _undecided_message
from elenctic.discovery import discover
from elenctic.expectation import parse
from elenctic.harness import case_verdict, run_case
from elenctic.result import (
    Conclusion,
    ConsistentEnumeration,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    SolveOutcome,
    Verdict,
    collection_of,
)
from elenctic.run import runs_for
from elenctic.terms import parse_litset

_UNFINISHED = [Conclusion.INCOMPLETE, Conclusion.INTERRUPTED]

# An optimum this machine cannot prove in a thousand times the budget the test gives it, but which
# grounds in milliseconds: 16-queens under an objective. Measured — the proof does not finish in a
# minute, so a 0.05s budget is never a race.
_UNPROVABLE_OPTIMUM = """
#const n=16.
row(1..n). col(1..n).
1 { queen(R,C) : col(C) } 1 :- row(R).
:- queen(R1,C), queen(R2,C), R1 < R2.
:- queen(R1,C1), queen(R2,C2), R1 < R2, R2-R1 == |C2-C1|.
#minimize { R*C,R,C : queen(R,C) }.
#show queen/2.
"""


def _census(*models: str) -> ConsistentEnumeration:
    return ConsistentEnumeration(
        tuple(Observable(frozenset(parse_litset(model))) for model in models)
    )


@pytest.mark.parametrize("conclusion", _UNFINISHED)
def test_expect_sat_is_decided_by_a_search_that_did_not_finish(conclusion: Conclusion) -> None:
    report = checks.expect_sat(line=1)(SolveOutcome(_census("a"), conclusion))
    assert report.verdict is Verdict.PASS, (
        "@expect sat reads nothing from the collection, so one model settles it"
    )


@pytest.mark.parametrize("conclusion", _UNFINISHED)
def test_a_census_reading_is_undecided_by_a_search_that_did_not_finish(
    conclusion: Conclusion,
) -> None:
    report = checks.count_is(1, line=1)(SolveOutcome(_census("a"), conclusion))
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
    report = checks.cautious_contains(frozenset(parse_litset("a")), line=1)(
        SolveOutcome(_census("a"), conclusion)
    )
    assert report.verdict is Verdict.UNDECIDED


def test_a_finished_search_decides_both() -> None:
    outcome = SolveOutcome(_census("a"), Conclusion.EXHAUSTED)
    assert checks.expect_sat(line=1)(outcome).verdict is Verdict.PASS
    assert checks.count_is(1, line=1)(outcome).verdict is Verdict.PASS


def test_the_undecided_message_says_which_way_the_search_ended() -> None:
    # Raising a budget and shrinking a corpus are different remedies, so a report that cannot say
    # which kind of not-knowing it met leaves the reader nothing to act on.
    incomplete = checks.count_is(1, line=1)(SolveOutcome(_census("a"), Conclusion.INCOMPLETE))
    interrupted = checks.count_is(1, line=1)(SolveOutcome(_census("a"), Conclusion.INTERRUPTED))
    assert incomplete.message != interrupted.message
    assert "answer sets" in incomplete.message, "it names what ends a search this way"
    assert "--budget" in interrupted.message, "it names the remedy"


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


def test_every_unfinished_conclusion_has_a_diagnostic() -> None:
    # The partition is closed here as it is everywhere else in this codebase: a conclusion added
    # later without a message would otherwise surface as a bare lookup failure inside a check, at
    # verdict time, on a user's corpus.
    described = {Conclusion.EXHAUSTED}  # a finished search needs no excuse
    for conclusion in Conclusion:
        if conclusion in described:
            with pytest.raises(HarnessError):
                _partial_message(conclusion)
        else:
            assert _partial_message(conclusion), f"{conclusion.name} has no diagnostic"


# --- the same question on the other arm: a solve that settled nothing at all ---


def test_the_undecided_arm_says_which_way_the_search_ended() -> None:
    # An undecided solve used to discard how its search ended, so every check on the arm said the
    # same thing. @cost lands here whenever an optimal search runs out of budget — the reading most
    # likely to be short of time was the one that could not say so, while a @count over the same
    # program named the remedy.
    #
    # Each conclusion is tied to its OWN wording, not merely to a distinct one: three messages that
    # are pairwise different would survive being dealt to the wrong conclusions, and that failure
    # tells a user whose search stopped short that a larger budget cannot help — the inverse of the
    # advice this diagnostic exists to give.
    check = checks.cost_is((1,), line=1)
    messages = {
        conclusion: check(SolveOutcome(Inconclusive(), conclusion)).message
        for conclusion in Conclusion
    }
    assert "--budget" in messages[Conclusion.INTERRUPTED], "it names the remedy"
    assert "stopped short" in messages[Conclusion.INCOMPLETE], "it names a bound run into"
    assert "covered the space" in messages[Conclusion.EXHAUSTED], "it claims no remedy it cannot"
    assert len(set(messages.values())) == len(Conclusion), "each way of ending reads differently"


@pytest.mark.parametrize("conclusion", list(Conclusion))
def test_a_report_carries_the_search_behind_it_rather_than_assuming_one(
    conclusion: Conclusion,
) -> None:
    # Over every arm and every conclusion, because the report's own field is what a consumer reads
    # and no reader in this process does: the human render shows the verdict and the message, so a
    # report that hard-coded one conclusion would look right everywhere the eye can reach and be
    # wrong in the document. A cancelled search claiming it closed the space is the exact reading
    # this vocabulary exists to prevent, one layer out.
    check = checks.expect_sat(line=1)  # reads nothing, so it decides on every arm and conclusion
    for determination in (Inconclusive(), _census("a")):
        assert check(SolveOutcome(determination, conclusion)).conclusion is conclusion
    assert (
        check(SolveOutcome(Inconsistent(), Conclusion.EXHAUSTED)).conclusion is Conclusion.EXHAUSTED
    )


def test_an_undecided_solve_is_undecided_however_its_search_ended() -> None:
    # The verdict does not move: carrying the conclusion changes what the report can say, never
    # what it decides. A solve that settled nothing is UNDECIDED, never FAIL, on every conclusion.
    for conclusion in Conclusion:
        report = checks.count_is(1, line=1)(SolveOutcome(Inconclusive(), conclusion))
        assert report.verdict is Verdict.UNDECIDED


def test_every_conclusion_has_an_undecided_diagnostic() -> None:
    # Closed like the partition beside it. Unlike the partial-reading message this one is total: an
    # exhausted search reaches this arm too, by way of the optimal-class driver's second phase
    # returning no model on a control the first already exhausted, and refusing that input would
    # raise inside a check at verdict time instead of saying the little that is known.
    for conclusion in Conclusion:
        assert _undecided_message(conclusion), f"{conclusion.name} has no diagnostic"


def test_a_cost_under_a_hit_budget_names_the_remedy(tmp_path: Path) -> None:
    # End to end through the ordinary path, on the reading the defect was found in. Both ways this
    # run can end short of a shape — no model collected yet, or a best-so-far that is not a proven
    # optimum — report the same interruption, so the assertion does not race the search.
    case_file = tmp_path / "hard.lp"
    case_file.write_text("% @expect sat\n% @cost { 1 }\n" + _UNPROVABLE_OPTIMUM, encoding="utf-8")
    (case,) = discover(case_file)
    (report,) = [r for r in run_case(case, budget=0.05) if r.label == "@cost"]
    assert report.verdict is Verdict.UNDECIDED
    assert "--budget" in report.message, "the mode most likely to be short of time must say so"
