"""Pure per-tag checks: each is a :class:`Check`, a labelled callable.

A check reads one :class:`~elenctic.result.SolveOutcome` and returns a :class:`CheckReport` — a
three-valued :class:`~elenctic.result.Verdict`, *the diagnostic* (the contract ``label`` and an
expected-vs-actual ``message``), and *enough to place it*: the claim's own ``subject``, the
``line`` it was written on, and how the search behind the verdict ended. A check **dispatches on
the arm**: ``Inconclusive`` →
``UNDECIDED`` (a timeout is never FAIL); ``Inconsistent`` (AS(P)=∅) → the tag's static
verdict (``@expect unsat`` PASSes, every other tag FAILs); ``Consistent`` → the per-tag decision,
reading the fields it declared via the accessor seam (``result.*_of``).

Each check declares ``reads: frozenset[Field]`` — the wiring rule (``run.py``) attaches it only to a
run whose mode populates those fields (a misroute is a ``RoutingError`` at plan construction, before
any solve; the ``SeamError`` at the accessor seam is the should-never-fire backstop). So a
``Consistent``-arm read never misses, and there is no per-field ``is None`` guard. The
containment checks (⊆) reject an empty litset at construction — mirroring ``terms.parse_litset``
at the type boundary — so no vacuous ``∅ ⊆ A`` PASS arises.

A check also decides whether the search behind a result was good enough for *its* reading. That
requirement belongs here rather than at the solver because it depends on what is read, and one run
carries several checks that do not all range over the same thing: a census over part of a collection
is not the census, while a check that reads nothing from the collection is settled by one model
whatever the rest of the search would have found.

Checks are pure over a ``SolveOutcome``; only ``solvers.py`` touches clingo/clingcon.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field as dc_field
from typing import Final, assert_never

from clingo import Symbol

from elenctic.expectation import WitnessClaim, require_line, require_tag
from elenctic.query import (
    Answer,
    BindingQuery,
    GroundQuery,
    Query,
    QueryForm,
    QueryLiteral,
    Var,
    binding_set,
    classify,
    conjunctive_answer,
    singleton_answer,
)
from elenctic.result import (
    Conclusion,
    Consistent,
    Field,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    SolveOutcome,
    Verdict,
    brave_of,
    brave_optimal_of,
    cautious_of,
    cautious_optimal_of,
    collection_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    shown_census_of,
    shown_optimal_census_of,
    witness_of,
)
from elenctic.terms import contrary, intersect_all

__all__ = [
    "Check",
    "CheckReport",
    "assign_contains",
    "assign_optimal_contains",
    "brave_contains",
    "brave_optimal_contains",
    "cautious_contains",
    "cautious_optimal_contains",
    "cost_is",
    "count_is",
    "count_optimal_is",
    "expect_sat",
    "expect_unsat",
    "has_model",
    "has_optimal_model",
    "query_matches",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckReport:
    """The outcome of one check: a three-valued verdict, the diagnostic to surface, and enough of
    the check's identity for a consumer to place it.

    ``label`` is the contract tag (e.g. ``@cautious optimal``); ``subject`` discriminates instances
    of a repeatable tag and is ``""`` otherwise, so ``(label, subject)`` names the check; ``line``
    is the 1-based line of the case file the claim was written on, and ``(label, subject, line)``
    identifies it, since at most one tag occupies a line. ``message`` is the diagnostic the user
    sees on a non-``PASS``. ``conclusion`` is how the search behind the verdict ended — present on
    every report, because every verdict comes from a search that ran, and it is what lets a reader
    tell a program that is wrong from a search that ran out of room. The case's ``@note`` and its
    source provenance are the renderer's concern, read from the case, not carried here.

    Built by keyword, with the run-level records it is reported beside. ``message`` and ``subject``
    are neighbouring strings, so a transposed pair type-checks clean and renders a plausible row
    against the wrong claim; and this is a shape a consumer decoding the run's output meets, where
    a field is identified by its name and by nothing else.
    """

    verdict: Verdict
    label: str
    message: str
    subject: str
    line: int
    conclusion: Conclusion

    def __post_init__(self) -> None:
        require_tag(self.label)
        require_line(self.line)


# Why a solve settled nothing, in terms of how its search ended. Total over the conclusions, unlike
# its partial-reading sibling: a search that closed its space reaches this arm too, when it closed
# it and still left the mode without what its shape is made of — the optimal-class driver's second
# phase does exactly that when it returns no model. The exhausted entry claims nothing about what
# would help, because on that path nothing about the budget was the problem, and on the other way
# such a pairing could arise — a search cancelled just as it finished — a larger budget is exactly
# what would help.
_UNDECIDED_MESSAGE: Final[dict[Conclusion, str]] = {
    Conclusion.EXHAUSTED: (
        "the solve did not settle the question — UNDECIDED, never FAIL. The search covered the "
        "space and still reported nothing this reading could be made of"
    ),
    Conclusion.INCOMPLETE: (
        "the solve did not settle the question — UNDECIDED, never FAIL. The search stopped short "
        "of covering the space, so what ended it was a bound it ran into rather than an answer"
    ),
    Conclusion.INTERRUPTED: (
        "the solve did not settle the question — UNDECIDED, never FAIL. The search was cut short "
        "before it could: the per-solve time budget is what stops a search this way from the "
        "command line, so a larger --budget may decide it"
    ),
}

# Why a reading over a collection could not be made, in terms of how the search ended. A report
# that cannot say which kind of not-knowing it met leaves the reader nothing to act on: raising a
# budget and shrinking a corpus are different remedies.
_PARTIAL_MESSAGE: Final[dict[Conclusion, str]] = {
    Conclusion.INCOMPLETE: (
        "the search stopped short of covering the collection this reads, so what it holds is part "
        "of the collection and not the collection — UNDECIDED, never FAIL. A program with more "
        "answer sets than one solve will hold ends a search this way"
    ),
    Conclusion.INTERRUPTED: (
        "the search was cut short before covering the collection this reads, so what it holds is "
        "part of the collection and not the collection — UNDECIDED, never FAIL. The per-solve time "
        "budget is what stops a search this way from the command line, so a larger --budget may "
        "decide it"
    ),
}


def _undecided_message(conclusion: Conclusion) -> str:
    """Why a solve settled nothing, given how its search ended. Total, so the arm that carries no
    field of its own still carries something a reader can act on."""
    return _UNDECIDED_MESSAGE[conclusion]


def _partial_message(conclusion: Conclusion) -> str:
    """Why a reading over a collection could not be made, given how the search ended.

    Total over the two conclusions that describe a search too partial to read from. A finished
    search is refused rather than given a message, because it does not describe one and has nothing
    to excuse."""
    if conclusion is Conclusion.EXHAUSTED:
        raise HarnessError(
            "a search that finished needs no partial-reading diagnostic (an elenctic bug, not a "
            "verdict)"
        )
    return _PARTIAL_MESSAGE[conclusion]


@dataclass(frozen=True, slots=True, eq=False)
class Check:
    """A pure per-tag check carrying its contract-tag ``label``, an optional ``subject`` (the
    instance discriminator for a repeatable tag), and the ``reads`` it declares — all first-class
    and statically inspectable (the wiring rule's LHS), so a consumer can group,
    identify, route, or *explain* a check before any solve.

    Calling it dispatches on the ``Determination`` arm: ``Inconclusive`` → ``UNDECIDED`` (before
    any decision logic); ``Inconsistent`` → the static ``_inconsistent`` verdict (AS(P)=∅ needs no
    field, and needs no search either — a result that no answer set exists is one only a search
    that covered the space can report); ``Consistent`` → ``UNDECIDED`` if this check's reading
    needed more of the search than it got, else ``_decide`` over the shape, reading fields through
    the seam.
    ``_inconsistent`` and ``_decide`` are private and omitted from ``repr`` so the arm dispatch
    cannot be bypassed.

    Three fields say which check this is, and they do different jobs. ``label`` is the contract tag,
    and it **groups**. ``subject`` discriminates instances of a *repeatable* tag by their surface —
    ``@query``, and the four consequence tags, which a contract may write on more than one line;
    ``""`` for a tag that can occur only once, where there is nothing to discriminate. ``line`` is
    the 1-based line of the case file the claim was written on; a claim brace-continued over several
    lines reports the line its tag opened on.

    ``(label, subject)`` names a check but does not **identify** one: nothing stops an author
    writing the same claim on two lines, and then two checks share both. ``(label, subject, line)``
    identifies, because at most one contract tag occupies a line. That triple is what a consumer
    should key on, and the line is what lets it place a diagnostic against the claim rather than
    against the file.

    Equality is by **identity** (``eq=False``): compare the fields above, never ``check == check``.
    """

    label: str
    reads: frozenset[Field]
    line: int
    _inconsistent: tuple[Verdict, str] = dc_field(repr=False)
    _decide: Callable[[Consistent], tuple[Verdict, str]] = dc_field(repr=False)
    subject: str = ""

    def __post_init__(self) -> None:
        require_tag(self.label)
        require_line(self.line)

    @property
    def needs_exhausted_search(self) -> bool:
        """Whether this check's reading requires the search behind it to have finished.

        Derived from what the check declares it reads, never stored, so a check added later cannot
        forget to declare it. A reading of a whole collection — a census, an intersection, a union,
        a proven optimum — is a claim about every member, so a search that did not close the space
        makes it a claim about an arbitrary part instead. A check whose reads range over no
        collection is exempt: ``@expect sat`` reads nothing at all, and ``@expect unsat`` reads only
        the witness, and each is settled by what one model shows whatever the rest of the search
        would have found.

        Asked of each field separately rather than of ``reads`` as a whole, and that is not a
        stylistic choice: :func:`~elenctic.result.collection_of` is undefined on the empty set —
        deliberately, since a *run* reading no collection has no optimization to lower to — and
        ``@expect sat`` reads exactly that. Over an empty ``reads`` this yields ``False``, which is
        the right answer. The whole-set form is the right one where disagreement must be loud, and
        ``run.py`` uses it there.
        """
        return any(collection_of(frozenset({field})).needs_exhausted_search for field in self.reads)

    def __call__(self, outcome: SolveOutcome) -> CheckReport:
        """Judge one solve against this check, as the report a reader is shown.

        The verdict and its sentence are decided together by ``_judge`` and merely dressed here with
        what identifies the check, so a report can never carry one tag's verdict under another
        tag's name."""
        verdict, message = self._judge(outcome)
        return CheckReport(
            verdict=verdict,
            label=self.label,
            message=message,
            subject=self.subject,
            line=self.line,
            conclusion=outcome.conclusion,
        )

    def _judge(self, outcome: SolveOutcome) -> tuple[Verdict, str]:
        """The arm dispatch, to a verdict and its diagnostic. Split from ``__call__`` so the
        report's identity is attached at one place: an arm added here cannot forget to carry it."""
        match outcome.determination:
            case Inconclusive():
                return Verdict.UNDECIDED, _undecided_message(outcome.conclusion)
            case Inconsistent():
                return self._inconsistent
            case Consistent() as shape:
                if self.needs_exhausted_search and outcome.conclusion is not Conclusion.EXHAUSTED:
                    return Verdict.UNDECIDED, _partial_message(outcome.conclusion)
                return self._decide(shape)
            case _:
                assert_never(outcome.determination)


# --- construction helpers ---


def _check(
    label: str,
    reads: frozenset[Field],
    *,
    line: int,
    inconsistent: tuple[Verdict, str],
    decide: Callable[[Consistent], tuple[Verdict, str]],
    subject: str = "",
) -> Check:
    """The single construction site for a check (the arm dispatch lives in ``Check._judge``)."""
    return Check(label, reads, line, inconsistent, decide, subject)


def _unsat_fail(reason: str) -> tuple[Verdict, str]:
    """The ``Inconsistent``-arm FAIL for a model-needing tag: ``<reason> — AS(P) = ∅``."""
    return Verdict.FAIL, f"{reason} — AS(P) = ∅"


def _require_nonempty(items: frozenset[Symbol] | frozenset[tuple[Symbol, int]], tag: str) -> None:
    """Reject an empty litset/assignment at construction: ``∅ ⊆ A`` would be a vacuous PASS (the
    empty-litset false-PASS), mirroring ``terms.parse_litset``'s rejection at the boundary."""
    if not items:
        raise ValueError(f"{tag} needs a non-empty set — an empty set is a vacuous claim")


# --- diagnostic rendering (deterministic: sorted by text, so messages are stable) ---


# How many members of a set a diagnostic shows before it summarizes the rest. Every set a check
# renders passes through `_braces`, and the sets a program can produce are as large as the program
# makes them — a cautious reading over a big fact base is the whole fact base. A line nobody can
# read is not a better diagnostic than a line that says how much it left out, and a consumer on the
# other end of a pipe has to hold whatever is written.
_SHOWN_MEMBERS: Final = 32


def _braces(parts: list[str]) -> str:
    """Wrap already-rendered parts as a set literal ``{ a, b }`` (``{ }`` when empty), showing at
    most :data:`_SHOWN_MEMBERS` of them and counting the remainder.

    Parts arrive sorted, so what is shown is the same across runs rather than whichever members the
    search happened to reach first."""
    if not parts:
        return "{ }"
    if len(parts) <= _SHOWN_MEMBERS:
        return "{ " + ", ".join(parts) + " }"
    shown = ", ".join(parts[:_SHOWN_MEMBERS])
    return f"{{ {shown}, … (+{len(parts) - _SHOWN_MEMBERS} more) }}"


def _show_set(symbols: Iterable[Symbol]) -> str:
    """Render a set of atoms ``{ a, b, c }`` for a diagnostic."""
    return _braces(sorted(str(symbol) for symbol in symbols))


def _show_models(models: Iterable[frozenset[Symbol]]) -> str:
    """Render a set of shown models (a set of atom-sets) for a diagnostic."""
    return _braces(sorted(_show_set(model) for model in models))


def _show_assign(assignment: Iterable[tuple[Symbol, int]]) -> str:
    """Render one theory assignment ``{ v=k, … }`` for a diagnostic."""
    return _braces(sorted(f"{var}={value}" for var, value in assignment))


def _show_assignments(observables: tuple[Observable, ...]) -> str:
    """Render the theory assignments observed across a run, for an ``@assign`` failure."""
    return _braces(sorted(_show_assign(o.assign) for o in observables))


def _show_observables(observables: tuple[Observable, ...]) -> str:
    """Render observed (shown, assignment) pairs, for a joint ``where``-witness failure — the shown
    and the assignment together, so a failure shows which coordinate (or coupling) did not hold."""
    return _braces(sorted(f"({_show_set(o.shown)}, {_show_assign(o.assign)})" for o in observables))


def _show_cost(cost: tuple[int, ...]) -> str:
    """Render a cost vector ``(4, 2)`` for a diagnostic."""
    return "(" + ", ".join(str(component) for component in cost) + ")"


def _show_tuples(tuples: Iterable[tuple[Symbol, ...]]) -> str:
    """Render a binding set ``{ (s), (a, t) }`` (the ``@query`` answer tuples)."""
    return _braces(sorted("(" + ", ".join(str(term) for term in tup) + ")" for tup in tuples))


def _show_goal(goal: QueryLiteral) -> str:
    """Render a query goal literal ``reachable(X)`` / ``-blocked(X)`` for a diagnostic."""
    sign = "" if goal.positive else "-"
    if not goal.args:
        return f"{sign}{goal.name}"
    args = ", ".join(arg.name if isinstance(arg, Var) else str(arg) for arg in goal.args)
    return f"{sign}{goal.name}({args})"


# --- shared decisions (one per mode; reused across the all/optimal bases) ---


def _witness(
    litset: frozenset[Symbol], shown_models: Iterable[frozenset[Symbol]], noun: str
) -> tuple[Verdict, str]:
    """``L ∈ { shown }`` — whole-shown-model membership over a class named ``noun``."""
    models = tuple(shown_models)  # materialise once: both the test and the diagnostic read it
    if any(model == litset for model in models):
        return Verdict.PASS, f"{_show_set(litset)} ∈ {noun}"
    return Verdict.FAIL, f"{_show_set(litset)} ∉ {noun} = {_show_models(models)}"


def _joint_witness(
    claim: WitnessClaim, observables: tuple[Observable, ...], noun: str
) -> tuple[Verdict, str]:
    """``∃ M: shown(M) = L ∧ assign(M) ⊇ A`` — the joint (pair) witness over the full census: shown
    by equality, assignment by containment, both on one model."""
    if any(o.shown == claim.shown and claim.assign <= o.assign for o in observables):
        return (
            Verdict.PASS,
            f"some {noun} is {_show_set(claim.shown)} with assignment "
            f"⊇ {_show_assign(claim.assign)}",
        )
    return (
        Verdict.FAIL,
        f"no {noun} is {_show_set(claim.shown)} with assignment ⊇ {_show_assign(claim.assign)}; "
        f"observed = {_show_observables(observables)}",
    )


def _containment(
    litset: frozenset[Symbol], aggregate: frozenset[Symbol], glyph: str
) -> tuple[Verdict, str]:
    """``L ⊆ aggregate`` where ``aggregate`` is ⋂ or ⋃ (``glyph``), surfacing the missing atoms on a
    failure."""
    if litset <= aggregate:
        return Verdict.PASS, f"{_show_set(litset)} ⊆ {glyph} = {_show_set(aggregate)}"
    return (
        Verdict.FAIL,
        f"{_show_set(litset)} ⊄ {glyph} = {_show_set(aggregate)} "
        f"(missing: {_show_set(litset - aggregate)})",
    )


def _count(expected: int, actual: int, noun: str) -> tuple[Verdict, str]:
    """``len(base) == n`` on a ``Consistent`` result — total at both ends. ``expected`` is at least
    1 here: counting to zero is a claim about *satisfiability*, decided without a census by the arm
    dispatch, and the ``@count`` checks route it there rather than through this."""
    if actual == expected:
        return Verdict.PASS, f"|{noun}| = {expected}"
    return Verdict.FAIL, f"expected {expected} {noun}, got {actual}"


# --- the all-base checks ---


def expect_sat(*, line: int) -> Check:
    """``@expect sat``: ``AS(P) ≠ ∅`` — a model exists. Reads only the arm."""
    return _check(
        "@expect sat",
        frozenset(),
        line=line,
        inconsistent=(Verdict.FAIL, "expected sat, but AS(P) = ∅ — no model"),
        decide=lambda _shape: (Verdict.PASS, "AS(P) ≠ ∅ — a model exists"),
    )


def expect_unsat(*, line: int) -> Check:
    """``@expect unsat``: ``AS(P) = ∅`` — no model. PASSes on the ``Inconsistent`` arm;
    on a ``Consistent`` run it FAILs with the witnessing model (the DEFAULT witness)."""

    def decide(shape: Consistent) -> tuple[Verdict, str]:
        shown = witness_of(shape).shown
        return Verdict.FAIL, f"expected unsat, but a model exists: {_show_set(shown)}"

    return _check(
        "@expect unsat",
        frozenset({Field.WITNESS}),
        line=line,
        inconsistent=(Verdict.PASS, "AS(P) = ∅ — no model, as expected"),
        decide=decide,
    )


def has_model(claim: WitnessClaim, *, line: int) -> Check:
    """``@model { L } [where { A }]``: a bare claim asserts ``L`` is some answer set's shown
    projection (the shown census, projection-invariant); a ``where``-qualified claim asserts there
    is one model with ``shown(M) = L`` AND ``assign(M) ⊇ A`` (the joint witness, full census — so it
    suppresses projection by reading the full token)."""
    if not claim.assign:
        return _check(
            "@model",
            frozenset({Field.SHOWN_CENSUS}),
            line=line,
            inconsistent=_unsat_fail(f"no model equals {_show_set(claim.shown)}"),
            decide=lambda shape: _witness(claim.shown, shown_census_of(shape), "enumerated models"),
        )
    return _check(
        "@model",
        frozenset({Field.FULL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail(
            f"no model is {_show_set(claim.shown)} with assignment ⊇ {_show_assign(claim.assign)}"
        ),
        decide=lambda shape: _joint_witness(claim, observables_of(shape), "model"),
    )


def count_is(n: int, *, line: int) -> Check:
    """``@count n``: exactly ``n`` distinct observables (total at both ends). Reads the full
    census — its theory-distinct count is what projection would collapse, so a ``@count`` rider
    suppresses projection.

    ``@count 0`` is ``@expect unsat`` said with another tag, and it is decided the same way rather
    than by counting: it PASSes on the ``Inconsistent`` arm, and a single model refutes it whatever
    the rest of the search would have found. So it reads **nothing** — which is what lets the claim
    ride the cheap witness solve an unsat contract already runs, instead of demanding an enumeration
    to count to zero. The refutation names no witness because the ``@expect unsat`` beside it
    reports one: the contract language admits ``@count 0`` only under that tag."""
    if n == 0:
        return _check(
            "@count",
            frozenset(),
            line=line,
            inconsistent=(Verdict.PASS, "|models| = 0"),
            decide=lambda _shape: (
                Verdict.FAIL,
                "expected 0 models, but AS(P) ≠ ∅ — a model exists",
            ),
        )
    return _check(
        "@count",
        frozenset({Field.FULL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail(f"expected {n} models, got 0"),
        decide=lambda shape: _count(n, len(observables_of(shape)), "models"),
    )


def cautious_contains(litset: frozenset[Symbol], *, line: int) -> Check:
    """``@cautious { L }``: ``L ⊆ ⋂`` (the cautious consequences)."""
    _require_nonempty(litset, "@cautious")
    return _check(
        "@cautious",
        frozenset({Field.CAUTIOUS}),
        line=line,
        inconsistent=_unsat_fail("no cautious consequences"),
        decide=lambda shape: _containment(litset, cautious_of(shape), "⋂ AS(P)"),
        subject=_show_set(litset),
    )


def brave_contains(litset: frozenset[Symbol], *, line: int) -> Check:
    """``@brave { L }``: ``L ⊆ ⋃`` (the brave consequences)."""
    _require_nonempty(litset, "@brave")
    return _check(
        "@brave",
        frozenset({Field.BRAVE}),
        line=line,
        inconsistent=_unsat_fail("no brave consequences"),
        decide=lambda shape: _containment(litset, brave_of(shape), "⋃ AS(P)"),
        subject=_show_set(litset),
    )


def cost_is(cost: tuple[int, ...], *, line: int) -> Check:
    """``@cost { c }``: the proven optimum cost vector equals ``c`` by value."""

    def decide(shape: Consistent) -> tuple[Verdict, str]:
        actual = optimum_of(shape).cost
        if actual == cost:
            return Verdict.PASS, f"optimum cost = {_show_cost(cost)}"
        return Verdict.FAIL, f"expected cost {_show_cost(cost)}, got {_show_cost(actual)}"

    return _check(
        "@cost",
        frozenset({Field.OPTIMUM}),
        line=line,
        inconsistent=(
            Verdict.FAIL,
            f"no optimum proven — AS(P) = ∅; expected cost {_show_cost(cost)}",
        ),
        decide=decide,
    )


def assign_contains(assignment: frozenset[tuple[Symbol, int]], *, line: int) -> Check:
    """``@assign { A }``: some observable's theory assignment ⊇ ``A``. Reads the full census (the
    assignment dimension projection would erase, so an ``@assign`` rider suppresses projection)."""
    _require_nonempty(assignment, "@assign")

    def decide(shape: Consistent) -> tuple[Verdict, str]:
        observables = observables_of(shape)
        if any(assignment <= o.assign for o in observables):
            return Verdict.PASS, f"{_show_assign(assignment)} ⊆ some observable's assignment"
        return (
            Verdict.FAIL,
            f"no observable's assignment ⊇ {_show_assign(assignment)}; "
            f"assignments seen = {_show_assignments(observables)}",
        )

    return _check(
        "@assign",
        frozenset({Field.FULL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail(f"no assignment ⊇ {_show_assign(assignment)}"),
        decide=decide,
    )


# --- the optimal base (each mode is its all-base aggregation over Opt(P)) ---


def has_optimal_model(claim: WitnessClaim, *, line: int) -> Check:
    """``@optimal { L } [where { A }]``: a bare claim reads the shown optimal census
    (projection-invariant) — what lets it ride a projecting optimal run and terminate; a
    ``where``-qualified claim asserts one optimal model with ``shown(M) = L`` AND ``assign(M) ⊇ A``
    (the joint witness over the full optimal census)."""
    if not claim.assign:
        return _check(
            "@optimal",
            frozenset({Field.SHOWN_OPTIMAL_CENSUS}),
            line=line,
            inconsistent=_unsat_fail(f"no optimal model equals {_show_set(claim.shown)}"),
            decide=lambda shape: _witness(
                claim.shown, shown_optimal_census_of(shape), "optimal models"
            ),
        )
    return _check(
        "@optimal",
        frozenset({Field.FULL_OPTIMAL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail(
            f"no optimal model is {_show_set(claim.shown)} with assignment ⊇ "
            f"{_show_assign(claim.assign)}"
        ),
        decide=lambda shape: _joint_witness(claim, optimal_observables_of(shape), "optimal model"),
    )


def cautious_optimal_contains(litset: frozenset[Symbol], *, line: int) -> Check:
    """``@cautious optimal { L }``: ``L ⊆ ⋂ Opt(P)`` (the optimal backbone). Reads the shown optimal
    census (projection-invariant)."""
    _require_nonempty(litset, "@cautious optimal")
    return _check(
        "@cautious optimal",
        frozenset({Field.SHOWN_OPTIMAL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail("no optimal models"),
        decide=lambda shape: _containment(litset, cautious_optimal_of(shape), "⋂ Opt(P)"),
        subject=_show_set(litset),
    )


def brave_optimal_contains(litset: frozenset[Symbol], *, line: int) -> Check:
    """``@brave optimal { L }``: ``L ⊆ ⋃ Opt(P)``. Reads the shown optimal census
    (projection-invariant)."""
    _require_nonempty(litset, "@brave optimal")
    return _check(
        "@brave optimal",
        frozenset({Field.SHOWN_OPTIMAL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail("no optimal models"),
        decide=lambda shape: _containment(litset, brave_optimal_of(shape), "⋃ Opt(P)"),
        subject=_show_set(litset),
    )


def count_optimal_is(n: int, *, line: int) -> Check:
    """``@count optimal n``: exactly ``n`` distinct optimal observables. Reads the full optimal
    census (the theory-distinct count projection would collapse, so it suppresses projection).

    ``@count optimal 0`` is the ``Opt(P)`` reading of ``@expect unsat``, and reads nothing for the
    same reason :func:`count_is` gives. Its refutation is one step longer and does not need an
    optimal solve to take it: an objective is minimised over a finite grounding, so the optimum is
    attained wherever there is anything to attain it — ``Opt(P)`` is empty exactly when ``AS(P)``
    is, and a single model settles both."""
    if n == 0:
        return _check(
            "@count optimal",
            frozenset(),
            line=line,
            inconsistent=(Verdict.PASS, "|optimal models| = 0"),
            decide=lambda _shape: (
                Verdict.FAIL,
                "expected 0 optimal models, but AS(P) ≠ ∅ — a model exists, and Opt(P) is empty "
                "only where AS(P) is",
            ),
        )
    return _check(
        "@count optimal",
        frozenset({Field.FULL_OPTIMAL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail(f"expected {n} optimal models, got 0"),
        decide=lambda shape: _count(n, len(optimal_observables_of(shape)), "optimal models"),
    )


def assign_optimal_contains(assignment: frozenset[tuple[Symbol, int]], *, line: int) -> Check:
    """``@assign optimal { A }``: some optimal model's theory assignment ⊇ ``A`` — there is an
    M ∈ Opt(P) with assign(M) ⊇ A. Reads the full optimal census (projection-sensitive, so it
    suppresses projection)."""
    _require_nonempty(assignment, "@assign optimal")

    def decide(shape: Consistent) -> tuple[Verdict, str]:
        observables = optimal_observables_of(shape)
        if any(assignment <= o.assign for o in observables):
            return Verdict.PASS, f"{_show_assign(assignment)} ⊆ some optimal model's assignment"
        return (
            Verdict.FAIL,
            f"no optimal model's assignment ⊇ {_show_assign(assignment)}; "
            f"assignments seen = {_show_assignments(observables)}",
        )

    return _check(
        "@assign optimal",
        frozenset({Field.FULL_OPTIMAL_CENSUS}),
        line=line,
        inconsistent=_unsat_fail(f"no optimal assignment ⊇ {_show_assign(assignment)}"),
        decide=decide,
    )


# --- the @query check (Def 2.2.2, corrected per the errata; base-fixed to AS(P)) ---


def _cautious_localization(
    conjuncts: tuple[Symbol, ...], cautious: frozenset[Symbol], computed: Answer
) -> str:
    """Localize a failing *singleton* ground query off ⋂."""
    if computed is Answer.unknown:
        return f" (not entailed: {_show_set(c for c in conjuncts if c not in cautious)})"
    if computed is Answer.no:
        return f" (counter-entailed: {_show_set(c for c in conjuncts if contrary(c) in cautious)})"
    return ""


def _census_localization(
    conjuncts: tuple[Symbol, ...], census: frozenset[frozenset[Symbol]], computed: Answer
) -> str:
    """Localize a failing *conjunctive* ground query off the census: for ``no`` a conjunct is
    falsified iff some model carries its contrary (⋂ would be empty when each model falsifies a
    different conjunct — the case the published errata corrected)."""
    if computed is Answer.unknown:
        missing = _show_set(c for c in conjuncts if c not in intersect_all(tuple(census)))
        return f" (not entailed: {missing})"
    if computed is Answer.no:
        falsified = _show_set(c for c in conjuncts if any(contrary(c) in model for model in census))
        return f" (falsified in some model: {falsified})"
    return ""


def _ground_verdict(
    answer: Answer, conjuncts: tuple[Symbol, ...], computed: Answer, localization: str
) -> tuple[Verdict, str]:
    """The program's computed answer vs the contract's, for a ground query."""
    if computed is answer:
        return Verdict.PASS, f"{_show_set(conjuncts)}: computed {answer.value}"
    return (
        Verdict.FAIL,
        f"{_show_set(conjuncts)}: expected {answer.value}, computed {computed.value}{localization}",
    )


def _binding_verdict(
    goal: QueryLiteral,
    answer: Answer,
    expected: frozenset[tuple[Symbol, ...]],
    found: set[tuple[Symbol, ...]],
) -> tuple[Verdict, str]:
    """The program's computed binding set vs the contract's, for a binding query."""
    if found == expected:
        return Verdict.PASS, f"{_show_goal(goal)}: computed {answer.value} {_show_tuples(found)}"
    return (
        Verdict.FAIL,
        f"{_show_goal(goal)}: expected {answer.value} {_show_tuples(expected)}, "
        f"computed {_show_tuples(found)}",
    )


def query_matches(query: Query, *, line: int) -> Check:
    """The ``@query`` check (Gelfond–Kahl Def 2.2.2, corrected per the errata): the
    program's computed answer matches the contract's. A *singleton* ground query reads the cautious
    consequences ⋂; a *conjunctive* (n≥2) ground query reads the model census (its "no"/"unknown" is
    a per-model property ⋂ cannot express); a yes/no binding reads ⋂; an unknown binding reads ⋂ and
    ⋃. On the ``Inconsistent`` arm (AS(P)=∅) every query FAILs — each is vacuously yes-and-no.

    The form comes from the shared ``query.classify`` (so route and read never disagree); the shape
    match supplies the typed pattern bindings. Each arm builds its decide closure and returns
    immediately. ``subject`` carries the query's surface so the repeatable ``@query`` tag is
    discernible before any solve (``label`` stays ``@query``; ``(label, subject)`` is the identity).
    """
    inconsistent = (Verdict.FAIL, "AS(P) = ∅ — every query is vacuously yes-and-no; @query fails")

    match query:
        case GroundQuery(answer, conjuncts):
            subject = f"{answer.value} {_show_set(conjuncts)}"
            if classify(query) is QueryForm.SINGLETON_GROUND:
                literal = conjuncts[0]

                def decide_singleton(shape: Consistent) -> tuple[Verdict, str]:
                    cautious = cautious_of(shape)
                    computed = singleton_answer(literal, cautious)
                    return _ground_verdict(
                        answer,
                        conjuncts,
                        computed,
                        _cautious_localization(conjuncts, cautious, computed),
                    )

                return _check(
                    "@query",
                    frozenset({Field.CAUTIOUS}),
                    line=line,
                    inconsistent=inconsistent,
                    decide=decide_singleton,
                    subject=subject,
                )

            def decide_conjunctive(shape: Consistent) -> tuple[Verdict, str]:
                census = shown_census_of(shape)
                computed = conjunctive_answer(conjuncts, census)
                return _ground_verdict(
                    answer, conjuncts, computed, _census_localization(conjuncts, census, computed)
                )

            return _check(
                "@query",
                frozenset({Field.SHOWN_CENSUS}),
                line=line,
                inconsistent=inconsistent,
                decide=decide_conjunctive,
                subject=subject,
            )

        case BindingQuery(answer, goal, bindings):
            subject = f"{answer.value} {_show_goal(goal)}"
            if classify(query) is QueryForm.BINDING_UNKNOWN:

                def decide_binding_unknown(shape: Consistent) -> tuple[Verdict, str]:
                    found = binding_set(goal, answer, cautious_of(shape), brave_of(shape))
                    return _binding_verdict(goal, answer, bindings, found)

                return _check(
                    "@query",
                    frozenset({Field.CAUTIOUS, Field.BRAVE}),
                    line=line,
                    inconsistent=inconsistent,
                    decide=decide_binding_unknown,
                    subject=subject,
                )

            def decide_binding_settled(shape: Consistent) -> tuple[Verdict, str]:
                found = binding_set(goal, answer, cautious_of(shape), None)
                return _binding_verdict(goal, answer, bindings, found)

            return _check(
                "@query",
                frozenset({Field.CAUTIOUS}),
                line=line,
                inconsistent=inconsistent,
                decide=decide_binding_settled,
                subject=subject,
            )

        case _:
            assert_never(query)
