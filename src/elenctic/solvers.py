"""Solver facades over the clingo/clingcon Python API — the **only impure module**.

A facade runs one configured solve and returns a :data:`~elenctic.result.Determination`:
:class:`~elenctic.result.Inconclusive` if the solve did not settle the question — the budget was
hit, the solver gave up, or the search stopped before covering the collection the mode's reading
ranges over (any of the three ``UNDECIDED``, never FAIL/UNSAT),
:class:`~elenctic.result.Inconsistent` if the whole-result ``unsatisfiable`` bit is set (decided
once, never inferred from an empty field),
else the :class:`~elenctic.result.Consistent` shape the mode produces.

**The lowering contract (the accessor seam's second premise).** ``solve(mode)`` produces, for a SAT
run, *exactly* ``run.shape_for(mode)`` carrying the fields ``run.populates(mode)``. The match in
:func:`_consistent_shape` is that Mode→shape arrow; the gating lowering-postcondition test ties it
to ``shape_for``/``populates`` so the construction here and the type oracle in ``run`` do not drift.
A single ``_Collector`` dispatches on ``model.type``:
``StableModel`` rows become observables (with cost); a final ``CautiousConsequences`` /
``BraveConsequences`` model carries ⋂/⋃. clingo enumeration always projects onto shown atoms
(information-preserving there, ``assign ≡ ∅``); clingcon projects only when no rider reads the full
census — a contract-induced decision (``run.should_project``), since projecting clingcon collapses
the CSP multiplicity that ``@count``/``@assign`` observe.

Known v1 limitation: a ``#maximize`` objective is reported by clingo in negated
minimize-internal form, so :func:`optimum_of`'s cost is natural for ``#minimize`` (the
minimize-dominated v1 corpus) but negated for ``#maximize``; sign-normalisation is deferred until a
maximize-using corpus arrives (it needs per-priority-level sign tracking).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, assert_never

from clingo import Control, Symbol
from clingo.solving import Model, ModelType, SolveResult

from elenctic.discovery import SolverUnavailableError
from elenctic.program import ProgramError
from elenctic.registry import SOLVERS
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

# The companion bound to TIME_BUDGET, over the other exhaustible resource. A solve holds every
# model it is shown, and a time budget says nothing about how fast they arrive — a program decides
# that — so a budget that never expires can still end in exhausted memory. High enough that no
# corpus reading a collection anyone means to read will meet it, and a run that does meet it is
# reported as not having finished, which is what it is.
MODEL_CAP: int = 1_000_000


class _Collector:
    """Accumulates a solve's observations, dispatching on ``model.type``.

    ``StableModel`` rows become observables paired with their cost; the single final
    ``CautiousConsequences`` / ``BraveConsequences`` model (under cautious/brave ``--enum-mode``)
    carries the shown ⋂/⋃. The per-mode accessors read exactly what that mode's shape needs.
    """

    def __init__(self, cap: int = MODEL_CAP) -> None:
        self._cap = cap
        self.models_seen = 0
        self._observables: list[Observable] = []
        self._costs: list[tuple[int, ...]] = []
        self._cautious: frozenset[Symbol] | None = None
        self._brave: frozenset[Symbol] | None = None

    def on_model(self, model: Model, assign: frozenset[tuple[Symbol, int]] = frozenset()) -> bool:
        """Take one model; return whether the search should continue.

        Returning ``False`` at the cap is clingo's own way to stop a search, and stopping is what
        keeps the accumulation below it. A stopped search reports itself as not exhausted, so a
        reading over a whole collection is already routed to ``Inconclusive`` — the cap needs no
        verdict vocabulary of its own, because running out of room and running out of time are the
        same fact about knowledge."""
        # The lists stay index-aligned because the StableModel branch is the only writer of both.
        shown = frozenset(model.symbols(shown=True))
        match model.type:
            case ModelType.CautiousConsequences:
                self._cautious = shown
            case ModelType.BraveConsequences:
                self._brave = shown
            case ModelType.StableModel:
                self.models_seen += 1
                self._observables.append(Observable(shown, assign))
                self._costs.append(tuple(model.cost))
            case _:
                assert_never(model.type)  # a future ModelType fails loud, never silently counted
        return self.models_seen < self._cap

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
        return min(costs)  # lexicographic, priority-ordered highest-first


def _require_consequence(value: frozenset[Symbol] | None, register: str) -> frozenset[Symbol]:
    """Narrow a consequence field to non-``None`` — the clingo-contract reliance made loud. A SAT
    ``--enum-mode`` run reports its ⋂/⋃ as a final consequence model, so the field is set on this
    call path; ``None`` here is a violated clingo contract (a harness bug), never a verdict."""
    if value is None:
        raise HarnessError(
            f"a satisfiable {register} run produced no consequence model (clingo assumption "
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


def _undecided_or_unsat(completed: bool, result: SolveResult) -> Inconclusive | Inconsistent | None:
    """Reduce one solve's satisfiability outcome to the arm it settles, or ``None`` if it decided
    satisfiable.

    clingo's solve result is three-valued — satisfiable, unsatisfiable, or unknown — and the third
    value is a real outcome rather than an absent one: the search stopped without deciding. It is
    reported exactly as a hit time budget is, because they are the same fact about knowledge
    (nothing was determined), and reading either as satisfiable would build an answer out of a
    search that produced none. Every solve in this module reduces its result here, so this
    three-valued read happens in one place.

    This settles *whether a model exists*. Whether the search that ran covered what the mode's
    reading ranges over is the separate question :func:`_exhaustion_satisfied` asks, because the
    two are independent and only the second is mode-dependent."""
    if not completed or result.unknown:
        return Inconclusive()
    if result.unsatisfiable:
        return Inconsistent()
    return None


def _exhaustion_satisfied(mode: Mode, result: SolveResult) -> bool:
    """Whether ``result``'s search covered what ``mode``'s reading requires of it.

    A solve reports exhaustiveness separately from satisfiability, and the two are independent: a
    search can decide satisfiable and still stop before covering the collection. A reading that
    ranges over a whole collection is a claim about every member, so over such a search it becomes a
    claim about an arbitrary prefix — the same absence of knowledge an undecided solve reports, and
    reported the same way. A reading of a single witness carries no such claim, so it is exempt.

    ``exhausted`` is necessary here, not sufficient. It certifies that the search space was covered
    *under the configuration the run was given*, so it says nothing about whether that configuration
    was the right one — an enumeration under an active objective exhausts while having visited only
    the improving sequence. That second requirement is carried by each mode's ``args`` and gated
    separately. What the bit entails also varies by enumeration mode: a census is complete, a
    consequence run reached its fixpoint so the reported ⋂/⋃ is the true one, and an optimizing run
    has *proven* its optimum rather than reporting a best-so-far.

    An unsatisfiable result never reaches here: a proof that no answer set exists is already a
    complete answer about the collection."""
    return result.exhausted or not mode.asks.needs_exhausted_search


def _determination(
    mode: Mode,
    collector: _Collector,
    completed: bool,
    result: SolveResult,
    projects_to_shown: bool = False,
) -> Determination:
    """The three-arm decision: a solve that did not decide → ``Inconclusive``; the whole-result
    ``unsatisfiable`` bit → ``Inconsistent``; else the mode's ``Consistent`` shape (shown-only when
    projecting), reported only if the search behind it finished.

    The shape is formed before the exhaustion question is asked, so that a mode whose requirements
    the solve did not meet still fails loudly. ``OPTIMAL`` on a program carrying no objective is
    that case: clingo has nothing to optimize, so it stops at the first model and reports a search
    that did not finish — the same bit a truncated search sets. Reducing that to ``UNDECIDED`` would
    report an elenctic fault as a statement about the program under test, and would swallow the
    diagnostic saying the encoding has no ``#minimize``/``#maximize``."""
    settled = _undecided_or_unsat(completed, result)
    if settled is not None:
        return settled
    shape = _consistent_shape(mode, collector, projects_to_shown)
    return shape if _exhaustion_satisfied(mode, result) else Inconclusive()


