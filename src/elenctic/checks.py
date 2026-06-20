"""Pure per-tag checks (spec §3, dx#9): each is a :class:`Check`, a labelled callable.

A check reads one :class:`~elenctic.result.Determination` and returns a :class:`CheckReport` — a
three-valued :class:`~elenctic.result.Verdict` *plus the diagnostic* (dx#9): the contract ``label``
and an expected-vs-actual ``message``. A check **dispatches on the arm**: ``Inconclusive`` →
``UNDECIDED`` (§7a — a timeout is never FAIL); ``Inconsistent`` (AS(P)=∅) → the tag's static
verdict (``@expect unsat`` PASSes, every other tag FAILs); ``Consistent`` → the per-tag decision,
reading the fields it declared via the accessor seam (``result.*_of``).

Each check declares ``reads: frozenset[Field]`` — the wiring rule (``run.py``) attaches it only to a
run whose mode populates those fields, so a ``Consistent``-arm read never misses (a misroute is a
``SeamError`` at the seam, never a verdict). There is therefore no per-field ``is None`` guard and
no "missing field" case: the litsets a check is built from are non-empty by construction (``parse``
rejects an empty litset, §2.1), so no vacuous ``∅ ⊆ A`` PASS arises.

Checks are pure over a ``Determination``; only ``solvers.py`` touches clingo/clingcon.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import assert_never

from clingo import Symbol

from elenctic.query import (
    Answer,
    BindingQuery,
    GroundQuery,
    Query,
    QueryLiteral,
    Var,
    binding_set,
    conjunctive_answer,
    singleton_answer,
)
from elenctic.result import (
    Consistent,
    Determination,
    Field,
    Inconclusive,
    Inconsistent,
    Observable,
    Verdict,
    brave_of,
    cautious_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    witness_of,
)
from elenctic.terms import contrary


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The outcome of one check: a three-valued verdict plus the diagnostic to surface (dx#9, §3).

    ``label`` is the contract tag (e.g. ``@cautious optimal``); ``message`` is the diagnostic the
    user sees on a non-``PASS`` (the expected-vs-actual reading, dx#9). The report is exactly the
    *check's* output — the case's ``@note`` and ``path:line`` are the renderer's concern, read from
    the case, not carried here.
    """

    verdict: Verdict
    label: str
    message: str


_UNDECIDED_MESSAGE = "the solve did not complete within the budget — UNDECIDED, never FAIL"


@dataclass(frozen=True, slots=True, eq=False)
class Check:
    """A pure per-tag check carrying its contract-tag ``label`` and the ``reads`` it declares, both
    first-class and statically inspectable (dx#9 / option C / the wiring rule's LHS), so a consumer
    can group, identify, route, or *explain* a check before any solve.

    Calling it dispatches on the ``Determination`` arm: ``Inconclusive`` → ``UNDECIDED`` (§7a,
    before any decision logic); ``Inconsistent`` → the static ``_inconsistent`` verdict (AS(P)=∅
    needs no field); ``Consistent`` → ``_decide`` over the shape, reading fields through the seam.
    ``_inconsistent`` and ``_decide`` are private and omitted from ``repr`` so the arm dispatch
    cannot be bypassed and the identity is the label alone. Equality is by **identity**
    (``eq=False``): compare ``check.label``, never ``check == check``.
    """

    label: str
    reads: frozenset[Field]
    _inconsistent: tuple[Verdict, str] = field(repr=False)
    _decide: Callable[[Consistent], tuple[Verdict, str]] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.label.startswith("@"):
            raise ValueError(f"a check label must be a contract tag, got {self.label!r}")

    def __call__(self, determination: Determination) -> CheckReport:
        match determination:
            case Inconclusive():
                return CheckReport(Verdict.UNDECIDED, self.label, _UNDECIDED_MESSAGE)
            case Inconsistent():
                verdict, message = self._inconsistent
                return CheckReport(verdict, self.label, message)
            case Consistent() as shape:
                verdict, message = self._decide(shape)
                return CheckReport(verdict, self.label, message)


# --- diagnostic rendering (deterministic: sorted by text, so messages are stable) ---


def _braces(parts: list[str]) -> str:
    """Wrap already-rendered parts as a set literal ``{ a, b }`` (``{ }`` when empty)."""
    return "{ " + ", ".join(parts) + " }" if parts else "{ }"


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


# --- check construction ---


