"""The one place that owns a clingo `Control`: it grounds a program and runs searches over it."""

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import reduce
from operator import itemgetter
from pathlib import Path
from time import monotonic
from typing import Any, Final, Self

from clingo import Control, SolveHandle, Symbol, SymbolType
from clingo import Model as ClingoModel
from clingo.ast import AST, ASTType, ProgramBuilder, UnaryOperator, parse_files, parse_string
from clingo.configuration import Configuration

from elenctic.determination import (
    Consequences,
    Consistent,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Mode,
    Model,
    Models,
    NoAssumptions,
    NotThese,
    Optimized,
    Optimum,
    Refutation,
    These,
    Truncation,
)
from elenctic.literals import AnswerSet, Assumption, Literal, Scenario, Signature
from elenctic.spans import UNLOCATED, Diagnostic, Severity, diagnose

_SLICE: Final = 0.02


@dataclass(frozen=True, slots=True)
class Program:
    """ASP source text, and where it came from; `path` makes `#include` resolve beside it."""

    text: str
    source: str = "<string>"
    path: Path | None = None

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls(path.read_text(encoding="utf-8"), str(path), path)


class Locus(StrEnum):
    """Whose fault a failure is."""

    PROGRAM = "program"
    REQUEST = "request"


@dataclass(frozen=True, slots=True)
class Fault:
    """A failure that is no answer about the program: it could not be asked."""

    locus: Locus
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class Limits:
    """How far a search may go; `None` is no limit."""

    seconds: float | None = None
    models: int | None = None

    def __post_init__(self) -> None:
        if any(limit is not None and limit < 0 for limit in (self.seconds, self.models)):
            message = "a limit is never negative"
            raise ValueError(message)


class Interrupt:
    """A request to stop, which may be made from any thread and is heeded between models."""

    def __init__(self) -> None:
        self._pulled = threading.Event()

    def pull(self) -> None:
        self._pulled.set()

    @property
    def pulled(self) -> bool:
        return self._pulled.is_set()


@dataclass(frozen=True, slots=True)
class _Run[T]:
    """What one clingo solve call found, and how it ended; `core` only when it found nothing."""

    found: tuple[T, ...]
    conclusion: Exhausted | Truncation
    core: frozenset[Assumption]

    @property
    def refuted(self) -> bool:
        """Whether the whole space was searched and held nothing."""
        return self.conclusion is Exhausted.EXHAUSTED and not self.found


def _literals(symbols: Iterable[Symbol]) -> AnswerSet:
    """Keep the classical literals of `symbols`; `#show` may also select numbers or strings."""
    return frozenset(Literal.of(s) for s in symbols if s.type is SymbolType.Function and s.name)


def _model(model: ClingoModel) -> Model:
    return Model(
        _literals(model.symbols(atoms=True)),
        _literals(model.symbols(shown=True)),
        cost=tuple(model.cost),
    )


def _step(model: ClingoModel) -> tuple[Model, bool]:
    """Pair a model with whether it is proven optimal, as every model is without an objective."""
    return _model(model), model.optimality_proven or not model.cost


def _cutter(limits: Limits, interrupt: Interrupt | None) -> Callable[[], Truncation | None]:
    deadline = None if limits.seconds is None else monotonic() + limits.seconds

    def cut() -> Truncation | None:
        if interrupt is not None and interrupt.pulled:
            return Truncation.INTERRUPTED
        return Truncation.BUDGET if deadline is not None and monotonic() >= deadline else None

    return cut


def _await(handle: SolveHandle, cut: Callable[[], Truncation | None]) -> Truncation | None:
    """Wait for a model or the end, cancelling the search if it is cut first."""
    while (truncation := cut()) is None:
        if handle.wait(_SLICE):
            return None
    handle.cancel()
    return truncation


