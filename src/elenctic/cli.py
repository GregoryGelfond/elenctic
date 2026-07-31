"""The ``elenctic`` console entry: run a corpus of ``@``-contracts, or explain its run plan.

``elenctic [target]`` discovers cases under ``target`` — a single ``.lp`` case file or a directory
walked for contract-bearing files (default ``tests/``) — validates **every** case's run
plan up front (so a misroute — a harness bug — is reported before any solving),
then solves and checks each case, rendering any non-``PASS`` outcome. ``--explain`` stops after the
plan: it narrates the derived runs (mode + checks) per case without solving, the dry-run the
``reads``/``populates`` surface was made introspectable for.

Exit status separates the outcome registers: ``0`` all cases pass; ``1`` some case FAILed or
is UNDECIDED (a statement about a program under test); ``2`` a corpus, program or harness error (a
bad contract, a mis-shaped corpus, a program that cannot be run, or an elenctic bug — never a
verdict). A case that cannot be run does not stop the others: it is reported in its own register
and the run continues, so one broken encoding never costs the run every other case's result. This
is the standalone runner; the pytest-client path (per-case ``parametrize``) is a separate consumer.
"""

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from elenctic.discovery import (
    Case,
    DiscoveryError,
    HygieneReport,
    check_solver_available,
    inspect_corpus,
)
from elenctic.display import legible
from elenctic.expectation import ContractError
from elenctic.harness import case_verdict, render, run_case
from elenctic.program import ProgramError
from elenctic.registry import provides_theory
from elenctic.result import HarnessError, Verdict
from elenctic.run import runs_for
from elenctic.solvers import TIME_BUDGET


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
        help=f"per-solve budget; a hit budget is UNDECIDED, not FAIL (default {TIME_BUDGET}s)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``elenctic`` CLI; return the process exit status (0 pass / 1 fail / 2 error).

    The last two registers are here, because a fault that reaches this frame is by definition one
    no inner register anticipated, and the user still has to be told something they can act on."""
    try:
        return _dispatch(argv)
    except MemoryError:
        # Grounding has no bound available to it — clingo's API offers neither a clock nor a size
        # limit on it — so a small program can exhaust memory, and clingo reports that as a
        # MemoryError rather than the RuntimeError the fault paths are written against. Being
        # unable to *bound* the resource is not a reason to be unable to *report* it.
        print(
            "resource error: elenctic ran out of memory running this corpus. A program can be "
            "small and still ground to something enormous, and grounding has no size limit to "
            "hold it under — run this corpus with a memory limit, or reduce what it grounds. No "
            "verdict was produced.",
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
        print(f"corpus error: {legible(str(exc))}", file=sys.stderr)
        return 2
    for _path, fault in corpus.unrunnable:
        # Discovered but unusable — an unresolvable #include, an undecodable byte, a malformed
        # contract. Reported against the file it belongs to, in the same register as a case the
        # runner could not run, so one bad file never costs the corpus its other results.
        # Every discovery diagnostic carries its own provenance, so the path is not repeated here.
        print(f"CASE ERROR — {legible(str(fault))}", file=sys.stderr)
    status = (
        _explain(corpus.cases)
        if args.explain
        else _run(corpus.cases, args.budget, undiscoverable=len(corpus.unrunnable))
    )
    if corpus.unrunnable:
        status = 2
    return _report_hygiene(corpus.hygiene, strict=args.strict, status=status)


def _report_hygiene(hygiene: HygieneReport, *, strict: bool, status: int) -> int:
    """Report corpus hygiene (the ``--strict`` dial) as an aggregated end-of-run stderr
    summary. Orphan libraries warn by default and leave the exit ``status`` (a verdict register)
    unchanged; under ``--strict`` they — plus the otherwise-silent undeclared solvers — become
    errors that fail the run (exit ``2``, the CI gate, dominating the verdict register). Hygiene is
    never a verdict; with nothing to report in this mode, the ``status`` is unchanged."""
    records = hygiene.render(strict=strict)
    if not records:
        return status
    print(f"\nhygiene {'errors (--strict)' if strict else 'warnings'}:", file=sys.stderr)
    for line in records:
        print(f"  {line}", file=sys.stderr)
    return 2 if strict else status


def _explain(cases: tuple[Case, ...]) -> int:
    """Narrate the derived run plan per case without solving (the dry-run): each run's mode and the
    projection decision (which the contract's reads induce), and each check with the fields it
    reads. 0, or 2 on a misroute."""
    status = 0
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
            print(f"    HARNESS ERROR: {legible(str(exc))}", file=sys.stderr)
            status = 2
    return status


def _run(cases: tuple[Case, ...], budget: float, undiscoverable: int = 0) -> int:
    """Validate every plan up front, then solve + check each case; render non-PASS outcomes.

    ``undiscoverable`` counts the contract-bearing files discovery could not turn into cases. They
    are counted into the corpus total and the not-run register here rather than omitted, so the
    summary never accounts for a file by leaving it out."""
    valid, harness_errors = _validate_plans(cases)
    nonpassing = 0
    case_errors: list[Case] = []
    for case in valid:
        try:
            # The declared solver is checked here, per case, so an absent optional backend costs
            # only the cases that declare it rather than the whole run.
            check_solver_available(case.solver, case.contract_source)
            reports = run_case(case, budget=budget)  # plan validated above
        except DiscoveryError as exc:
            # the environment cannot run this case (its declared solver is not installed). The
            # message carries its own provenance, as every discovery diagnostic does.
            print(f"SOLVER ERROR — {legible(str(exc))}", file=sys.stderr)
            case_errors.append(case)
            continue
        except ProgramError as exc:
            # the program under test cannot be run (it will not ground, an #include is unresolvable)
            # — its author fixes the .lp. Not a verdict, and not elenctic's fault either, so it is
            # reported apart from both and the remaining cases still run.
            print(
                f"PROGRAM ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            case_errors.append(case)
            continue
        except HarnessError as exc:
            # a solve-time invariant breach (a seam, a missing cost) is a harness bug too, never a
            # verdict — report it like a misroute (exit 2) and keep testing the other cases.
            print(
                f"HARNESS ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            harness_errors.append(case)
            continue
        if case_verdict(reports) is not Verdict.PASS:
            print(render(case, reports))
            nonpassing += 1
    total = len(cases) + undiscoverable
    not_run = len(case_errors) + undiscoverable
    passed = len(cases) - nonpassing - len(harness_errors) - len(case_errors)
    summary = f"{passed}/{total} passed"
    if not_run:
        summary += f", {not_run} could not be run"
    if harness_errors:
        summary += f", {len(harness_errors)} harness error(s)"
    print(f"\n{summary}")
    if harness_errors or case_errors:
        return 2
    return 1 if nonpassing else 0


def _validate_plans(cases: tuple[Case, ...]) -> tuple[list[Case], list[Case]]:
    """Build every case's run plan up front (pure ``runs_for``), so all wiring errors surface before
    any solving. Returns the well-routed cases and the misrouted ones (each
    reported as a harness error — never a verdict)."""
    valid: list[Case] = []
    harness_errors: list[Case] = []
    for case in cases:
        try:
            runs_for(case.expectation, provides_theory(case.solver))
        except HarnessError as exc:
            print(
                f"HARNESS ERROR — {legible(str(case.contract_source))}: {legible(str(exc))}",
                file=sys.stderr,
            )
            harness_errors.append(case)
        else:
            valid.append(case)
    return valid, harness_errors


if __name__ == "__main__":
    sys.exit(main())
