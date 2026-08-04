"""Run a whole corpus of ``@``-contracts, or derive the plan a run would follow.

The corpus layer, sitting above the per-case one in ``harness``: which cases exist, what to do with
a file that could not become one, and what the whole run produced. A case is the unit ``harness``
knows about; a corpus is the unit anyone actually runs, and this is where the two meet.

:func:`run_corpus` and :func:`explain_corpus` each take an :class:`~elenctic.outcome.Invocation` and
return everything they produced — verdicts or plans, the reasons some case produced neither, and
what was observed about the corpus's health. Both are **total over their argument**: every
invocation that can be written is one they can carry out, because the modes that produce no run
cannot be expressed as an ``Invocation`` at all. Faults the run anticipates are recorded rather than
raised, which is what the error register is for; what still escapes is what no register anticipated,
and backstopping that belongs to whoever is running this rather than to the run.

This is what ``elenctic.cli`` is built out of. The console entry parses a command line into an
invocation, calls in here, renders what comes back and reads a status off it — so the program is a
derivation of the library rather than the place the library's work is done, and an embedder driving
these directly gets the same values the shipped runner does.
"""

import sys
from pathlib import Path
from time import monotonic
from typing import assert_never

from elenctic.discovery import (
    ORPHAN_LIBRARY,
    UNDECLARED_SOLVER,
    Case,
    Corpus,
    DiscoveryError,
    HygieneReport,
    check_solver_available,
    inspect_corpus,
)
from elenctic.display import legible
from elenctic.expectation import ContractError
from elenctic.harness import render, run_case
from elenctic.outcome import (
    CaseOutcome,
    CasePlan,
    ErrorKind,
    ErrorRecord,
    Grade,
    HygieneKind,
    HygieneRecord,
    Invocation,
    PlanOutcome,
    RunOutcome,
    Scope,
    error_kind,
    summary,
)
from elenctic.program import ProgramError
from elenctic.registry import provides_theory
from elenctic.result import HarnessError, Verdict
from elenctic.run import runs_for

__all__ = ["explain_corpus", "run_corpus"]


# What an allocation failure has to say about the case that met it — shared by the diagnostic the
# reader sees and the record a consumer reads, so those two cannot come to differ. The backstop in
# ``main`` says the same thing about a whole corpus and says it separately, because a frame with no
# case to name cannot claim which one was running. Where the memory went is not knowable from either
# frame: grounding is the usual answer, and a solve holds every model it is shown, so both are named
# rather than the likelier one asserted.
_OUT_OF_MEMORY = (
    "elenctic ran out of memory running this case. Grounding has no size limit available to it, "
    "and a solve holds every model it is shown — reduce what this case grounds or enumerates, or "
    "run the corpus under a memory limit. No verdict was produced for it."
)


def run_corpus(invocation: Invocation) -> RunOutcome:
    """Run the corpus an invocation names, and return everything the run produced.

    The seam the process status is read off and the machine-readable report is built from, so that
    the number a shell sees and the document a consumer stores are two readings of one value and
    cannot come to disagree about the same run. It is also what makes a record observable at all: a
    status carries one closed bit of one, and the diagnostics are written where each fault is met,
    so without this the locus a fault was filed under would be asserted nowhere.

    Total over its argument: every invocation this can be given is one it can run, because the
    modes that produce no run cannot be written as an :class:`Invocation`. Faults the run
    anticipates are recorded rather than raised — that is what the error register is — and what
    still escapes is what no register anticipated, which the console entry backstops.

    It is not silent. The human report is written as the run goes, so a caller wanting standard
    output for something else diverts it first; the returned value does not determine that prose,
    and the prose does not determine the value.

    Named apart from the module ``elenctic.run``, which a package attribute of the same name would
    resolve to instead.
    """
    match _discover(invocation.target):
        case ErrorRecord() as fault:
            return RunOutcome(cases=(), errors=(fault,), hygiene=())
        case Corpus() as corpus:
            unrunnable, hygiene = _record_discovered(corpus, strict=invocation.strict)
            outcome = _run(
                corpus.cases,
                invocation.budget,
                unrunnable=unrunnable,
                hygiene=hygiene,
                deadline=invocation.deadline,
            )
            # The tally is composed here rather than where the cases are solved, so that the run
            # loop hands back a value and every rendering of it is decided in one place.
            print(f"\n{_summary_line(outcome)}")
            _report_hygiene(hygiene)
            return outcome
        case unreachable:
            assert_never(unreachable)


