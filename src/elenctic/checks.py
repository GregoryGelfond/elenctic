"""Pure per-tag checks (spec §3, dx#9): each is a :class:`Check`, a labelled callable.

A check reads one :class:`~elenctic.result.Determination` and returns a :class:`CheckReport` — a
three-valued :class:`~elenctic.result.Verdict` *plus the diagnostic* (dx#9): the contract ``label``
and an expected-vs-actual ``message``. A check **dispatches on the arm**: ``Inconclusive`` →
``UNDECIDED`` (§7a — a timeout is never FAIL); ``Inconsistent`` (AS(P)=∅) → the tag's static
verdict (``@expect unsat`` PASSes, every other tag FAILs); ``Consistent`` → the per-tag decision,
reading the fields it declared via the accessor seam (``result.*_of``).

Each check declares ``reads: frozenset[Field]`` — the wiring rule (``run.py``) attaches it only to a
run whose mode populates those fields (a misroute is a ``RoutingError`` at plan construction, before
any solve; the ``SeamError`` at the accessor seam is the should-never-fire backstop). So a
``Consistent``-arm read never misses, and there is no per-field ``is None`` guard. The
containment checks (⊆) reject an empty litset at construction — mirroring ``terms.parse_litset``
(§2.1) at the type boundary — so no vacuous ``∅ ⊆ A`` PASS arises.

Checks are pure over a ``Determination``; only ``solvers.py`` touches clingo/clingcon.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import assert_never

from clingo import Symbol

from elenctic.expectation import WitnessClaim
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
    Consistent,
    Determination,
    Field,
    Inconclusive,
    Inconsistent,
    Observable,
    Verdict,
    brave_of,
    brave_optimal_of,
    cautious_of,
    cautious_optimal_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    shown_census_of,
    shown_optimal_census_of,
    witness_of,
)
from elenctic.terms import contrary, intersect_all


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The outcome of one check: a three-valued verdict plus the diagnostic to surface (dx#9, §3).

    ``label`` is the contract tag (e.g. ``@cautious optimal``); ``message`` is the diagnostic the
    user sees on a non-``PASS`` (the expected-vs-actual reading, dx#9). The report is exactly the
    *check's* output — the case's ``@note`` and its source provenance are the renderer's concern,
    read from the case (Model A), not carried here.
    """

    verdict: Verdict
    label: str
    message: str


_UNDECIDED_MESSAGE = "the solve did not complete within the budget — UNDECIDED, never FAIL"


@dataclass(frozen=True, slots=True, eq=False)
class Check:
    """A pure per-tag check carrying its contract-tag ``label``, an optional ``subject`` (the
    instance discriminator for a repeatable tag), and the ``reads`` it declares — all first-class
    and statically inspectable (dx#9 / option C / the wiring rule's LHS), so a consumer can group,
    identify, route, or *explain* a check before any solve.

    Calling it dispatches on the ``Determination`` arm: ``Inconclusive`` → ``UNDECIDED`` (§7a,
    before any decision logic); ``Inconsistent`` → the static ``_inconsistent`` verdict (AS(P)=∅
    needs no field); ``Consistent`` → ``_decide`` over the shape, reading fields through the seam.
    ``_inconsistent`` and ``_decide`` are private and omitted from ``repr`` so the arm dispatch
    cannot be bypassed. ``label`` is the contract tag (it groups checks); ``subject`` discriminates
    instances of the one repeatable tag (the ``@query`` surface; ``""`` otherwise), so
    ``(label, subject)`` names a check for explain. Equality is by **identity** (``eq=False``):
    compare ``check.label`` / ``check.subject``, never ``check == check``.
    """

    label: str
    reads: frozenset[Field]
    _inconsistent: tuple[Verdict, str] = dc_field(repr=False)
    _decide: Callable[[Consistent], tuple[Verdict, str]] = dc_field(repr=False)
    subject: str = ""

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
            case _:
                assert_never(determination)


