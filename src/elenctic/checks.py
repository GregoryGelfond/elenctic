"""Pure per-tag checks: ``Callable[[SolveResult], CheckReport]`` (spec §3, dx#9).

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

Checks are pure over ``SolveResult``; only ``solvers.py`` touches clingo/clingcon.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from clingo import Symbol

from elenctic.result import Observable, SolveResult, Verdict


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The outcome of one check: a verdict and the diagnostic to surface (dx#9, §3).

    ``label`` is the contract tag (e.g. ``@cautious optimal``); ``message`` is the
    expected-vs-actual reading the user sees on a non-``PASS`` (the dx#9 value).
    ``note`` is the case's ``@note``, attached by ``run_case`` on a failure (§2.1) —
    a check is pure over ``SolveResult`` alone and so cannot know it, and leaves it
    ``None``.
    """

    verdict: Verdict
    label: str
    message: str
    note: str | None = None


type Check = Callable[[SolveResult], CheckReport]


# --- diagnostic rendering (deterministic: sorted by text, so messages are stable) ---


def _show_set(symbols: Iterable[Symbol]) -> str:
    """Render a set of atoms ``{ a, b, c }`` (``{ }`` when empty) for a diagnostic."""
    rendered = sorted(str(symbol) for symbol in symbols)
    return "{ " + ", ".join(rendered) + " }" if rendered else "{ }"


def _show_models(models: Iterable[frozenset[Symbol]]) -> str:
    """Render a set of shown models (a set of atom-sets) for a diagnostic."""
    rendered = sorted(_show_set(model) for model in models)
    return "{ " + ", ".join(rendered) + " }" if rendered else "{ }"


def _show_assign(assignment: Iterable[tuple[Symbol, int]]) -> str:
    """Render one theory assignment ``{ v=k, … }`` for a diagnostic."""
    rendered = sorted(f"{var}={value}" for var, value in assignment)
    return "{ " + ", ".join(rendered) + " }" if rendered else "{ }"


def _show_assignments(observables: tuple[Observable, ...]) -> str:
    """Render the theory assignments observed across a run, for an ``@assign`` failure."""
    rendered = sorted(_show_assign(o.assign) for o in observables)
    return "{ " + ", ".join(rendered) + " }" if rendered else "{ }"


def _show_cost(cost: tuple[int, ...]) -> str:
    """Render a cost vector ``(4, 2)`` for a diagnostic."""
    return "(" + ", ".join(str(component) for component in cost) + ")"


# --- check construction ---

_UNDECIDED_MESSAGE = "the solve did not complete within the budget — UNDECIDED, never FAIL (§7a)"


def _verdict(passed: bool) -> Verdict:
    return Verdict.PASS if passed else Verdict.FAIL


def _check(label: str, decide: Callable[[SolveResult], tuple[Verdict, str]]) -> Check:
    """Build a check from a per-tag decision, short-circuiting an incomplete solve to
    ``UNDECIDED`` (consequence-soundness, §7a) *before* any decision logic runs."""

    def run(result: SolveResult) -> CheckReport:
        if not result.completed:
            return CheckReport(Verdict.UNDECIDED, label, _UNDECIDED_MESSAGE)
        verdict, message = decide(result)
        return CheckReport(verdict, label, message)

    return run


# --- shared decisions (one per mode; reused across the all/optimal bases) ---


def _witness(
    litset: frozenset[Symbol], models: tuple[frozenset[Symbol], ...]
) -> tuple[Verdict, str]:
    """``L ∈ { shown }`` — whole-shown-model membership over an enumerated class (§3)."""
    if any(model == litset for model in models):
        return Verdict.PASS, f"{_show_set(litset)} ∈ enumerated models"
    return Verdict.FAIL, f"{_show_set(litset)} ∉ enumerated models = {_show_models(models)}"


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
        witness = _show_set(result.observables[0].shown)
        return Verdict.FAIL, f"expected unsat, but a model exists: {witness}"

    return _check("@expect unsat", decide)


def has_model(litset: frozenset[Symbol]) -> Check:
    """``@model { L }``: some enumerated observable's shown model equals ``L`` (§3)."""
    return _check(
        "@model",
        lambda result: _witness(litset, tuple(o.shown for o in result.observables)),
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
        actual = tuple(result.optimum_cost)
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
