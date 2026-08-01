"""Outcome data types: ``Observable``, ``Verdict``, the ``Determination``, and the ``Conclusion``.

A solved program yields a :data:`Determination` — a three-arm outcome surface:
:class:`Inconsistent` (AS(P)=∅), :class:`Inconclusive` (the solve did not decide), or one of the
:class:`Consistent` family. Each ``Consistent`` shape carries
*exactly* the observations its run-mode computes, so a field's absence is a type fact, not a
sentinel — there is no ``NotConfigured`` and no per-field guard.

Whether a model exists and whether the search that looked covered the space are independent
questions, so the second has its own answer: a :class:`Conclusion`, paired with the determination
as a :class:`SolveOutcome`. Which readings that answer disturbs is a question about what is read,
so it is settled where the reading is (``checks.py``), not here and not at the solver.

A check reads a field through one accessor (``*_of``); the single centralised ``_seam_violation`` is
the one narrowing assertion, unreachable through the supported path on **two** premises: (1) the
``reads ⊆ populates`` wiring rule (``run.py``) attaches a check only to a run whose mode populates
what it reads, and (2) the lowering postcondition — ``solvers.py`` produces, for a run of mode M,
exactly the ``Consistent`` shape whose fields are ``populates(M)``. Checks (``checks.py``) are pure
functions of a ``SolveOutcome``; only ``solvers.py`` constructs one.

:class:`Collection` — what a reading ranges over — lives here beside :class:`Field` because it is a
statement about a *field*, not about a run: a mode and a check each read whatever their fields read,
so neither declares one and the two cannot drift apart.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final, NoReturn, final

from clingo import Symbol

from elenctic.terms import intersect_all, union_all

__all__ = [
    "Collection",
    "Conclusion",
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
    "SolveOutcome",
    "Verdict",
    "brave_of",
    "brave_optimal_of",
    "cautious_of",
    "cautious_optimal_of",
    "collection_of",
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


class Collection(Enum):
    """What a reading ranges over — the structural fact that fixes how a run must treat an
    objective, and whether the search behind a reading had to finish.

    An objective (``#minimize``/``#maximize``/``:~``) *ranks* answer sets; it never removes any, so
    AS(P) is the same set with or without one. A solver need not enumerate it that way, though:
    clingo optimizes by default, and an enumerating solve under an active objective reports only the
    branch-and-bound **improving sequence** — the models the search passed through on its way to the
    optimum. That sequence is neither AS(P) nor Opt(P), it varies with the search heuristic, and
    clingo says so where consequences are involved ("Consequences may depend on enumeration order").

    So what a reading ranges over settles the optimization it needs:

    - ``ALL`` — all of AS(P), so the objective must be switched **off** or the search prunes it.
    - ``OPTIMAL`` — all of Opt(P), which only an active objective identifies, so **on**.
    - ``WITNESS`` — a single answer set, and only its existence and contents. An objective changes
      neither whether one exists nor whether a given model qualifies, so the setting cannot move
      the answer and the reading states none.
    """

    ALL = "AS(P)"
    OPTIMAL = "Opt(P)"
    WITNESS = "one answer set"

    @property
    def needs_exhausted_search(self) -> bool:
        """Whether a reading over this collection requires the search that produced it to have
        finished.

        A solver settles two separate things: whether a model exists, and whether the search that
        found one covered everything it was asked to. ``ALL`` and ``OPTIMAL`` are readings of a
        whole collection — a census, an intersection, a union, a proven optimum — and each is a
        claim about every member, so a search that stopped early leaves an arbitrary part unseen
        and answers a different question.

        ``WITNESS`` asks only whether some answer set exists and what is in it, which one model
        settles whatever the rest of the search would have found. The exemption is not merely
        permitted but necessary: with nothing else driving it a witness search stops at the first
        answer set and reports a search that did not finish, so requiring exhaustion would report
        satisfiable programs as undecided. It is *not* that such a search never finishes — an
        objective puts the solver's own optimization in force and proving an optimum does exhaust —
        which is why this is a statement about what the reading requires, not about what the search
        happens to do."""
        return self is not Collection.WITNESS


# Which collection each field is a reading of. This is the partition both the mode-level and the
# check-level collection derive from: a field IS a question about a collection (⋂/⋃/a census are
# questions about AS(P); a cost or an optimal census about Opt(P); a witness about one model), so
# neither a mode nor a check declares one — each reads whatever its fields read.
_READS: Final[dict[Field, Collection]] = {
    Field.WITNESS: Collection.WITNESS,
    Field.SHOWN_CENSUS: Collection.ALL,
    Field.FULL_CENSUS: Collection.ALL,
    Field.CAUTIOUS: Collection.ALL,
    Field.BRAVE: Collection.ALL,
    Field.SHOWN_OPTIMAL_CENSUS: Collection.OPTIMAL,
    Field.FULL_OPTIMAL_CENSUS: Collection.OPTIMAL,
    Field.OPTIMUM: Collection.OPTIMAL,
}


def collection_of(fields: frozenset[Field]) -> Collection:
    """The collection a reader of ``fields`` ranges over. Total over the field vocabulary (an
    unmapped field raises ``KeyError`` at import, before any solve), and defined only where the
    fields agree: a run reading both AS(P) and Opt(P) has no single optimization to lower to, so it
    is a contradiction, reported loudly rather than resolved by picking one."""
    collections = {_READS[field] for field in fields}
    if len(collections) != 1:
        named = ", ".join(sorted(collection.value for collection in collections)) or "nothing"
        raise HarnessError(
            f"a run reading {{{', '.join(sorted(field.value for field in fields))}}} would read "
            f"{named}, but a run reads exactly one collection — it lowers to one optimization "
            "setting, and no setting answers for two (an elenctic bug, not a verdict)"
        )
    return collections.pop()


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
    """The solve did not settle the question — the time budget was hit, the solver gave up without
    an answer, or it answered over a search that stopped before covering what the reading ranges
    over. Every check → ``UNDECIDED``. Carries no fields, so reading an answer off an undecided
    solve is inexpressible — including which of the three it was."""


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


class Conclusion(Enum):
    """How a search that settled satisfiability came to an end.

    Separate from the :data:`Determination` because the two are independent: a search can decide
    that an answer set exists and still stop long before it has seen them all. Reading a stopped
    search as a finished one is the error this vocabulary exists to prevent — a reading over a whole
    collection is a claim about every member, and over a partial search it is a claim about an
    arbitrary part instead.
    """

    EXHAUSTED = "exhausted"
    """The search closed the space: every answer set the configuration admits was seen."""
    STOPPED = "stopped"
    """A bound the run itself requested was reached — a normal, chosen end, neither an error nor
    completeness."""
    INTERRUPTED = "interrupted"
    """The search was cut short from outside it, by a time budget rather than by anything the
    search found."""


@dataclass(frozen=True, slots=True)
class SolveOutcome:
    """One solve's result: what it determined, and how the search that determined it ended.

    ``conclusion`` is ``None`` exactly when the solve settled nothing (the :class:`Inconclusive`
    arm) — there is no completed search to describe. On either other arm it is present, and an
    :class:`Inconsistent` result always closed the space, since no search can report that a program
    has no answer set without covering it.
    """

    determination: Determination
    conclusion: Conclusion | None

    def __post_init__(self) -> None:
        decided = not isinstance(self.determination, Inconclusive)
        if decided != (self.conclusion is not None):
            raise HarnessError(
                "a decided solve reports how its search ended and an undecided one has no search "
                f"to describe; this pairs {type(self.determination).__name__} with "
                f"{self.conclusion!r} (an elenctic bug, not a verdict)"
            )


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
