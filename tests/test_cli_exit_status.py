"""What the process status says, and that the run's outcome alone says it.

Four things a run can report, kept apart because they ask different things of the reader: every case
passed; a case was tested and decided wrong, or could not be decided; the corpus holds a fault its
author can fix; elenctic violated one of its own invariants. The last outranks the rest, because a
harness that is wrong about one case is evidence about every other.

The status is a function of what the run produced and of nothing else. A strictness dial grades an
observation where the observation is recorded, so the record carries the grade and the status reads
it off — which is what lets a consumer holding only the report say what the process returned, and an
embedder that never parsed a command line ask the question at all.
"""

from inspect import signature
from pathlib import Path

import pytest

from elenctic.checks import CheckReport
from elenctic.cli import ExitStatus, exit_status
from elenctic.discovery import Case
from elenctic.expectation import Unsat
from elenctic.outcome import (
    CaseOutcome,
    ErrorKind,
    ErrorRecord,
    Grade,
    HygieneKind,
    HygieneRecord,
    PlanOutcome,
    RunOutcome,
    Scope,
)
from elenctic.result import Conclusion, Verdict


def _case(verdict: Verdict) -> CaseOutcome:
    return CaseOutcome(
        case=Case(Path("a.lp"), "clingo", Unsat(expect_line=1), frozenset()),
        reports=(
            CheckReport(
                verdict=verdict,
                label="@expect unsat",
                message="the diagnostic",
                subject="",
                line=1,
                conclusion=Conclusion.EXHAUSTED,
            ),
        ),
    )


def _error(kind: ErrorKind) -> ErrorRecord:
    return ErrorRecord(
        kind=kind, scope=Scope.CASE, source=Path("a.lp"), message="no verdict was produced"
    )


def _observation(grade: Grade) -> HygieneRecord:
    return HygieneRecord(
        kind=HygieneKind.ORPHAN_LIBRARY,
        grade=grade,
        source=Path("lib.lp"),
        message="nothing includes it",
    )


def _outcome(
    *,
    cases: tuple[CaseOutcome, ...] = (),
    errors: tuple[ErrorRecord, ...] = (),
    hygiene: tuple[HygieneRecord, ...] = (),
) -> RunOutcome:
    """A run outcome with every register empty but the ones a test is about."""
    return RunOutcome(cases=cases, errors=errors, hygiene=hygiene)


def test_a_run_in_which_every_case_passed_is_the_only_zero() -> None:
    assert exit_status(_outcome(cases=(_case(Verdict.PASS), _case(Verdict.PASS)))) == ExitStatus.OK


def test_a_corpus_of_no_cases_has_no_case_that_did_not_pass() -> None:
    # Nothing to report is not a failure to report. A target holding no contract-bearing file
    # discovers nothing, and there is no case for the status to be about.
    assert exit_status(_outcome()) == ExitStatus.OK


@pytest.mark.parametrize("verdict", [Verdict.FAIL, Verdict.UNDECIDED])
def test_a_case_not_decided_right_is_the_verdict_register(verdict: Verdict) -> None:
    # UNDECIDED shares the status with FAIL rather than with PASS. The two mean different things to
    # a reader — one is a wrong answer, the other no answer — but a caller gating on the status is
    # asking whether the contract was shown to hold, and neither shows it.
    assert (
        exit_status(_outcome(cases=(_case(Verdict.PASS), _case(verdict)))) == ExitStatus.NOT_PASSED
    )


def test_a_fault_the_user_can_fix_outranks_a_verdict() -> None:
    # A case that could not be run leaves the run's answer incomplete, so a corpus whose remaining
    # cases all passed must not report the status that says the corpus was checked and is clean.
    outcome = _outcome(cases=(_case(Verdict.PASS),), errors=(_error(ErrorKind.PROGRAM),))
    assert exit_status(outcome) == ExitStatus.USER_FAULT


def test_a_harness_fault_outranks_every_other_signal() -> None:
    # An elenctic bug puts every verdict in the run in doubt, so it is what the status reports.
    outcome = _outcome(
        cases=(_case(Verdict.FAIL),),
        errors=(_error(ErrorKind.PROGRAM), _error(ErrorKind.HARNESS)),
        hygiene=(_observation(Grade.ERROR),),
    )
    assert exit_status(outcome) == ExitStatus.HARNESS_FAULT