def _check(
    label: str,
    reads: frozenset[Field],
    *,
    inconsistent: tuple[Verdict, str],
    decide: Callable[[Consistent], tuple[Verdict, str]],
) -> Check:
    """The single construction site for a check (the arm dispatch lives in ``Check.__call__``)."""
    return Check(label, reads, inconsistent, decide)


# --- shared decisions (one per mode; reused across the all/optimal bases) ---


def _witness(
    litset: frozenset[Symbol], models: tuple[frozenset[Symbol], ...], noun: str
) -> tuple[Verdict, str]:
    """``L ∈ { shown }`` — whole-shown-model membership over a class named ``noun`` (§3)."""
    if any(model == litset for model in models):
        return Verdict.PASS, f"{_show_set(litset)} ∈ {noun}"
    return Verdict.FAIL, f"{_show_set(litset)} ∉ {noun} = {_show_models(models)}"


def _containment(
    litset: frozenset[Symbol], aggregate: frozenset[Symbol], glyph: str
) -> tuple[Verdict, str]:
    """``L ⊆ aggregate`` where ``aggregate`` is ⋂ or ⋃ (``glyph``), surfacing the missing atoms on a
    failure (§3)."""
    if litset <= aggregate:
        return Verdict.PASS, f"{_show_set(litset)} ⊆ {glyph} = {_show_set(aggregate)}"
    return (
        Verdict.FAIL,
        f"{_show_set(litset)} ⊄ {glyph} = {_show_set(aggregate)} "
        f"(missing: {_show_set(litset - aggregate)})",
    )


def _count(expected: int, actual: int, noun: str) -> tuple[Verdict, str]:
    """``len(base) == n`` — total at both ends (``@count 0`` over ∅ is ``PASS``, §3)."""
    if actual == expected:
        return Verdict.PASS, f"|{noun}| = {expected}"
    return Verdict.FAIL, f"expected {expected} {noun}, got {actual}"


# --- the all-base checks ---


def expect_sat() -> Check:
    """``@expect sat``: ``AS(P) ≠ ∅`` — a model exists (spec §2.1). Reads only the arm."""
    return _check(
        "@expect sat",
        frozenset(),
        inconsistent=(Verdict.FAIL, "expected sat, but AS(P) = ∅ — no model"),
        decide=lambda _shape: (Verdict.PASS, "AS(P) ≠ ∅ — a model exists"),
    )


def expect_unsat() -> Check:
    """``@expect unsat``: ``AS(P) = ∅`` — no model (spec §2.1). PASSes on the ``Inconsistent`` arm;
    on a ``Consistent`` run it FAILs with the witnessing model (the DEFAULT witness)."""

    def decide(shape: Consistent) -> tuple[Verdict, str]:
        shown = witness_of(shape).shown
        return Verdict.FAIL, f"expected unsat, but a model exists: {_show_set(shown)}"

    return _check(
        "@expect unsat",
        frozenset({Field.WITNESS}),
        inconsistent=(Verdict.PASS, "AS(P) = ∅ — no model, as expected"),
        decide=decide,
    )


def has_model(litset: frozenset[Symbol]) -> Check:
    """``@model { L }``: some enumerated observable's shown model equals ``L`` (§3)."""
    return _check(
        "@model",
        frozenset({Field.OBSERVABLES}),
        inconsistent=(Verdict.FAIL, f"no model equals {_show_set(litset)} — AS(P) = ∅"),
        decide=lambda shape: _witness(
            litset, tuple(o.shown for o in observables_of(shape)), "enumerated models"
        ),
    )


def count_is(n: int) -> Check:
    """``@count n``: exactly ``n`` distinct observables (total at both ends, §3). ``@count 0`` is
    the unsat case, so it PASSes on ``Inconsistent``."""
    inconsistent = (
        (Verdict.PASS, "|models| = 0") if n == 0 else (Verdict.FAIL, f"expected {n} models, got 0")
    )
    return _check(
        "@count",
        frozenset({Field.OBSERVABLES}),
        inconsistent=inconsistent,
        decide=lambda shape: _count(n, len(observables_of(shape)), "models"),
    )


def cautious_contains(litset: frozenset[Symbol]) -> Check:
    """``@cautious { L }``: ``L ⊆ ⋂`` (the cautious consequences, §3)."""
    return _check(
        "@cautious",
        frozenset({Field.CAUTIOUS}),
        inconsistent=(Verdict.FAIL, "no cautious consequences — AS(P) = ∅"),
        decide=lambda shape: _containment(litset, cautious_of(shape), "⋂"),
    )


