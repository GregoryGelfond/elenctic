"""The run-level registers: what a whole run of a corpus produced.

A run produces three kinds of thing, and keeping them apart is the point of the module. A
**verdict** is a judgment about a program under test. An **error** is the claim that no verdict
could be produced — never about the program's answer-set behaviour, and so never a verdict. A
**hygiene** record is an observation about the corpus's health, which is neither.

The three are disjoint by construction rather than by discipline: a :class:`CaseOutcome` has no
error kind and an :class:`ErrorRecord` has no verdict, so an error costumed as a verdict is a type
error rather than a mistake to be caught in review. What the types cannot enforce is that every
discovered case *reaches* one of the lists; that is the case-atomicity invariant, and
``tests/test_cli_records.py::test_every_discovered_case_reaches_exactly_one_register`` is its
mechanised check.

The :class:`Invocation` a run was given lives here too. It is not something a run produced, but it
is one of the shapes a consumer decoding the output meets, and a shape with two homes is a shape
that drifts.

Every record here is built by keyword. These are the shapes a consumer decoding the run's output
meets, and that output identifies a field by its name; constructing them by position would give the
same data a second identity, one that a field inserted later silently re-means. It also closes the
gap that motivated the rule: a record whose neighbouring fields have the same type accepts them
transposed, type-checks clean, and reads as a plausible row.
"""

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from elenctic.checks import CheckReport
from elenctic.discovery import Case, DiscoveryError
from elenctic.expectation import ContractError
from elenctic.harness import case_verdict
from elenctic.program import ProgramError
from elenctic.result import HarnessError, Verdict
from elenctic.run import Run

__all__ = [
    "CaseOutcome",
    "CasePlan",
    "ErrorKind",
    "ErrorRecord",
    "Grade",
    "HygieneKind",
    "HygieneRecord",
    "Invocation",
    "Outcome",
    "PlanOutcome",
    "RunOutcome",
    "Scope",
    "error_kind",
    "is_duration",
    "summary",
]


class ErrorKind(Enum):
    """Where the fault lies — which part of the system a reader has to look at.

    A growable vocabulary: a consumer that meets a value it does not know treats it as one it
    cannot act on specifically, which is why the actionability split below is the closed one.
    Growable is what lets a locus be named for what it is: neither a deadline the run passed nor a
    resource it ran out of is a malformed program, and filing either as one would tell an author
    their encoding is broken when it is not.

    The values name loci, not exception classes. Two of them are not this package's exceptions at
    all — a deadline is a clock the run passed and raises nothing, and a resource running out
    arrives as a built-in — so a vocabulary of class names would promise an import that does not
    exist for a third of it.
    """

    CONTRACT = "contract"
    DISCOVERY = "discovery"
    PROGRAM = "program"
    DEADLINE = "deadline"
    RESOURCE = "resource"
    HARNESS = "harness"

    @property
    def is_elenctic_bug(self) -> bool:
        """Whether a reader should report this rather than fix it — the closed, two-valued split
        the exit status reads. Everything that is not a harness fault is the user's to fix,
        including any value added later, so a new locus never silently changes what an exit status
        means."""
        return self is ErrorKind.HARNESS


class Scope(Enum):
    """What the error killed: one case, or the whole corpus."""

    CORPUS = "corpus"
    CASE = "case"


class Grade(Enum):
    """How loudly a run graded a corpus-health observation — the closed vocabulary every reading of
    that grade shares.

    Grading is a policy and the policy is the caller's: the same observation is a gate's error and
    an author's aside. Applying it where the observation is recorded leaves one field deciding what
    is printed and what fails the run, so those two cannot come to disagree — and a consumer is told
    the grade rather than made to re-derive it from a table of kinds it would have to keep in step
    with this one.

    A grade rather than a severity, and the difference is not a preference. This language keeps the
    two apart: its severity ladder runs from debug to critical and has no member meaning *do not
    show this*, because suppression there is a filter and not a level. A reader who meets a field
    called a severity will map it onto a scale of severities, and the first of these three has no
    place on such a scale — so the obvious reading of the field would work for two values and fail
    quietly on the third, drawing attention to the one observation whose grade exists in order not
    to draw any. Naming it for what it is also settles how closed it is: a severity invites a fourth
    member, since an informational one is easy to imagine, while recorded, reported and fatal are
    the whole of what a dial can say.
    """

    SILENT = "silent"
    """Observed and recorded, but not reported: what it observes is legitimate, so saying it would
    nag about the expected case rather than tell anyone anything."""
    WARNING = "warning"
    """Reported, and it changes nothing about whether the run succeeded."""
    ERROR = "error"
    """Reported, and the run fails on it."""


