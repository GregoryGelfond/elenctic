"""The ``elenctic`` console entry: run a corpus of ``@``-contracts, or explain its run plan.

``elenctic [target]`` discovers cases under ``target`` — a single ``.lp`` case file or a directory
walked for contract-bearing files (default ``tests/``) — validates **every** case's run
plan up front (so a misroute — a harness bug — is reported before any solving),
then solves and checks each case, rendering any non-``PASS`` outcome. ``--explain`` stops after the
plan: it narrates the derived runs (mode + checks) per case without solving, the dry-run the
``reads``/``populates`` surface was made introspectable for.

Exit status separates the outcome registers: ``0`` all cases pass; ``1`` some case FAILed or is
UNDECIDED (a statement about a program under test); ``2`` a fault the user can fix — a bad contract,
a mis-shaped corpus, a program that cannot be run, a declared solver this environment does not have,
a case that ran out of memory, a run that passed its deadline, or a corpus-health observation under
``--strict`` — and ``3`` an elenctic bug, which
outranks the rest because a harness wrong about one case is evidence about every other. The two
error levels ask different things of the reader, which is why they are not one: ``2`` is a corpus to
attend to, ``3`` is a bug to report. Neither is ever a verdict. A case that cannot be run does not
stop the others: it is reported in its own register and the run continues, so one broken encoding
never costs the run every other case's result. This is the standalone runner; the pytest-client path
(per-case ``parametrize``) is a separate consumer.
"""

import argparse
import os
import sys
import traceback
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
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
    HygieneKind,
    HygieneRecord,
    Invocation,
    Outcome,
    PlanOutcome,
    RunOutcome,
    Scope,
    Severity,
    error_kind,
    summary,
)
from elenctic.program import ProgramError
from elenctic.registry import provides_theory
from elenctic.result import HarnessError, Verdict
from elenctic.run import runs_for
from elenctic.solvers import TIME_BUDGET

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

# The same allocation failure with no case to name it against, and the reason it is worded
# separately rather than reused: a frame that cannot say which case was running cannot offer the
# remedy that names one, so it asks for the whole corpus to be bounded instead.
_CORPUS_OUT_OF_MEMORY = (
    "elenctic ran out of memory running this corpus. Grounding has no size limit available to it, "
    "and a solve holds every model it is shown — run this corpus with a memory limit, or reduce "
    "what it grounds and enumerates. No verdict was produced."
)

