"""Run a discovered case end-to-end and render its outcome — the top of the module DAG.

Three responsibilities, layered by purity:

- :func:`run_case` — the **impure orchestrator**: derive the case's runs (``run.runs_for``), solve
  each (``solvers.solve``), apply its checks, collect the :class:`~elenctic.checks.CheckReport`s. It
  touches no solver directly (the purity boundary stays in ``solvers.py``); it only sequences the
  pure plan against the impure facade.
- :func:`case_verdict` — **pure**: fold the per-check reports to one case verdict. A definite
  failure sinks the case, so **FAIL dominates UNDECIDED dominates PASS** (a case passes iff every
  check does; an UNDECIDED check is "could not decide", a FAIL is "decided wrong" —
  both red, but a decisive FAIL is the more informative label).
- :func:`render` — **pure**: the human diagnostic. FAIL and UNDECIDED stay **distinct** (never
  collapsed into one red), and the case's ``@note`` prose and its ``contract_source`` (file-level
  provenance; per-tag line precision is deferred) are read from the *case* (Model A — the
  renderer's concern, not the check's; the reports carry no note). ``@note`` surfaces on **any**
  non-PASS (FAIL or UNDECIDED — a "known-slow" note explains a timeout).

A **misrouted run-plan** is a :class:`~elenctic.result.HarnessError` (``RoutingError``) raised by
``runs_for`` at plan construction — a harness bug, never a verdict. ``run_case`` lets it
**propagate** to the runner (the pytest client or the CLI), which reports it under a distinct
"harness error" status (the pytest collection-error analog), keeps testing the other cases, and
fails the run with a non-zero exit. The plan is pure and buildable up front, so a session can
pre-validate every case's plan (call ``runs_for`` for all cases) *before* any solving if it wants
all wiring errors at once; ``run_case`` bundles build-then-solve for the per-case path.

The pytest ``parametrize`` + assertion (and the session-level aggregation) live in the **client**
(the pytest client or the CLI); elenctic **ships the diagnostic value** rather than pushing it to
consumers.
"""

from elenctic.checks import CheckReport
from elenctic.discovery import Case
from elenctic.registry import provides_theory
from elenctic.result import Verdict
from elenctic.run import runs_for
from elenctic.solvers import TIME_BUDGET, solve

__all__ = ["case_verdict", "render", "run_case"]


def run_case(case: Case, budget: float = TIME_BUDGET) -> tuple[CheckReport, ...]:
    """Run ``case`` to its check reports (impure via ``solvers.solve``): for each derived run, solve
    under ``budget`` and apply the run's checks. Output order follows ``runs_for`` (deterministic).
    ``theory_in_force`` is fixed once at the boundary as the case's solver being a theory solver
    (clingcon), then flows as a property into the per-run projection decision. A misrouted plan
    raises a ``RoutingError`` (``HarnessError``) from ``runs_for`` — propagated to the runner as a
    harness error, never a verdict."""
    theory_in_force = provides_theory(case.solver)
    reports: list[CheckReport] = []
    for run in runs_for(case.expectation, theory_in_force):
        determination = solve(
            case.solver, run.mode, files=case.files, budget=budget, project=run.project
        )
        reports.extend(check(determination) for check in run.checks)
    return tuple(reports)


def case_verdict(reports: tuple[CheckReport, ...]) -> Verdict:
    """The case verdict: ``PASS`` iff every check passes, else ``FAIL`` if any check decided wrong,
    else ``UNDECIDED`` (some check could not decide). FAIL dominates UNDECIDED."""
    verdicts = {report.verdict for report in reports}
    if Verdict.FAIL in verdicts:
        return Verdict.FAIL
    if Verdict.UNDECIDED in verdicts:
        return Verdict.UNDECIDED
    return Verdict.PASS


def render(case: Case, reports: tuple[CheckReport, ...]) -> str:
    """Render the case outcome as a human diagnostic (pure). The header names the contract source,
    the solver, and the case verdict; each non-``PASS`` check contributes a line tagged with its own
    verdict (FAIL vs UNDECIDED kept distinct); and on any non-``PASS`` outcome the case's
    ``@note`` prose is surfaced (Model A — read from the case). A passing case is a terse header."""
    verdict = case_verdict(reports)
    lines = [f"{case.contract_source} [{case.solver}] — {verdict.name}"]
    lines.extend(
        f"  [{report.verdict.name}] {report.label}: {report.message}"
        for report in reports
        if report.verdict is not Verdict.PASS
    )
    if verdict is not Verdict.PASS:
        lines.extend(f"  note: {note}" for note in case.expectation.notes)
    return "\n".join(lines)