def brave_contains(litset: frozenset[Symbol]) -> Check:
    """``@brave { L }``: ``L ⊆ ⋃`` (the brave consequences, §3)."""
    return _check(
        "@brave",
        frozenset({Field.BRAVE}),
        inconsistent=(Verdict.FAIL, "no brave consequences — AS(P) = ∅"),
        decide=lambda shape: _containment(litset, brave_of(shape), "⋃"),
    )


def cost_is(cost: tuple[int, ...]) -> Check:
    """``@cost { c }``: the proven optimum cost vector equals ``c`` by value (§3, §2.0)."""

    def decide(shape: Consistent) -> tuple[Verdict, str]:
        actual = optimum_of(shape).cost
        if actual == cost:
            return Verdict.PASS, f"optimum cost = {_show_cost(cost)}"
        return Verdict.FAIL, f"expected cost {_show_cost(cost)}, got {_show_cost(actual)}"

    return _check(
        "@cost",
        frozenset({Field.OPTIMUM}),
        inconsistent=(
            Verdict.FAIL,
            f"no optimum proven — AS(P) = ∅; expected cost {_show_cost(cost)}",
        ),
        decide=decide,
    )


def assign_contains(assignment: frozenset[tuple[Symbol, int]]) -> Check:
    """``@assign { A }``: some observable's theory assignment ⊇ ``A`` (§3, §6.3)."""

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
        frozenset({Field.OBSERVABLES}),
        inconsistent=(Verdict.FAIL, f"no assignment ⊇ {_show_assign(assignment)} — AS(P) = ∅"),
        decide=decide,
    )


# --- the optimal base (each mode is its all-base aggregation over Opt(P), §3) ---


def _optimal_shown(shape: Consistent) -> tuple[frozenset[Symbol], ...]:
    return tuple(o.shown for o in optimal_observables_of(shape))


def _intersection(family: tuple[frozenset[Symbol], ...]) -> frozenset[Symbol]:
    """⋂ of a non-empty family of atom sets (the shape's invariant guarantees non-emptiness)."""
    return family[0].intersection(*family[1:])


def _union(family: tuple[frozenset[Symbol], ...]) -> frozenset[Symbol]:
    """⋃ of a non-empty family of atom sets."""
    return family[0].union(*family[1:])


def has_optimal_model(litset: frozenset[Symbol]) -> Check:
    """``@optimal { L }`` (= ``@model optimal``): ``L`` is some optimal model (§3)."""
    return _check(
        "@optimal",
        frozenset({Field.OPTIMAL_OBSERVABLES}),
        inconsistent=(Verdict.FAIL, f"no optimal model equals {_show_set(litset)} — AS(P) = ∅"),
        decide=lambda shape: _witness(litset, _optimal_shown(shape), "optimal models"),
    )


def cautious_optimal_contains(litset: frozenset[Symbol]) -> Check:
    """``@cautious optimal { L }``: ``L ⊆ ⋂ Opt(P)`` (the optimal backbone, §3)."""
    return _check(
        "@cautious optimal",
        frozenset({Field.OPTIMAL_OBSERVABLES}),
        inconsistent=(Verdict.FAIL, "no optimal models — AS(P) = ∅"),
        decide=lambda shape: _containment(litset, _intersection(_optimal_shown(shape)), "⋂ Opt(P)"),
    )


def brave_optimal_contains(litset: frozenset[Symbol]) -> Check:
    """``@brave optimal { L }``: ``L ⊆ ⋃ Opt(P)`` (§3)."""
    return _check(
        "@brave optimal",
        frozenset({Field.OPTIMAL_OBSERVABLES}),
        inconsistent=(Verdict.FAIL, "no optimal models — AS(P) = ∅"),
        decide=lambda shape: _containment(litset, _union(_optimal_shown(shape)), "⋃ Opt(P)"),
    )


def count_optimal_is(n: int) -> Check:
    """``@count optimal n``: exactly ``n`` distinct optimal observables (§3)."""
    inconsistent = (
        (Verdict.PASS, "|optimal models| = 0")
        if n == 0
        else (Verdict.FAIL, f"expected {n} optimal models, got 0")
    )
    return _check(
        "@count optimal",
        frozenset({Field.OPTIMAL_OBSERVABLES}),
        inconsistent=inconsistent,
        decide=lambda shape: _count(n, len(optimal_observables_of(shape)), "optimal models"),
    )


# --- the @query check (Def 2.2.2, corrected per the errata; base-fixed to AS(P)) ---


