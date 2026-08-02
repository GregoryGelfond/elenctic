"""Solver facades over the clingo/clingcon Python API — the **only impure module**.

A facade runs one configured solve and returns a :class:`~elenctic.result.SolveOutcome`: the arm the
solve settled, paired with how its search ended. The arm is
:class:`~elenctic.result.Inconclusive` if the solve settled nothing — the budget was hit before it
decided, or the solver gave up (both ``UNDECIDED``, never FAIL/UNSAT);
:class:`~elenctic.result.Inconsistent` if the whole-result ``unsatisfiable`` bit is set (decided
once, never inferred from an empty field);
else the :class:`~elenctic.result.Consistent` shape the mode produces.

A search cut short still reports the satisfiability it settled, and every arm reports the search
behind it — the undecided one included, where how the search ended is the only thing there is to
say. Whether that search covered what a *reading* needs is a question about what is read, and a run
carries several checks that do not all range over the same thing — so that question is answered
where the reading is (``checks.py``), and this module reports only the
:class:`~elenctic.result.Conclusion` it observed.

**The lowering contract (the accessor seam's second premise).** Whenever ``solve(mode)`` yields a
``Consistent``, it is *exactly* ``run.shape_for(mode)`` carrying the fields ``run.populates(mode)``.
A satisfiable solve does not always yield one: a search may settle satisfiability and still produce
nothing the mode's shape can honestly be made of, which is reported as a solve that settled nothing.
The match in :func:`_consistent_shape` is that Mode→shape arrow; the gating lowering-postcondition
test ties it to ``shape_for``/``populates`` so the construction here and the type oracle in ``run``
do not drift.
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
from contextlib import AbstractContextManager, contextmanager, nullcontext
from functools import partial
from pathlib import Path
from typing import Any, Final, assert_never

from clingo import Control, Symbol
from clingo.solving import Model, ModelType, SolveResult

from elenctic.discovery import SolverUnavailableError
from elenctic.program import ProgramError
from elenctic.registry import SOLVERS
from elenctic.result import (
    Conclusion,
    Consistent,
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalEnumeration,
    ConsistentOptimum,
    ConsistentShownCensus,
    ConsistentShownOptimalCensus,
    ConsistentWitness,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    SolveOutcome,
)
from elenctic.run import Mode

__all__ = ["TIME_BUDGET", "run_clingcon", "run_clingo", "solve"]

# The hang-protection default, in seconds. A budget hit *before* the solve decides is UNDECIDED
# and never FAIL; one hit after it decides keeps what was decided, and only the readings that
# needed more of the search go UNDECIDED.
TIME_BUDGET: float = 30.0

# The companion bound to TIME_BUDGET, over the other exhaustible resource. An enumerating solve
# holds every model it is shown, and a time budget says nothing about how fast they arrive — a
# program decides that — so a budget that never expires can still end in exhausted memory. High
# enough that no corpus reading a collection anyone means to read will meet it, and a run that does
# meet it is reported as not having finished, which is what it is.
#
# It counts stable models, so it bounds the modes that are shown them: the enumerations. A
# consequence run is shown a refining sequence of consequence *sets* instead, of which only the
# latest is kept, so it is bounded already and this cap never fires there.
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
        keeps the accumulation below it. A stopped search reports itself as not exhausted, which is
        what a reading over a whole collection consults before trusting it — so the cap needs no
        verdict vocabulary of its own. Note that clingo does *not* set its interrupted bit for a
        callback that asks it to stop: the bit is for an interruption from outside the search."""
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

    def cautious(self) -> frozenset[Symbol] | None:
        """The last cautious-consequence set clingo reported (``CAUTIOUS_ALL``), or ``None`` if the
        search ended before it reported one.

        clingo narrows this set as the search proceeds, so it is ⋂ only once the search has closed
        the space; over a search that did not close the space it is a *superset* of ⋂. Which of the
        two you hold is what the outcome's conclusion says, and no reader may treat this as ⋂
        without
        consulting it."""
        return self._cautious

    def brave(self) -> frozenset[Symbol] | None:
        """The last brave-consequence set clingo reported (``BRAVE_ALL``), or ``None`` if the search
        ended before it reported one.

        clingo widens this set as the search proceeds, so it is ⋃ only once the search has closed
        the space; over a search that did not close the space it is a *subset* of ⋃ — the mirror of
        the
        cautious case, and read under the same condition."""
        return self._brave

    def optimum(self) -> Optimum:
        """The lexicographic minimum cost over the models this collector saw.

        It takes a minimum; it proves nothing. Whether that minimum is *the* optimum is the
        caller's to have established — by a search that closed its own space, or by an earlier
        phase that proved the bound this one enumerates at. Both phases of the two-phase optimal
        driver call it, as does the single-optimum mode."""
        return Optimum(self._optimum_cost())

    def _optimum_cost(self) -> tuple[int, ...]:
        costs = [cost for cost in self._costs if cost]  # cost-bearing optimization models
        if not costs:
            # A ``ProgramError``, not a ``HarnessError``. The discovery precondition reads a
            # *syntactic* fact — a ``#minimize``/``#maximize``/``:~`` appears in the program — and
            # having a cost is a fact about the *ground* program, which is not the same thing: an
            # objective over an empty domain grounds away and leaves none. So arriving here does
            # not establish that the precondition failed, and claiming it did would accuse
            # elenctic of a bug the corpus explains. Either way the program lacks what the mode
            # needs, which its author is the one who can fix.
            raise ProgramError(
                "an optimization mode produced no cost vector: the ground program has no "
                "objective. Either the encoding declares no #minimize/#maximize at all, or it "
                "declares one that is not in the ground program — its elements ground away, or it "
                "sits in a program part this run does not ground"
            )
        return min(costs)  # lexicographic, priority-ordered highest-first


