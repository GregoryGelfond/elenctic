"""Run a discovered case end-to-end and render its outcome — the per-case layer.

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
  collapsed into one red); each non-PASS line names the contract line it judged, and the claim's
  own surface where the tag is a repeatable one. The case's ``@note`` prose and its
  ``contract_source`` are read from the *case* — the renderer's concern, not the check's, so the
  reports carry no note. ``@note`` surfaces on **any** non-PASS (FAIL or UNDECIDED — a
  "known-slow" note explains a timeout).

A **misrouted run-plan** is a :class:`~elenctic.result.HarnessError` (``RoutingError``) raised by
``runs_for`` at plan construction — a harness bug, never a verdict. ``run_case`` lets it
**propagate** to whatever is running the corpus, which reports it under a distinct "harness error"
status — pytest's collection error is the same idea: something went wrong *before* a test could
have an outcome, so it is reported as its own kind of thing rather than as a failing test — keeps
testing the other cases, and fails the run with a non-zero exit. The plan is pure and buildable up
front, so a caller wanting every wiring error at once can call ``runs_for`` for all cases *before*
any solving; ``run_case`` bundles build-then-solve for the per-case path.

These three functions are the per-*case* layer, and everything above a case belongs to whoever runs
the corpus: which cases exist, what to do with a case that could not be run at all, and the counts
at the end. ``elenctic.cli`` is one such runner and the one that ships; a consumer embedding these
three in a runner of their own — driving :func:`run_case` from ``pytest.mark.parametrize``, say — is
the other, and gets the same three values to build a report out of. Either way elenctic **ships the
diagnostic value** rather than pushing it to consumers.
"""

from collections.abc import Iterable
from typing import Final

from elenctic.checks import CheckReport
from elenctic.discovery import Case
from elenctic.display import legible
from elenctic.registry import provides_theory
from elenctic.result import Verdict
from elenctic.run import Run, runs_for
from elenctic.solvers import TIME_BUDGET, solve

__all__ = ["case_verdict", "render", "run_case", "run_plan"]


def run_case(case: Case, budget: float = TIME_BUDGET) -> tuple[CheckReport, ...]:
    """Run ``case`` to its check reports (impure via ``solvers.solve``): for each derived run, solve
    under ``budget`` and apply the run's checks. Output order follows ``runs_for`` (deterministic).
    ``theory_in_force`` is fixed once at the boundary as the case's solver being a theory solver
    (clingcon), then flows as a property into the per-run projection decision.

    **What it raises, which is the caller's whole job to handle.** A case that cannot be run does
    not come back as a verdict — there is no verdict to be had — so it leaves by raising, and a
    runner catching one family and not the others loses the corpus on the first case meeting
    another. Four families reach a caller, each saying something different about whose fault it is:

    - :class:`~elenctic.program.ProgramError` — the program under test will not ground, or an
      ``#include`` will not resolve. The corpus author fixes the ``.lp``.
    - :class:`~elenctic.discovery.DiscoveryError` — a discovery-time precondition this case fails.
      Its subclass ``SolverUnavailableError`` is the common one, and it is a fault in the
      *environment* rather than in the corpus — :func:`~elenctic.outcome.error_kind` files it
      under that locus. It is worth heading off: call
      ``discovery.check_solver_available`` per case before running, which is what turns "this
      machine has no clingcon" into a report about that case rather than an exception midway.
    - ``MemoryError`` — the machine ran out. Nothing about the encoding is wrong, and the frame that
      can bound what a case consumes is the one that started it.
    - :class:`~elenctic.result.HarnessError` — including ``RoutingError`` from ``runs_for``, raised
      at plan construction before any solving. An elenctic bug, never a statement about the program.

    The first three cost that case its verdict and no other's; the last is evidence about every
    case in the run. ``elenctic.corpus`` catches all four per case and files each as an
    :class:`~elenctic.outcome.ErrorRecord`, which is the shape a runner of your own wants too.

    A caller that has already derived the plan — because it validated every plan before solving
    anything, which is what running a corpus does — passes it to :func:`run_plan` instead and does
    not derive it a second time."""
    return run_plan(case, runs_for(case.expectation, provides_theory(case.solver)), budget=budget)


def run_plan(
    case: Case, runs: Iterable[Run], budget: float = TIME_BUDGET
) -> tuple[CheckReport, ...]:
    """Carry out an already-derived plan for ``case``: solve each run under ``budget`` and apply its
    checks. Output order follows the plan (deterministic).

    Apart from :func:`run_case` because deriving the plan and carrying it out are separable and a
    corpus separates them: it builds every plan first, so a wiring fault surfaces before any
    solving, and then runs the ones that built. Written as one function that does both, that costs a
    second derivation per case and — worse — leaves the validated plan discarded, so what is carried
    out is a plan nothing proved rather than the one that was proved. Here the proof travels with
    the value.

    It raises what :func:`run_case` raises, minus the one that comes from deriving: a plan handed in
    has already been built, so ``RoutingError`` belongs to whoever built it."""
    reports: list[CheckReport] = []
    for run in runs:
        outcome = solve(case.solver, run.mode, files=case.files, budget=budget, project=run.project)
        reports.extend(check(outcome) for check in run.checks)
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


