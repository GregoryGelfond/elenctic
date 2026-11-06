"""The one place that owns a clingo `Control`: it grounds a program and runs searches over it."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final, override

from clingo import Control
from clingo.ast import AST, ProgramBuilder, parse_files, parse_string
from clingo.backend import Observer

from elenctic.contract import Solver
from elenctic.determination import AnswerSets, Determination
from elenctic.facts import Facts, objective_at, shown_by, theory_at
from elenctic.grounded import Grounded
from elenctic.literals import Scenario
from elenctic.program import Fault, Locus, Program
from elenctic.search import Interrupt, Limits
from elenctic.spans import Diagnostic, diagnose, failure, first_unlexable, in_code
from elenctic.theory import Clingcon, Plain, Theory

_EXTRA: Final = "theory"
_UNDEFINED: Final = re.compile(r"no definition found for theory atom:\s+(?P<atom>\S+)")


def _clarified(diagnostic: Diagnostic) -> Diagnostic:
    """Say in elenctic's terms what clingo says of a theory atom that has no `#theory`."""
    joined = "\n".join((diagnostic.message, *(child.message for child in diagnostic.children)))
    if (found := _UNDEFINED.search(joined)) is None:
        return diagnostic
    return failure(
        diagnostic.span,
        f"theory atom `&{found['atom']}` has no `#theory` definition",
        label="cannot be grounded",
        help=("define the theory, or declare `% @elenctic solver clingcon` for clingcon's",),
    )


def _relocated(diagnostic: Diagnostic, source: str) -> Diagnostic:
    if diagnostic.span is None or diagnostic.span.source != "<string>":
        return diagnostic
    return replace(diagnostic, span=replace(diagnostic.span, source=source))


def _source_texts(program: Program) -> dict[str, str]:
    """Map each source name to its text: the program and every `#include` it reaches."""
    texts = {program.source: program.text}
    if program.path is None:
        return texts
    seen = {program.path.resolve()}
    pending = [program.path.parent / target for target in _include_targets(program.text)]
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            included = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        texts[str(path)] = included
        # Also under the relative name clingo may report.
        texts[path.name] = included
        pending.extend(path.parent / target for target in _include_targets(included))
    return texts


def _fault(messages: list[str], error: RuntimeError, program: Program) -> Fault:
    # The logger may be silent (e.g. missing python/lua support); the exception text still locates.
    joined = "".join(messages) or str(error)
    diagnostics = tuple(
        _clarified(_relocated(d, program.source))
        for d in diagnose(joined, texts=_source_texts(program))
    )
    return Fault(Locus.PROGRAM, diagnostics or (failure(None, str(error).strip()),))


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


def _absent(solver: Solver, _program: Program) -> Fault:
    """Say the contract names a solver that is not installed, and what installs it."""
    return Fault(
        Locus.REQUEST,
        (
            failure(
                None,
                f"solver `{solver}` is not installed",
                help=(
                    f"install `elenctic[{_EXTRA}]`, or install clingcon in the same environment",
                ),
            ),
        ),
    )


_INCLUDE = re.compile(r"#include\s*(?:\"([^\"]+)\"|<([^>]+)>)")


def _include_targets(text: str) -> tuple[str, ...]:
    """Return the paths named by `#include` directives outside strings and comments."""
    code = in_code(text)
    return tuple(
        quoted or angled
        for match in _INCLUDE.finditer(text)
        if code[match.start()]
        for quoted, angled in [match.groups()]
    )


def included_sources(program: Program) -> frozenset[Path]:
    """Return this program's path and every readable `#include` it reaches."""
    if program.path is None:
        return frozenset()
    found = {program.path.resolve()}
    pending = [program.path.parent / target for target in _include_targets(program.text)]
    while pending:
        path = pending.pop().resolve()
        if path in found:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        found.add(path)
        pending.extend(path.parent / target for target in _include_targets(text))
    return frozenset(found)


def containment(program: Program, root: Path) -> Fault | None:
    """Refuse a program that `#include`s a file outside `root`, the directory the run is held to.

    The diagnostic names escaping paths only — never their contents — so a refused include cannot
    publish another file through elenctic's own report.
    """
    root = root.resolve()
    escaped = sorted(path for path in included_sources(program) if not path.is_relative_to(root))
    if not escaped:
        return None
    named = ", ".join(str(path) for path in escaped)
    return Fault(
        Locus.REQUEST,
        (
            failure(
                None,
                f"this case loads {named}, which is outside the root {root}",
                notes=("a case may only include files under its root",),
                help=(
                    (
                        "test from a directory that holds every included file, or name one "
                        "as the root (`--root` on the command line, `root=` to `check`)"
                    ),
                ),
            ),
        ),
    )


def _lexable(program: Program) -> Fault | None:
    """Refuse program text (and `#include`d files) that would abort pyclingo's logger."""
    if (refused := first_unlexable(program.text, program.source)) is not None:
        return Fault(Locus.PROGRAM, (refused,))
    if program.path is None:
        return None
    seen: set[Path] = {program.path.resolve()}
    pending = [program.path.parent / target for target in _include_targets(program.text)]
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            included = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue  # clingo will report the missing or unreadable include
        if (refused := first_unlexable(included, str(path))) is not None:
            return Fault(Locus.PROGRAM, (refused,))
        pending.extend(path.parent / target for target in _include_targets(included))
    return None


def ground(program: Program, solver: Solver = Solver.CLINGO) -> Grounded | Fault:
    """Ground `program` for `solver`, or say why it cannot be."""
    if (refused := _lexable(program)) is not None:
        return refused
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
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    solver: Solver = Solver.CLINGO,
) -> Determination[AnswerSets] | Fault:
    """Enumerate the answer sets of `program` satisfying `scenario`."""
    grounded = ground(program, solver)
    if isinstance(grounded, Fault):
        return grounded
    return grounded.solve(scenario, limits=limits, interrupt=interrupt)