class _CallbackGuard:
    """Preserve the type of an exception raised inside elenctic's own model callback.

    An asynchronous ``Control.solve`` does not re-raise a callback exception unchanged: it surfaces
    at ``SolveHandle.get`` rewrapped as a plain ``RuntimeError``, keeping only the message. Since
    the surrounding boundary reads a ``RuntimeError`` as a fault in the program under test, an
    unguarded failure in elenctic's callback would be reported as its author's fault. Recording the
    original here lets it be re-raised with its type intact, which leaves ``RuntimeError`` meaning
    what the translation assumes: a fault originating in the solver."""

    __slots__ = ("_on_model", "failure")

    def __init__(self, on_model: Callable[[Model], bool]) -> None:
        self._on_model = on_model
        self.failure: BaseException | None = None

    def __call__(self, model: Model) -> bool:
        # The callback's answer is passed through, not discarded: returning False is how clingo is
        # told to stop, so swallowing it would leave the collector's cap unreachable.
        try:
            return self._on_model(model)
        except BaseException as exc:
            self.failure = exc
            raise

    def reraise_if_failed(self) -> None:
        """Re-raise the recorded callback exception, if there was one, with its type intact."""
        if self.failure is not None:
            raise self.failure


def _solve_under_budget(
    control: Control, on_model: Callable[[Model], bool], budget: float
) -> tuple[bool, SolveResult]:
    """One async solve under ``budget`` reduced to ``(completed, result)``: ``wait(budget)`` then
    ``cancel`` on a miss; the handle closes via the context manager. A failure raised inside
    ``on_model`` reaches ``get()`` with its type erased, so it is restored from the guard before it
    can be mistaken for a fault originating in the solver."""
    guard = _CallbackGuard(on_model)
    with control.solve(on_model=guard, async_=True) as handle:
        completed = handle.wait(budget)
        if not completed:
            handle.cancel()
        try:
            result = handle.get()
        except RuntimeError:
            # A callback failure arrives here with its type erased; restore the original.
            guard.reraise_if_failed()
            raise
        # And on the path where nothing was raised at all: a cancelled solve can absorb the
        # callback's exception entirely, returning as though only the budget had been missed. The
        # recorded failure is re-raised here too, because reporting an elenctic fault as a budget
        # miss would present an internal bug as the verdict UNDECIDED — a statement about the
        # program under test that was never made.
        guard.reraise_if_failed()
        return completed, result