# --- construction helpers ---


def _check(
    label: str,
    reads: frozenset[Field],
    *,
    inconsistent: tuple[Verdict, str],
    decide: Callable[[Consistent], tuple[Verdict, str]],
    subject: str = "",
) -> Check:
    """The single construction site for a check (the arm dispatch lives in ``Check.__call__``)."""
    return Check(label, reads, inconsistent, decide, subject)


def _unsat_fail(reason: str) -> tuple[Verdict, str]:
    """The ``Inconsistent``-arm FAIL for a model-needing tag: ``<reason> — AS(P) = ∅``."""
    return Verdict.FAIL, f"{reason} — AS(P) = ∅"


def _require_nonempty(items: frozenset[Symbol] | frozenset[tuple[Symbol, int]], tag: str) -> None:
    """Reject an empty litset/assignment at construction: ``∅ ⊆ A`` would be a vacuous PASS (the
    empty-litset false-PASS), mirroring ``terms.parse_litset``'s §2.1 rejection at the boundary."""
    if not items:
        raise ValueError(f"{tag} needs a non-empty set — an empty set is a vacuous claim")


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


def has_model(claim: WitnessClaim) -> Check:
    """``@model { L } [where { A }]``: a bare claim asserts ``L`` is some answer set's shown
    projection (the shown census, projection-invariant); a ``where``-qualified claim asserts there
    is one model with ``shown(M) = L`` AND ``assign(M) ⊇ A`` (the joint witness, full census — so it
    suppresses projection by reading the full token)."""
    if not claim.assign:
        return _check(
            "@model",
            frozenset({Field.SHOWN_CENSUS}),
            inconsistent=_unsat_fail(f"no model equals {_show_set(claim.shown)}"),
            decide=lambda shape: _witness(claim.shown, shown_census_of(shape), "enumerated models"),
        )
    return _check(
        "@model",
        frozenset({Field.FULL_CENSUS}),
        inconsistent=_unsat_fail(
            f"no model is {_show_set(claim.shown)} with assignment ⊇ {_show_assign(claim.assign)}"
        ),
        decide=lambda shape: _joint_witness(claim, observables_of(shape), "model"),
    )


def count_is(n: int) -> Check:
    """``@count n``: exactly ``n`` distinct observables (total at both ends). ``@count 0`` is the
    unsat case, so it PASSes on ``Inconsistent``. Reads the full census — its theory-distinct count
    is what projection would collapse, so a ``@count`` rider suppresses projection."""
    inconsistent = (
        (Verdict.PASS, "|models| = 0") if n == 0 else _unsat_fail(f"expected {n} models, got 0")
    )
    return _check(
        "@count",
        frozenset({Field.FULL_CENSUS}),
        inconsistent=inconsistent,
        decide=lambda shape: _count(n, len(observables_of(shape)), "models"),
    )


def cautious_contains(litset: frozenset[Symbol]) -> Check:
    """``@cautious { L }``: ``L ⊆ ⋂`` (the cautious consequences, §3)."""
    _require_nonempty(litset, "@cautious")
    return _check(
        "@cautious",
        frozenset({Field.CAUTIOUS}),
        inconsistent=_unsat_fail("no cautious consequences"),
        decide=lambda shape: _containment(litset, cautious_of(shape), "⋂ AS(P)"),
    )


def brave_contains(litset: frozenset[Symbol]) -> Check:
    """``@brave { L }``: ``L ⊆ ⋃`` (the brave consequences, §3)."""
    _require_nonempty(litset, "@brave")
    return _check(
        "@brave",
        frozenset({Field.BRAVE}),
        inconsistent=_unsat_fail("no brave consequences"),
        decide=lambda shape: _containment(litset, brave_of(shape), "⋃ AS(P)"),
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
        inconsistent=_unsat_fail(f"no assignment ⊇ {_show_assign(assignment)}"),
        decide=decide,
    )