# The continuation line is indented past the "  [" that opens a row, so it reads as part of the row
# above rather than as a row of its own. One fixed width rather than one measured off each verdict:
# a continuation that started in a different column per verdict would make the column carry meaning
# it does not have, and every continuation would move if a verdict were ever renamed. It clears the
# widest thing it must clear — the "  [FAIL] " that opens the commoner row — and sits inside the
# opening of a longer "  [UNDECIDED] ", which still reads as continuation because no row begins
# there.
_CONTINUATION: Final = " " * len("  [FAIL] ")

# The continuation is deliberately NOT truncated the way a rendered *set* is (`checks._braces`).
# The two bound different things: a set comes from the program and is as large as the program makes
# it, while this list is one entry per contract line an author wrote, so its length is bounded by
# what someone typed. A generated corpus could still make it long; that is worth revisiting with a
# real case rather than pre-empting, and a cap here would have to say how much it left out.


def _claim(report: CheckReport) -> str:
    """Which claim a report judged: the claim's own surface where the tag is a repeatable one, and
    always the line, since that is what identifies it."""
    subject = f"{legible(report.subject)} " if report.subject else ""
    return f"{subject}(line {report.line})"


def _rows(group: list[CheckReport]) -> list[str]:
    """One diagnostic, rendered over the claims that share it.

    A single claim is a row. Several claims that reached the *same* verdict with the *same* words
    are one fact about all of them, so the fact is stated once and the claims follow on a
    continuation line — each paired with its own coordinate, so a reader never has to line up two
    lists. Ascending by line, so the same reports render the same bytes and a reader meets the
    claims in the order the file holds them."""
    first = group[0]
    opening = f"  [{first.verdict.name}] {first.label}"
    if len(group) == 1:
        return [f"{opening} {_claim(first)}: {legible(first.message)}"]
    applied = ", ".join(_claim(report) for report in sorted(group, key=lambda r: r.line))
    return [f"{opening}: {legible(first.message)}", f"{_CONTINUATION}applied to {applied}"]


def _grouped(reports: tuple[CheckReport, ...]) -> list[list[CheckReport]]:
    """The non-``PASS`` reports, gathered into the diagnostics they share.

    Keyed on the verdict as well as the tag and the message: a row carries one verdict, so grouping
    without it could tag a claim with a verdict it did not earn — and a differing verdict is not
    the coordinate this collapses over. Insertion-ordered, so groups appear where their first claim
    did and the run's own order survives."""
    groups: dict[tuple[Verdict, str, str], list[CheckReport]] = {}
    for report in reports:
        if report.verdict is not Verdict.PASS:
            groups.setdefault((report.verdict, report.label, report.message), []).append(report)
    return list(groups.values())


def render(case: Case, reports: tuple[CheckReport, ...]) -> str:
    """Render the case outcome as a human diagnostic (pure). The header names the contract source,
    the solver, and the case verdict; each non-``PASS`` diagnostic contributes a row tagged with its
    own verdict (FAIL vs UNDECIDED kept distinct) and the claim it judged; and on any non-``PASS``
    outcome the case's ``@note`` prose is surfaced, read from the case. A passing case is a terse
    header.

    Claims that failed for the *same* reason share a row. A repeated tag whose diagnostic does not
    turn on the claim — every ``@cautious`` line on a program with no answer set, say — would
    otherwise state one fact once per claim, and the reader who has to scan that is the one already
    being told something went wrong. Where the diagnostic *does* turn on the claim, which is the
    informative case, nothing is shared and each claim keeps its own row.

    Collapsing is display only. The verdict folds a set, so it cannot move; a consumer reading the
    reports still gets one per claim.

    The path, the note prose, each claim's subject and each diagnostic's message all come from the
    corpus, so each is made :func:`~elenctic.display.legible` first: this string is the verdict a
    reader acts on, and text that could rewrite it would undo the point of producing it."""
    verdict = case_verdict(reports)
    lines = [f"{legible(str(case.contract_source))} [{case.solver}] — {verdict.name}"]
    for group in _grouped(reports):
        lines.extend(_rows(group))
    if verdict is not Verdict.PASS:
        lines.extend(f"  note: {legible(note)}" for note in case.expectation.notes)
    return "\n".join(lines)