def _consistent_shape(
    mode: Mode,
    collector: _Collector,
    projects_to_shown: bool,
    conclusion: Conclusion,
) -> Consistent | None:
    """The Mode→shape lowering arrow. Total over ``Mode`` × the projection coordinate; produces
    exactly ``run.shape_for(mode, projects_to_shown)`` (the lowering-postcondition test proves it).
    A projecting run of an enumeration mode builds the shown-only shape.

    ``None`` where the search did not produce what the shape is *made of*, which is not the same
    question as whether a reading over it would be sound — that one belongs to the reading, and is
    asked of the check. Two cases:

    - a consequence mode whose search ended before clingo reported its fixpoint, so the ⋂ or ⋃ that
      mode exists to produce was never computed and there is no partial one to offer instead;
    - ``OPTIMAL`` over a search that did not finish, because an :class:`~elenctic.result.Optimum`
      asserts a *proven* optimum by its own construction. The best cost a stopped search happened
      to reach is not one, and building it would put a claim nobody established into a type whose
      meaning is that someone did. ``OPTIMAL_ENUM`` needs no such guard: its optimum is proven by a
      first phase that must exhaust before a second runs, so a truncated second phase yields a
      partial class around a sound optimum, and it is the class the reading is refused over.

    The caller reports either as a solve that settled nothing."""
    match mode:
        case Mode.DEFAULT:
            return ConsistentWitness(collector.witness())
        case Mode.ENUM_ALL:
            if projects_to_shown:
                return ConsistentShownCensus(collector.shown_census())
            return ConsistentEnumeration(collector.observables())
        case Mode.CAUTIOUS_ALL:
            cautious = collector.cautious()
            return None if cautious is None else ConsistentCautious(cautious)
        case Mode.BRAVE_ALL:
            brave = collector.brave()
            return None if brave is None else ConsistentBrave(brave)
        case Mode.OPTIMAL_ENUM:
            # reached via the two-phase driver: the collector holds the cost-c* class (a single
            # optimization level), so its observables ARE the optimal class and its min cost is c*.
            optimal = collector.observables()
            optimum = collector.optimum()
            if projects_to_shown:
                return ConsistentShownOptimalCensus(frozenset(o.shown for o in optimal), optimum)
            return ConsistentOptimalEnumeration(optimal, optimum)
        case Mode.OPTIMAL:
            # Three states, and the order separates them. A search that reported no model at all
            # says nothing about the program, so nothing is claimed about it. One that reported
            # models but no cost has told us the ground program carries no objective — a fact
            # independent of how far the search got, and one that must be surfaced rather than
            # folded into "undecided", because a program with nothing to optimize does not exhaust
            # this mode's search. Only then does an unproven best-so-far get refused.
            if not collector.models_seen:
                return None
            optimum = collector.optimum()
            if conclusion is not Conclusion.EXHAUSTED:
                return None
            return ConsistentOptimum(optimum)
        case _:
            assert_never(mode)