def _ground_witness(
    conjuncts: tuple[Symbol, ...], cautious: frozenset[Symbol], computed: Answer
) -> str:
    """Localize a failing ground query — the conjuncts that fell short of the answer (§2.4). Uses ⋂
    for the localization even in the conjunctive (census) case, which is an adequate diagnostic."""
    if computed is Answer.unknown:
        missing = _show_set(c for c in conjuncts if c not in cautious)
        return f" (not entailed: {missing})"
    if computed is Answer.no:
        refuted = _show_set(c for c in conjuncts if contrary(c) in cautious)
        return f" (counter-entailed: {refuted})"
    return ""  # computed yes but a non-yes answer was asserted — the conjuncts are all entailed


def _ground_verdict(
    answer: Answer, conjuncts: tuple[Symbol, ...], computed: Answer, cautious: frozenset[Symbol]
) -> tuple[Verdict, str]:
    """The program's computed answer vs the contract's, for a ground query (§3)."""
    if computed is answer:
        return Verdict.PASS, f"{_show_set(conjuncts)}: computed {answer.value}"
    return (
        Verdict.FAIL,
        f"{_show_set(conjuncts)}: expected {answer.value}, computed {computed.value}"
        f"{_ground_witness(conjuncts, cautious, computed)}",
    )


def _binding_verdict(
    goal: QueryLiteral,
    answer: Answer,
    expected: frozenset[tuple[Symbol, ...]],
    found: set[tuple[Symbol, ...]],
) -> tuple[Verdict, str]:
    """The program's computed binding set vs the contract's, for a binding query (§3)."""
    if found == expected:
        return Verdict.PASS, f"{_show_goal(goal)}: computed {answer.value} {_show_tuples(found)}"
    return (
        Verdict.FAIL,
        f"{_show_goal(goal)}: expected {answer.value} {_show_tuples(expected)}, "
        f"computed {_show_tuples(found)}",
    )


def query_matches(query: Query) -> Check:
    """The ``@query`` check (Gelfond–Kahl Def 2.2.2, corrected per the errata; spec §3): the
    program's computed answer matches the contract's. A *singleton* ground query reads the cautious
    consequences ⋂; a *conjunctive* (n≥2) ground query reads the model census (its "no"/"unknown" is
    a per-model property ⋂ cannot express); a yes/no binding reads ⋂; an unknown binding reads ⋂ and
    ⋃. On the ``Inconsistent`` arm (AS(P)=∅) every query FAILs — each is vacuously yes-and-no (§2.2,
    FR#9)."""
    inconsistent = (Verdict.FAIL, "AS(P) = ∅ — every query is vacuously yes-and-no; @query fails")

    match query:
        case GroundQuery(answer, conjuncts) if len(conjuncts) == 1:
            literal = conjuncts[0]

            def decide_singleton(shape: Consistent) -> tuple[Verdict, str]:
                cautious = cautious_of(shape)
                computed = singleton_answer(literal, cautious)
                return _ground_verdict(answer, conjuncts, computed, cautious)

            return _check(
                "@query",
                frozenset({Field.CAUTIOUS}),
                inconsistent=inconsistent,
                decide=decide_singleton,
            )

        case GroundQuery(answer, conjuncts):

            def decide_conjunctive(shape: Consistent) -> tuple[Verdict, str]:
                census = tuple(o.shown for o in observables_of(shape))
                computed = conjunctive_answer(conjuncts, census)
                return _ground_verdict(answer, conjuncts, computed, _intersection(census))

            return _check(
                "@query",
                frozenset({Field.OBSERVABLES}),
                inconsistent=inconsistent,
                decide=decide_conjunctive,
            )

        case BindingQuery(answer, goal, bindings) if answer is Answer.unknown:

            def decide_unknown(shape: Consistent) -> tuple[Verdict, str]:
                found = binding_set(goal, answer, cautious_of(shape), brave_of(shape))
                return _binding_verdict(goal, answer, bindings, found)

            return _check(
                "@query",
                frozenset({Field.CAUTIOUS, Field.BRAVE}),
                inconsistent=inconsistent,
                decide=decide_unknown,
            )

        case BindingQuery(answer, goal, bindings):

            def decide_binding(shape: Consistent) -> tuple[Verdict, str]:
                found = binding_set(goal, answer, cautious_of(shape), None)
                return _binding_verdict(goal, answer, bindings, found)

            return _check(
                "@query",
                frozenset({Field.CAUTIOUS}),
                inconsistent=inconsistent,
                decide=decide_binding,
            )

        case _:
            assert_never(query)
