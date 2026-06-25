"""elenctic — a declarative testing framework for Answer Set Programming.

The reference implementation of a language-neutral ``@``-contract format over the *observable* of an
answer-set program (shown atoms + theory assignment). A contract is parsed (:func:`parse`) into an
:data:`Expectation`; :func:`discover` walks a corpus into :class:`Case`\\ s; :func:`runs_for`
derives the solver runs and their checks; :func:`solve` collects a :data:`Determination`; and
:func:`run_case` / :func:`render` run a case end-to-end and format its diagnostic. See the design
spec for the denotational semantics of each tag.

**The three-valued verdict (§7a).** A check yields a :class:`Verdict` about the *program under
test*: ``PASS`` (the contract holds), ``FAIL`` (the program decided wrong), or ``UNDECIDED`` (the
solve was cut off — never conflated with FAIL or UNSAT). :func:`case_verdict` folds the reports.

**The error taxonomy (errors are never verdicts).** Three loud error families, distinct from the
``Verdict``:

- :class:`ContractError` — an ill-formed ``@``-contract (``parse``, spec §2.2). The *author* wrote a
  bad contract.
- :class:`DiscoveryError` — a corpus that violates a discovery-time precondition or matches no
  convention (``discover``, spec §5). The *corpus* is mis-shaped.
- :class:`HarnessError` (and its subclasses :class:`RoutingError`, :class:`SeamError`) — an internal
  invariant elenctic itself violated: a stale route, a narrowing-seam breach. A *harness bug*, never
  a statement about the program under test, so the runner reports it under a distinct "harness
  error" status, never as a costumed verdict.

The curated surface is resolved **lazily** (PEP 562): importing ``elenctic`` does not eagerly load
every submodule, so ``import elenctic`` stays cheap (clingo loads only when a solver is actually
used) and ``python -m elenctic.<stage>`` runs a stage module without a re-import warning.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # static visibility for the lazily-resolved curated surface
    from elenctic.checks import CheckReport
    from elenctic.discovery import Case, DiscoveryError, Layout, discover
    from elenctic.expectation import ContractError, Expectation, Sat, Unsat, parse
    from elenctic.harness import case_verdict, render, run_case
    from elenctic.query import Answer, Query
    from elenctic.registry import SOLVERS, Solver
    from elenctic.result import (
        Consistent,
        Determination,
        HarnessError,
        Inconclusive,
        Inconsistent,
        Observable,
        Optimum,
        SeamError,
        Verdict,
    )
    from elenctic.run import Mode, RoutingError, Run, runs_for
    from elenctic.solvers import solve

__version__ = "0.1.0"

# The curated public API, grouped by home module — the single source for both __all__ and the lazy
# resolver, so the two cannot drift. Internals (the Consistent shapes, accessors, check builders,
# Field) are deliberately absent (dx#11).
_EXPORTS: dict[str, tuple[str, ...]] = {
    "elenctic.checks": ("CheckReport",),
    "elenctic.discovery": ("Case", "DiscoveryError", "Layout", "discover"),
    "elenctic.expectation": ("ContractError", "Expectation", "Sat", "Unsat", "parse"),
    "elenctic.harness": ("case_verdict", "render", "run_case"),
    "elenctic.query": ("Answer", "Query"),
    "elenctic.registry": ("SOLVERS", "Solver"),
    "elenctic.result": (
        "Consistent",
        "Determination",
        "HarnessError",
        "Inconclusive",
        "Inconsistent",
        "Observable",
        "Optimum",
        "SeamError",
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