def _outcome_unless_satisfiable(completed: bool, result: SolveResult) -> SolveOutcome | None:
    """The outcome of a solve that did not decide *satisfiable*, or ``None`` if it did.

    clingo's result is three-valued — satisfiable, unsatisfiable, or neither — and its first two
    fields are ``None`` rather than ``False`` when nothing was settled, so testing them in turn is
    total and needs nothing else. In particular a search cut short by a budget still reports the
    satisfiability it managed to settle, and that answer is kept: discarding it would report a
    question as unanswered because a *different* question ran out of time.

    Both arms report the search that produced them, and a solve that settled nothing reports it too:
    that is the only thing such a solve has to say, and it is what tells a reader whether to raise a
    budget or to look at the program."""
    if result.satisfiable:
        return None
    arm = Inconsistent() if result.unsatisfiable else Inconclusive()
    return SolveOutcome(arm, _conclusion(completed, result))


def _conclusion(completed: bool, result: SolveResult) -> Conclusion:
    """How a search that settled satisfiability ended.

    Exhaustion wins a tie: a search that closed the space did so whatever else was also true of it.
    Otherwise an external cut — clingo's own interrupted bit, or a budget this side missed —
    outranks a bound the run requested, because a run that both hit its bound and was cancelled was
    still ended from outside.

    What ``exhausted`` certifies is that the space was covered *under the configuration the run was
    given*, so it says nothing about whether that configuration was the right one: an enumeration
    under an active objective exhausts having visited only the improving sequence. That second
    requirement is carried by each mode's ``args`` and gated separately."""
    if result.exhausted:
        return Conclusion.EXHAUSTED
    if result.interrupted or not completed:
        return Conclusion.INTERRUPTED
    return Conclusion.INCOMPLETE


def _outcome(
    mode: Mode,
    collector: _Collector,
    completed: bool,
    result: SolveResult,
    projects_to_shown: bool = False,
) -> SolveOutcome:
    """The solve's arm together with how its search ended: a solve that settled nothing is
    ``Inconclusive``; the whole-result ``unsatisfiable`` bit is ``Inconsistent``; else the mode's
    ``Consistent`` shape (shown-only when projecting). Every arm is paired with the same observed
    conclusion, including the one that carries no field of its own — a solve with nothing to report
    about the program still has something to report about the search.

    Whether that search covered what a reading needs is deliberately **not** decided here. It
    depends on what is read, and this module does not know what will read it — one run carries
    several checks and they do not all range over the same thing."""
    decided = _outcome_unless_satisfiable(completed, result)
    if decided is not None:
        return decided
    conclusion = _conclusion(completed, result)
    shape = _consistent_shape(mode, collector, projects_to_shown, conclusion)
    if shape is None:
        return SolveOutcome(Inconclusive(), conclusion)
    return SolveOutcome(shape, conclusion)


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


# The region a caller supplies to say whose fault a solver-origin failure is. It is a factory
# rather than a context manager because a driver may solve more than once, and a region is entered
# once. `nullcontext` is what a caller with no program to name supplies: a direct call has no file
# to attribute a fault to, so nothing is translated and the failure propagates as itself.
type _FaultRegion = Callable[[], AbstractContextManager[None]]