def test_a_locus_that_is_not_a_harness_fault_stays_the_user_s_to_fix() -> None:
    # The elenctic-bug side of the split is the closed one, so a locus named for something that is
    # nobody's bug — a deadline the run passed — reports a corpus to attend to, not a bug to file.
    assert exit_status(_outcome(errors=(_error(ErrorKind.DEADLINE),))) == ExitStatus.USER_FAULT


def test_an_observation_graded_an_error_fails_the_run() -> None:
    # Hygiene reaches the status by exactly one route: the grade the run put on the observation.
    outcome = _outcome(cases=(_case(Verdict.PASS),), hygiene=(_observation(Grade.ERROR),))
    assert exit_status(outcome) == ExitStatus.USER_FAULT


@pytest.mark.parametrize("grade", [Grade.WARNING, Grade.SILENT])
def test_an_observation_graded_below_an_error_leaves_the_status_alone(
    grade: Grade,
) -> None:
    # Hygiene is never a verdict, so an observation this run did not grade an error must not reach
    # the status by some other route: a corpus that passes with a warning has passed.
    outcome = _outcome(cases=(_case(Verdict.PASS),), hygiene=(_observation(grade),))
    assert exit_status(outcome) == ExitStatus.OK


def test_the_ladder_is_the_numbers_it_publishes() -> None:
    # The one place the numbers themselves are asserted, and it is deliberate that there is one.
    #
    # Naming the rungs is what lets every other test here say what it means rather than make a
    # reader recall that 2 is a corpus to attend to. But a name is only ever equal to itself, so a
    # suite that named them everywhere and nowhere pinned the integers would pass with the ladder
    # renumbered — and these integers are a published contract. A shell script gating on 2, a CI
    # job testing for exactly 3, and the README's own account of them are all outside this suite
    # and cannot be renumbered by it.
    #
    # Ordered rather than a set, because the order is the precedence: a rung that outranks another
    # is the lower number, and swapping two members would keep the set and lose the ladder.
    assert [(rung.name, rung.value) for rung in ExitStatus] == [
        ("OK", 0),
        ("NOT_PASSED", 1),
        ("USER_FAULT", 2),
        ("HARNESS_FAULT", 3),
    ]


def test_every_rung_of_the_ladder_is_one_a_run_can_actually_reach() -> None:
    # The help is rendered from the ladder rather than written beside it, so "a number documented
    # that nothing returns" and "a rung returned that nothing documents" are both unrepresentable
    # and there is nothing left to compare. What is left to hold is the claim the rendering assumes:
    # that every member is a status some run can actually leave with. A member nobody can reach is
    # a rung documented to a reader who will never see it, and the enum is closed precisely so that
    # adding one is a deliberate act — this is what makes it a deliberate act with evidence.
    reached = {
        exit_status(_outcome(cases=(_case(Verdict.PASS),))): ExitStatus.OK,
        exit_status(_outcome(cases=(_case(Verdict.FAIL),))): ExitStatus.NOT_PASSED,
        exit_status(_outcome(errors=(_error(ErrorKind.PROGRAM),))): ExitStatus.USER_FAULT,
        exit_status(_outcome(errors=(_error(ErrorKind.HARNESS),))): ExitStatus.HARNESS_FAULT,
    }
    assert set(reached) == set(ExitStatus), f"unreached: {set(ExitStatus) - set(reached)}"
    assert all(got is expected for got, expected in reached.items()), reached


def test_the_dry_run_reaches_the_same_ladder_and_not_a_rung_of_its_own() -> None:
    # A dry run decides nothing, so it has no verdict to have got wrong and leaves with the rung
    # that says nothing went wrong — which is why the first rung is glossed that way rather than as
    # "every case passed", a sentence that would be told to a reader who solved nothing. The faults
    # it can meet are the same faults and rank the same way.
    assert exit_status(PlanOutcome(plans=(), errors=(), hygiene=())) is ExitStatus.OK
    assert exit_status(PlanOutcome(plans=(), errors=(_error(ErrorKind.PROGRAM),), hygiene=())) is (
        ExitStatus.USER_FAULT
    )
    assert exit_status(PlanOutcome(plans=(), errors=(_error(ErrorKind.HARNESS),), hygiene=())) is (
        ExitStatus.HARNESS_FAULT
    )


def test_the_status_is_a_function_of_the_outcome_and_nothing_else() -> None:
    # A consumer holding only the report has to be able to say what the process returned, and an
    # embedder that never parsed a command line has no flag to supply. Taking the strictness dial
    # here as well as at the record would put the same decision in two places, where the same run
    # could be read two ways depending on which was consulted.
    (parameter,) = signature(exit_status).parameters.values()
    assert parameter.name == "outcome"
