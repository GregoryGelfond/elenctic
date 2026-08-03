"""The ``elenctic`` console entry: run a corpus of ``@``-contracts, or explain its run plan.

``elenctic [target]`` discovers cases under ``target`` — a single ``.lp`` case file or a directory
walked for contract-bearing files (default ``tests/``) — validates **every** case's run
plan up front (so a misroute — a harness bug — is reported before any solving),
then solves and checks each case, rendering any non-``PASS`` outcome. ``--explain`` stops after the
plan: it narrates the derived runs (mode + checks) per case without solving, the dry-run the
``reads``/``populates`` surface was made introspectable for.

Exit status separates the outcome registers: ``0`` all cases pass; ``1`` some case FAILed or
is UNDECIDED (a statement about a program under test); ``2`` a corpus, program, resource or harness
error (a bad contract, a mis-shaped corpus, a program that cannot be run, a case that exhausted
memory, or an elenctic bug — never a verdict). A case that cannot be run does not stop the others:
it is reported in its own register and the run continues, so one broken encoding never costs the
run every other case's result. This is the standalone runner; the pytest-client path (per-case
``parametrize``) is a separate consumer.
"""

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from time import monotonic

from elenctic.discovery import (
    ORPHAN_LIBRARY,
    UNDECLARED_SOLVER,
    Case,
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
    ErrorKind,
    ErrorRecord,
    HygieneKind,
    HygieneRecord,
    RunOutcome,
    Scope,
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
    """Run the ``elenctic`` CLI; return the process exit status (0 pass / 1 fail / 2 error).

    The last two registers are here, because a fault that reaches this frame is by definition one
    no inner register anticipated, and the user still has to be told something they can act on."""
    try:
        return _dispatch(argv)
    except MemoryError:
        # The backstop, for an allocation that fails where no case owns it. A case that exhausts
        # memory is caught in the run loop and costs only its own result; reaching this frame means
        # there was no case to report it against. Being unable to *bound* the resource — clingo's
        # API offers neither a clock nor a size limit on grounding — is not a reason to be unable
        # to *report* it. What consumed the memory is not knowable from here, so it is not claimed.
        print(
            "resource error: elenctic ran out of memory running this corpus. Grounding has no size "
            "limit available to it, and a solve holds every model it is shown — run this corpus "
            "with a memory limit, or reduce what it grounds and enumerates. No verdict was "
            "produced.",
            file=sys.stderr,
        )
        return 2
    except Exception:
        # Whatever this is, the user did not cause it and cannot fix it. Say so first, then show
        # the traceback: it is the report, not a failure to produce one.
        print(
            "internal error: this is an elenctic bug, not a fault in your corpus. Please report "
            "it with the traceback below.",
            file=sys.stderr,
        )
        traceback.print_exc()
        return 2


def _dispatch(argv: Sequence[str] | None) -> int:
    """Parse the invocation, discover the corpus, and run or explain it."""
    args = _build_parser().parse_args(argv)
    try:
        corpus = inspect_corpus(args.target)
    except (DiscoveryError, ContractError, ProgramError) as exc:
        # Nothing was discovered, so this fault belongs to no case — it is the corpus's, and it is
        # the whole of what the invocation produced.
        print(f"corpus error: {legible(str(exc))}", file=sys.stderr)
        corpus_fault = ErrorRecord(
            kind=error_kind(exc),
            scope=Scope.CORPUS,
            # A named file is the only file involved, so the fault can be placed in it. A directory
            # names no one file, and the diagnostic's own provenance is where the reader looks.
            source=args.target if args.target.is_file() else None,
            message=str(exc),
        )
        return _status(RunOutcome(cases=(), errors=(corpus_fault,), hygiene=()), strict=args.strict)
    unrunnable = _unrunnable_records(corpus.unrunnable)
    for record in unrunnable:
        # Discovered but unusable — an unresolvable #include, an undecodable byte, a malformed
        # contract. Reported against the file it belongs to, in the same register as a case the
        # runner could not run, so one bad file never costs the corpus its other results.
        # Every discovery diagnostic carries its own provenance, so the path is not repeated here.
        print(f"CASE ERROR — {legible(record.message)}", file=sys.stderr)
    hygiene = _hygiene_records(corpus.hygiene)
    if args.explain:
        # The dry run narrates a plan; it decides nothing, so it has no case register to fill and
        # builds no run outcome. Giving it one would report a corpus of cases as a run of none —
        # the very accounting the registers exist to make impossible. What can still go wrong is a
        # plan that cannot be built, which is what this mode exists to surface.
        misroutes = _explain(corpus.cases)
        _report_hygiene(hygiene, strict=args.strict)
        return 2 if unrunnable or misroutes or (args.strict and hygiene) else 0
    outcome = _run(
        corpus.cases,
        args.budget,
        unrunnable=unrunnable,
        hygiene=hygiene,
        deadline=args.deadline,
    )
    _report_hygiene(hygiene, strict=args.strict)
    return _status(outcome, strict=args.strict)


def _status(outcome: RunOutcome, *, strict: bool) -> int:
    """The process status for a completed run, highest signal winning: ``2`` a fault that stopped
    something from being decided, or a hygiene observation the caller asked to be strict about;
    ``1`` a case decided wrong or could not be decided; ``0`` every case passed. Hygiene is never a
    verdict, which is why it can only reach the error level and only when asked to."""
    if outcome.errors or (strict and outcome.hygiene):
        return 2
    if any(case.verdict is not Verdict.PASS for case in outcome.cases):
        return 1
    return 0


def _hygiene_records(hygiene: HygieneReport) -> tuple[HygieneRecord, ...]:
    """Every corpus-health observation, whatever the strictness dial says about reporting it.

    The dial decides what is *printed* and what fails the run; it does not decide what was
    *observed*. A consumer reading the run's output is owed the observations themselves and applies
    its own policy to them, which it cannot do if the run has already dropped the ones this
    invocation chose to stay silent about."""
    return (
        *(
            HygieneRecord(kind=HygieneKind.ORPHAN_LIBRARY, source=path, message=ORPHAN_LIBRARY)
            for path in hygiene.orphan_libraries
        ),
        *(
            HygieneRecord(
                kind=HygieneKind.UNDECLARED_SOLVER, source=path, message=UNDECLARED_SOLVER
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


def _report_hygiene(hygiene: tuple[HygieneRecord, ...], *, strict: bool) -> None:
    """Report corpus hygiene (the ``--strict`` dial) as an aggregated end-of-run stderr
    summary. Orphan libraries warn by default; under ``--strict`` they — plus the otherwise-silent
    undeclared solvers — become errors that fail the run (the CI gate). Hygiene is never a verdict;
    what a reported observation does to the exit status is decided with the rest of it.

    Rendered from the same records the run reports, so what is printed and what fails the run are
    read off one collection rather than two that happen to be empty together."""
    orphans = [record for record in hygiene if record.kind is HygieneKind.ORPHAN_LIBRARY]
    undeclared = [record for record in hygiene if record.kind is HygieneKind.UNDECLARED_SOLVER]
    lines = [
        f"orphan library: {legible(str(record.source))} {record.message}" for record in orphans
    ]
    if strict and undeclared:
        # Aggregated: a corpus that never declares a solver would otherwise report every case, and
        # the observation is about the corpus's habit rather than about any one file.
        listed = ", ".join(legible(str(record.source)) for record in undeclared)
        lines.append(f"undeclared solver: {len(undeclared)} case(s) {UNDECLARED_SOLVER}: {listed}")
    if not lines:
        return
    print(f"\nhygiene {'errors (--strict)' if strict else 'warnings'}:", file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)


def _explain(cases: tuple[Case, ...]) -> tuple[ErrorRecord, ...]:
    """Narrate the derived run plan per case without solving (the dry-run): each run's mode and the
    projection decision (which the contract's reads induce), and each check with the fields it
    reads. Returns the misroutes it met — a plan that cannot be built is a harness fault, and this
    is the mode whose whole purpose is to surface one before any solving."""
    misroutes: list[ErrorRecord] = []
    for case in cases:
        print(f"{legible(str(case.contract_source))} [{case.solver}]")
        # The @note prose leads the narration — the author's what/why above the harness's how.
        # Both Sat and Unsat carry notes; documentation, never a verdict.
        for note in case.expectation.notes:
            print(f"    note: {legible(note)}")
        try:
            for run in runs_for(case.expectation, provides_theory(case.solver)):
                projects = "yes" if run.projects_to_shown else "no"
                print(f"    {run.mode.name} (projects: {projects}):")
                for check in run.checks:
                    # subject discerns the repeatable @query tag before any solve.
                    name = f"{check.label} ({check.subject})" if check.subject else check.label
                    reads = ", ".join(sorted(field.value for field in check.reads)) or "—"
                    print(f"        {name} — reads {{{reads}}}")
        except HarnessError as exc:
            # Named, though the narration above it on standard output already names the case: these
            # go to standard error, and a reader who has only that stream is owed the file.
            print(
                f"    HARNESS ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            misroutes.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
    return tuple(misroutes)


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
    run = RunOutcome(cases=tuple(outcomes), errors=tuple(errors), hygiene=hygiene)
    print(f"\n{_summary_line(run)}")
    return run


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
