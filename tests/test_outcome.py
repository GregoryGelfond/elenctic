"""Every discovered case has exactly one home, and the summary is a projection of the registers.

A count computed by subtraction cannot say where a missing case went. These pin the partition and
the conservation law that follows from it.
"""

import json
from dataclasses import fields
from enum import Enum
from pathlib import Path

import pytest
from hypothesis import given, strategies as st
from jsonschema import Draft202012Validator

from elenctic.checks import CheckReport
from elenctic.discovery import Case, DiscoveryError, SolverUnavailableError
from elenctic.expectation import ContractError, Unsat
from elenctic.harness import case_verdict
from elenctic.json_report import dumps, schema_text
from elenctic.outcome import (
    CaseOutcome,
    ErrorKind,
    ErrorRecord,
    Grade,
    HygieneKind,
    HygieneRecord,
    Invocation,
    RunOutcome,
    Scope,
    error_kind,
    is_duration,
    summary,
)
from elenctic.program import ProgramError
from elenctic.registry import SOLVERS
from elenctic.result import Conclusion, HarnessError, SeamError, Verdict
from elenctic.run import RoutingError


def _a_case() -> Case:
    return Case(Path("a.lp"), "clingo", Unsat(expect_line=1), frozenset())


# Every duration the published description refuses. Zero and the negatives are not lengths of time;
# the last three have no JSON form at all, which is why a document carrying one could not be read
# by the consumer it was written for. One list, used both against the record and against the
# description, so the two are shown to refuse the same values rather than each refusing its own.
_NOT_A_DURATION = (0.0, -1.0, -0.5, float("inf"), float("-inf"), float("nan"))


@pytest.mark.parametrize("seconds", _NOT_A_DURATION)
def test_an_invocation_refuses_a_budget_that_is_not_a_length_of_time(seconds: float) -> None:
    with pytest.raises(ValueError, match="budget"):
        Invocation(target=Path("corpus"), strict=False, budget=seconds, deadline=None)


@pytest.mark.parametrize("seconds", _NOT_A_DURATION)
def test_an_invocation_refuses_a_deadline_that_is_not_a_length_of_time(seconds: float) -> None:
    with pytest.raises(ValueError, match="deadline"):
        Invocation(target=Path("corpus"), strict=False, budget=30.0, deadline=seconds)


def test_an_invocation_refuses_a_budget_that_is_absent() -> None:
    # The two durations differ in exactly one way and this is it: a run with no deadline leaves the
    # flag off, while there is no way to ask for no per-solve budget at all. So absence is a value
    # for one and not for the other, and a guard treating them alike lets a null into the field the
    # published description types as a number — the very shape the guard exists to prevent.
    with pytest.raises(ValueError, match="budget"):
        Invocation(target=Path("corpus"), strict=False, budget=None, deadline=None)  # type: ignore[arg-type]


def test_an_invocation_with_no_deadline_is_the_ordinary_one() -> None:
    # The absent deadline is the default and must not be caught by the guard: refusing it would
    # make the commonest invocation the unrepresentable one.
    asked = Invocation(target=Path("corpus"), strict=False, budget=30.0, deadline=None)
    assert asked.deadline is None


@pytest.mark.parametrize("seconds", _NOT_A_DURATION)
@pytest.mark.parametrize("field", ["budget", "deadline"])
def test_the_named_durations_the_record_refuses_are_refused_by_the_description(
    field: str, seconds: float
) -> None:
    # The readable statement of the four named cases. The general one is the property below, which
    # is what actually holds the seam; this is here because a table a person can read is worth
    # keeping beside a property a person cannot.
    invocation = {"target": "corpus", "strict": False, "budget": 30.0, "deadline": None}
    invocation[field] = seconds
    assert not _the_description_can_carry(field, seconds), (
        f"the description accepts {field}={seconds}, which the record refuses"
    )