def _drive(
    control: Control,
    mode: Mode,
    collector: _Collector,
    on_model: Callable[[Model], bool],
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
    make_on_model: Callable[[_Collector], Callable[[Model], bool]],
    budget: float,
    projects_to_shown: bool,
) -> Determination:
    """Enumerate Opt(P) in two phases on one grounded ``control``, so the optimal class is correct
    independent of clingo's ``--project`` cross-level deduplication scoping:

    1. Prove the optimum c* (``opt_mode='opt'``) — a single-optimum solve.
    2. Enumerate at the fixed optimum (``opt_mode='enum,c*'``; ``--project`` is already on the
       control when projecting) — a single optimization level, so every emitted model has cost c*
       and is optimal (no post-filter needed) and no model below the optimum is enumerable.

    Each phase honours ``budget`` (a per-solve hang cap). A phase that does not decide — the budget
    was hit, or the search gave up — yields ``Inconclusive``, as does one that decides but stops
    before finishing: phase 1 would then not have *proven* the optimum, and phase 2 would hold part
    of the optimal class rather than the class. UNSAT in phase 1 yields ``Inconsistent``. Setting
    ``opt_mode`` overrides the construction ``--opt-mode=optN``."""
    _set_opt_mode(control, "opt")
    prover = _Collector()
    completed, result = _solve_under_budget(control, make_on_model(prover), budget)
    settled = _undecided_or_unsat(completed, result)
    if settled is not None:
        return settled
    optimum = prover.optimum()  # the proven optimum cost vector — the phase-2 bound
    if not _exhaustion_satisfied(Mode.OPTIMAL_ENUM, result):
        return Inconclusive()  # the bound was not proven, so there is nothing to enumerate at
    _set_opt_mode(control, "enum," + ",".join(str(c) for c in optimum.cost))
    enumerator = _Collector()
    completed, result = _solve_under_budget(control, make_on_model(enumerator), budget)
    settled = _undecided_or_unsat(completed, result)
    if settled is not None:
        return settled
    shape = _consistent_shape(Mode.OPTIMAL_ENUM, enumerator, projects_to_shown)
    return shape if _exhaustion_satisfied(Mode.OPTIMAL_ENUM, result) else Inconclusive()


# clingo's enumeration modes always project: ``--project`` is information-preserving here (the
# theory assignment is empty, so deduplicating by shown atoms equals deduplicating by observable),
# a pure performance win that never changes the result.
_CLINGO_ENUM_MODES: Final = frozenset({Mode.ENUM_ALL, Mode.OPTIMAL_ENUM})


def _capture(messages: list[str]) -> Callable[[object, str], None]:
    """A clingo logger that records diagnostics into ``messages`` rather than letting them reach
    stderr — elenctic owns its own output, and the routine ones ("atom does not occur in any rule
    head", the projection caveat) are noise here.

    Capturing rather than discarding them is load-bearing. When grounding fails, clingo reports the
    offending file, line and cause through this channel, while the exception it raises carries only
    a generic summary; without the captured text a program fault cannot be reported with the
    provenance its author needs. Mirrors the captured logger ``program.inspect`` already uses."""

    def logger(_code: object, message: str) -> None:
        messages.append(message)

    return logger


