"""The one place that owns a clingo `Control`: it grounds a program and runs searches over it."""

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import Final, Self

from clingo import Control, SolveHandle, Symbol
from clingo import Model as ClingoModel
from clingo.ast import AST, ProgramBuilder, parse_files, parse_string
from clingo.configuration import Configuration

from aspnext.determination import (
    Consequences,
    Consistent,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Mode,
    Model,
    Models,
    Refutation,
    Truncation,
)
from aspnext.literals import Assumption, Literal, Scenario
from aspnext.spans import UNLOCATED, Diagnostic, Severity, diagnose

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
class _Search:
    models: tuple[Model, ...]
    conclusion: Exhausted | Truncation
    core: frozenset[Assumption]


def _model(model: ClingoModel) -> Model:
    return Model(
        frozenset(map(Literal.of, model.symbols(atoms=True))),
        frozenset(map(Literal.of, model.symbols(shown=True))),
    )


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


def _drain(
    handle: SolveHandle, cut: Callable[[], Truncation | None], cap: int | None
) -> tuple[list[Model], Exhausted | Truncation]:
    found: list[Model] = []
    handle.resume()
    while (truncation := _await(handle, cut)) is None:
        if (model := handle.model()) is None:
            return found, Exhausted.EXHAUSTED if handle.get().exhausted else Truncation.TARGET
        found.append(_model(model))
        if cap is not None and len(found) > cap:
            handle.cancel()
            return found[:cap], Truncation.TARGET
        handle.resume()
    return found, truncation


def _solve_section(ctl: Control) -> Configuration:
    section = ctl.configuration.solve
    if isinstance(section, Configuration):
        return section
    message = "clingo has no solve configuration"
    raise TypeError(message)


def _determine(search: _Search) -> Determination[Models]:
    if search.models:
        return Consistent(Models(search.models[0], search.models[1:]), search.conclusion)
    match search.conclusion:
        case Exhausted.EXHAUSTED:
            return Inconsistent(Refutation(search.core))
        case Truncation() as truncation:
            return Inconclusive(truncation)


def _consequences(mode: Mode, search: _Search) -> Determination[Consequences]:
    match search.conclusion:
        case Truncation() as truncation:
            return Inconclusive(truncation)
        case Exhausted.EXHAUSTED if search.models:
            return Consistent(Consequences(mode, search.models[-1].shown), search.conclusion)
        case Exhausted.EXHAUSTED:
            return Inconsistent(Refutation(search.core))


class Grounded:
    """A program grounded once, to be searched under any number of scenarios."""

    def __init__(self, control: Control) -> None:
        self._control = control
        # Read before any search: clingo later drops atoms that assumptions have made false.
        self._literals: Mapping[Symbol, int] = {
            atom.symbol: atom.literal for atom in control.symbolic_atoms
        }

    def _derivable(self, literal: Literal) -> bool:
        return bool(self._literals.get(literal.symbol))

    def _search(
        self,
        scenario: Scenario,
        enum_mode: str,
        cap: int | None,
        limits: Limits,
        interrupt: Interrupt | None,
    ) -> _Search:
        impossible = frozenset(a for a in scenario if a.holds and not self._derivable(a.literal))
        if impossible:
            return _Search((), Exhausted.EXHAUSTED, impossible)
        literals = {
            (lit if a.holds else -lit): a
            for a in scenario
            if (lit := self._literals.get(a.literal.symbol))
        }
        section = _solve_section(self._control)
        section.models, section.opt_mode, section.enum_mode = "0", "ignore", enum_mode
        with self._control.solve(assumptions=list(literals), yield_=True, async_=True) as handle:
            found, conclusion = _drain(handle, _cutter(limits, interrupt), cap)
            refuted = conclusion is Exhausted.EXHAUSTED and not found
            core = frozenset(literals[lit] for lit in handle.core()) if refuted else frozenset()
        return _Search(tuple(found), conclusion, core)

    def solve(
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),  # noqa: B008
        interrupt: Interrupt | None = None,
    ) -> Determination[Models]:
        """Enumerate the stable models satisfying `scenario`, whatever the program optimizes."""
        return _determine(self._search(scenario, "auto", limits.models, limits, interrupt))

    def consequences(
        self,
        mode: Mode,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),  # noqa: B008
        interrupt: Interrupt | None = None,
    ) -> Determination[Consequences]:
        """Compute the cautious or brave consequences among the shown atoms, natively."""
        return _consequences(mode, self._search(scenario, mode.value, None, limits, interrupt))


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


def ground(program: Program) -> Grounded | Fault:
    """Ground `program`, or say why it cannot be."""
    messages: list[str] = []

    def log(_code: object, message: str) -> None:
        messages.append(message)

    control = Control(["--warn=none"], logger=log)
    try:
        with ProgramBuilder(control) as builder:
            _parse(program, builder.add, log)
        control.ground([("base", [])])
    except RuntimeError as error:
        return _fault(messages, error, program)
    return Grounded(control)


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