class HygieneKind(Enum):
    """A corpus-health observation, graded by the run that made it and promotable to an error.

    The default grade differs by kind and is decided in one place below, so "warned by default" is
    true of one of these and not of the other.
    """

    ORPHAN_LIBRARY = "orphan_library"
    UNDECLARED_SOLVER = "undeclared_solver"

    def grade_under(self, *, strict: bool) -> Grade:
        """How loudly this observation is graded under the strictness dial — the one place the
        default footing of each kind is decided.

        Named apart from the graded record's own ``grade`` so that the two are not one word for a
        value and a way of computing one; reached from a record, ``kind.grade_under(...)`` asks a
        question and ``grade`` is the answer this run already gave.

        Strictness grades everything an error; that is the whole of what it asks for. Without it the
        two differ, because they are not the same news. A library nothing includes is a real smell —
        a forgotten case, or dead code — and worth saying once. Relying on the stated ``clingo``
        default is legitimate, so saying it unasked would nag about the expected case: the
        ``mypy --strict`` and ``pytest --strict-markers`` posture, where a default is fine until you
        opt into explicitness.
        """
        if strict:
            return Grade.ERROR
        match self:
            case HygieneKind.ORPHAN_LIBRARY:
                return Grade.WARNING
            case HygieneKind.UNDECLARED_SOLVER:
                return Grade.SILENT


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseOutcome:
    """One case that produced a verdict, with the reports it was folded from.

    The verdict is derived rather than stored, so a report set and the verdict beside it cannot
    disagree.
    """

    case: Case
    reports: tuple[CheckReport, ...]

    def __post_init__(self) -> None:
        if not self.reports:
            raise ValueError(
                "a case outcome carries the reports its verdict was folded from, and this one "
                "carries none. The fold over no reports meets neither FAIL nor UNDECIDED and so "
                "answers PASS — a case reported as passing that was never checked"
            )

    @property
    def verdict(self) -> Verdict:
        return case_verdict(self.reports)


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorRecord:
    """One reason a verdict could not be produced. ``source`` is the file it belongs to, or ``None``
    for a corpus-level fault that belongs to no single file. The message is required: an error whose
    reason was dropped is not a report."""

    kind: ErrorKind
    scope: Scope
    source: Path | None
    message: str

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("an error record carries the reason it was raised")


@dataclass(frozen=True, slots=True, kw_only=True)
class HygieneRecord:
    """One corpus-health observation, against the file it concerns, at the footing this run put it
    on.

    ``grade`` is the observation as graded, not the observation itself: ``kind`` still says what
    was seen, so a consumer that disagrees with this run's grading can apply its own policy to the
    same fact. What it must not have to do is reconstruct *this* run's policy from the kind, which
    is the only way it could learn why the process exited as it did.
    """

    kind: HygieneKind
    grade: Grade
    source: Path
    message: str


def is_duration(seconds: float | None) -> bool:
    """Whether ``seconds`` is a length of time elenctic can be asked for: positive and finite.

    Positive because zero and the negatives are not lengths of time — a zero budget asks for a
    solve that has already run out, and there is no reading at all for a negative one. Finite
    because an infinity and a NaN have no JSON form, so a report carrying either could not be read
    by the consumer it was written for. Total over absence as well: ``None`` is not a duration,
    because absence is not a length of time. Answering that rather than raising is what lets a
    caller ask the question of a value they have not checked, which is the only way to ask it that
    is worth anything.

    One predicate rather than one per site. The rule holds in four places — this record, the
    command line's refusal, the range constraint in the description elenctic publishes for its
    output, and the encoder that writes the document, which is what refuses an infinity where a
    range constraint cannot reach one. A rule written out four times is how two of them come to
    disagree; the *sentences* stay separate, because the reader who typed a flag and the reader who
    called a constructor need different remedies, and only the question is shared.
    """
    return seconds is not None and math.isfinite(seconds) and seconds > 0


