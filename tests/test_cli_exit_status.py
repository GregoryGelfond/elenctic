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
from elenctic.cli import exit_status
from elenctic.discovery import Case
from elenctic.expectation import Unsat
from elenctic.outcome import (
    CaseOutcome,
    ErrorKind,
    ErrorRecord,
    Grade,
    HygieneKind,
    HygieneRecord,
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
    assert exit_status(_outcome(cases=(_case(Verdict.PASS), _case(Verdict.PASS)))) == 0


def test_a_corpus_of_no_cases_has_no_case_that_did_not_pass() -> None:
    # Nothing to report is not a failure to report. A target holding no contract-bearing file
    # discovers nothing, and there is no case for the status to be about.
    assert exit_status(_outcome()) == 0


@pytest.mark.parametrize("verdict", [Verdict.FAIL, Verdict.UNDECIDED])
def test_a_case_not_decided_right_is_the_verdict_register(verdict: Verdict) -> None:
    # UNDECIDED shares the status with FAIL rather than with PASS. The two mean different things to
    # a reader — one is a wrong answer, the other no answer — but a caller gating on the status is
    # asking whether the contract was shown to hold, and neither shows it.
    assert exit_status(_outcome(cases=(_case(Verdict.PASS), _case(verdict)))) == 1


def test_a_fault_the_user_can_fix_outranks_a_verdict() -> None:
    # A case that could not be run leaves the run's answer incomplete, so a corpus whose remaining
    # cases all passed must not report the status that says the corpus was checked and is clean.
    outcome = _outcome(cases=(_case(Verdict.PASS),), errors=(_error(ErrorKind.PROGRAM),))
    assert exit_status(outcome) == 2


def test_a_harness_fault_outranks_every_other_signal() -> None:
    # An elenctic bug puts every verdict in the run in doubt, so it is what the status reports.
    outcome = _outcome(
        cases=(_case(Verdict.FAIL),),
        errors=(_error(ErrorKind.PROGRAM), _error(ErrorKind.HARNESS)),
        hygiene=(_observation(Grade.ERROR),),
    )
    assert exit_status(outcome) == 3


def test_a_locus_that_is_not_a_harness_fault_stays_the_user_s_to_fix() -> None:
    # The elenctic-bug side of the split is the closed one, so a locus named for something that is
    # nobody's bug — a deadline the run passed — reports a corpus to attend to, not a bug to file.
    assert exit_status(_outcome(errors=(_error(ErrorKind.DEADLINE),))) == 2


def test_an_observation_graded_an_error_fails_the_run() -> None:
    # Hygiene reaches the status by exactly one route: the grade the run put on the observation.
    outcome = _outcome(cases=(_case(Verdict.PASS),), hygiene=(_observation(Grade.ERROR),))
    assert exit_status(outcome) == 2


@pytest.mark.parametrize("grade", [Grade.WARNING, Grade.SILENT])
def test_an_observation_graded_below_an_error_leaves_the_status_alone(
    grade: Grade,
) -> None:
    # Hygiene is never a verdict, so an observation this run did not grade an error must not reach
    # the status by some other route: a corpus that passes with a warning has passed.
    outcome = _outcome(cases=(_case(Verdict.PASS),), hygiene=(_observation(grade),))
    assert exit_status(outcome) == 0


def test_the_status_is_a_function_of_the_outcome_and_nothing_else() -> None:
    # A consumer holding only the report has to be able to say what the process returned, and an
    # embedder that never parsed a command line has no flag to supply. Taking the strictness dial
    # here as well as at the record would put the same decision in two places, where the same run
    # could be read two ways depending on which was consulted.
    (parameter,) = signature(exit_status).parameters.values()
    assert parameter.name == "outcome"
