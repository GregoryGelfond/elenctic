"""The one place that owns a clingo `Control`: it grounds a program and runs searches over it."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Final, override

from clingo import Control
from clingo.ast import AST, ProgramBuilder, parse_files, parse_string
from clingo.backend import Observer

from elenctic.contract import Solver
from elenctic.determination import Determination, Models
from elenctic.facts import Facts, objective_at, shown_by, theory_at
from elenctic.grounded import Grounded
from elenctic.literals import Scenario
from elenctic.program import Fault, Locus, Program
from elenctic.search import UNLIMITED, Interrupt, Limits
from elenctic.spans import UNLOCATED, Diagnostic, Position, Severity, Span, diagnose
from elenctic.theory import Clingcon, Plain, Theory

_EXTRA: Final = "theory"
_UNDEFINED: Final = re.compile(r"no definition found for theory atom:\s+(?P<atom>\S+)")


def _clarified(diagnostic: Diagnostic) -> Diagnostic:
    """Say in elenctic's terms what clingo says of a theory atom that has no `#theory`."""
    if (found := _UNDEFINED.fullmatch(diagnostic.message)) is None:
        return diagnostic
    message = (
        f"the theory atom `&{found['atom']}` has no `#theory` definition, so it cannot be "
        "grounded; define the theory, or declare `% @elenctic solver clingcon` for clingcon's"
    )
    return replace(diagnostic, message=message)


def _fault(messages: list[str], error: RuntimeError, program: Program) -> Fault:
    diagnostics = tuple(
        _clarified(
            replace(d, span=replace(d.span, source=program.source))
            if d.span.source == "<string>"
            else d
        )
        for d in diagnose("".join(messages))
    )
    return Fault(Locus.PROGRAM, diagnostics or (Diagnostic(UNLOCATED, Severity.ERROR, str(error)),))


def _parse(program: Program, add: Callable[[AST], None], logger: Callable[..., None]) -> None:
    if program.path is None:
        parse_string(program.text, add, logger=logger)
    else:
        parse_files([str(program.path)], add, logger=logger)


class _Objective(Observer):
    """Observe the grounding for an objective: one that grounds away never reaches the solver."""

    def __init__(self) -> None:
        self.seen = False

    @override
    def minimize(self, priority: int, literals: Sequence[tuple[int, int]]) -> None:
        """Record that a priority level has weighted literals (the observer's callback)."""
        self.seen = True


_THEORIES: Final[Mapping[Solver, Callable[[], Theory | None]]] = {
    Solver.CLINGO: Plain,
    Solver.CLINGCON: Clingcon.load,
}


def _absent(solver: Solver, program: Program) -> Fault:
    """Say the contract names a solver that is not installed, and what installs it."""
    here = Span(program.source, Position(1, 1), Position(1, 1))
    message = (
        f"the contract declares `% @elenctic solver {solver}`, which is not installed; "
        f"install `elenctic[{_EXTRA}]`, or use the pixi `{_EXTRA}` environment"
    )
    return Fault(Locus.REQUEST, (Diagnostic(here, Severity.ERROR, message),))


def ground(program: Program, solver: Solver = Solver.CLINGO) -> Grounded | Fault:
    """Ground `program` for `solver`, or say why it cannot be."""
    theory = _THEORIES[solver]()
    if theory is None:
        return _absent(solver, program)
    messages: list[str] = []

    def log(_code: object, message: str) -> None:
        messages.append(message)

    control = Control(["--warn=none"], logger=log)
    theory.register(control)
    objective = _Objective()
    control.register_observer(objective)
    statements: list[AST] = []
    try:
        with ProgramBuilder(control) as builder:

            def add(statement: AST) -> None:
                statements.append(statement)
                theory.rewrite(statement, builder.add)

            _parse(program, add, log)
        control.ground([("base", [])])
        theory.prepare(control)
    except RuntimeError as error:
        return _fault(messages, error, program)
    facts = Facts(
        shown_by(statements),
        objective.seen,
        theory_at(control, statements, program),
        objective_at(statements, program) if solver is Solver.CLINGCON else None,
    )
    return Grounded(control, facts, theory)


def solve(
    program: Program,
    scenario: Scenario = frozenset(),
    *,
    limits: Limits = UNLIMITED,
    interrupt: Interrupt | None = None,
    solver: Solver = Solver.CLINGO,
) -> Determination[Models] | Fault:
    """Enumerate the stable models of `program` satisfying `scenario`."""
    grounded = ground(program, solver)
    if isinstance(grounded, Fault):
        return grounded
    return grounded.solve(scenario, limits=limits, interrupt=interrupt)