@contextmanager
def _program_faults(files: tuple[Path, ...], messages: list[str]) -> Iterator[None]:
    """Translate a solver-origin ground or solve failure into a ``ProgramError`` naming the program
    and carrying clingo's own captured diagnostic.

    A program that will not ground has no answer sets *defined*, which is not the same as having
    none, so this must never produce ``Inconsistent`` — that would silently pass an ``@expect
    unsat`` contract written against a broken program. The catch is by exception type and
    deliberately narrow: elenctic's own errors are not in it and stay loud, and ``RecursionError``
    is re-raised because it is a ``RuntimeError`` subclass that never means the program under test
    is at fault."""
    try:
        yield
    except RecursionError:
        raise
    except (RuntimeError, UnicodeDecodeError, OSError) as exc:
        names = ", ".join(str(path) for path in files) or "<inline program>"
        # Both, never one or the other: the logger holds the provenance (file, line, cause) but
        # accumulates routine notices too, so a fault raised after a clean ground would otherwise
        # be reported as whichever harmless notice happened to be logged first, with the real
        # cause dropped.
        detail = "; ".join([*messages, str(exc)])
        raise ProgramError(f"cannot run the program ({names}): {detail}") from exc


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
    messages: list[str] = []
    control = Control(
        _solver_args(mode, project or mode in _CLINGO_ENUM_MODES), logger=_capture(messages)
    )
    with _program_faults(files, messages):
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
    try:
        import clingcon
    except ImportError as exc:
        # A direct facade call bypasses the per-case check, so the same condition is reported here
        # with the same type and the same remedy — catchable either as an ImportError, which is
        # what a missing optional dependency is, or by name.
        raise SolverUnavailableError(
            'clingcon is not installed — install the theory extra: pip install "elenctic[theory]"'
        ) from exc

    # clingcon is untyped; isolate the dynamic boundary to this one Any (the theory handle), so the
    # downstream register/rewrite/prepare/on_model/assignment calls need no scattered ignores.
    theory: Any = clingcon.ClingconTheory()  # type: ignore[no-untyped-call]
    messages: list[str] = []
    control = Control(_solver_args(mode, project), logger=_capture(messages))
    with _program_faults(files, messages):
        theory.register(control)
        _rewrite_program(control, theory, program, files)
        control.ground([("base", [])])
        theory.prepare(control)

        def make_on_model(collector: _Collector) -> Callable[[Model], bool]:
            def on_model(model: Model) -> bool:
                theory.on_model(model)  # populate the theory assignment before reading it
                # clingcon is a linear-integer CSP solver, so assignment() yields (Symbol, int)
                # pairs: `Observable.assign`'s `int` is exact here, not a narrowing of the untyped
                # boundary.
                assign = frozenset((sym, val) for sym, val in theory.assignment(model.thread_id))
                # The collector's answer is returned, not dropped: the theory path is bounded by
                # the same cap as the plain one.
                return collector.on_model(model, assign)

            return on_model

        if mode is Mode.OPTIMAL_ENUM:
            return _optimal_enum_two_phase(
                control, make_on_model, budget, projects_to_shown=project
            )
        collector = _Collector()
        return _drive(
            control, mode, collector, make_on_model(collector), budget, projects_to_shown=project
        )


type _Facade = Callable[[Mode, str, tuple[Path, ...], float, bool], Determination]

_FACADES: Final[dict[str, _Facade]] = {"clingo": run_clingo, "clingcon": run_clingcon}
assert frozenset(_FACADES) == SOLVERS, "solvers._FACADES drifted from registry.SOLVERS"


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
    """Load inline ``program`` and ``files`` into clingo's ``base`` part. ``control.load`` resolves
    each file's ``#include`` directives relative to the including file; the inline
    ``program`` (no file context) goes through ``control.add``."""
    if program:
        control.add("base", [], program)
    for path in files:
        control.load(str(path))


def _rewrite_program(control: Control, theory: Any, program: str, files: tuple[Path, ...]) -> None:
    """Rewrite inline ``program`` and ``files`` through clingcon's theory rewriter into ``control``.
    ``parse_files`` resolves ``#include`` relative to the including file AND fires the
    theory rewrite on the *expanded* AST (a theory atom inside an ``#include``d
    library is rewritten and propagated) — unlike ``parse_string`` over ``read_text``, which
    resolves ``#include`` relative to CWD. ``theory`` is the untyped clingcon handle; the local
    clingo.ast import keeps that dependency at the theory boundary."""
    from clingo.ast import ProgramBuilder, parse_files, parse_string

    with ProgramBuilder(control) as builder:

        def add(ast: object) -> None:
            theory.rewrite_ast(ast, builder.add)

        if program:
            parse_string(program, add)
        if files:
            parse_files([str(path) for path in files], add)


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
