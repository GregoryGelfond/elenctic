"""Outcome data types: ``Observable``, ``Verdict``, and the ``Determination`` (spec §3, §5).

A solved program yields a :data:`Determination` — aspis's three-arm outcome surface
(``~/Projects/aspis/docs/spec.md §5``): :class:`Inconsistent` (AS(P)=∅), :class:`Inconclusive`
(the solve was cut off), or one of the :class:`Consistent` family. Each ``Consistent`` shape carries
*exactly* the observations its run-mode computes, so a field's absence is a type fact, not a
sentinel — there is no ``NotConfigured`` and no per-field guard.

A check reads a field through one accessor (``*_of``); the single centralised ``_seam_violation`` is
the one narrowing assertion, unreachable through the supported path on **two** premises: (1) the
``reads ⊆ populates`` wiring rule (``run.py``) attaches a check only to a run whose mode populates
what it reads, and (2) the lowering postcondition — ``solvers.py`` produces, for a run of mode M,
exactly the ``Consistent`` shape whose fields are ``populates(M)``. Checks (``checks.py``) are pure
functions of a ``Determination``; only ``solvers.py`` constructs one.
"""

from dataclasses import dataclass
from enum import Enum
from typing import NoReturn, final

from clingo import Symbol

from elenctic.terms import intersect_all, union_all

__all__ = [
    "Consistent",
    "ConsistentBrave",
    "ConsistentCautious",
    "ConsistentEnumeration",
    "ConsistentOptimalEnumeration",
    "ConsistentOptimum",
    "ConsistentWitness",
    "Determination",
    "Field",
    "HarnessError",
    "Inconclusive",
    "Inconsistent",
    "Observable",
    "Optimum",
    "SeamError",
    "Verdict",
    "brave_of",
    "brave_optimal_of",
    "cautious_of",
    "cautious_optimal_of",
    "observables_of",
    "optimal_observables_of",
    "optimum_of",
    "witness_of",
]


@dataclass(frozen=True, slots=True)
class Observable:
    """One answer set as the program makes it observable (spec §2.0).

    ``shown`` is the projection onto ``#show``-declared predicates; ``assign`` is the theory (CSP)
    assignment, empty for pure clingo. Two answer sets with equal ``shown`` but different ``assign``
    are distinct observables (spec §2.0, TR4), which the value equality of this frozen dataclass
    realises directly.

    Invariant (single-valued, not enforced by the type): ``assign`` holds at most one ``(v, k)`` per
    CSP variable ``v`` — the hashable realisation of the spec's ``Mapping[Symbol, int]`` (§3); the
    solver facade constructs it so.
    """

    shown: frozenset[Symbol]
    assign: frozenset[tuple[Symbol, int]] = frozenset()


class Verdict(Enum):
    """Three-valued check outcome (spec §3). ``UNDECIDED`` is never ``FAIL`` (spec §7a)."""

    PASS = "pass"
    FAIL = "fail"
    UNDECIDED = "undecided"


class Field(Enum):
    """A gated observation a ``Consistent`` outcome can provide — the wiring-rule vocabulary
    (``Check.reads`` ⊆ ``populates(mode)`` in ``run.py``). Six capabilities, one per readable field;
    the explain/dry-run surface narrates these, so they stay user-legible."""

    WITNESS = "witness"
    OBSERVABLES = "observables"
    CAUTIOUS = "cautious"
    BRAVE = "brave"
    OPTIMAL_OBSERVABLES = "optimal observables"
    OPTIMUM = "optimum"


@dataclass(frozen=True, slots=True)
class Optimum:
    """The proven optimum of an optimisation run (aspis register, §5). ``cost`` is the
    priority-ordered (lexicographic) cost vector, compared positionally (spec §2.0), never a scalar.

    Read it as a proof-token of *proven* optimality: by construction convention only ``solvers.py``
    builds one, and only once the optimum is proven, so a best-so-far never reaches a check. Python
    has no private constructor (as aspis's Rust does), so this is a construction convention, not a
    type guarantee — sound because checks are pure readers that never mint a result.
    """

    cost: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.cost:
            raise ValueError("an Optimum carries a non-empty priority-ordered cost vector")


