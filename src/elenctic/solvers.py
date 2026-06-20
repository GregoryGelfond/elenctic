"""Solver facades over the clingo/clingcon Python API — the **only impure module** (spec §4, §6).

A facade runs one configured solve and returns a :data:`~elenctic.result.Determination` (the
keystone surface): :class:`~elenctic.result.Inconclusive` if the budget was hit (§7a — a timeout
is ``UNDECIDED``, never FAIL/UNSAT), :class:`~elenctic.result.Inconsistent` if the whole-result
``unsatisfiable`` bit is set (§9.7 — decided once, never inferred from an empty field), else the
:class:`~elenctic.result.Consistent` shape the mode produces.

**The lowering contract (the accessor seam's second premise).** ``solve(mode)`` produces, for a SAT
run, *exactly* ``run.shape_for(mode)`` carrying the fields ``run.populates(mode)``. The match in
:func:`_consistent_shape` is that Mode→shape arrow; the gating lowering-postcondition test ties it
to ``shape_for``/``populates`` so the construction here and the type oracle in ``run`` do not drift.
A single ``_Collector`` dispatches on ``model.type`` (§9.1, confirmed by the §9 spikes):
``StableModel`` rows become observables (with cost); a final ``CautiousConsequences`` /
``BraveConsequences`` model carries ⋂/⋃. clingo enumeration projects onto shown atoms (distinct
observables); **clingcon never projects** — that would erase theory multiplicity (§9.3/§6.3), whose
distinctness lives in the CSP assignment.

Known v1 limitation (ledgered): a ``#maximize`` objective is reported by clingo in negated
minimize-internal form (§9.1 spike), so :func:`optimum_of`'s cost is natural for ``#minimize`` (the
minimize-dominated v1 corpus) but negated for ``#maximize``; sign-normalisation is deferred until a
maximize-using corpus arrives (it needs per-priority-level sign tracking).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, assert_never

from clingo import Control, Symbol
from clingo.solving import Model, ModelType, SolveResult

from elenctic.result import (
    Consistent,
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalEnumeration,
    ConsistentOptimum,
    ConsistentWitness,
    Determination,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
)
from elenctic.run import Mode

__all__ = ["TIME_BUDGET", "run_clingcon", "run_clingo", "solve"]

TIME_BUDGET: float = 30.0  # seconds; the harness-level hang-protection default (spec §7a)

# The enumeration modes that count distinct *shown* observables: clingo projects onto shown atoms so
# the stream is already deduplicated (spec §3 table). The consequence and witness modes do not (the
# §9.1 consequence model is computed regardless); clingcon never projects (§9.3).
_PROJECTED: Final = frozenset({Mode.ENUM_ALL, Mode.OPTIMAL_ENUM})


class _Collector:
    """Accumulates a solve's observations, dispatching on ``model.type`` (§9.1).

    ``StableModel`` rows become observables paired with their cost; the single final
    ``CautiousConsequences`` / ``BraveConsequences`` model (under cautious/brave ``--enum-mode``)
    carries the shown ⋂/⋃. The per-mode accessors read exactly what that mode's shape needs.
    """

    def __init__(self) -> None:
        self._observables: list[Observable] = []
        self._costs: list[tuple[int, ...]] = []
        self._cautious: frozenset[Symbol] | None = None
        self._brave: frozenset[Symbol] | None = None

    def on_model(self, model: Model, assign: frozenset[tuple[Symbol, int]] = frozenset()) -> None:
        # The lists stay index-aligned because the StableModel branch is the only writer of both.
        shown = frozenset(model.symbols(shown=True))
        match model.type:
            case ModelType.CautiousConsequences:
                self._cautious = shown
            case ModelType.BraveConsequences:
                self._brave = shown
            case ModelType.StableModel:
                self._observables.append(Observable(shown, assign))
                self._costs.append(tuple(model.cost))
            case _:
                assert_never(model.type)  # a future ModelType fails loud, never silently counted

    def witness(self) -> Observable:
        """The single satisfiability witness (``DEFAULT``): SAT ⟹ the ≤1-model solve found one."""
        return self._observables[0]

    def observables(self) -> tuple[Observable, ...]:
        """The distinct enumerated observables (``ENUM_ALL``), deduplicated order-preservingly."""
        return tuple(dict.fromkeys(self._observables))

    def cautious(self) -> frozenset[Symbol]:
        """The cautious consequences ⋂ (``CAUTIOUS_ALL``), from the final consequence model."""
        return _require_consequence(self._cautious, "cautious")

    def brave(self) -> frozenset[Symbol]:
        """The brave consequences ⋃ (``BRAVE_ALL``), from the final consequence model."""
        return _require_consequence(self._brave, "brave")

    def optimal_class(self) -> tuple[tuple[Observable, ...], Optimum]:
        """The distinct optimal observables and the proven optimum (``OPTIMAL_ENUM``). Under
        ``--opt-mode=optN`` the stream holds the improving prefix *and* the optimal class, so the
        class is the min-cost slice (spec §9.2/TR7), deduplicated."""
        optimum = self._optimum_cost()
        optimal = tuple(
            dict.fromkeys(
                observable
                for observable, cost in zip(self._observables, self._costs, strict=True)
                if cost == optimum
            )
        )
        return optimal, Optimum(optimum)

    def optimum(self) -> Optimum:
        """The proven optimum cost alone (``OPTIMAL``): the lexicographic min over the stream."""
        return Optimum(self._optimum_cost())

    def _optimum_cost(self) -> tuple[int, ...]:
        costs = [cost for cost in self._costs if cost]  # cost-bearing optimization models
        if not costs:
            raise HarnessError(
                "an optimization mode produced no cost vector — the encoding has no "
                "#minimize/#maximize (a discovery precondition should have caught this)"
            )
        return min(costs)  # lexicographic, priority-ordered highest-first (spec §2.0)


def _require_consequence(value: frozenset[Symbol] | None, register: str) -> frozenset[Symbol]:
    """Narrow a consequence field to non-``None`` — the §9.1 reliance made loud. A SAT
    ``--enum-mode`` run reports its ⋂/⋃ as a final consequence model, so the field is set on this
    call path; ``None`` here is a violated clingo contract (a harness bug), never a verdict."""
    if value is None:
        raise HarnessError(
            f"a satisfiable {register} run produced no consequence model (clingo §9.1 assumption "
            "violated)"
        )
    return value


def _consistent_shape(mode: Mode, collector: _Collector) -> Consistent:
    """The Mode→shape lowering arrow — the keystone's premise 2. Total over ``Mode``; produces
    exactly ``run.shape_for(mode)`` (the gating lowering-postcondition test proves it)."""
    match mode:
        case Mode.DEFAULT:
            return ConsistentWitness(collector.witness())
        case Mode.ENUM_ALL:
            return ConsistentEnumeration(collector.observables())
        case Mode.CAUTIOUS_ALL:
            return ConsistentCautious(collector.cautious())
        case Mode.BRAVE_ALL:
            return ConsistentBrave(collector.brave())
        case Mode.OPTIMAL_ENUM:
            optimal, optimum = collector.optimal_class()
            return ConsistentOptimalEnumeration(optimal, optimum)
        case Mode.OPTIMAL:
            return ConsistentOptimum(collector.optimum())
        case _:
            assert_never(mode)


def _determination(
    mode: Mode, collector: _Collector, completed: bool, result: SolveResult
) -> Determination:
    """The three-arm decision (spec §3, §7a, §9.7): timeout → ``Inconclusive``; the whole-result
    ``unsatisfiable`` bit → ``Inconsistent``; else the mode's ``Consistent`` shape."""
    if not completed:
        return Inconclusive()
    if result.unsatisfiable:
        return Inconsistent()
    return _consistent_shape(mode, collector)