def _drain[T](
    handle: SolveHandle,
    cut: Callable[[], Truncation | None],
    cap: int | None,
    convert: Callable[[ClingoModel], T],
    counted: Callable[[T], bool],
) -> tuple[list[T], Exhausted | Truncation]:
    """Take models until the end, the cut, or one more counted model than `cap`."""
    found: list[T] = []
    seen = 0
    handle.resume()
    while (truncation := _await(handle, cut)) is None:
        if (model := handle.model()) is None:
            return found, Exhausted.EXHAUSTED if handle.get().exhausted else Truncation.TARGET
        found.append(convert(model))
        seen += counted(found[-1])
        if cap is not None and seen > cap:
            handle.cancel()
            return found[:-1], Truncation.TARGET
        handle.resume()
    return found, truncation


def _solve_section(ctl: Control) -> Configuration:
    section = ctl.configuration.solve
    if isinstance(section, Configuration):
        return section
    message = "clingo has no solve configuration"
    raise TypeError(message)


@dataclass(frozen=True, slots=True)
class _Plan[T]:
    """How to run a solve: the (enum, opt) modes, what to keep of a model, what counts to a cap."""

    modes: tuple[str, str]
    convert: Callable[[ClingoModel], T]
    counted: Callable[[T], bool]


def _always(_: object) -> bool:
    return True


def _key(assumption: Assumption) -> tuple[Literal, bool]:
    return assumption.literal, assumption.holds


def _decide[T, E](
    run: _Run[T],
    refutation: Refutation | None,
    evidence: Callable[[list[T]], E],
) -> Determination[E]:
    """Read a run as a determination: models make it consistent, an exhausted none inconsistent."""
    if run.found:
        return Consistent(evidence(list(run.found)), run.conclusion)
    match run.conclusion:
        case Exhausted.EXHAUSTED if refutation is not None:
            return Inconsistent(refutation)
        case Truncation() as truncation:
            return Inconclusive(truncation)
    message = "an exhausted search that found nothing is refuted"
    raise ValueError(message)


def _models(found: list[Model]) -> Models:
    return Models(found[0], tuple(found[1:]))


def _optimized(found: list[tuple[Model, bool]]) -> Optimized:
    optimal = [model for model, proven in found if proven]
    if optimal:
        return Optimum(optimal[0].cost, _models(optimal))
    return Incumbent(found[-1][0])


@dataclass(frozen=True, slots=True)
class Shown:
    """The predicates `#show` selects; with no `#show` statement every atom is shown.

    A `#show` of a term with a variable selects what the grounder decides, so it is `wild`.
    """

    signatures: frozenset[Signature] = frozenset()
    restricted: bool = False
    wild: bool = False

    def covers(self, signature: Signature) -> bool:
        return not self.restricted or self.wild or signature in self.signatures

    def __or__(self, other: Shown) -> Shown:
        return Shown(
            self.signatures | other.signatures,
            self.restricted or other.restricted,
            self.wild or other.wild,
        )


@dataclass(frozen=True, slots=True)
class Facts:
    """What the grounded program says about itself, which a contract is checked against."""

    shown: Shown = Shown()
    optimizes: bool = False
    theory: bool = False


def _signature(term: AST) -> Signature | None:
    """Read the predicate a `#show` term names; `None` for a term that is not a literal."""
    match term.ast_type:
        case ASTType.Function:
            return Signature(term.name, len(term.arguments))
        case ASTType.SymbolicTerm if term.symbol.type is SymbolType.Function:
            return Signature(term.symbol.name, len(term.symbol.arguments), term.symbol.positive)
        case ASTType.UnaryOperation if term.operator_type == UnaryOperator.Minus:
            inner = _signature(term.argument)
            return inner and Signature(inner.name, inner.arity, positive=not inner.positive)
        case _:
            return None


