r"""elenctic — a declarative testing framework for Answer Set Programming.

The reference implementation of a language-parametric ``@``-contract format over the *observable*
of an answer-set program (shown atoms + theory assignment). A contract is parsed (:func:`parse`)
into an :data:`Expectation`; :func:`discover` walks a corpus into :class:`Case`\ s;
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

**Running a corpus.** :func:`run_corpus` takes an :class:`Invocation` — the settled form of a
command line — and returns a :class:`RunOutcome`; :func:`explain_corpus` derives the run plans
instead and returns a :class:`PlanOutcome`; :func:`exit_status` reads either against the
:class:`ExitStatus` ladder, and :func:`as_json` renders one as the published document. Both runners
are silent, and a caller who wants to watch a long run as it happens supplies a
:class:`RunObserver` or a :class:`PlanObserver`, which is told each verdict, plan and fault as it
is established. ``elenctic.cli`` is these five calls with a command line in front of them; a
consumer who wants elenctic's results somewhere else has the same pieces, and can equally work one
case at a time with :func:`run_case`.

The curated surface is resolved **lazily** (PEP 562): importing ``elenctic`` does not eagerly load
every submodule, so ``import elenctic`` stays cheap (clingo loads only when a solver is actually
used) and ``python -m elenctic.<stage>`` runs a stage module without a re-import warning.
"""

import logging
from typing import TYPE_CHECKING

# What a library owes its own logger. Without it, this package's first record would be emitted by
# logging's last-resort handler — which writes to standard error — so a library that has been
# careful to write to no stream would write to one the moment something inside it had a debugging
# remark to make. With it, elenctic says nothing until the program embedding it configures logging
# and asks; the records are there either way. This is the documented practice for a library, and it
# is the same rule the rest of this package follows for a different reason: a diagnostic a *user*
# acts on is a structured record, and a logger carries only what a *developer* acts on.
logging.getLogger(__name__).addHandler(logging.NullHandler())

if TYPE_CHECKING:  # static visibility for the lazily-resolved curated surface
    from elenctic.checks import CheckReport as CheckReport
    from elenctic.corpus import (
        Observer as Observer,
        PlanObserver as PlanObserver,
        RunObserver as RunObserver,
        explain_corpus as explain_corpus,
        run_corpus as run_corpus,
    )
    from elenctic.discovery import (
        Case as Case,
        Corpus as Corpus,
        DiscoveryError as DiscoveryError,
        HygieneReport as HygieneReport,
        SolverUnavailableError as SolverUnavailableError,
        discover as discover,
        inspect_corpus as inspect_corpus,
    )
    from elenctic.display import legible as legible
    from elenctic.expectation import (
        Claimed as Claimed,
        ContractError as ContractError,
        Expectation as Expectation,
        Sat as Sat,
        Unsat as Unsat,
        parse as parse,
    )
    from elenctic.harness import (
        case_verdict as case_verdict,
        render as render,
        run_case as run_case,
    )
    from elenctic.json_report import (
        SCHEMA_VERSION as SCHEMA_VERSION,
        as_json as as_json,
        dumps as dumps,
        schema_text as schema_text,
    )
    from elenctic.outcome import (
        CaseOutcome as CaseOutcome,
        CasePlan as CasePlan,
        ErrorKind as ErrorKind,
        ErrorRecord as ErrorRecord,
        ExitStatus as ExitStatus,
        Grade as Grade,
        HygieneKind as HygieneKind,
        HygieneRecord as HygieneRecord,
        Invocation as Invocation,
        Outcome as Outcome,
        PlanOutcome as PlanOutcome,
        RunOutcome as RunOutcome,
        Scope as Scope,
        error_kind as error_kind,
        exit_status as exit_status,
        is_duration as is_duration,
        summary as summary,
    )
    from elenctic.program import ProgramError as ProgramError
    from elenctic.query import Answer as Answer, Query as Query
    from elenctic.registry import SOLVERS as SOLVERS, Solver as Solver
    from elenctic.result import (
        Collection as Collection,
        Conclusion as Conclusion,
        Consistent as Consistent,
        Determination as Determination,
        HarnessError as HarnessError,
        Inconclusive as Inconclusive,
        Inconsistent as Inconsistent,
        Observable as Observable,
        Optimum as Optimum,
        SeamError as SeamError,
        SolveOutcome as SolveOutcome,
        Verdict as Verdict,
    )
    from elenctic.run import (
        Mode as Mode,
        RoutingError as RoutingError,
        Run as Run,
        runs_for as runs_for,
    )
    from elenctic.solvers import TIME_BUDGET as TIME_BUDGET, solve as solve

__version__ = "0.3.0"

# The curated public API, grouped by home module — the single source for both __all__ and the lazy
# resolver, so the two cannot drift. Internals (the Consistent shapes, accessors, check builders,
# Field) are deliberately absent.
_EXPORTS: dict[str, tuple[str, ...]] = {
    "elenctic.checks": ("CheckReport",),
    "elenctic.corpus": (
        "Observer",
        "PlanObserver",
        "RunObserver",
        "explain_corpus",
        "run_corpus",
    ),
    "elenctic.display": ("legible",),
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
    "elenctic.json_report": ("SCHEMA_VERSION", "as_json", "dumps", "schema_text"),
    "elenctic.outcome": (
        "CaseOutcome",
        "CasePlan",
        "ErrorKind",
        "ErrorRecord",
        "ExitStatus",
        "HygieneKind",
        "HygieneRecord",
        "Invocation",
        "Outcome",
        "PlanOutcome",
        "RunOutcome",
        "Grade",
        "Scope",
        "error_kind",
        "exit_status",
        "is_duration",
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
    "elenctic.solvers": ("TIME_BUDGET", "solve"),
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