def _drive(
    control: Control,
    mode: Mode,
    collector: _Collector,
    on_model: Callable[[Model], None],
    budget: float,
) -> Determination:
    """Run an async solve under ``budget`` and reduce it to a ``Determination`` (spec §6.1/§7a):
    ``wait(budget)`` then ``cancel`` on a miss; the handle closes via the context manager."""
    with control.solve(on_model=on_model, async_=True) as handle:
        completed = handle.wait(budget)
        if not completed:
            handle.cancel()
        result = handle.get()
    return _determination(mode, collector, completed, result)


def run_clingo(
    mode: Mode, program: str = "", files: tuple[Path, ...] = (), budget: float = TIME_BUDGET
) -> Determination:
    """Run pure clingo for ``mode`` over ``program`` + ``files``; collect a ``Determination``."""
    control = Control(_clingo_args(mode))
    _add_program(control, program, files)
    control.ground([("base", [])])
    collector = _Collector()
    return _drive(control, mode, collector, collector.on_model, budget)


def run_clingcon(
    mode: Mode, program: str = "", files: tuple[Path, ...] = (), budget: float = TIME_BUDGET
) -> Determination:
    """Run clingcon (theory-aware) for ``mode``; the observable carries the CSP assignment (§6.3).

    No ``--project``: it would erase theory multiplicity (§9.3/§6.3), the distinctness that lets
    ``@count``/``@assign`` denote uniqueness over CSP output. Theory atoms are rewritten through a
    ``ProgramBuilder`` (``Control.load`` does not rewrite theory atoms, §6.2)."""
    import clingcon

    # clingcon is untyped; isolate the dynamic boundary to this one Any (the theory handle), so the
    # downstream register/rewrite/prepare/on_model/assignment calls need no scattered ignores.
    theory: Any = clingcon.ClingconTheory()  # type: ignore[no-untyped-call]
    control = Control(list(mode.args))
    theory.register(control)
    _rewrite_program(control, theory, program, files)
    control.ground([("base", [])])
    theory.prepare(control)
    collector = _Collector()

    def on_model(model: Model) -> None:
        theory.on_model(model)  # populate the theory assignment before reading it (spec §6.1)
        # clingcon is a linear-*integer* CSP solver, so assignment() yields (Symbol, int) pairs —
        # `Observable.assign`'s `int` is exact here, not a silent narrowing of the untyped boundary.
        assign = frozenset((sym, val) for sym, val in theory.assignment(model.thread_id))
        collector.on_model(model, assign)

    return _drive(control, mode, collector, on_model, budget)


