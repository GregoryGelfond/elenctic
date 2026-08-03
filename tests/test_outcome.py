"""Every discovered case has exactly one home, and the summary is a projection of the registers.

A count computed by subtraction cannot say where a missing case went. These pin the partition and
the conservation law that follows from it.
"""

from dataclasses import fields
from enum import Enum
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from elenctic.checks import CheckReport
from elenctic.discovery import Case, DiscoveryError, SolverUnavailableError
from elenctic.expectation import ContractError, Unsat
from elenctic.harness import case_verdict
from elenctic.outcome import (
    CaseOutcome,
    ErrorKind,
    ErrorRecord,
    HygieneKind,
    HygieneRecord,
    RunOutcome,
    Scope,
    Severity,
    error_kind,
    summary,
)
from elenctic.program import ProgramError
from elenctic.registry import SOLVERS
from elenctic.result import Conclusion, HarnessError, SeamError, Verdict
from elenctic.run import RoutingError


def _a_case() -> Case:
    return Case(Path("a.lp"), "clingo", Unsat(expect_line=1), frozenset())


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


def test_a_declared_solver_this_environment_lacks_is_a_discovery_fault() -> None:
    # It is deliberately both a DiscoveryError and an ImportError, so either idiom catches it. The
    # ladder must resolve it by the root it belongs to rather than by whichever arm it also fits.
    assert error_kind(SolverUnavailableError("no clingcon")) is ErrorKind.DISCOVERY


def test_an_unrecognised_exception_is_re_raised_never_costumed() -> None:
    # An error family the taxonomy does not know is not silently filed under one it does.
    with pytest.raises(ValueError):
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
                "CONTRACT": "ContractError",
                "DISCOVERY": "DiscoveryError",
                "PROGRAM": "ProgramError",
                "DEADLINE": "DeadlineError",
                "RESOURCE": "ResourceError",
                "HARNESS": "HarnessError",
            },
        ),
        (Scope, {"CORPUS": "corpus", "CASE": "case"}),
        (Severity, {"SILENT": "silent", "WARNING": "warning", "ERROR": "error"}),
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
    assert all(kind.severity_under(strict=True) is Severity.ERROR for kind in HygieneKind)


def test_the_two_observations_have_different_footing_by_default() -> None:
    # They are not the same news. A library nothing includes is a real smell — a forgotten case or
    # dead code — so it is said once. Relying on the stated default solver is legitimate, so saying
    # it unasked would nag about the expected case, and a report a reader learns to skip is worse
    # than one that was never made.
    assert HygieneKind.ORPHAN_LIBRARY.severity_under(strict=False) is Severity.WARNING
    assert HygieneKind.UNDECLARED_SOLVER.severity_under(strict=False) is Severity.SILENT


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
                severity=Severity.WARNING,
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
    with pytest.raises(ValueError):
        ErrorRecord(kind=ErrorKind.PROGRAM, scope=Scope.CASE, source=Path("a.lp"), message="")


def test_a_case_outcome_carries_the_reports_its_verdict_was_folded_from() -> None:
    # A case that checked nothing has not passed; it has not been tested. The fold over an empty set
    # meets neither FAIL nor UNDECIDED and so answers PASS, which would let a run report a clean
    # corpus it never examined — the vacuous pass this codebase refuses at every other boundary.
    with pytest.raises(ValueError):
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
    severity=st.sampled_from(Severity),
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