def explain_corpus(invocation: Invocation) -> PlanOutcome:
    """Narrate the run plan this invocation would follow, and return everything the dry run
    produced.

    The sibling of :func:`run_corpus`, and the same shape for the same reason: a dry run decides
    nothing, but it still establishes something about every case it meets — a plan, or the reason
    there is none — and a mode that hands back only a number leaves that unobserved. What it must
    not do is report those plans as verdicts, which is why they are their own register rather than
    an empty one.

    A plan that cannot be built is elenctic's own fault, and surfacing one before any solving is
    the whole purpose of this mode.
    """
    match _discover(invocation.target):
        case ErrorRecord() as fault:
            return PlanOutcome(plans=(), errors=(fault,), hygiene=())
        case Corpus() as corpus:
            unrunnable, hygiene = _record_discovered(corpus, strict=invocation.strict)
            plans, misroutes = _explain(corpus.cases)
            _report_hygiene(hygiene)
            return PlanOutcome(plans=plans, errors=(*unrunnable, *misroutes), hygiene=hygiene)
        case unreachable:
            assert_never(unreachable)


def _discover(target: Path) -> Corpus | ErrorRecord:
    """The corpus a target holds, or — when discovery could not read one — the fault that is the
    whole of what the invocation produced.

    A fault here belongs to no case, because there are none: it is the corpus's. It is handed back
    as a record rather than as an outcome because which outcome holds it is the caller's question,
    and the two modes answer it differently."""
    try:
        return inspect_corpus(target)
    except (DiscoveryError, ContractError, ProgramError) as exc:
        print(f"corpus error: {legible(str(exc))}", file=sys.stderr)
        return _corpus_fault(error_kind(exc), str(exc), source=target if target.is_file() else None)


def _record_discovered(
    corpus: Corpus, *, strict: bool
) -> tuple[tuple[ErrorRecord, ...], tuple[HygieneRecord, ...]]:
    """The contract-bearing files discovery could not use, reported and recorded, together with
    what it observed about the corpus around them — the two things every mode starts from."""
    unrunnable = _unrunnable_records(corpus.unrunnable)
    for record in unrunnable:
        # Discovered but unusable — an unresolvable #include, an undecodable byte, a malformed
        # contract. Reported against the file it belongs to, in the same register as a case the
        # runner could not run, so one bad file never costs the corpus its other results.
        # Every discovery diagnostic carries its own provenance, so the path is not repeated here.
        print(f"CASE ERROR — {legible(record.message)}", file=sys.stderr)
    return unrunnable, _hygiene_records(corpus.hygiene, strict=strict)


def _corpus_fault(kind: ErrorKind, message: str, *, source: Path | None = None) -> ErrorRecord:
    """One fault belonging to no single case, and therefore to the corpus: nothing was discovered,
    or the frame that met the fault had no case to name.

    ``source`` is the file when exactly one was involved — a target named on the command line is
    the only file the fault can belong to, while a directory names no one file and the diagnostic's
    own provenance is where the reader looks."""
    return ErrorRecord(kind=kind, scope=Scope.CORPUS, source=source, message=message)


def _hygiene_records(hygiene: HygieneReport, *, strict: bool) -> tuple[HygieneRecord, ...]:
    """Every corpus-health observation, whatever the strictness dial says about reporting it, each
    carrying the footing that dial put it on.

    The dial decides what is *printed* and what fails the run; it does not decide what was
    *observed*. A consumer reading the run's output is owed the observations themselves and applies
    its own policy to them, which it cannot do if the run has already dropped the ones this
    invocation chose to stay silent about. Grading them here is what leaves one collection to read
    for both — and one place where the dial is consulted at all."""
    return (
        *(
            HygieneRecord(
                kind=HygieneKind.ORPHAN_LIBRARY,
                grade=HygieneKind.ORPHAN_LIBRARY.grade_under(strict=strict),
                source=path,
                message=ORPHAN_LIBRARY,
            )
            for path in hygiene.orphan_libraries
        ),
        *(
            HygieneRecord(
                kind=HygieneKind.UNDECLARED_SOLVER,
                grade=HygieneKind.UNDECLARED_SOLVER.grade_under(strict=strict),
                source=path,
                message=UNDECLARED_SOLVER,
            )
            for path in hygiene.undeclared_solvers
        ),
    )


def _unrunnable_records(unrunnable: tuple[tuple[Path, Exception], ...]) -> tuple[ErrorRecord, ...]:
    """The contract-bearing files discovery could not turn into cases, in the same register as a
    case the runner could not run: both are a file that will produce no verdict, and the reader
    does not care which side of discovery it failed on."""
    return tuple(
        ErrorRecord(kind=error_kind(fault), scope=Scope.CASE, source=path, message=str(fault))
        for path, fault in unrunnable
    )