type _Facade = Callable[[Mode, str, tuple[Path, ...], float], Determination]

_FACADES: Final[dict[str, _Facade]] = {"clingo": run_clingo, "clingcon": run_clingcon}


def solve(
    solver: str,
    mode: Mode,
    program: str = "",
    files: tuple[Path, ...] = (),
    budget: float = TIME_BUDGET,
) -> Determination:
    """Dispatch to the named solver facade (the run_case entry point). ``solver`` is the case's
    derived solver name (``"clingo"`` | ``"clingcon"``); an unknown name is a programming error."""
    try:
        facade = _FACADES[solver]
    except KeyError:
        # ``Case.solver`` is a Literal, so an unknown name is a type-bypass at the public API
        # boundary (a bad argument), not a mid-run harness-invariant violation — hence ValueError,
        # not HarnessError: crash loudly at the dispatch boundary, do not report it per-case.
        raise ValueError(f"unknown solver {solver!r} (known: {sorted(_FACADES)})") from None
    return facade(mode, program, files, budget)


def _clingo_args(mode: Mode) -> list[str]:
    """clingo's args for ``mode``: the mode's lowering, plus ``--project`` for the enumeration modes
    that count distinct shown observables (spec §3 table). clingcon never projects (§9.3)."""
    args = list(mode.args)
    if mode in _PROJECTED:
        args.append("--project")
    return args


def _add_program(control: Control, program: str, files: tuple[Path, ...]) -> None:
    """Load inline ``program`` and ``files`` into clingo's ``base`` part (the load order)."""
    if program:
        control.add("base", [], program)
    for path in files:
        control.add("base", [], path.read_text(encoding="utf-8"))


def _rewrite_program(control: Control, theory: Any, program: str, files: tuple[Path, ...]) -> None:
    """Rewrite inline ``program`` and ``files`` through clingcon's theory rewriter into ``control``
    (spec §6.2). ``theory`` is the untyped clingcon handle; the local clingo.ast import keeps that
    dependency at the theory boundary."""
    from clingo.ast import ProgramBuilder, parse_string

    with ProgramBuilder(control) as builder:

        def add(ast: object) -> None:
            theory.rewrite_ast(ast, builder.add)

        if program:
            parse_string(program, add)
        for path in files:
            parse_string(path.read_text(encoding="utf-8"), add)