def _not_a_duration(field: str, seconds: float | None) -> str:
    """What to say to a caller who built a record naming a duration that is not one.

    Addressed to whoever called the constructor, and so different from what the command line says
    to whoever typed a flag: there is no flag to leave off here, and the reason the value cannot
    stand is that a report of this run would not answer to the account elenctic publishes for it.
    """
    given = "no budget at all" if seconds is None else str(seconds)
    return (
        f"{field} is a length of time in seconds, so it is positive and finite, and this "
        f"invocation was built with {given}. An invocation says what a run was asked to do, and "
        f"elenctic's published description of its output states {field} as a positive finite "
        f"number — so a report of this run would contradict the account it is published under."
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Invocation:
    """What a run was asked to do: the settled form of a command line, and the provenance a stored
    report needs for its exit status to be reconstructed by a reader who has only the report.

    It is what the runner takes, so a mode that produces no run has no way to be expressed here —
    a dry run is not an invocation with a flag set but a different thing to do, and keeping it out
    of this type is what makes running total rather than something that has to refuse.

    Both durations are checked here, which is the only place a caller who never parsed a command
    line passes through. The published description of the output states them as properties of the
    *document* — a budget is "always a positive finite number" — so a record that accepted anything
    else would be a report contradicting the account it is published under, produced without
    complaint. The command line refuses first and in its own words, so this is the backstop for the
    library path rather than the diagnostic anybody typing a flag will meet.
    """

    target: Path
    strict: bool
    budget: float
    deadline: float | None

    def __post_init__(self) -> None:
        # The two are checked apart rather than in one loop, because they differ in exactly one way
        # and it is this: a run with no deadline leaves the flag off, while there is no way to ask
        # for no per-solve budget at all. So absence is a value for one and not for the other, and
        # a guard that treated them alike would let a null into the field the published description
        # types as a number — the shape this guard exists to prevent, surviving in the one place it
        # was not looked for.
        if not is_duration(self.budget):
            raise ValueError(_not_a_duration("budget", self.budget))
        if self.deadline is not None and not is_duration(self.deadline):
            raise ValueError(_not_a_duration("deadline", self.deadline))


@dataclass(frozen=True, slots=True, kw_only=True)
class CasePlan:
    """One case whose run plan could be derived, with the runs it derived to.

    What a dry run produces where a real one produces a verdict: the plan is the answer to the
    question the dry run asks, so it is carried rather than only narrated.
    """

    case: Case
    runs: tuple[Run, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RunOutcome:
    """Everything one run produced, partitioned into the three registers."""

    cases: tuple[CaseOutcome, ...]
    errors: tuple[ErrorRecord, ...]
    hygiene: tuple[HygieneRecord, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanOutcome:
    """Everything one dry run produced, partitioned the same way.

    A dry run decides nothing, so where a run has verdicts this has the plans they would have come
    from. The other two registers are the same registers and mean the same things — a plan that
    could not be built is an error exactly as a case that could not be solved is, and both are
    elenctic's own fault when the reason is a misroute.
    """

    plans: tuple[CasePlan, ...]
    errors: tuple[ErrorRecord, ...]
    hygiene: tuple[HygieneRecord, ...]


type Outcome = RunOutcome | PlanOutcome
"""What an invocation produced, whichever mode it was asked for.

The two share the registers that say what went wrong and what was observed, and differ only in what
they made: verdicts, or the plans behind them. Reading a status is therefore one function over both
rather than a ladder written twice, which is how the two modes came to disagree once already."""


def error_kind(exc: Exception) -> ErrorKind:
    """Where an exception says the fault lies.

    An ordered test against disjoint roots, so a subclass resolves to the root it belongs to and no
    root can absorb another. An exception from outside the taxonomy is re-raised rather than filed
    under the nearest match: reporting an unknown fault as a known one is how a defect gets
    described as something the user could have prevented.
    """
    match exc:
        case ContractError():
            return ErrorKind.CONTRACT
        case DiscoveryError():
            return ErrorKind.DISCOVERY
        case ProgramError():
            return ErrorKind.PROGRAM
        case HarnessError():
            return ErrorKind.HARNESS
        case _:
            raise exc


def summary(outcome: RunOutcome) -> dict[str, int]:
    """The register counts, computed from the registers and never tallied alongside them.

    ``total`` is the number of cases discovered — those that produced a verdict plus those that
    could not be run — so it never accounts for a case by leaving it out. A corpus-scoped fault is
    counted among the errors but not among the cases, because it cost no single case its verdict.
    """
    verdicts = [case.verdict for case in outcome.cases]
    unrun = sum(1 for error in outcome.errors if error.scope is Scope.CASE)
    return {
        "total": len(outcome.cases) + unrun,
        "passed": sum(1 for verdict in verdicts if verdict is Verdict.PASS),
        "failed": sum(1 for verdict in verdicts if verdict is Verdict.FAIL),
        "undecided": sum(1 for verdict in verdicts if verdict is Verdict.UNDECIDED),
        "errors": len(outcome.errors),
        "hygiene": len(outcome.hygiene),
    }