@given(st.floats())
def test_the_record_and_the_description_agree_about_every_duration(seconds: float) -> None:
    # The invariant is stated twice — here, and in the description elenctic publishes for the
    # document this record is written into — and a rule written twice is how two of them come to
    # disagree. Asserted as a biconditional over the whole domain rather than in one direction over
    # six chosen values, because each direction has its own failure and only one of them is the one
    # a six-row table was ever going to find.
    #
    # Record accepts, description refuses: a document produced without complaint that fails
    # elenctic's own published account of it. That is the direction a ceiling added to the
    # description would open, and it is the direction the table cannot see, because the table is
    # built from values the record already refuses.
    #
    # Record refuses, description accepts: a duration a caller may legitimately ask for and cannot,
    # which is a fabricated constraint with nothing to justify it.
    assert is_duration(seconds) == _the_description_can_carry("budget", seconds)


def _the_description_can_carry(field: str, seconds: float) -> bool:
    """Whether elenctic's published description of its output admits ``seconds`` in ``field``.

    Two seams, not one, and the second is why this is a function rather than a validator call. A
    range constraint cannot reach an infinity or a NaN because JSON has no form for either, so the
    encoder is what refuses those — and it is asked here through ``dumps``, the encoder the package
    actually writes documents with, rather than through a second call to the standard library
    configured the same way by hand.
    """
    invocation: dict[str, object] = {
        "target": "corpus",
        "strict": False,
        "budget": 30.0,
        "deadline": None,
    }
    invocation[field] = seconds
    try:
        dumps(invocation)
    except ValueError:
        return False
    definition = json.loads(schema_text())["$defs"]["invocation"]
    return Draft202012Validator(definition).is_valid(invocation)


def _a_report(verdict: Verdict) -> CheckReport:
    return CheckReport(
        verdict=verdict,
        label="@expect unsat",
        message="m",
        subject="",
        line=1,
        conclusion=Conclusion.EXHAUSTED,
    )


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ContractError("x"), ErrorKind.CONTRACT),
        (DiscoveryError("x"), ErrorKind.DISCOVERY),
        (ProgramError("x"), ErrorKind.PROGRAM),
        (HarnessError("x"), ErrorKind.HARNESS),
        (SeamError("x"), ErrorKind.HARNESS),
        (RoutingError("x"), ErrorKind.HARNESS),
    ],
)
def test_each_root_maps_to_its_own_locus(exc: Exception, kind: ErrorKind) -> None:
    assert error_kind(exc) is kind


def test_a_declared_solver_this_environment_lacks_is_an_environment_fault() -> None:
    # The one place the ordering of the ladder is load-bearing, and the one exception class that
    # serves two loci: it is a DiscoveryError by inheritance, and the corpus walk never met it —
    # the declared solver is checked per case at run time. Filed where the fault is.
    #
    # This test asserted `DISCOVERY` until the locus vocabulary gained `ENVIRONMENT`, at which point
    # it was a green test defending a disagreement between two published surfaces: `run_corpus`
    # filed the same condition as `environment` while this said `discovery`.
    assert error_kind(SolverUnavailableError("no clingcon")) is ErrorKind.ENVIRONMENT


def test_an_unrecognised_exception_is_re_raised_never_costumed() -> None:
    # An error family the taxonomy does not know is not silently filed under one it does. Matched
    # on the message that was handed in, which is the whole claim: what comes back out is the
    # original exception and not one this package built to stand in for it.
    with pytest.raises(ValueError, match="not an elenctic error family"):
        error_kind(ValueError("not an elenctic error family"))


def test_a_program_error_is_not_a_harness_error() -> None:
    # The two are disjoint roots: a broken program under test is not evidence of a broken harness.
    assert not isinstance(ProgramError("x"), HarnessError)
    assert not isinstance(HarnessError("x"), ProgramError)


def test_only_a_harness_fault_is_elenctic_s_to_fix() -> None:
    # The closed half of the split the exit status reads: everything that is not a harness fault is
    # the user's, so a locus added later never silently changes what a status means.
    assert ErrorKind.HARNESS.is_elenctic_bug
    assert not any(kind.is_elenctic_bug for kind in ErrorKind if kind is not ErrorKind.HARNESS)


