"""Pure per-tag checks (spec §3, dx#9): each is a :class:`Check`, a labelled callable.

A check reads one :class:`~elenctic.result.SolveResult` and returns a
:class:`CheckReport` — a three-valued :class:`~elenctic.result.Verdict` *plus the
diagnostic* (dx#9): the contract ``label`` and an expected-vs-actual ``message``.
The dx#9 layer (``run_case``/``render``) ships that diagnostic to the consumer
rather than re-deriving it in every client.

Two invariants hold for every check (spec §3, §7a):

- **Consequence-soundness:** an incomplete solve (``not completed``) is
  ``UNDECIDED``, never ``FAIL`` — an interrupted brave/cautious run carries a
  one-sided error, so unknown is never false.
- **Totality (TR2):** on an empty base-selected set (``observables == ()`` at
  base ``all``, ``optimal_observables == ()`` at base ``optimal``,
  ``union``/``intersection`` then ``None``) a check returns ``FAIL`` — never
  raising, never evaluating ``L ⊆ None``.

The litsets and cost vectors a check is built from are non-empty by construction
(``parse`` rejects an empty litset, §2.1), so a check never faces a vacuous
``∅ ⊆ A`` PASS through the pipeline.

Checks are pure over ``SolveResult``; only ``solvers.py`` touches clingo/clingcon.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
    ground_answer,
)
from elenctic.result import Observable, SolveResult, Verdict
from elenctic.terms import contrary


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The outcome of one check: a three-valued verdict plus the diagnostic to surface (dx#9, §3).

    ``label`` is the contract tag (e.g. ``@cautious optimal``); ``message`` is the
    expected-vs-actual reading the user sees on a non-``PASS`` (the dx#9 value). The report
    is exactly the *check's* output — the case's documentation (``@note``) and its
    ``path:line`` are the renderer's concern, read from the case, not carried here.
    """

    verdict: Verdict
    label: str
    message: str


_UNDECIDED_MESSAGE = "the solve did not complete within the budget — UNDECIDED, never FAIL"


@dataclass(frozen=True, slots=True)
class Check:
    """A pure per-tag check carrying its contract-tag ``label`` as a first-class, statically
    inspectable identity (dx#9). Every check is labelled — there is no unlabelled check — and the
    label it *reports* is the same one it *carries* (a single source), so a consumer can group,
    identify, or *explain* the checks a run will perform before any solve, without running them.

    Calling the check runs it: an incomplete solve (``not completed``) short-circuits to
    ``UNDECIDED`` (consequence-soundness, §7a) *before* any decision logic; otherwise the per-tag
    ``_decide`` yields the ``(verdict, message)`` of the diagnostic. ``_decide`` is private so the
    §7a short-circuit cannot be bypassed.
    """

    label: str
    _decide: Callable[[SolveResult], tuple[Verdict, str]]

    def __call__(self, result: SolveResult) -> CheckReport:
        if not result.completed:
            return CheckReport(Verdict.UNDECIDED, self.label, _UNDECIDED_MESSAGE)
        verdict, message = self._decide(result)
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


def _check(label: str, decide: Callable[[SolveResult], tuple[Verdict, str]]) -> Check:
    """Build a labelled check from a per-tag decision (the §7a short-circuit lives in ``Check``)."""
    return Check(label, decide)


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
    """``L ⊆ aggregate`` where ``aggregate`` is ⋂ or ⋃ (``glyph``), surfacing the
    missing atoms on a failure (§3)."""
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
    """``@expect sat``: ``AS(P) ≠ ∅`` — a model exists (spec §2.1)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        if result.observables != ():
            return Verdict.PASS, "AS(P) ≠ ∅ — a model exists"
        return Verdict.FAIL, "expected sat, but AS(P) = ∅ — no model"

    return _check("@expect sat", decide)


def expect_unsat() -> Check:
    """``@expect unsat``: ``AS(P) = ∅`` — no model (spec §2.1)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        if result.observables == ():
            return Verdict.PASS, "AS(P) = ∅ — no model, as expected"
        witness = min(result.observables, key=lambda o: sorted(map(str, o.shown)))
        return Verdict.FAIL, f"expected unsat, but a model exists: {_show_set(witness.shown)}"

    return _check("@expect unsat", decide)