@dataclass(frozen=True, slots=True)
class Inconsistent:
    """AS(P) = ∅: the program has no answer set, exhaustively determined (spec §5). A check reads
    the arm, not a field — ``@expect unsat`` PASSes here, every other tag FAILs."""


@dataclass(frozen=True, slots=True)
class Inconclusive:
    """The solve was cut off before deciding (timeout). §7a: every check → ``UNDECIDED``. Carries no
    fields, so reading an answer off a timed-out solve is inexpressible."""


class Consistent:
    """Marker base of the SAT family (the program has ≥1 answer set). Each concrete shape carries
    *exactly* the observations its run-mode computes; a field's absence is a type fact, not a
    sentinel, so there are no ``NotConfigured`` states and no per-field guards. Abstract: construct
    one of the six concrete shapes, never ``Consistent`` itself."""

    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> Consistent:
        if cls is Consistent:
            raise TypeError("Consistent is abstract; construct one of the six concrete shapes")
        return super().__new__(cls)


@final
@dataclass(frozen=True, slots=True)
class ConsistentWitness(Consistent):
    """``DEFAULT``: a single satisfiability witness (the ≤1-model solve), for ``@expect``'s
    counter-model diagnostic."""

    witness: Observable


@final
@dataclass(frozen=True, slots=True)
class ConsistentEnumeration(Consistent):
    """``ENUM_ALL``: the complete answer-set census. The cautious ⋂ and brave ⋃ are *views* of it
    (derived by ``cautious_of`` / ``brave_of``), never stored, so they cannot disagree with the
    census — single source of truth. Carries ≥1 observable by construction (Consistent ⟹ AS(P)≠∅),
    which makes ``query.conjunctive_answer``'s non-empty-census precondition hold structurally."""

    observables: tuple[Observable, ...]

    def __post_init__(self) -> None:
        if not self.observables:
            raise ValueError("a ConsistentEnumeration carries ≥1 observable (AS(P) ≠ ∅)")


@final
@dataclass(frozen=True, slots=True)
class ConsistentCautious(Consistent):
    """``CAUTIOUS_ALL``: the cautious consequences ⋂ alone (clingo-emitted; no census to derive
    from)."""

    cautious: frozenset[Symbol]


@final
@dataclass(frozen=True, slots=True)
class ConsistentBrave(Consistent):
    """``BRAVE_ALL``: the brave consequences ⋃ alone (clingo-emitted; no census to derive from)."""

    brave: frozenset[Symbol]


@final
@dataclass(frozen=True, slots=True)
class ConsistentOptimalEnumeration(Consistent):
    """``OPT_ENUM``: the enumerated optimal class Opt(P), with the proven optimum. Carries ≥1
    optimal model by construction (Consistent ⟹ Opt(P)≠∅). The optimal-models census; pairs with
    :class:`ConsistentEnumeration` (all models)."""

    optimal_observables: tuple[Observable, ...]
    optimum: Optimum

    def __post_init__(self) -> None:
        if not self.optimal_observables:
            raise ValueError("a ConsistentOptimalEnumeration carries ≥1 optimal model (Opt(P) ≠ ∅)")


@final
@dataclass(frozen=True, slots=True)
class ConsistentOptimum(Consistent):
    """``OPT``: the proven optimum cost alone (no optimal-class enumeration)."""

    optimum: Optimum


type Determination = Inconsistent | Inconclusive | Consistent


# --- harness-internal errors (never a Verdict; the runner reports them as harness errors) ---


class HarnessError(Exception):
    """Root of elenctic's own bugs — an internal invariant the harness violated, never a statement
    about the program under test, so never a ``Verdict``. The runner reports these under a distinct
    "harness error" status. Raised explicitly (not via ``assert``), so it survives ``python -O``."""


