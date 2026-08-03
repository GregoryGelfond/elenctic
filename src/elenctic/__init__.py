"""elenctic — a declarative testing framework for Answer Set Programming.

The reference implementation of a language-parametric ``@``-contract format over the *observable*
of an answer-set program (shown atoms + theory assignment). A contract is parsed (:func:`parse`)
into an :data:`Expectation`; :func:`discover` walks a corpus into :class:`Case`\\ s;
:func:`runs_for` derives the solver runs and their checks; :func:`solve` collects a
:class:`SolveOutcome` — what the solve determined, and how far the search behind it got; and
:func:`run_case` / :func:`render` run a case end-to-end and format its diagnostic.

**The three-valued verdict.** A check yields a :class:`Verdict` about the *program under
test*: ``PASS`` (the contract holds), ``FAIL`` (the program decided wrong), or ``UNDECIDED`` —
which covers both a solve that decided nothing and a search too partial for what this check reads.
``UNDECIDED`` is never conflated with FAIL or UNSAT. :func:`case_verdict` folds the reports.

**The error taxonomy (errors are never verdicts).** Four loud error families, distinct from the
``Verdict`` and disjoint from one another:

- :class:`ContractError` — an ill-formed ``@``-contract (``parse``). The *author* wrote a
  bad contract.
- :class:`DiscoveryError` — a corpus that violates a discovery-time precondition or matches no
  convention (``discover``). The *corpus* is mis-shaped. Its subclass
  :class:`SolverUnavailableError` reports a declared solver this environment does not have, and is
  also an :class:`ImportError`, so either idiom catches it.
- :class:`ProgramError` — a program elenctic cannot run: an unresolvable ``#include``, a parse
  error, or a program that will not ground. The *program under test* is broken, so its author fixes
  the ``.lp``.
- :class:`HarnessError` (and its subclasses :class:`RoutingError`, :class:`SeamError`) — an internal
  invariant elenctic itself violated: a stale route, a narrowing-seam breach. A *harness bug*, never
  a statement about the program under test, so the runner reports it under a distinct "harness
  error" status, never as a costumed verdict.

The first three are the author's to fix; the last is elenctic's. That cut is why ``ProgramError``
is not a ``HarnessError``: a broken program under test is not evidence of a broken harness.

**The three registers.** A whole run lands in a :class:`RunOutcome`, which keeps apart the three
kinds of thing a run produces: a :class:`CaseOutcome` per case that reached a verdict, an
:class:`ErrorRecord` per reason a verdict could not be produced, and a :class:`HygieneRecord` per
observation about the corpus's health — that one carrying the :class:`Grade` the run graded it,
since how loudly an observation is taken is a policy the caller sets and a consumer should be told
rather than left to re-derive. Every discovered case has exactly one home among the first two, and
:func:`summary` projects the counts out of them rather than tallying beside them — so a reader is
never shown fewer cases than exist with nothing said about where the rest went.

The curated surface is resolved **lazily** (PEP 562): importing ``elenctic`` does not eagerly load
every submodule, so ``import elenctic`` stays cheap (clingo loads only when a solver is actually
used) and ``python -m elenctic.<stage>`` runs a stage module without a re-import warning.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # static visibility for the lazily-resolved curated surface
    from elenctic.checks import CheckReport
    from elenctic.discovery import (
        Case,
        Corpus,
        DiscoveryError,
        HygieneReport,
        SolverUnavailableError,
        discover,
        inspect_corpus,
    )
    from elenctic.expectation import Claimed, ContractError, Expectation, Sat, Unsat, parse
    from elenctic.harness import case_verdict, render, run_case
    from elenctic.outcome import (
        CaseOutcome,
        ErrorKind,
        ErrorRecord,
        Grade,
        HygieneKind,
        HygieneRecord,
        RunOutcome,
        Scope,
        summary,
    )
    from elenctic.program import ProgramError
    from elenctic.query import Answer, Query
    from elenctic.registry import SOLVERS, Solver
    from elenctic.result import (
        Collection,
        Conclusion,
        Consistent,
        Determination,
        HarnessError,
        Inconclusive,
        Inconsistent,
        Observable,
        Optimum,
        SeamError,
        SolveOutcome,
        Verdict,
    )
    from elenctic.run import Mode, RoutingError, Run, runs_for
    from elenctic.solvers import solve

__version__ = "0.2.0"

# The curated public API, grouped by home module — the single source for both __all__ and the lazy
# resolver, so the two cannot drift. Internals (the Consistent shapes, accessors, check builders,
# Field) are deliberately absent.
_EXPORTS: dict[str, tuple[str, ...]] = {
    "elenctic.checks": ("CheckReport",),
    "elenctic.discovery": (
        "Case",
        "Corpus",
        "DiscoveryError",
        "HygieneReport",
        "SolverUnavailableError",
        "discover",
        "inspect_corpus",
    ),
    "elenctic.expectation": ("Claimed", "ContractError", "Expectation", "Sat", "Unsat", "parse"),
    "elenctic.harness": ("case_verdict", "render", "run_case"),
    "elenctic.outcome": (
        "CaseOutcome",
        "ErrorKind",
        "ErrorRecord",
        "HygieneKind",
        "HygieneRecord",
        "RunOutcome",
        "Scope",
        "Grade",
        "summary",
    ),
    "elenctic.program": ("ProgramError",),
    "elenctic.query": ("Answer", "Query"),
    "elenctic.registry": ("SOLVERS", "Solver"),
    "elenctic.result": (
        "Collection",
        "Conclusion",
        "Consistent",
        "Determination",
        "HarnessError",
        "Inconclusive",
        "Inconsistent",
        "Observable",
        "Optimum",
        "SeamError",
        "SolveOutcome",
        "Verdict",
    ),
    "elenctic.run": ("Mode", "RoutingError", "Run", "runs_for"),
    "elenctic.solvers": ("solve",),
}

_HOME: dict[str, str] = {name: module for module, names in _EXPORTS.items() for name in names}

__all__ = sorted([*_HOME, "__version__"])


def __getattr__(name: str) -> object:
    """Lazily resolve a curated export (PEP 562) from its home submodule."""
    module = _HOME.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    return list(__all__)