def _report_hygiene(hygiene: tuple[HygieneRecord, ...]) -> None:
    """Report corpus hygiene as an aggregated end-of-run stderr summary, at the footing each
    observation was graded on. Orphan libraries warn by default; under ``--strict`` they — plus the
    otherwise-silent undeclared solvers — become errors that fail the run (the CI gate). Hygiene is
    never a verdict; what a reported observation does to the exit status is decided with the rest of
    it.

    Rendered from the records themselves — their text as well as their grade — so what is printed
    and what fails the run cannot disagree about a single observation. Every kind is walked and the
    match over them is exhaustive, because a kind that reached the grading but not the rendering
    would fail a run under ``--strict`` and print nothing to say why."""
    reported = [record for record in hygiene if record.grade is not Grade.SILENT]
    lines: list[str] = []
    for kind in HygieneKind:
        observed = [record for record in reported if record.kind is kind]
        if not observed:
            continue
        match kind:
            case HygieneKind.ORPHAN_LIBRARY:
                lines.extend(
                    f"orphan library: {legible(str(record.source))} {record.message}"
                    for record in observed
                )
            case HygieneKind.UNDECLARED_SOLVER:
                # Aggregated: a corpus that never declares a solver would otherwise report every
                # case, and the observation is about the corpus's habit rather than about any one
                # file. The sentence is stated once because it is one observation, and every record
                # of a kind carries the same one.
                listed = ", ".join(legible(str(record.source)) for record in observed)
                lines.append(
                    f"undeclared solver: {len(observed)} case(s) {observed[0].message}: {listed}"
                )
            case _:
                assert_never(kind)
    if not lines:
        return
    failing = any(record.grade is Grade.ERROR for record in reported)
    print(f"\nhygiene {'errors (--strict)' if failing else 'warnings'}:", file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)


