"""Outcome data types: ``Observable``, ``Verdict``, and the ``Determination`` (spec §3, §5).

A solved program yields a :data:`Determination` — aspis's three-arm outcome surface
(``~/Projects/aspis/docs/spec.md §5``): :class:`Inconsistent` (AS(P)=∅), :class:`Inconclusive`
(the solve was cut off), or one of the :class:`Consistent` family. Under depth D each ``Consistent``
shape carries *exactly* the observations its run-mode computes, so a field's absence is a type fact,
not a sentinel — there is no ``NotConfigured`` and no per-field guard (the field-compatibility
keystone). A check reads a field through one accessor (``*_of``); the single centralised
``_seam_violation`` is the one provably-unreachable narrowing assertion (the wiring rule in
``run.py`` makes it unreachable through the supported path). Checks (``checks.py``) are pure
functions of a ``Determination``; only ``solvers.py`` constructs one.
"""

from dataclasses import dataclass
from enum import Enum
from typing import NoReturn

from clingo import Symbol


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
    (``Check.reads`` ⊆ ``run.populates(mode)``). Six capabilities, one per readable field; the
    explain/dry-run surface narrates these, so they stay user-legible."""

    WITNESS = "witness"
    OBSERVABLES = "observables"
    CAUTIOUS = "cautious"
    BRAVE = "brave"
    OPTIMAL_OBSERVABLES = "optimal observables"
    OPTIMUM = "optimum"


@dataclass(frozen=True, slots=True)
class Optimum:
    """A proof-token of proven optimality (aspis register, §5). Constructed only by the solver
    facade once the optimum is *proven*, so holding one is the proof — a best-so-far cannot
    masquerade. ``cost`` is the priority-ordered (lexicographic) cost vector, compared positionally
    (spec §2.0); never a scalar."""

    cost: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Inconsistent:
    """AS(P) = ∅: the program has no answer set, exhaustively determined (spec §5). A check reads
    the arm, not a field — ``@expect unsat`` PASSes here, every other tag FAILs."""


@dataclass(frozen=True, slots=True)
class Inconclusive:
    """The solve was cut off before deciding (timeout). §7a: every check → ``UNDECIDED``. Carries no
    fields, so reading an answer off a timed-out solve is inexpressible."""


class Consistent:
    """Marker base of the SAT family (the program has ≥1 answer set). Depth D — each concrete
    shape carries *exactly* the observations its run-mode computes; a field's absence is a type
    fact, not a sentinel, so there are no ``NotConfigured`` states and no per-field guards."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class ConsistentWitness(Consistent):
    """``DEFAULT``: a single satisfiability witness (the ≤1-model solve), for ``@expect``'s
    counter-model diagnostic."""

    witness: Observable


@dataclass(frozen=True, slots=True)
class ConsistentEnumeration(Consistent):
    """``ENUM_ALL``: the complete answer-set census, with the derived cautious ⋂ and brave ⋃.

    Carries ≥1 observable by construction (Consistent ⟹ AS(P)≠∅) — enforced below, which makes
    ``query.conjunctive_answer``'s non-empty-census precondition hold structurally (a result-shape
    invariant, distinct from that function's own boundary guard)."""

    observables: tuple[Observable, ...]
    cautious: frozenset[Symbol]
    brave: frozenset[Symbol]

    def __post_init__(self) -> None:
        if not self.observables:
            raise ValueError("a ConsistentEnumeration carries ≥1 observable (AS(P) ≠ ∅)")


@dataclass(frozen=True, slots=True)
class ConsistentCautious(Consistent):
    """``CAUTIOUS_ALL``: the cautious consequences ⋂ alone."""

    cautious: frozenset[Symbol]


@dataclass(frozen=True, slots=True)
class ConsistentBrave(Consistent):
    """``BRAVE_ALL``: the brave consequences ⋃ alone."""

    brave: frozenset[Symbol]


@dataclass(frozen=True, slots=True)
class ConsistentOptimalClass(Consistent):
    """``OPT_ENUM``: the enumerated optimal class Opt(P), with the proven optimum. Carries ≥1
    optimal model by construction (Consistent ⟹ Opt(P)≠∅)."""

    optimal_observables: tuple[Observable, ...]
    optimum: Optimum

    def __post_init__(self) -> None:
        if not self.optimal_observables:
            raise ValueError("a ConsistentOptimalClass carries ≥1 optimal model (Opt(P) ≠ ∅)")


@dataclass(frozen=True, slots=True)
class ConsistentOptimum(Consistent):
    """``OPT``: the proven optimum cost alone (no optimal-class enumeration)."""

    optimum: Optimum


type Determination = Inconsistent | Inconclusive | Consistent


class SeamError(AssertionError):
    """A check read a field off a ``Consistent`` shape that does not populate it — the
    ``reads ⊆ populates`` wiring rule (``run.py``) was violated. An elenctic bug, never a verdict.
    Subclasses ``AssertionError`` for its category, but is raised explicitly (not via ``assert``),
    so it survives ``python -O``."""


def _seam_violation(field: Field, shape: Consistent) -> NoReturn:
    """The one centralised narrowing assertion: every accessor funnels its unreachable case here."""
    raise SeamError(
        f"{field.value} read off {type(shape).__name__}, which does not populate it — the "
        "reads ⊆ populates wiring rule was broken (an elenctic bug, not a test outcome)"
    )


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
    """The cautious consequences ⋂ (``Field.CAUTIOUS``)."""
    match shape:
        case ConsistentCautious() | ConsistentEnumeration():
            return shape.cautious
        case _:
            _seam_violation(Field.CAUTIOUS, shape)


def brave_of(shape: Consistent) -> frozenset[Symbol]:
    """The brave consequences ⋃ (``Field.BRAVE``)."""
    match shape:
        case ConsistentBrave() | ConsistentEnumeration():
            return shape.brave
        case _:
            _seam_violation(Field.BRAVE, shape)


def optimal_observables_of(shape: Consistent) -> tuple[Observable, ...]:
    """The enumerated optimal class Opt(P) (``Field.OPTIMAL_OBSERVABLES``)."""
    match shape:
        case ConsistentOptimalClass():
            return shape.optimal_observables
        case _:
            _seam_violation(Field.OPTIMAL_OBSERVABLES, shape)


def optimum_of(shape: Consistent) -> Optimum:
    """The proven optimum (``Field.OPTIMUM``)."""
    match shape:
        case ConsistentOptimum() | ConsistentOptimalClass():
            return shape.optimum
        case _:
            _seam_violation(Field.OPTIMUM, shape)


@dataclass(frozen=True, slots=True)
class SolveResult:
    """DEPRECATED — superseded by :data:`Determination`. Kept only until ``checks.py`` adopts the
    three-arm shape (field-compatibility keystone, Task 3), then removed. The ``None``/``()``
    sentinels this carries are exactly the overloaded definedness the keystone lifts into the arms.

    The (partial) outcome of one configured run over the observable (spec §3). A run populates only
    the fields its mode produces; ``None`` and ``()`` are distinct on purpose (``intersection is
    None`` means the cautious aggregate was never computed; an empty ``frozenset()`` is a real
    intersection with no shared atom).
    """

    completed: bool
    observables: tuple[Observable, ...] = ()
    union: frozenset[Symbol] | None = None
    intersection: frozenset[Symbol] | None = None
    optimum_cost: tuple[int, ...] | None = None
    optimal_observables: tuple[Observable, ...] = ()
