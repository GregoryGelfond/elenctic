"""The ``elenctic`` console entry: run a corpus of ``@``-contracts, or explain its run plan.

``elenctic <encodings_root> [cases_root]`` discovers the corpus (spec §5), validates **every**
case's run plan up front (so a misroute — a harness bug — is reported before any solving, keystone
decision 6), then solves and checks each case, rendering any non-``PASS`` outcome. ``--explain``
stops after the plan: it narrates the derived runs (mode + checks) per case without solving, the
dry-run the ``reads``/``populates`` surface was made introspectable for.

Exit status separates the three outcome registers: ``0`` all cases pass; ``1`` some case FAILed or
is UNDECIDED (a statement about a program under test); ``2`` a corpus or harness error (a bad
contract, a mis-shaped corpus, or an elenctic bug — never a verdict). This is the standalone runner;
the pytest-client path (per-case ``parametrize``) lives in the corpus repo (Plan 2).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from elenctic.discovery import Case, DiscoveryError, Layout, discover
from elenctic.expectation import ContractError
from elenctic.harness import case_verdict, render, run_case
from elenctic.result import HarnessError, Verdict
from elenctic.run import runs_for
from elenctic.solvers import TIME_BUDGET


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elenctic", description="Run a corpus of @-contracts over Answer Set Programs."
    )
    parser.add_argument("encodings", type=Path, help="the encodings root (encodings/<domain>/)")
    parser.add_argument(
        "cases",
        type=Path,
        nargs="?",
        help="the cases root (tests/cases/<domain>/); omit for self-contained encodings",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="narrate the derived run plan per case, without solving (a dry-run)",
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
    """Run the ``elenctic`` CLI; return the process exit status (0 pass / 1 fail / 2 error)."""
    args = _build_parser().parse_args(argv)
    cases_root = args.cases or args.encodings / "_none"  # self-contained corpus: no cases tree
    layout = Layout(encodings_root=args.encodings, cases_root=cases_root)
    try:
        cases = discover(layout)
    except (DiscoveryError, ContractError) as exc:
        print(f"corpus error: {exc}", file=sys.stderr)
        return 2
    return _explain(cases) if args.explain else _run(cases, args.budget)


def _explain(cases: tuple[Case, ...]) -> int:
    """Narrate the derived run plan per case without solving (the dry-run); 0, or 2 on misroute."""
    status = 0
    for case in cases:
        print(f"{case.contract_source} [{case.solver}]")
        try:
            for run in runs_for(case.expectation):
                # subject discerns the repeatable @query tag before any solve (keystone surface).
                checks = ", ".join(
                    f"{check.label} ({check.subject})" if check.subject else check.label
                    for check in run.checks
                )
                print(f"    {run.mode.name}: {checks}")
        except HarnessError as exc:
            print(f"    HARNESS ERROR: {exc}", file=sys.stderr)
            status = 2
    return status


def _run(cases: tuple[Case, ...], budget: float) -> int:
    """Validate every plan up front, then solve + check each case; render non-PASS outcomes."""
    valid, harness_errors = _validate_plans(cases)
    nonpassing = 0
    for case in valid:
        try:
            reports = run_case(case, budget=budget)  # plan validated above
        except HarnessError as exc:
            # a solve-time invariant breach (a seam, a missing cost) is a harness bug too, never a
            # verdict — report it like a misroute (exit 2) and keep testing the other cases.
            print(f"HARNESS ERROR — {case.contract_source}: {exc}", file=sys.stderr)
            harness_errors.append(case)
            continue
        if case_verdict(reports) is not Verdict.PASS:
            print(render(case, reports))
            nonpassing += 1
    passed = len(cases) - nonpassing - len(harness_errors)
    summary = f"{passed}/{len(cases)} passed"
    if harness_errors:
        summary += f", {len(harness_errors)} harness error(s)"
    print(f"\n{summary}")
    if harness_errors:
        return 2
    return 1 if nonpassing else 0


def _validate_plans(cases: tuple[Case, ...]) -> tuple[list[Case], list[Case]]:
    """Build every case's run plan up front (pure ``runs_for``), so all wiring errors surface before
    any solving (keystone decision 6). Returns the well-routed cases and the misrouted ones (each
    reported as a harness error — never a verdict)."""
    valid: list[Case] = []
    harness_errors: list[Case] = []
    for case in cases:
        try:
            runs_for(case.expectation)
        except HarnessError as exc:
            print(f"HARNESS ERROR — {case.contract_source}: {exc}", file=sys.stderr)
            harness_errors.append(case)
        else:
            valid.append(case)
    return valid, harness_errors


if __name__ == "__main__":
    sys.exit(main())