def _shown(statement: AST) -> Shown:
    """Read what a statement selects to show; a statement that is no `#show` selects nothing."""
    match statement.ast_type:
        case ASTType.ShowSignature:
            signature = Signature(statement.name, statement.arity, bool(statement.positive))
            return Shown(frozenset({signature}), restricted=True)
        case ASTType.ShowTerm:
            term = _signature(statement.term)
            return Shown(
                frozenset({term} if term else ()),
                restricted=True,
                wild=statement.term.ast_type is ASTType.Variable,
            )
        case _:
            return Shown()


_PLAIN: Final = _Plan[Model](("auto", "ignore"), _model, _always)


class Grounded:
    """A program grounded once, to be searched under any number of scenarios."""

    def __init__(self, control: Control, facts: Facts = Facts()) -> None:  # noqa: B008
        self._control = control
        self.facts = replace(facts, theory=next(iter(control.theory_atoms), None) is not None)
        # Read before any search: clingo later drops atoms that assumptions have made false.
        self._literals: Mapping[Symbol, int] = {
            atom.symbol: atom.literal for atom in control.symbolic_atoms
        }
        self.signatures: frozenset[Signature] = frozenset(
            Signature(symbol.name, len(symbol.arguments), symbol.positive)
            for symbol in self._literals
            if symbol.type is SymbolType.Function
        )

    def _derivable(self, literal: Literal) -> bool:
        return bool(self._literals.get(literal.symbol))

    def _assumed(self, scenario: Iterable[Assumption]) -> dict[int, Assumption]:
        """Map the clingo literal of each assumption that says something about the grounding."""
        return {
            (lit if a.holds else -lit): a
            for a in scenario
            if (lit := self._literals.get(a.literal.symbol))
        }

    def _impossible(self, scenario: Iterable[Assumption]) -> frozenset[Assumption]:
        return frozenset(a for a in scenario if a.holds and not self._derivable(a.literal))

    def _run[T](
        self,
        scenario: Scenario,
        plan: _Plan[T],
        cap: int | None,
        cut: Callable[[], Truncation | None],
    ) -> _Run[T]:
        assumed = self._assumed(scenario)
        if impossible := self._impossible(scenario):
            return _Run((), Exhausted.EXHAUSTED, impossible)
        section = _solve_section(self._control)
        section.models = "0"
        section.enum_mode, section.opt_mode = plan.modes
        with self._control.solve(assumptions=list(assumed), yield_=True, async_=True) as handle:
            found, conclusion = _drain(handle, cut, cap, plan.convert, plan.counted)
            run = _Run(tuple(found), conclusion, frozenset())
            core = frozenset(assumed[lit] for lit in handle.core()) if run.refuted else frozenset()
        return replace(run, core=core)

    def _contradicts(
        self, scenario: frozenset[Assumption], cut: Callable[[], Truncation | None]
    ) -> frozenset[Assumption] | Truncation | None:
        """Return a core of `scenario`, a truncation, or `None` if some model satisfies it."""
        if impossible := self._impossible(scenario):
            return impossible
        run = self._run(scenario, _PLAIN, 0, cut)
        match run.conclusion:
            case Exhausted.EXHAUSTED:
                return run.core
            case Truncation.TARGET:
                return None
            case Truncation() as truncation:
                return truncation

    def _refutation(
        self, scenario: Scenario, core: frozenset[Assumption], cut: Callable[[], Truncation | None]
    ) -> Refutation:
        """Why no model satisfies `scenario`: a minimal clashing subset, shrunk from `core`."""
        if not scenario:
            return NoAssumptions()
        kept = core
        for assumption in sorted(kept, key=_key):
            if assumption not in kept:
                continue
            match self._contradicts(kept - {assumption}, cut):
                case frozenset() as smaller:
                    kept = smaller
                case Truncation():
                    return These(kept, minimal=False)
                case None:
                    pass
        return These(kept) if kept else NotThese()

    def _refutation_of(
        self, scenario: Scenario, run: _Run[Any], cut: Callable[[], Truncation | None]
    ) -> Refutation | None:
        """Refute a run that exhausted its space and found nothing; `None` for any other."""
        return self._refutation(scenario, run.core, cut) if run.refuted else None

    def _search[T, E](
        self,
        scenario: Scenario,
        plan: _Plan[T],
        cap: int | None,
        cut: Callable[[], Truncation | None],
        evidence: Callable[[list[T]], E],
    ) -> Determination[E]:
        run = self._run(scenario, plan, cap, cut)
        return _decide(run, self._refutation_of(scenario, run, cut), evidence)

    def solve(
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),  # noqa: B008
        interrupt: Interrupt | None = None,
    ) -> Determination[Models]:
        """Enumerate the stable models satisfying `scenario`, whatever the program optimizes."""
        cut = _cutter(limits, interrupt)
        return self._search(scenario, _PLAIN, limits.models, cut, _models)

    def consequences(
        self,
        mode: Mode,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),  # noqa: B008
        interrupt: Interrupt | None = None,
    ) -> Determination[Consequences]:
        """Compute the cautious or brave consequences among the shown atoms, natively."""
        plan = _Plan((mode.value, "ignore"), _model, _always)
        cut = _cutter(limits, interrupt)
        return self._search(
            scenario, plan, None, cut, lambda found: Consequences(mode, found[-1].shown)
        )

    def optimize(
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),  # noqa: B008
        interrupt: Interrupt | None = None,
    ) -> Determination[Optimized]:
        """Find the optimum under `scenario` and the models that attain it.

        `limits.models` bounds the optimal models, not the improving ones found on the way.
        """
        plan = _Plan(("auto", "optN"), _step, itemgetter(1))
        cut = _cutter(limits, interrupt)
        return self._search(scenario, plan, limits.models, cut, _optimized)