@pytest.mark.parametrize(
    ("vocabulary", "wire"),
    [
        (
            ErrorKind,
            {
                "CONTRACT": "contract",
                "DISCOVERY": "discovery",
                "PROGRAM": "program",
                "DEADLINE": "deadline",
                "RESOURCE": "resource",
                "ENVIRONMENT": "environment",
                "HARNESS": "harness",
            },
        ),
        (Scope, {"CORPUS": "corpus", "CASE": "case"}),
        (Grade, {"SILENT": "silent", "WARNING": "warning", "ERROR": "error"}),
        (
            HygieneKind,
            {"ORPHAN_LIBRARY": "orphan_library", "UNDECLARED_SOLVER": "undeclared_solver"},
        ),
    ],
)
def test_each_vocabulary_spells_its_members_as_a_reader_outside_will_meet_them(
    vocabulary: type[Enum], wire: dict[str, str]
) -> None:
    # These strings leave the package: they are what a report says and what something reading one
    # switches on. A member's spelling is therefore not an implementation detail that may be tidied
    # — changing one breaks a reader that was written against it, and adding one silently hands a
    # reader a value it has no branch for. Written out in full rather than derived, so both are a
    # deliberate edit here.
    assert {member.name: member.value for member in vocabulary} == wire


def test_the_strictness_dial_grades_every_observation_an_error() -> None:
    # What strictness asks for, and the whole of it: corpus health becomes something to fix rather
    # than something to notice, whatever footing an observation has by default.
    assert all(kind.grade_under(strict=True) is Grade.ERROR for kind in HygieneKind)


def test_the_two_observations_have_different_footing_by_default() -> None:
    # They are not the same news. A library nothing includes is a real smell — a forgotten case or
    # dead code — so it is said once. Relying on the stated default solver is legitimate, so saying
    # it unasked would nag about the expected case, and a report a reader learns to skip is worse
    # than one that was never made.
    assert HygieneKind.ORPHAN_LIBRARY.grade_under(strict=False) is Grade.WARNING
    assert HygieneKind.UNDECLARED_SOLVER.grade_under(strict=False) is Grade.SILENT


def test_the_summary_is_a_projection_of_the_registers() -> None:
    outcome = RunOutcome(
        cases=(),
        errors=(
            ErrorRecord(
                kind=ErrorKind.PROGRAM,
                scope=Scope.CASE,
                source=Path("a.lp"),
                message="will not ground",
            ),
            ErrorRecord(
                kind=ErrorKind.DISCOVERY, scope=Scope.CORPUS, source=None, message="no solver"
            ),
        ),
        hygiene=(
            HygieneRecord(
                kind=HygieneKind.ORPHAN_LIBRARY,
                grade=Grade.WARNING,
                source=Path("lib.lp"),
                message="unused",
            ),
        ),
    )
    counts = summary(outcome)
    assert counts["errors"] == 2
    assert counts["hygiene"] == 1
    # total counts the discovered cases: the ones with a verdict plus the ones that could not be run
    assert counts["total"] == counts["passed"] + counts["failed"] + counts["undecided"] + 1


def test_a_corpus_scoped_error_is_not_counted_as_a_case() -> None:
    # A fault that belongs to no single file did not cost a case its verdict, so counting it as one
    # would report a corpus of more cases than were ever discovered.
    outcome = RunOutcome(
        cases=(),
        errors=(
            ErrorRecord(
                kind=ErrorKind.DISCOVERY, scope=Scope.CORPUS, source=None, message="no solver"
            ),
        ),
        hygiene=(),
    )
    assert summary(outcome)["total"] == 0


def test_an_error_record_always_carries_a_message() -> None:
    with pytest.raises(ValueError, match="an error record carries the reason"):
        ErrorRecord(kind=ErrorKind.PROGRAM, scope=Scope.CASE, source=Path("a.lp"), message="")