def has_model(litset: frozenset[Symbol]) -> Check:
    """``@model { L }``: some enumerated observable's shown model equals ``L`` (§3)."""
    return _check(
        "@model",
        lambda result: _witness(
            litset, tuple(o.shown for o in result.observables), "enumerated models"
        ),
    )


def count_is(n: int) -> Check:
    """``@count n``: exactly ``n`` distinct observables (total at both ends, §3)."""
    return _check("@count", lambda result: _count(n, len(result.observables), "models"))


def cautious_contains(litset: frozenset[Symbol]) -> Check:
    """``@cautious { L }``: ``L ⊆ ⋂`` (the cautious consequences, §3)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        if result.intersection is None:
            return (
                Verdict.FAIL,
                "no cautious consequences — ⋂ not computed (AS(P) = ∅ or no cautious run)",
            )
        return _containment(litset, result.intersection, "⋂")

    return _check("@cautious", decide)


def brave_contains(litset: frozenset[Symbol]) -> Check:
    """``@brave { L }``: ``L ⊆ ⋃`` (the brave consequences, §3)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        if result.union is None:
            return (
                Verdict.FAIL,
                "no brave consequences — ⋃ not computed (AS(P) = ∅ or no brave run)",
            )
        return _containment(litset, result.union, "⋃")

    return _check("@brave", decide)


def cost_is(cost: tuple[int, ...]) -> Check:
    """``@cost { c }``: the proven optimum cost vector equals ``c`` by value (§3, §2.0)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        if result.optimum_cost is None:
            return (
                Verdict.FAIL,
                f"no optimum proven (need an optimization run); expected cost {_show_cost(cost)}",
            )
        actual = result.optimum_cost
        if actual == cost:
            return Verdict.PASS, f"optimum cost = {_show_cost(cost)}"
        return Verdict.FAIL, f"expected cost {_show_cost(cost)}, got {_show_cost(actual)}"

    return _check("@cost", decide)


def assign_contains(assignment: frozenset[tuple[Symbol, int]]) -> Check:
    """``@assign { A }``: some observable's theory assignment ⊇ ``A`` (§3, §6.3)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        if any(assignment <= o.assign for o in result.observables):
            return Verdict.PASS, f"{_show_assign(assignment)} ⊆ some observable's assignment"
        return (
            Verdict.FAIL,
            f"no observable's assignment ⊇ {_show_assign(assignment)}; "
            f"assignments seen = {_show_assignments(result.observables)}",
        )

    return _check("@assign", decide)


# --- the optimal base (each mode is its all-base aggregation over Opt(P), §3) ---


def _optimal_shown(result: SolveResult) -> tuple[frozenset[Symbol], ...]:
    return tuple(o.shown for o in result.optimal_observables)


def _intersection(family: tuple[frozenset[Symbol], ...]) -> frozenset[Symbol]:
    """⋂ of a non-empty family of atom sets (the caller guards emptiness)."""
    return family[0].intersection(*family[1:])


def _union(family: tuple[frozenset[Symbol], ...]) -> frozenset[Symbol]:
    """⋃ of a non-empty family of atom sets (the caller guards emptiness)."""
    return family[0].union(*family[1:])


def has_optimal_model(litset: frozenset[Symbol]) -> Check:
    """``@optimal { L }`` (= ``@model optimal``): ``L`` is some optimal model (§3)."""
    return _check(
        "@optimal",
        lambda result: _witness(litset, _optimal_shown(result), "optimal models"),
    )