class SeamError(HarnessError):
    """A check read a field off a ``Consistent`` shape that does not populate it — the one
    provably-unreachable narrowing assertion fired, unreachable on **two** premises: the
    ``reads ⊆ populates`` wiring rule (the primary guard, ``run.py``) attaches a check only to a
    run whose mode populates what it reads; and the ``solvers.py`` lowering postcondition produces,
    for a run of mode M, the shape whose fields are exactly ``populates(M)``. If it fires, one of
    those was violated — an elenctic bug, never a verdict."""


def _seam_violation(field: Field, shape: Consistent) -> NoReturn:
    """The one centralised narrowing assertion: every accessor's unreachable case funnels here."""
    raise SeamError(
        f"narrowing seam: {field.value} read off {type(shape).__name__}, which does not populate "
        "it — the reads ⊆ populates wiring rule was bypassed (an elenctic bug, not a test outcome)"
    )


# --- consequence views derived from the census (single source of truth) ---


def _shown_intersection(observables: tuple[Observable, ...]) -> frozenset[Symbol]:
    """⋂ of the census's shown projections (observables is non-empty by the shape's invariant)."""
    return intersect_all(tuple(observable.shown for observable in observables))


def _shown_union(observables: tuple[Observable, ...]) -> frozenset[Symbol]:
    """⋃ of the census's shown projections."""
    return union_all(tuple(observable.shown for observable in observables))


# --- the accessor seam: read one field, narrowing to the shapes that populate it ---


def witness_of(shape: Consistent) -> Observable:
    """The DEFAULT satisfiability witness (``Field.WITNESS``)."""
    match shape:
        case ConsistentWitness():
            return shape.witness
        case _:
            _seam_violation(Field.WITNESS, shape)


def observables_of(shape: Consistent) -> tuple[Observable, ...]:
    """The complete answer-set census (``Field.OBSERVABLES``)."""
    match shape:
        case ConsistentEnumeration():
            return shape.observables
        case _:
            _seam_violation(Field.OBSERVABLES, shape)


def cautious_of(shape: Consistent) -> frozenset[Symbol]:
    """The cautious consequences ⋂ (``Field.CAUTIOUS``): stored for the native cautious run, derived
    from the census for a full enumeration (single source of truth)."""
    match shape:
        case ConsistentCautious():
            return shape.cautious
        case ConsistentEnumeration():
            return _shown_intersection(shape.observables)
        case _:
            _seam_violation(Field.CAUTIOUS, shape)


def brave_of(shape: Consistent) -> frozenset[Symbol]:
    """The brave consequences ⋃ (``Field.BRAVE``): stored for the native brave run, derived from the
    census for a full enumeration."""
    match shape:
        case ConsistentBrave():
            return shape.brave
        case ConsistentEnumeration():
            return _shown_union(shape.observables)
        case _:
            _seam_violation(Field.BRAVE, shape)


def optimal_observables_of(shape: Consistent) -> tuple[Observable, ...]:
    """The enumerated optimal class Opt(P) (``Field.OPTIMAL_OBSERVABLES``)."""
    match shape:
        case ConsistentOptimalEnumeration():
            return shape.optimal_observables
        case _:
            _seam_violation(Field.OPTIMAL_OBSERVABLES, shape)


def optimum_of(shape: Consistent) -> Optimum:
    """The proven optimum (``Field.OPTIMUM``)."""
    match shape:
        case ConsistentOptimum() | ConsistentOptimalEnumeration():
            return shape.optimum
        case _:
            _seam_violation(Field.OPTIMUM, shape)


def cautious_optimal_of(shape: Consistent) -> frozenset[Symbol]:
    """⋂ Opt(P): the cautious consequences over the optimal class, derived from the optimal census
    (the optimal-base counterpart of :func:`cautious_of`; reads ``Field.OPTIMAL_OBSERVABLES``)."""
    return _shown_intersection(optimal_observables_of(shape))


def brave_optimal_of(shape: Consistent) -> frozenset[Symbol]:
    """⋃ Opt(P): the brave consequences over the optimal class (the optimal-base counterpart of
    :func:`brave_of`; reads ``Field.OPTIMAL_OBSERVABLES``)."""
    return _shown_union(optimal_observables_of(shape))
