"""Outcome data types: Observable, SolveResult, Verdict.

A :class:`SolveResult` is the (partial) record of one configured solver run over
the *observable* (spec §2.0/§3). Checks (``checks.py``) are pure functions of a
:class:`SolveResult`; only ``solvers.py`` constructs one.
"""

from dataclasses import dataclass
from enum import Enum

from clingo import Symbol


@dataclass(frozen=True, slots=True)
class Observable:
    """One answer set as the program makes it observable (spec §2.0).

    ``shown`` is the projection onto ``#show``-declared predicates; ``assign`` is
    the theory (CSP) assignment, empty for pure clingo. Two answer sets with equal
    ``shown`` but different ``assign`` are distinct observables (spec §2.0, TR4),
    which the value equality of this frozen dataclass realises directly.
    """

    shown: frozenset[Symbol]
    assign: frozenset[tuple[Symbol, int]] = frozenset()


class Verdict(Enum):
    """Three-valued check outcome (spec §3). ``UNDECIDED`` is never ``FAIL`` (spec §7a)."""

    PASS = "pass"
    FAIL = "fail"
    UNDECIDED = "undecided"


@dataclass(frozen=True, slots=True)
class SolveResult:
    """The (partial) outcome of one configured run over the observable (spec §3).

    A run populates only the fields its mode produces: an enumeration run sets
    ``observables`` (and, being a full enumeration, ``union``/``intersection``); a
    native cautious/brave run sets ``intersection``/``union``; an optimisation run
    sets ``optimum_cost``/``optimal_observables``. ``completed`` is ``False`` on
    timeout, which every check maps to ``UNDECIDED`` (spec §7a).

    ``None`` and ``()`` are distinct on purpose: ``intersection is None`` means the
    cautious aggregate was never computed (no run, or ``AS(P) = ∅``), whereas an
    empty ``frozenset()`` is a real intersection with no shared atom.
    """

    completed: bool
    observables: tuple[Observable, ...] = ()
    union: frozenset[Symbol] | None = None
    intersection: frozenset[Symbol] | None = None
    optimum_cost: tuple[int, ...] | None = None
    optimal_observables: tuple[Observable, ...] = ()