def cautious_optimal_contains(litset: frozenset[Symbol]) -> Check:
    """``@cautious optimal { L }``: ``L ⊆ ⋂ Opt(P)`` (the optimal backbone, §3)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        shown = _optimal_shown(result)
        if not shown:
            return Verdict.FAIL, "no optimal models — Opt(P) not enumerated"
        return _containment(litset, _intersection(shown), "⋂ Opt(P)")

    return _check("@cautious optimal", decide)


def brave_optimal_contains(litset: frozenset[Symbol]) -> Check:
    """``@brave optimal { L }``: ``L ⊆ ⋃ Opt(P)`` (§3)."""

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        shown = _optimal_shown(result)
        if not shown:
            return Verdict.FAIL, "no optimal models — Opt(P) not enumerated"
        return _containment(litset, _union(shown), "⋃ Opt(P)")

    return _check("@brave optimal", decide)


def count_optimal_is(n: int) -> Check:
    """``@count optimal n``: exactly ``n`` distinct optimal observables (§3)."""
    return _check(
        "@count optimal",
        lambda result: _count(n, len(result.optimal_observables), "optimal models"),
    )


# --- the @query check (Def 2.2.2, base-fixed to AS(P); reads ⋂, and ⋃ for unknown) ---


def _ground_witness(
    conjuncts: tuple[Symbol, ...], intersection: frozenset[Symbol], actual: Answer
) -> str:
    """Localize a failing ground query — the conjuncts that fell short of the answer (§2.4)."""
    if actual is Answer.unknown:
        missing = _show_set(c for c in conjuncts if c not in intersection)
        return f" (not entailed: {missing})"
    if actual is Answer.no:
        refuted = _show_set(c for c in conjuncts if contrary(c) in intersection)
        return f" (counter-entailed: {refuted})"
    return ""  # computed yes but a non-yes answer was asserted — the conjuncts are all entailed


def query_matches(query: Query) -> Check:
    """The ``@query`` check (Def 2.2.2, spec §3): the program's computed answer matches the
    contract's. Reads the cautious consequences ⋂ (and the brave ⋃ for an ``unknown``
    binding); short-circuits to ``FAIL`` on ``AS(P) = ∅``, where every query is vacuously
    yes-and-no (§2.2, FR#9).

    Total: a misroute that withholds ⋃ from an ``unknown`` binding is a ``FAIL`` naming the
    missing aggregate, never a raise. (``runs_for`` routes an ``unknown`` binding to a run
    that populates ⋃; this guard is the belt-and-suspenders if that ever fails.)
    """

    def decide(result: SolveResult) -> tuple[Verdict, str]:
        intersection = result.intersection
        if intersection is None:
            return Verdict.FAIL, "AS(P) = ∅ — every query is vacuously yes-and-no; @query fails"
        match query:
            case GroundQuery(answer, conjuncts):
                actual = ground_answer(conjuncts, intersection)
                if actual is answer:
                    return Verdict.PASS, f"{_show_set(conjuncts)}: computed {answer.value}"
                witness = _ground_witness(conjuncts, intersection, actual)
                return (
                    Verdict.FAIL,
                    f"{_show_set(conjuncts)}: expected {answer.value}, "
                    f"computed {actual.value}{witness}",
                )
            case BindingQuery(answer, goal, bindings):
                if answer is Answer.unknown and result.union is None:
                    return (
                        Verdict.FAIL,
                        f"{_show_goal(goal)}: an unknown binding needs the brave consequences ⋃ "
                        "— not computed (route to a brave run)",
                    )
                found = binding_set(goal, answer, intersection, result.union)
                if found == bindings:
                    return (
                        Verdict.PASS,
                        f"{_show_goal(goal)}: computed {answer.value} {_show_tuples(found)}",
                    )
                return (
                    Verdict.FAIL,
                    f"{_show_goal(goal)}: expected {answer.value} {_show_tuples(bindings)}, "
                    f"computed {_show_tuples(found)}",
                )
            case _:
                assert_never(query)

    return _check("@query", decide)