# What a fault no register anticipated says about itself. Shared by the diagnostic and the record
# for the same reason as the two above: one sentence, stated once.
_INTERNAL_ERROR = "this is an elenctic bug, not a fault in your corpus"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elenctic", description="Run a corpus of @-contracts over Answer Set Programs."
    )
    parser.add_argument(
        "target",
        type=Path,
        nargs="?",
        default=Path("tests"),
        help="a case file or a directory to walk for contract-bearing cases (default: tests/)",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="narrate the derived run plan per case, without solving (a dry-run)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail the run on any corpus-hygiene issue (the CI gate): orphan libraries (warned by "
        "default) become errors, and undeclared solvers (silent by default) are required explicit",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=TIME_BUDGET,
        metavar="SECONDS",
        help="per-solve time budget in seconds. A budget hit before the solve decides is UNDECIDED "
        "and never FAIL; one hit after it decides keeps what was decided, and only the checks "
        f"that needed more of the search are UNDECIDED (default {TIME_BUDGET}s)",
    )
    parser.add_argument(
        "--deadline",
        type=float,
        default=None,
        metavar="SECONDS",
        help="stop the run once it has taken this long; cases not reached are reported as not run "
        "(off by default — --budget bounds one solve, this bounds the whole corpus)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``elenctic`` CLI; return the process exit status (0 pass / 1 fail or undecided /
    2 a fault in the corpus / 3 an elenctic bug).

    The two outermost handlers are here because a fault that reaches this frame is by definition one
    no inner register anticipated, and the user still has to be told something they can act on. Each
    files the fault it met into an outcome of its own and reads the status off that, so the status
    follows from a record rather than being chosen beside one.

    The invocation is settled in this frame rather than one below it: below here it is a value of
    a type that cannot express a mode which produces no run, which is what lets running be total
    rather than something that has to refuse."""
    try:
        args = _build_parser().parse_args(argv)
        invocation = Invocation(
            target=args.target,
            strict=args.strict,
            budget=args.budget,
            deadline=args.deadline,
        )
        produced = explain_corpus(invocation) if args.explain else run_corpus(invocation)
        return exit_status(produced)
    except MemoryError:
        # The backstop, for an allocation that fails where no case owns it. A case that exhausts
        # memory is caught in the run loop and costs only its own result; reaching this frame means
        # there was no case to report it against. Being unable to *bound* the resource — clingo's
        # API offers neither a clock nor a size limit on grounding — is not a reason to be unable
        # to *report* it. What consumed the memory is not knowable from here, so it is not claimed.
        print(f"resource error: {_CORPUS_OUT_OF_MEMORY}", file=sys.stderr)
        outcome = _fault_outcome(ErrorKind.RESOURCE, _CORPUS_OUT_OF_MEMORY)
        return exit_status(outcome)
    except Exception as exc:
        # Whatever this is, the user did not cause it and cannot fix it. Say so first, then show
        # the traceback: it is the report, not a failure to produce one. The record names the family
        # rather than rendering the exception, so the last frame that can report anything cannot
        # itself fail on a __repr__ that raises.
        print(
            f"internal error: {_INTERNAL_ERROR}. Please report it with the traceback below.",
            file=sys.stderr,
        )
        traceback.print_exc()
        outcome = _fault_outcome(ErrorKind.HARNESS, f"{_INTERNAL_ERROR}: {type(exc).__name__}")
        return exit_status(outcome)


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


def exit_status(outcome: Outcome) -> int:
    """The process status for a completed invocation, highest signal winning.

    ``3`` an elenctic bug — a harness that is wrong about one case is evidence about every other, so
    it puts the whole run's verdicts in doubt and outranks them all; ``2`` a fault the user can fix,
    or an observation this run graded an error; ``1`` a case decided wrong or could not be decided;
    ``0`` nothing went wrong. The two error levels are the closed split of where a fault lies:
    anything that is not a harness fault is the user's, so a locus added later never silently
    changes what a status means.

    One function over both modes rather than a ladder written twice, because the faults a dry run
    can meet are the same faults and rank the same way — and the one thing that differs, having
    verdicts to weigh, is exactly what the two outcome types differ in. A dry run reaching the last
    rung is ``0`` because it decided nothing: there is no verdict for it to have got wrong.

    A function of what the invocation produced and of nothing else. The strictness dial is applied
    where an observation is recorded, so the grade travels on the record and this reading of it is
    the same reading the end-of-run summary makes — rather than a second consultation of a flag,
    which is how a run comes to print one thing and return another.
    """
    if any(error.kind.is_elenctic_bug for error in outcome.errors):
        return 3
    if outcome.errors or any(record.severity is Severity.ERROR for record in outcome.hygiene):
        return 2
    match outcome:
        case RunOutcome():
            return 1 if any(case.verdict is not Verdict.PASS for case in outcome.cases) else 0
        case PlanOutcome():
            return 0
        case unreachable:
            assert_never(unreachable)


def _corpus_fault(kind: ErrorKind, message: str, *, source: Path | None = None) -> ErrorRecord:
    """One fault belonging to no single case, and therefore to the corpus: nothing was discovered,
    or the frame that met the fault had no case to name.

    ``source`` is the file when exactly one was involved — a target named on the command line is
    the only file the fault can belong to, while a directory names no one file and the diagnostic's
    own provenance is where the reader looks."""
    return ErrorRecord(kind=kind, scope=Scope.CORPUS, source=source, message=message)


def _fault_outcome(kind: ErrorKind, message: str, *, source: Path | None = None) -> RunOutcome:
    """A run whose whole result is one corpus-level fault.

    A whole outcome rather than a record because such a fault *is* the whole of what the invocation
    produced, and the status is then the ordinary reading of an outcome rather than a number chosen
    beside one."""
    return RunOutcome(cases=(), errors=(_corpus_fault(kind, message, source=source),), hygiene=())


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
                severity=HygieneKind.ORPHAN_LIBRARY.severity_under(strict=strict),
                source=path,
                message=ORPHAN_LIBRARY,
            )
            for path in hygiene.orphan_libraries
        ),
        *(
            HygieneRecord(
                kind=HygieneKind.UNDECLARED_SOLVER,
                severity=HygieneKind.UNDECLARED_SOLVER.severity_under(strict=strict),
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


@contextmanager
def _stdout_to_stderr() -> Iterator[None]:
    """Send everything written to the process's standard output to standard error instead, for the
    duration of the region.

    Under a machine-readable format the report is the only thing that may appear on standard
    output: one foreign byte and the document will not parse. The redirect is at the file-descriptor
    level rather than at ``sys.stdout``, because rebinding the Python object leaves anything writing
    to the descriptor beneath it untouched — a C library reached through a binding writes where it
    chooses, and a guarantee that holds only while a dependency keeps choosing well is not one. What
    would otherwise land beside the document is moved rather than discarded: a reader still sees it,
    just not where a parser is looking.

    The two boundaries decide which stream holds what, which is why the buffer is emptied at each:
    output written before the region belongs on standard output, and output written inside it
    belongs with the diagnostics. Within the region the two streams are not ordered against each
    other — standard error is line-buffered and standard output need not be — so writes to the two
    can reach a reader in an order other than the one they were made in.

    The caller's side of the bargain: nothing inside the region may write to standard output, since
    for the length of it there is no way to reach it. Anything that asks the descriptor about itself
    — whether it is a terminal, how wide it is — is answered for standard error while it is open.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        # The flush guards the restore, because it is the step that can fail: it is issued against
        # standard error, so whatever makes standard error unwritable meets it here. Left
        # unguarded, it would keep the descriptor diverted for the rest of the process and send the
        # report itself to the one stream this region exists to keep it out of.
        try:
            sys.stdout.flush()
        finally:
            os.dup2(saved, 1)
            os.close(saved)


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
    reported = [record for record in hygiene if record.severity is not Severity.SILENT]
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
    failing = any(record.severity is Severity.ERROR for record in reported)
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
            # Reported against the case that exhausted it, and filed with the other cases that
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


if __name__ == "__main__":
    sys.exit(main())