def _fault(messages: list[str], error: RuntimeError, program: Program) -> Fault:
    diagnostics = tuple(
        replace(d, span=replace(d.span, source=program.source))
        if d.span.source == "<string>"
        else d
        for d in diagnose("".join(messages))
    )
    return Fault(Locus.PROGRAM, diagnostics or (Diagnostic(UNLOCATED, Severity.ERROR, str(error)),))


def _parse(program: Program, add: Callable[[AST], None], logger: Callable[..., None]) -> None:
    if program.path is None:
        parse_string(program.text, add, logger=logger)
    else:
        parse_files([str(program.path)], add, logger=logger)


class _Objective:
    """Observe the grounding for an objective: one that grounds away never reaches the solver."""

    def __init__(self) -> None:
        self.seen = False

    def minimize(self, priority: int, literals: Sequence[tuple[int, int]]) -> None:  # noqa: ARG002
        """Record that a priority level has weighted literals (the observer's callback)."""
        self.seen = True


def ground(program: Program) -> Grounded | Fault:
    """Ground `program`, or say why it cannot be."""
    messages: list[str] = []

    def log(_code: object, message: str) -> None:
        messages.append(message)

    control = Control(["--warn=none"], logger=log)
    objective = _Objective()
    control.register_observer(objective)  # type: ignore[arg-type]
    shown: list[Shown] = []
    try:
        with ProgramBuilder(control) as builder:

            def add(statement: AST) -> None:
                shown.append(_shown(statement))
                builder.add(statement)

            _parse(program, add, log)
        control.ground([("base", [])])
    except RuntimeError as error:
        return _fault(messages, error, program)
    return Grounded(control, Facts(reduce(Shown.__or__, shown, Shown()), objective.seen))


def solve(
    program: Program,
    scenario: Scenario = frozenset(),
    *,
    limits: Limits = Limits(),  # noqa: B008
    interrupt: Interrupt | None = None,
) -> Determination[Models] | Fault:
    """Enumerate the stable models of `program` satisfying `scenario`."""
    grounded = ground(program)
    if isinstance(grounded, Fault):
        return grounded
    return grounded.solve(scenario, limits=limits, interrupt=interrupt)