def _explain(
    cases: tuple[Case, ...],
) -> tuple[tuple[CasePlan, ...], tuple[ErrorRecord, ...]]:
    """Narrate the derived run plan per case without solving (the dry-run): each run's mode and the
    projection decision (which the contract's reads induce), and each check with the fields it
    reads.

    Every case leaves here in exactly one register — the plan it derived to, or the reason it
    derived to none — which is the same accounting a real run keeps, for the same reason: a mode
    that narrates a plan and then hands back nothing but a number has established something about
    each case that nothing can afterwards check. A plan that cannot be built is a harness fault,
    and this is the mode whose whole purpose is to surface one before any solving."""
    plans: list[CasePlan] = []
    misroutes: list[ErrorRecord] = []
    for case in cases:
        print(f"{legible(str(case.contract_source))} [{case.solver}]")
        # The @note prose leads the narration — the author's what/why above the harness's how.
        # Both Sat and Unsat carry notes; documentation, never a verdict.
        for note in case.expectation.notes:
            print(f"    note: {legible(note)}")
        try:
            derived = runs_for(case.expectation, provides_theory(case.solver))
        except HarnessError as exc:
            # Named, though the narration above it on standard output already names the case: these
            # go to standard error, and a reader who has only that stream is owed the file.
            print(
                f"    HARNESS ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            misroutes.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
            continue
        for plan in derived:
            projects = "yes" if plan.projects_to_shown else "no"
            print(f"    {plan.mode.name} (projects: {projects}):")
            for check in plan.checks:
                # subject discerns the repeatable @query tag before any solve.
                name = f"{check.label} ({check.subject})" if check.subject else check.label
                reads = ", ".join(sorted(field.value for field in check.reads)) or "—"
                print(f"        {name} — reads {{{reads}}}")
        plans.append(CasePlan(case=case, runs=tuple(derived)))
    return tuple(plans), tuple(misroutes)


def _run(
    cases: tuple[Case, ...],
    budget: float,
    *,
    unrunnable: tuple[ErrorRecord, ...],
    hygiene: tuple[HygieneRecord, ...],
    deadline: float | None = None,
) -> RunOutcome:
    """Validate every plan up front, then solve + check each case; render non-PASS outcomes.

    Every discovered case leaves here in exactly one register: a verdict it produced, or the reason
    it produced none. Nothing is counted by subtracting one register from another, so there is no
    arrangement in which a case is accounted for by being left out.

    ``unrunnable`` carries the contract-bearing files discovery could not turn into cases, and
    ``hygiene`` what discovery observed about the corpus around them. Both are passed through rather
    than recomputed: they were established before the run began, and the outcome is the whole of
    what the invocation produced. Neither has a default, because a caller who omitted one would get
    an outcome that accounts for fewer files than were discovered — which is the one thing the
    registers exist to make impossible.

    ``deadline`` bounds the run rather than a solve. ``budget`` bounds one solve, and a case can
    route to several, so a corpus costs a product of three numbers of which only one was bounded.
    It is off unless asked for: unlike a model cap there is no run duration obviously beyond
    legitimate use, and a default low enough to bound a hostile corpus would turn a large honest
    one into cases that could not be run — a worse failure than the one it prevents."""
    valid, misroutes = _validate_plans(cases)
    errors = [*unrunnable, *misroutes]
    outcomes: list[CaseOutcome] = []
    started = monotonic()
    for reached, case in enumerate(valid):
        if deadline is not None and monotonic() - started >= deadline:
            # Stop dispatching, and account for every case that will not run. Reporting them one
            # by one would bury the reason under its own consequences, so the reader is told once
            # while each case still gets its own record — a count cannot say which case is missing.
            unreached = valid[reached:]
            print(
                f"DEADLINE — the run passed its {deadline}s deadline; "
                f"{len(unreached)} case(s) were not reached",
                file=sys.stderr,
            )
            errors.extend(
                ErrorRecord(
                    kind=ErrorKind.DEADLINE,
                    scope=Scope.CASE,
                    source=unreached_case.contract_source,
                    message=f"the run passed its {deadline}s deadline before reaching this case",
                )
                for unreached_case in unreached
            )
            break
        try:
            # The declared solver is checked here, per case, so an absent optional backend costs
            # only the cases that declare it rather than the whole run.
            check_solver_available(case.solver, case.contract_source)
            reports = run_case(case, budget=budget)  # plan validated above
        except DiscoveryError as exc:
            # the environment cannot run this case (its declared solver is not installed). The
            # message carries its own provenance, as every discovery diagnostic does.
            print(f"SOLVER ERROR — {legible(str(exc))}", file=sys.stderr)
            errors.append(_case_error(ErrorKind.DISCOVERY, case, str(exc)))
            continue
        except ProgramError as exc:
            # the program under test cannot be run (it will not ground, an #include is unresolvable)
            # — its author fixes the .lp. Not a verdict, and not elenctic's fault either, so it is
            # reported apart from both and the remaining cases still run.
            print(
                f"PROGRAM ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            errors.append(_case_error(ErrorKind.PROGRAM, case, str(exc)))
            continue
        except MemoryError:
            # Reported against the case that ran out of it, and filed with the other cases that
            # could not be run, so the corpus keeps every result it had already earned. Nothing is
            # bounded by this — the grounder offers no size limit and so neither can elenctic —
            # but what it costs is one case's result rather than the whole run's. A resource the
            # caller is the one able to bound, so not elenctic's own fault to report.
            print(
                f"RESOURCE ERROR — {legible(str(case.contract_source))}: {_OUT_OF_MEMORY}",
                file=sys.stderr,
            )
            errors.append(_case_error(ErrorKind.RESOURCE, case, _OUT_OF_MEMORY))
            continue
        except HarnessError as exc:
            # a solve-time invariant breach (a seam, a missing cost) is a harness bug too, never a
            # verdict — report it like a misroute and keep testing the other cases.
            print(
                f"HARNESS ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            errors.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
            continue
        outcome = CaseOutcome(case=case, reports=reports)
        if outcome.verdict is not Verdict.PASS:
            print(render(case, reports))
        outcomes.append(outcome)
    return RunOutcome(cases=tuple(outcomes), errors=tuple(errors), hygiene=hygiene)


def _case_error(kind: ErrorKind, case: Case, message: str) -> ErrorRecord:
    """One case's reason for producing no verdict, against the file it belongs to."""
    return ErrorRecord(kind=kind, scope=Scope.CASE, source=case.contract_source, message=message)


def _summary_line(outcome: RunOutcome) -> str:
    """The end-of-run tally, read off the registers the machine-readable form is built from — so
    the two renderings cannot come to disagree about a number. The two error levels are kept apart
    because they ask different things of the reader: one is a corpus to fix, the other is a bug to
    report."""
    counts = summary(outcome)
    # Both are cases that produced no verdict, split by who can act on them — so neither is named
    # for the running they did not do, which is the half they have in common.
    theirs = sum(
        1
        for error in outcome.errors
        if error.scope is Scope.CASE and not error.kind.is_elenctic_bug
    )
    ours = sum(1 for error in outcome.errors if error.kind.is_elenctic_bug)
    line = f"{counts['passed']}/{counts['total']} passed"
    if theirs:
        line += f", {theirs} could not be run"
    if ours:
        line += f", {ours} harness error(s)"
    return line


def _validate_plans(cases: tuple[Case, ...]) -> tuple[list[Case], list[ErrorRecord]]:
    """Build every case's run plan up front (pure ``runs_for``), so all wiring errors surface before
    any solving. Returns the well-routed cases and a record per misrouted one (a harness error —
    never a verdict)."""
    valid: list[Case] = []
    misroutes: list[ErrorRecord] = []
    for case in cases:
        try:
            runs_for(case.expectation, provides_theory(case.solver))
        except HarnessError as exc:
            print(
                f"HARNESS ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            misroutes.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
        else:
            valid.append(case)
    return valid, misroutes