def test_a_case_outcome_carries_the_reports_its_verdict_was_folded_from() -> None:
    # A case that checked nothing has not passed; it has not been tested. The fold over an empty set
    # meets neither FAIL nor UNDECIDED and so answers PASS, which would let a run report a clean
    # corpus it never examined — the vacuous pass this codebase refuses at every other boundary.
    with pytest.raises(ValueError, match="carries the reports its verdict was folded from"):
        CaseOutcome(case=_a_case(), reports=())


def test_a_case_outcome_never_disagrees_with_the_fold_it_reports() -> None:
    # The verdict is derived, not stored, and this is what says so: a stored one could drift from
    # the reports beside it, and a derived one that did not call the fold would be a second, silent
    # definition of what a case verdict is.
    for verdict in Verdict:
        reports = (_a_report(verdict), _a_report(Verdict.PASS))
        assert CaseOutcome(case=_a_case(), reports=reports).verdict is case_verdict(reports)


@pytest.mark.parametrize(
    "record", [CaseOutcome, CheckReport, ErrorRecord, HygieneRecord, RunOutcome]
)
def test_every_record_a_consumer_meets_is_built_by_name(record: type) -> None:
    # The run's output identifies a field by its name, so the records behind it do too. Position
    # would be a second identity for the same data — one that a field inserted later re-means at
    # every call site, without changing a single type. It also closes the transposition the report
    # invites on its own: its message and subject are neighbouring strings, so a swapped pair
    # type-checks clean and renders a plausible row against the wrong claim.
    by_position = [field.name for field in fields(record) if not field.kw_only]
    assert not by_position, f"{record.__name__} still accepts {by_position} by position"


# --- the conservation law, over any outcome the registers admit ---

_TEXT = st.text(min_size=1, max_size=20)
_PATHS = st.builds(Path, st.text(alphabet="abcdefg", min_size=1, max_size=8))

_ERRORS = st.builds(
    ErrorRecord,
    kind=st.sampled_from(ErrorKind),
    scope=st.sampled_from(Scope),
    source=st.none() | _PATHS,
    message=_TEXT,
)
_HYGIENE = st.builds(
    HygieneRecord,
    kind=st.sampled_from(HygieneKind),
    grade=st.sampled_from(Grade),
    source=_PATHS,
    message=_TEXT,
)
# conclusion is drawn from the enum alone: every solve reports how its search ended, so there is no
# absent value for a report to carry.
_REPORTS = st.builds(
    CheckReport,
    verdict=st.sampled_from(Verdict),
    label=st.just("@expect sat"),
    message=_TEXT,
    subject=st.just(""),
    line=st.integers(min_value=1, max_value=500),
    conclusion=st.sampled_from(Conclusion),
)
_CASES = st.builds(
    CaseOutcome,
    case=st.builds(
        Case,
        path=_PATHS,
        solver=st.sampled_from(sorted(SOLVERS)),
        expectation=st.just(Unsat(expect_line=1)),
        shown=st.just(frozenset()),
    ),
    reports=st.lists(_REPORTS, min_size=1, max_size=4).map(tuple),
)


@given(
    cases=st.lists(_CASES, max_size=5).map(tuple),
    errors=st.lists(_ERRORS, max_size=5).map(tuple),
    hygiene=st.lists(_HYGIENE, max_size=3).map(tuple),
)
def test_the_conservation_law_holds_for_any_outcome(
    cases: tuple[CaseOutcome, ...],
    errors: tuple[ErrorRecord, ...],
    hygiene: tuple[HygieneRecord, ...],
) -> None:
    # Every discovered case is accounted for: it produced a verdict, or it is a case-scoped error
    # saying why it could not. A count that does not close is a case that went missing.
    outcome = RunOutcome(cases=cases, errors=errors, hygiene=hygiene)
    counts = summary(outcome)
    unrun = sum(1 for error in outcome.errors if error.scope is Scope.CASE)
    assert counts["total"] == counts["passed"] + counts["failed"] + counts["undecided"] + unrun