def _drive(
    control: Control,
    mode: Mode,
    collector: _Collector,
    on_model: Callable[[Model], bool],
    budget: float,
    projects_to_shown: bool = False,
    *,
    faults: _FaultRegion = nullcontext,
) -> SolveOutcome:
    """Run one async solve under ``budget`` and reduce it to a ``SolveOutcome`` (the single-solve
    modes; ``OPTIMAL_ENUM`` uses the two-phase driver instead).

    ``faults`` covers the solve and stops there. What follows is elenctic's own reduction of what
    came back, running long past the point where a failure could be the program's, so a region
    reaching over it would report an elenctic defect as a program that cannot be run."""
    with faults():
        completed, result = _solve_under_budget(control, on_model, budget)
    return _outcome(mode, collector, completed, result, projects_to_shown)


def _set_opt_mode(control: Control, opt_mode: str) -> None:
    """Set clingo's optimization mode on an already-grounded control (``'opt'`` or
    ``'enum,<bound>'``). The configuration proxy is dynamically typed, so the assignment is isolated
    here, mirroring the untyped clingcon-theory boundary.

    A rejected value is a ``HarnessError``: the string is elenctic's own construction, so the
    corpus cannot be at fault for it. Without this it would surface as the ``RuntimeError`` clingo
    reports every failure as, and the enclosing region would report it as a fault in the program."""
    try:
        control.configuration.solve.opt_mode = opt_mode  # type: ignore[union-attr]
    except RuntimeError as exc:
        raise HarnessError(
            f"clingo rejected the optimization mode elenctic built ({opt_mode!r})"
        ) from exc


