"""The one place that makes a clingo `Control`: it grounds a program to run searches over."""

import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, override

from clingo import Control, Symbol
from clingo.ast import AST, ProgramBuilder, parse_files, parse_string
from clingo.backend import Observer

from elenctic.contract import Solver
from elenctic.determination import AnswerSets, Determination
from elenctic.facts import Facts, objective_at, shown_by, theory_at
from elenctic.grounded import Grounded
from elenctic.literals import Scenario
from elenctic.program import Fault, Locus, Program
from elenctic.search import Interrupt, Limits
from elenctic.spans import (
    Diagnostic,
    Lexeme,
    diagnose,
    failure,
    first_unlexable,
    in_code,
    lexemes,
    unreadable,
)
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


def source_texts(program: Program) -> dict[str, str]:
    """Map each source name to its text: the program and every `#include` it reaches."""
    texts = {program.source: program.text}
    for loaded in _loaded(program):
        if isinstance(loaded.text, str):
            # Under its own path, and under the name clingo reports it by.
            texts[str(loaded.path)] = texts[loaded.name] = loaded.text
    return texts


def _fault(messages: list[str], error: RuntimeError, program: Program) -> Fault:
    # The logger may be silent (e.g. missing python/lua support); the exception text still locates.
    joined = "".join(messages) or str(error)
    diagnostics = tuple(
        _clarified(_relocated(d, program.source))
        for d in diagnose(joined, texts=source_texts(program))
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
        self.priorities: set[int] = set()

    @property
    def seen(self) -> bool:
        return bool(self.priorities)

    @override
    def minimize(self, priority: int, literals: Sequence[tuple[int, int]]) -> None:
        """Record that a priority level has weighted literals (the observer's callback)."""
        self.priorities.add(priority)


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


_DIRECTIVE: Final = re.compile("#include")
_BLANK: Final = frozenset(" \t\r\n")
_ESCAPED: Final = re.compile(r"\\(.)")
_UNESCAPED: Final = {"n": "\n", "\\": "\\", '"': '"'}


def _past_blanks(text: str, index: int, comments: Mapping[int, Lexeme]) -> int:
    while index < len(text):
        if text[index] in _BLANK:
            index += 1
        elif (comment := comments.get(index)) is not None:
            index = comment.end
        else:
            break
    return index


def _include_targets(text: str) -> tuple[str, ...]:
    """Return the files `#include "..."` directives name, read as clingo's lexer reads them.

    `#include <...>` names a built-in program (only `<incmode>` exists), never a file.
    """
    pieces = lexemes(text)
    code = in_code(text)
    comments = {piece.start: piece for piece in pieces if not piece.string}
    strings = {piece.start: piece for piece in pieces if piece.string}
    targets: list[str] = []
    for directive in _DIRECTIVE.finditer(text):
        if not code[directive.start()]:
            continue
        string = strings.get(_past_blanks(text, directive.end(), comments))
        if string is not None:
            quoted = text[string.start + 1 : string.end - 1]
            targets.append(_ESCAPED.sub(lambda escape: _UNESCAPED[escape[1]], quoted))
    return tuple(targets)


def _found(target: str, including: str) -> Path | None:
    """Return the path clingo opens for `#include "target"` in the file named `including`.

    Clingo tries `target` as written (from the working directory), then beside the including
    file, then under each directory of `CLINGOPATH`; the first that exists wins.
    """
    searched = os.environ.get("CLINGOPATH")
    directories = (
        Path(),
        Path(including).parent,
        *(() if searched is None else map(Path, searched.split(":"))),
    )
    return next((path for d in directories if (path := d / target).exists()), None)


@dataclass(frozen=True, slots=True)
class _Loaded:
    """A file clingo loads by `#include`: where it is, its name to clingo, and its text.

    The text is the decoding error for a file that is not UTF-8, and `None` for one that cannot
    be read (clingo reports that itself).
    """

    path: Path
    name: str
    text: str | UnicodeDecodeError | None


def _read(path: Path) -> str | UnicodeDecodeError | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        return error
    except OSError:
        return None


def _loaded(program: Program) -> Iterator[_Loaded]:
    """Yield each file clingo loads for `program`'s `#include`s, in the order it loads them."""
    if program.path is None:
        return
    seen = {program.path.resolve()}
    # Depth first, as clingo reads an included file where its directive stands.
    pending = [(str(program.path), iter(_include_targets(program.text)))]
    while pending:
        including, targets = pending[-1]
        if (target := next(targets, None)) is None:
            pending.pop()
            continue
        if (found := _found(target, including)) is None:
            continue  # clingo reports the missing include
        if (path := found.resolve()) in seen:
            continue
        seen.add(path)
        yield (loaded := _Loaded(path, str(found), _read(path)))
        if isinstance(loaded.text, str):
            pending.append((loaded.name, iter(_include_targets(loaded.text))))


def included_sources(program: Program) -> frozenset[Path]:
    """Return this program's path and every file its `#include`s load, readable or not."""
    if program.path is None:
        return frozenset()
    return frozenset((program.path.resolve(), *(loaded.path for loaded in _loaded(program))))


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
    for loaded in _loaded(program):
        match loaded.text:
            case UnicodeDecodeError() as error:
                return Fault(Locus.PROGRAM, (unreadable(str(loaded.path), error),))
            case str() as text if (refused := first_unlexable(text, str(loaded.path))) is not None:
                return Fault(Locus.PROGRAM, (refused,))
            case _:
                pass
    return None


type Extension = Callable[[Sequence[AST]], Sequence[AST]]
"""What adds statements to a program, from the statements it has: none, for `ground`."""


def _nothing(_statements: Sequence[AST]) -> Sequence[AST]:
    return ()


@dataclass(frozen=True, slots=True)
class Controlled:
    """A grounded control, its theory, and what the grounding showed: facts and priorities."""

    control: Control
    facts: Facts
    theory: Theory
    statements: tuple[AST, ...]
    priorities: tuple[int, ...] = field(default=())
    """The priority of each level of the objective, highest first."""


def controlled(
    program: Program, solver: Solver, extend: Extension = _nothing
) -> Controlled | Fault:
    """Ground `program` and what `extend` adds to it for `solver`, or say why it cannot be."""
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
        _parse(program, statements.append, log)
        with ProgramBuilder(control) as builder:
            for statement in (*statements, *extend(statements)):
                theory.rewrite(statement, builder.add)
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
    priorities = tuple(sorted(objective.priorities, reverse=True))
    return Controlled(control, facts, theory, tuple(statements), priorities)


def ground(program: Program, solver: Solver = Solver.CLINGO) -> Grounded | Fault:
    """Ground `program` for `solver`, or say why it cannot be."""
    grounded = controlled(program, solver)
    if isinstance(grounded, Fault):
        return grounded
    return Grounded(grounded.control, grounded.facts, grounded.theory)


def possible_atoms(text: str) -> tuple[Symbol, ...]:
    """Ground program text on its own and name every atom the grounding holds."""
    control = Control(["--warn=none"], logger=lambda _code, _message: None)
    with ProgramBuilder(control) as builder:
        parse_string(text, builder.add)
    control.ground([("base", [])])
    return tuple(atom.symbol for atom in control.symbolic_atoms)


def parsed(text: str) -> tuple[AST, ...]:
    """Read program text that elenctic wrote into statements."""
    statements: list[AST] = []
    parse_string(text, statements.append)
    return tuple(statements)


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
