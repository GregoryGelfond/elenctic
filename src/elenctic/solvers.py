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
    ConsistentShownCensus,
    ConsistentShownOptimalCensus,
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

TIME_BUDGET: float = 30.0  # seconds; the hang-protection default (a hit budget is UNDECIDED)


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

    def shown_census(self) -> frozenset[frozenset[Symbol]]:
        """The set of shown projections (for the projected enumeration shapes). Under ``--project``
        the stream is already shown-deduplicated; collecting the shown sets is total either way."""
        return frozenset(observable.shown for observable in self._observables)

    def cautious(self) -> frozenset[Symbol]:
        """The cautious consequences ⋂ (``CAUTIOUS_ALL``), from the final consequence model."""
        return _require_consequence(self._cautious, "cautious")

    def brave(self) -> frozenset[Symbol]:
        """The brave consequences ⋃ (``BRAVE_ALL``), from the final consequence model."""
        return _require_consequence(self._brave, "brave")

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


def _consistent_shape(
    mode: Mode, collector: _Collector, projects_to_shown: bool = False
) -> Consistent:
    """The Mode→shape lowering arrow. Total over ``Mode`` × the projection coordinate; produces
    exactly ``run.shape_for(mode, projects_to_shown)`` (the lowering-postcondition test proves it).
    A projecting run of an enumeration mode builds the shown-only shape."""
    match mode:
        case Mode.DEFAULT:
            return ConsistentWitness(collector.witness())
        case Mode.ENUM_ALL:
            if projects_to_shown:
                return ConsistentShownCensus(collector.shown_census())
            return ConsistentEnumeration(collector.observables())
        case Mode.CAUTIOUS_ALL:
            return ConsistentCautious(collector.cautious())
        case Mode.BRAVE_ALL:
            return ConsistentBrave(collector.brave())
        case Mode.OPTIMAL_ENUM:
            # reached via the two-phase driver: the collector holds the cost-c* class (a single
            # optimization level), so its observables ARE the optimal class and its min cost is c*.
            optimal = collector.observables()
            optimum = collector.optimum()
            if projects_to_shown:
                return ConsistentShownOptimalCensus(frozenset(o.shown for o in optimal), optimum)
            return ConsistentOptimalEnumeration(optimal, optimum)
        case Mode.OPTIMAL:
            return ConsistentOptimum(collector.optimum())
        case _:
            assert_never(mode)


def _determination(
    mode: Mode,
    collector: _Collector,
    completed: bool,
    result: SolveResult,
    projects_to_shown: bool = False,
) -> Determination:
    """The three-arm decision: timeout → ``Inconclusive``; the whole-result ``unsatisfiable`` bit →
    ``Inconsistent``; else the mode's ``Consistent`` shape (shown-only when projecting)."""
    if not completed:
        return Inconclusive()
    if result.unsatisfiable:
        return Inconsistent()
    return _consistent_shape(mode, collector, projects_to_shown)


def _solve_under_budget(
    control: Control, on_model: Callable[[Model], None], budget: float
) -> tuple[bool, SolveResult]:
    """One async solve under ``budget`` reduced to ``(completed, result)``: ``wait(budget)`` then
    ``cancel`` on a miss; the handle closes via the context manager."""
    with control.solve(on_model=on_model, async_=True) as handle:
        completed = handle.wait(budget)
        if not completed:
            handle.cancel()
        return completed, handle.get()


def _drive(
    control: Control,
    mode: Mode,
    collector: _Collector,
    on_model: Callable[[Model], None],
    budget: float,
    projects_to_shown: bool = False,
) -> Determination:
    """Run one async solve under ``budget`` and reduce it to a ``Determination`` (the single-solve
    modes; ``OPTIMAL_ENUM`` uses the two-phase driver instead)."""
    completed, result = _solve_under_budget(control, on_model, budget)
    return _determination(mode, collector, completed, result, projects_to_shown)


def _set_opt_mode(control: Control, opt_mode: str) -> None:
    """Set clingo's optimization mode on an already-grounded control (``'opt'`` or
    ``'enum,<bound>'``). The configuration proxy is dynamically typed, so the assignment is isolated
    here, mirroring the untyped clingcon-theory boundary."""
    control.configuration.solve.opt_mode = opt_mode  # type: ignore[union-attr]


def _optimal_enum_two_phase(
    control: Control,
    make_on_model: Callable[[_Collector], Callable[[Model], None]],
    budget: float,
    projects_to_shown: bool,
) -> Determination:
    """Enumerate Opt(P) in two phases on one grounded ``control``, so the optimal class is correct
    independent of clingo's ``--project`` cross-level deduplication scoping:

    1. Prove the optimum c* (``opt_mode='opt'``) — a single-optimum solve.
    2. Enumerate at the fixed optimum (``opt_mode='enum,c*'``; ``--project`` is already on the
       control when projecting) — a single optimization level, so every emitted model has cost c*
       and is optimal (no post-filter needed) and no model below the optimum is enumerable.

    Each phase honours ``budget`` (a per-solve hang cap): a miss in either phase yields
    ``Inconclusive``; UNSAT in phase 1 yields ``Inconsistent``. Setting ``opt_mode`` overrides the
    construction ``--opt-mode=optN``."""
    _set_opt_mode(control, "opt")
    prover = _Collector()
    completed, result = _solve_under_budget(control, make_on_model(prover), budget)
    if not completed:
        return Inconclusive()
    if result.unsatisfiable:
        return Inconsistent()
    optimum = prover.optimum()  # the proven optimum cost vector — the phase-2 bound
    _set_opt_mode(control, "enum," + ",".join(str(c) for c in optimum.cost))
    enumerator = _Collector()
    completed, _ = _solve_under_budget(control, make_on_model(enumerator), budget)
    if not completed:
        return Inconclusive()
    return _consistent_shape(Mode.OPTIMAL_ENUM, enumerator, projects_to_shown)