def _optimal_enum_two_phase(
    control: Control,
    make_on_model: Callable[[_Collector], Callable[[Model], bool]],
    budget: float,
    projects_to_shown: bool,
    *,
    faults: _FaultRegion = nullcontext,
) -> SolveOutcome:
    """Enumerate Opt(P) in two phases on one grounded ``control``, so the optimal class is correct
    independent of clingo's ``--project`` cross-level deduplication scoping:

    1. Prove the optimum c* (``opt_mode='opt'``) — a single-optimum solve.
    2. Enumerate at the fixed optimum (``opt_mode='enum,c*'``; ``--project`` is already on the
       control when projecting) — a single optimization level, so every emitted model has cost c*
       and is optimal (no post-filter needed) and no model below the optimum is enumerable.

    Each phase honours ``budget`` (a per-solve hang cap). A phase that does not decide — the budget
    was hit, or the search gave up — yields ``Inconclusive``. So does a first phase that decides but
    does not finish: an unproven optimum is not a bound there is anything to enumerate at, which is
    a fact about this driver rather than about what will be read, so it is settled here. UNSAT in
    phase 1 yields ``Inconsistent``. Setting ``opt_mode`` overrides the construction
    ``--opt-mode=optN``.

    ``faults`` covers each solve and nothing between them: the reduction that decides whether there
    is a second phase is elenctic's own, and so is ``_set_opt_mode``, which builds its argument
    here and therefore reports a rejected one as elenctic's rather than the corpus's."""
    _set_opt_mode(control, "opt")
    prover = _Collector()
    with faults():
        completed, result = _solve_under_budget(control, make_on_model(prover), budget)
    decided = _outcome_unless_satisfiable(completed, result)
    if decided is not None:
        return decided
    conclusion = _conclusion(completed, result)
    if conclusion is not Conclusion.EXHAUSTED:
        # The optimum was not proven, so there is no bound to enumerate at. Asked before the cost
        # is read, because a search cut short may have collected no cost at all, and reading one
        # there would report "this program has no objective" about a program whose objective the
        # budget never reached — an accusation the corpus did not earn. The honest form of that
        # diagnostic is not lost: this phase enumerates without a model bound, so a program that
        # really has no objective exhausts it, passes here, and meets the cost read below. The
        # single-optimum mode orders these the other way round, and safely, because it guards the
        # no-model case on its own and its search does *not* exhaust on such a program.
        return SolveOutcome(Inconclusive(), conclusion)
    optimum = prover.optimum()  # the proven optimum cost vector — the phase-2 bound
    _set_opt_mode(control, "enum," + ",".join(str(c) for c in optimum.cost))
    enumerator = _Collector()
    with faults():
        completed, result = _solve_under_budget(control, make_on_model(enumerator), budget)
    decided = _outcome_unless_satisfiable(completed, result)
    if decided is not None:
        return decided
    conclusion = _conclusion(completed, result)
    shape = _consistent_shape(Mode.OPTIMAL_ENUM, enumerator, projects_to_shown, conclusion)
    if shape is None:
        # Unreachable: the optimal-enumeration arm always builds, because phase 1 proved the
        # bound this phase enumerates at. Loud rather than absent, so a future arm that learns to
        # decline says so here instead of being read as an enumeration of nothing.
        raise HarnessError(
            "the optimal-class enumeration declined to build a shape (an elenctic bug, not a "
            "verdict)"
        )
    return SolveOutcome(shape, conclusion)


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
    is at fault.

    It is entered around the calls that hand work to the solver and left as soon as they return, so
    what it covers has one owner. Its postcondition is what makes each translation statable on its
    own: the solver ran, and either it produced a result or a ``ProgramError`` names the file and
    carries clingo's diagnostic. Reducing that result is elenctic's, and happens outside."""
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
) -> SolveOutcome:
    """Run pure clingo for ``mode`` over ``program`` + ``files``; collect a ``SolveOutcome``. The
    enumeration modes always project (information-preserving on clingo: ``assign ≡ ∅``), a pure
    performance win; a projecting clingo run still yields the full shape (``projects_to_shown`` is
    always ``False`` for a non-theory solver)."""
    messages: list[str] = []
    control = Control(
        _solver_args(mode, project or mode in _CLINGO_ENUM_MODES), logger=_capture(messages)
    )
    faults = partial(_program_faults, files, messages)
    with faults():
        _add_program(control, program, files)
        control.ground([("base", [])])
    if mode is Mode.OPTIMAL_ENUM:
        return _optimal_enum_two_phase(
            control, lambda c: c.on_model, budget, projects_to_shown=False, faults=faults
        )
    collector = _Collector()
    return _drive(
        control, mode, collector, collector.on_model, budget, projects_to_shown=False, faults=faults
    )


def run_clingcon(
    mode: Mode,
    program: str = "",
    files: tuple[Path, ...] = (),
    budget: float = TIME_BUDGET,
    project: bool = False,
) -> SolveOutcome:
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
    # Registering the propagator concerns the solver, not the program, so a failure there is not
    # the corpus author's and is left outside the region that would say it was.
    theory.register(control)
    faults = partial(_program_faults, files, messages)
    with faults():
        _rewrite_program(control, theory, program, files, messages)
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
            control, make_on_model, budget, projects_to_shown=project, faults=faults
        )
    collector = _Collector()
    return _drive(
        control,
        mode,
        collector,
        make_on_model(collector),
        budget,
        projects_to_shown=project,
        faults=faults,
    )


type _Facade = Callable[[Mode, str, tuple[Path, ...], float, bool], SolveOutcome]

_FACADES: Final[dict[str, _Facade]] = {"clingo": run_clingo, "clingcon": run_clingcon}
assert frozenset(_FACADES) == SOLVERS, "solvers._FACADES drifted from registry.SOLVERS"


def solve(
    solver: str,
    mode: Mode,
    program: str = "",
    files: tuple[Path, ...] = (),
    budget: float = TIME_BUDGET,
    project: bool = False,
) -> SolveOutcome:
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


def _rewrite_program(
    control: Control, theory: Any, program: str, files: tuple[Path, ...], messages: list[str]
) -> None:
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

        # The capturing logger belongs here as much as on the control: these calls do the parsing
        # on this path, so without it a theory program's parse diagnostics go to stderr unowned —
        # outside elenctic's framing, unsanitised, and missing from the fault this raises.
        capture = _capture(messages)
        if program:
            parse_string(program, add, logger=capture)
        if files:
            parse_files([str(path) for path in files], add, logger=capture)


def _main() -> None:
    """Inspect a solve: run a ``.lp`` file under a named ``Mode`` with clingo, print the
    ``SolveOutcome``."""
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