# --- the optimal base (each mode is its all-base aggregation over Opt(P)) ---


def has_optimal_model(claim: WitnessClaim) -> Check:
    """``@optimal { L } [where { A }]``: a bare claim reads the shown optimal census
    (projection-invariant) — what lets it ride a projecting optimal run and terminate; a
    ``where``-qualified claim asserts one optimal model with ``shown(M) = L`` AND ``assign(M) ⊇ A``
    (the joint witness over the full optimal census)."""
    if not claim.assign:
        return _check(
            "@optimal",
            frozenset({Field.SHOWN_OPTIMAL_CENSUS}),
            inconsistent=_unsat_fail(f"no optimal model equals {_show_set(claim.shown)}"),
            decide=lambda shape: _witness(
                claim.shown, shown_optimal_census_of(shape), "optimal models"
            ),
        )
    return _check(
        "@optimal",
        frozenset({Field.FULL_OPTIMAL_CENSUS}),
        inconsistent=_unsat_fail(
            f"no optimal model is {_show_set(claim.shown)} with assignment ⊇ "
            f"{_show_assign(claim.assign)}"
        ),
        decide=lambda shape: _joint_witness(claim, optimal_observables_of(shape), "optimal model"),
    )


def cautious_optimal_contains(litset: frozenset[Symbol]) -> Check:
    """``@cautious optimal { L }``: ``L ⊆ ⋂ Opt(P)`` (the optimal backbone). Reads the shown optimal
    census (projection-invariant)."""
    _require_nonempty(litset, "@cautious optimal")
    return _check(
        "@cautious optimal",
        frozenset({Field.SHOWN_OPTIMAL_CENSUS}),
        inconsistent=_unsat_fail("no optimal models"),
        decide=lambda shape: _containment(litset, cautious_optimal_of(shape), "⋂ Opt(P)"),
    )


def brave_optimal_contains(litset: frozenset[Symbol]) -> Check:
    """``@brave optimal { L }``: ``L ⊆ ⋃ Opt(P)``. Reads the shown optimal census
    (projection-invariant)."""
    _require_nonempty(litset, "@brave optimal")
    return _check(
        "@brave optimal",
        frozenset({Field.SHOWN_OPTIMAL_CENSUS}),
        inconsistent=_unsat_fail("no optimal models"),
        decide=lambda shape: _containment(litset, brave_optimal_of(shape), "⋃ Opt(P)"),
    )


def count_optimal_is(n: int) -> Check:
    """``@count optimal n``: exactly ``n`` distinct optimal observables. Reads the full optimal
    census (the theory-distinct count projection would collapse, so it suppresses projection)."""
    inconsistent = (
        (Verdict.PASS, "|optimal models| = 0")
        if n == 0
        else _unsat_fail(f"expected {n} optimal models, got 0")
    )
    return _check(
        "@count optimal",
        frozenset({Field.FULL_OPTIMAL_CENSUS}),
        inconsistent=inconsistent,
        decide=lambda shape: _count(n, len(optimal_observables_of(shape)), "optimal models"),
    )


def assign_optimal_contains(assignment: frozenset[tuple[Symbol, int]]) -> Check:
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
        inconsistent=_unsat_fail(f"no optimal assignment ⊇ {_show_assign(assignment)}"),
        decide=decide,
    )


# --- the @query check (Def 2.2.2, corrected per the errata; base-fixed to AS(P)) ---


def _cautious_localization(
    conjuncts: tuple[Symbol, ...], cautious: frozenset[Symbol], computed: Answer
) -> str:
    """Localize a failing *singleton* ground query off ⋂ (§2.4)."""
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
    """The program's computed answer vs the contract's, for a ground query (§3)."""
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
    FR#9).

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
                inconsistent=inconsistent,
                decide=decide_binding_settled,
                subject=subject,
            )

        case _:
            assert_never(query)
