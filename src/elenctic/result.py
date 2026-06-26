"""Outcome data types: ``Observable``, ``Verdict``, and the ``Determination``.

A solved program yields a :data:`Determination` — a three-arm outcome surface:
:class:`Inconsistent` (AS(P)=∅), :class:`Inconclusive`
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
    "ConsistentShownCensus",
    "ConsistentShownOptimalCensus",
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
    "shown_census_of",
    "shown_optimal_census_of",
    "witness_of",
]


@dataclass(frozen=True, slots=True)
class Observable:
    """One answer set as the program makes it observable.

    ``shown`` is the projection onto ``#show``-declared predicates; ``assign`` is the theory (CSP)
    assignment, empty for pure clingo. Two answer sets with equal ``shown`` but different ``assign``
    are distinct observables, which the value equality of this frozen dataclass
    realises directly.

    Invariant (single-valued, not enforced by the type): ``assign`` holds at most one ``(v, k)`` per
    CSP variable ``v`` — the hashable realisation of a ``Mapping[Symbol, int]``; the
    solver facade constructs it so.
    """

    shown: frozenset[Symbol]
    assign: frozenset[tuple[Symbol, int]] = frozenset()


class Verdict(Enum):
    """Three-valued check outcome. ``UNDECIDED`` is never ``FAIL``."""

    PASS = "pass"
    FAIL = "fail"
    UNDECIDED = "undecided"


class Field(Enum):
    """A gated observation a ``Consistent`` outcome can provide — the wiring-rule vocabulary
    (``Check.reads`` ⊆ ``populates(mode, projects_to_shown)`` in ``run.py``). The census splits
    into a shown view (projection-invariant) and a full view (projection-sensitive): a check reading
    the full view suppresses projection, one reading only the shown view rides a projecting run. The
    explain/dry-run surface narrates these, so they stay user-legible."""

    WITNESS = "witness"
    SHOWN_CENSUS = "shown census"
    FULL_CENSUS = "full census"
    CAUTIOUS = "cautious"
    BRAVE = "brave"
    SHOWN_OPTIMAL_CENSUS = "shown optimal census"
    FULL_OPTIMAL_CENSUS = "full optimal census"
    OPTIMUM = "optimum"


@dataclass(frozen=True, slots=True)
class Optimum:
    """The proven optimum of an optimisation run. ``cost`` is the
    priority-ordered (lexicographic) cost vector, compared positionally, never a scalar.

    Read it as a proof-token of *proven* optimality: by construction convention only ``solvers.py``
    builds one, and only once the optimum is proven, so a best-so-far never reaches a check. Python
    has no private constructor, so this is a construction convention, not a
    type guarantee — sound because checks are pure readers that never mint a result.
    """

    cost: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.cost:
            raise ValueError("an Optimum carries a non-empty priority-ordered cost vector")


@dataclass(frozen=True, slots=True)
class Inconsistent:
    """AS(P) = ∅: the program has no answer set, exhaustively determined. A check reads
    the arm, not a field — ``@expect unsat`` PASSes here, every other tag FAILs."""


@dataclass(frozen=True, slots=True)
class Inconclusive:
    """The solve was cut off before deciding (timeout). Every check → ``UNDECIDED``. Carries no
    fields, so reading an answer off a timed-out solve is inexpressible."""


class Consistent:
    """Marker base of the SAT family (the program has ≥1 answer set). Each concrete shape carries
    *exactly* the observations its run-mode computes; a field's absence is a type fact, not a
    sentinel, so there are no ``NotConfigured`` states and no per-field guards. Abstract: construct
    one of the eight concrete shapes, never ``Consistent`` itself."""

    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> Consistent:
        if cls is Consistent:
            raise TypeError("Consistent is abstract; construct one of the eight concrete shapes")
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
class ConsistentShownCensus(Consistent):
    """``ENUM_ALL`` projected to shown (a theory solver run under ``--project``): the *set* of shown
    projections, theory multiplicity erased. Carries ≥1 shown class by construction
    (Consistent ⟹ AS(P)≠∅). The full census (multiplicity + assignment) is irrecoverable from the
    shown set — a different object, not a coarser view of one — so reading it is a ``SeamError``."""

    shown_census: frozenset[frozenset[Symbol]]

    def __post_init__(self) -> None:
        if not self.shown_census:
            raise ValueError("a ConsistentShownCensus carries ≥1 shown class (AS(P) ≠ ∅)")


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
    """``OPTIMAL_ENUM``: the enumerated optimal class Opt(P), with the proven optimum. Carries ≥1
    optimal model by construction (Consistent ⟹ Opt(P)≠∅). The optimal-models census; pairs with
    :class:`ConsistentEnumeration` (all models)."""

    optimal_observables: tuple[Observable, ...]
    optimum: Optimum

    def __post_init__(self) -> None:
        if not self.optimal_observables:
            raise ValueError("a ConsistentOptimalEnumeration carries ≥1 optimal model (Opt(P) ≠ ∅)")


@final
@dataclass(frozen=True, slots=True)
class ConsistentShownOptimalCensus(Consistent):
    """``OPTIMAL_ENUM`` projected to shown: the *set* of shown projections of Opt(P), with the
    proven optimum — what lets the shown-only optimal modes terminate when a theory solver would
    otherwise enumerate an astronomically large optimal class. The full optimal class is withheld
    (a ``SeamError``); ``optimum`` is projection-invariant and kept."""

    shown_census: frozenset[frozenset[Symbol]]
    optimum: Optimum

    def __post_init__(self) -> None:
        if not self.shown_census:
            raise ValueError("a ConsistentShownOptimalCensus carries ≥1 shown class (Opt(P) ≠ ∅)")


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


def _meet(census: frozenset[frozenset[Symbol]]) -> frozenset[Symbol]:
    """⋂ of a non-empty set of shown projections (the shape invariant guarantees non-empty)."""
    return intersect_all(tuple(census))


def _join(census: frozenset[frozenset[Symbol]]) -> frozenset[Symbol]:
    """⋃ of a non-empty set of shown projections."""
    return union_all(tuple(census))


# --- the accessor seam: read one field, narrowing to the shapes that populate it ---


def witness_of(shape: Consistent) -> Observable:
    """The DEFAULT satisfiability witness (``Field.WITNESS``)."""
    match shape:
        case ConsistentWitness():
            return shape.witness
        case _:
            _seam_violation(Field.WITNESS, shape)


def shown_census_of(shape: Consistent) -> frozenset[frozenset[Symbol]]:
    """The set of shown projections ``{shown(M)}`` (``Field.SHOWN_CENSUS``): derived from the census
    on the full shape, stored on the projected shape. Projection-invariant — its cardinality is the
    shown-distinct count, which ``@count`` (wanting the theory-distinct count) cannot read here."""
    match shape:
        case ConsistentEnumeration():
            return frozenset(observable.shown for observable in shape.observables)
        case ConsistentShownCensus():
            return shape.shown_census
        case _:
            _seam_violation(Field.SHOWN_CENSUS, shape)


def observables_of(shape: Consistent) -> tuple[Observable, ...]:
    """The complete answer-set census, with multiplicity and theory assignment
    (``Field.FULL_CENSUS``) — narrows to the full shape; unreadable off a projected shown-only
    shape (the multiplicity/assignment was erased by ``--project`` and cannot be recovered)."""
    match shape:
        case ConsistentEnumeration():
            return shape.observables
        case _:
            _seam_violation(Field.FULL_CENSUS, shape)


def cautious_of(shape: Consistent) -> frozenset[Symbol]:
    """The cautious consequences ⋂ (``Field.CAUTIOUS``): stored for the native cautious run, derived
    from the shown census for either enumeration shape (single source of truth)."""
    match shape:
        case ConsistentCautious():
            return shape.cautious
        case ConsistentEnumeration() | ConsistentShownCensus():
            return _meet(shown_census_of(shape))
        case _:
            _seam_violation(Field.CAUTIOUS, shape)


def brave_of(shape: Consistent) -> frozenset[Symbol]:
    """The brave consequences ⋃ (``Field.BRAVE``): stored for the native brave run, derived from the
    shown census for either enumeration shape."""
    match shape:
        case ConsistentBrave():
            return shape.brave
        case ConsistentEnumeration() | ConsistentShownCensus():
            return _join(shown_census_of(shape))
        case _:
            _seam_violation(Field.BRAVE, shape)


def shown_optimal_census_of(shape: Consistent) -> frozenset[frozenset[Symbol]]:
    """The set of shown projections of Opt(P) (``Field.SHOWN_OPTIMAL_CENSUS``): derived on the full
    optimal shape, stored on the projected one."""
    match shape:
        case ConsistentOptimalEnumeration():
            return frozenset(observable.shown for observable in shape.optimal_observables)
        case ConsistentShownOptimalCensus():
            return shape.shown_census
        case _:
            _seam_violation(Field.SHOWN_OPTIMAL_CENSUS, shape)


def optimal_observables_of(shape: Consistent) -> tuple[Observable, ...]:
    """The enumerated optimal class Opt(P) with multiplicity/assignment
    (``Field.FULL_OPTIMAL_CENSUS``) — narrows to the full optimal shape; withheld off the projected
    one."""
    match shape:
        case ConsistentOptimalEnumeration():
            return shape.optimal_observables
        case _:
            _seam_violation(Field.FULL_OPTIMAL_CENSUS, shape)


def optimum_of(shape: Consistent) -> Optimum:
    """The proven optimum (``Field.OPTIMUM``) — every optimal shape carries it
    (projection-invariant)."""
    match shape:
        case ConsistentOptimum() | ConsistentOptimalEnumeration() | ConsistentShownOptimalCensus():
            return shape.optimum
        case _:
            _seam_violation(Field.OPTIMUM, shape)


def cautious_optimal_of(shape: Consistent) -> frozenset[Symbol]:
    """⋂ Opt(P): the cautious consequences over the optimal class, derived from the shown optimal
    census (the optimal-base counterpart of :func:`cautious_of`; reads
    ``Field.SHOWN_OPTIMAL_CENSUS``)."""
    return _meet(shown_optimal_census_of(shape))


def brave_optimal_of(shape: Consistent) -> frozenset[Symbol]:
    """⋃ Opt(P): the brave consequences over the optimal class (reads
    ``Field.SHOWN_OPTIMAL_CENSUS``)."""
    return _join(shown_optimal_census_of(shape))