# clingo's enumeration modes always project: ``--project`` is information-preserving here (the
# theory assignment is empty, so deduplicating by shown atoms equals deduplicating by observable),
# a pure performance win that never changes the result.
_CLINGO_ENUM_MODES: Final = frozenset({Mode.ENUM_ALL, Mode.OPTIMAL_ENUM})


def run_clingo(
    mode: Mode,
    program: str = "",
    files: tuple[Path, ...] = (),
    budget: float = TIME_BUDGET,
    project: bool = False,
) -> Determination:
    """Run pure clingo for ``mode`` over ``program`` + ``files``; collect a ``Determination``. The
    enumeration modes always project (information-preserving on clingo: ``assign ≡ ∅``), a pure
    performance win; a projecting clingo run still yields the full shape (``projects_to_shown`` is
    always ``False`` for a non-theory solver)."""
    control = Control(_solver_args(mode, project or mode in _CLINGO_ENUM_MODES))
    _add_program(control, program, files)
    control.ground([("base", [])])
    if mode is Mode.OPTIMAL_ENUM:
        return _optimal_enum_two_phase(
            control, lambda c: c.on_model, budget, projects_to_shown=False
        )
    collector = _Collector()
    return _drive(control, mode, collector, collector.on_model, budget, projects_to_shown=False)


def run_clingcon(
    mode: Mode,
    program: str = "",
    files: tuple[Path, ...] = (),
    budget: float = TIME_BUDGET,
    project: bool = False,
) -> Determination:
    """Run clingcon (theory-aware) for ``mode``; the observable carries the CSP assignment.

    Projection here erases theory multiplicity — the distinctness that lets ``@count``/``@assign``
    denote uniqueness over CSP output — so it is applied only when ``project`` is set (no rider
    reads the full census), and a projecting run builds the shown-only shape
    (``projects_to_shown = project``). Theory atoms are rewritten through a ``ProgramBuilder``
    (``Control.load`` does not rewrite theory atoms)."""
    import clingcon

    # clingcon is untyped; isolate the dynamic boundary to this one Any (the theory handle), so the
    # downstream register/rewrite/prepare/on_model/assignment calls need no scattered ignores.
    theory: Any = clingcon.ClingconTheory()  # type: ignore[no-untyped-call]
    control = Control(_solver_args(mode, project))
    theory.register(control)
    _rewrite_program(control, theory, program, files)
    control.ground([("base", [])])
    theory.prepare(control)

    def make_on_model(collector: _Collector) -> Callable[[Model], None]:
        def on_model(model: Model) -> None:
            theory.on_model(model)  # populate the theory assignment before reading it
            # clingcon is a linear-integer CSP solver, so assignment() yields (Symbol, int) pairs:
            # `Observable.assign`'s `int` is exact here, not a narrowing of the untyped boundary.
            assign = frozenset((sym, val) for sym, val in theory.assignment(model.thread_id))
            collector.on_model(model, assign)

        return on_model

    if mode is Mode.OPTIMAL_ENUM:
        return _optimal_enum_two_phase(control, make_on_model, budget, projects_to_shown=project)
    collector = _Collector()
    return _drive(
        control, mode, collector, make_on_model(collector), budget, projects_to_shown=project
    )


type _Facade = Callable[[Mode, str, tuple[Path, ...], float, bool], Determination]

_FACADES: Final[dict[str, _Facade]] = {"clingo": run_clingo, "clingcon": run_clingcon}


def solve(
    solver: str,
    mode: Mode,
    program: str = "",
    files: tuple[Path, ...] = (),
    budget: float = TIME_BUDGET,
    project: bool = False,
) -> Determination:
    """Dispatch to the named solver facade (the run_case entry point). ``solver`` is the case's
    derived solver name (``"clingo"`` | ``"clingcon"``); an unknown name is a programming error.
    ``project`` defaults False — a direct caller with no declared consumer does not project."""
    try:
        facade = _FACADES[solver]
    except KeyError:
        # ``Case.solver`` is a Literal, so an unknown name is a type-bypass at the public API
        # boundary (a bad argument), not a mid-run harness-invariant violation — hence ValueError,
        # not HarnessError: crash loudly at the dispatch boundary, do not report it per-case.
        raise ValueError(f"unknown solver {solver!r} (known: {sorted(_FACADES)})") from None
    return facade(mode, program, files, budget, project)


def _solver_args(mode: Mode, project: bool) -> list[str]:
    """The mode's search-config flags, plus ``--project`` iff the run projects. Shared by both
    backends — they append ``--project`` identically; whether it erases information (and so
    collapses the shape) is the facade's theory-awareness, not the flag."""
    args = list(mode.args)
    if project:
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


def _main() -> None:
    """Inspect a solve: run a ``.lp`` file under a named ``Mode`` with clingo, print the
    ``Determination``."""
    import sys

    if len(sys.argv) != 3:
        print("usage: python -m elenctic.solvers <MODE> <file.lp>", file=sys.stderr)
        print(f"  MODE one of: {', '.join(mode.name for mode in Mode)}", file=sys.stderr)
        raise SystemExit(2)
    try:
        mode = Mode[sys.argv[1]]
    except KeyError:
        known = ", ".join(mode.name for mode in Mode)
        print(f"unknown mode {sys.argv[1]!r}; one of: {known}", file=sys.stderr)
        raise SystemExit(2) from None
    print(run_clingo(mode, files=(Path(sys.argv[2]),)))


if __name__ == "__main__":
    _main()
