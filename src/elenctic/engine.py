"""The one place that makes a clingo `Control`: it grounds a program to run searches over."""

import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, overload, override

from clingo import Control, Symbol
from clingo.ast import AST, ProgramBuilder, parse_files, parse_string
from clingo.backend import Observer

from elenctic.contract import Solver
from elenctic.determination import AnswerSets, Determination
from elenctic.facts import Facts, objective_at, shown_by, theory_at
from elenctic.grounded import Grounded
from elenctic.literals import Scenario
from elenctic.program import TEXT, Fault, Locus, Program, named
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
    if (span := diagnostic.span) is None:
        return diagnostic
    return replace(diagnostic, span=named(span, source))


def source_texts(program: Program) -> dict[str, str]:
    """Map each source name to its text: the program and every file it loads."""
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
    """Give clingo the program and its libraries in one call, so it loads no file twice."""
    shared = [str(library) for library in loaded_libraries(program)]
    if program.path is not None:
        parse_files([str(program.path), *shared], add, logger=logger)
        return
    # A text has no file to list: its libraries are included after it, from where it is run.
    included = "".join(f'\n#include "{_escaped(library)}".' for library in shared)
    parse_string(program.text + included, add, logger=logger)


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


_ESCAPES: Final = {character: f"\\{name}" for name, character in _UNESCAPED.items()}


def _escaped(target: str) -> str:
    """Write `target` as an `#include` string, the inverse of how `_include_targets` reads one."""
    return "".join(_ESCAPES.get(character, character) for character in target)


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
    """A file clingo loads: where it is, its name to clingo, its text, and whether it is a library.

    The text is the decoding error for a file that is not UTF-8, and `None` for one that cannot
    be read (clingo reports that itself). A library is one of the program's `libraries`; every
    other file is loaded by `#include`.
    """

    path: Path
    name: str
    text: str | UnicodeDecodeError | None
    library: bool = False


def _read(path: Path) -> str | UnicodeDecodeError | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        return error
    except OSError:
        return None


def _included(including: str, text: str, seen: set[Path]) -> Iterator[_Loaded]:
    """Yield each file the `#include`s of `text` load that is not yet `seen`, depth first."""
    # Depth first, as clingo reads an included file where its directive stands.
    pending = [(including, iter(_include_targets(text)))]
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


def _loaded(program: Program) -> Iterator[_Loaded]:
    """Yield each file clingo loads for `program` besides its text, in the order it loads them.

    First what the text's `#include`s load, then each library and what its own load. A file
    already loaded is not loaded again, compared by its resolved path, so a library the program
    already includes is dropped: clingo is never given a file twice, on any platform. It reads
    the files afresh at each call.
    """
    if program.path is None:
        seen: set[Path] = set()
        yield from _included(TEXT, program.text, seen)
    else:
        seen = {program.path.resolve()}
        yield from _included(str(program.path), program.text, seen)
    for library in program.libraries:
        # A text's libraries are `#include`d after it (`_parse`), so clingo finds them as it does.
        found = None if program.path is not None else _found(str(library), TEXT)
        located = found or library
        if (path := located.resolve()) in seen:
            continue
        seen.add(path)
        yield (loaded := _Loaded(path, str(located), _read(path), library=True))
        if isinstance(loaded.text, str):
            yield from _included(loaded.name, loaded.text, seen)


def default_root(path: Path) -> Path:
    """Return the root a path is held to when none is named: a directory itself, else its file's.

    Links and `..` are resolved first, as every comparison with a root resolves them.
    """
    resolved = path.resolve()
    return resolved if resolved.is_dir() else resolved.parent


def common_root(paths: Sequence[Path], libraries: Sequence[Path]) -> Path:
    """Return the directory that holds every one of `paths` and `libraries`, links resolved."""
    return Path(os.path.commonpath([*map(default_root, paths), *map(default_root, libraries)]))


def shared_root(
    paths: Sequence[Path], libraries: Sequence[Path], root: Path | None, home: Path | None
) -> Path | Fault | None:
    """Return the root `paths` are held to together; `None` when each is held to its own.

    It is `root`, else, with `libraries`, the directory that holds every path and library. That
    default is refused when it is the file system's root or holds `home`, since a root so wide
    would contain nothing. A text, with no path, is held only to `root`.
    """
    if root is not None:
        return root.resolve()
    if not paths or not libraries:
        return None
    common = common_root(paths, libraries)
    if common == Path(common.anchor):
        why = "it is the root of the file system"
    elif home is not None and home.is_relative_to(common):
        why = "it is the home directory" if home == common else "it holds the home directory"
    else:
        return common
    problem = failure(
        None,
        f"the default root {common} is too wide",
        notes=(why, "it is the directory that holds every path and library"),
        help=(
            (
                "name the project's directory as the root "
                "(`--root` on the command line, `root=` to `check`)"
            ),
        ),
    )
    return Fault(Locus.REQUEST, (problem,))


@overload
def held_root(path: Path, root: Path | None) -> Path: ...
@overload
def held_root(path: Path | None, root: Path | None) -> Path | None: ...
def held_root(path: Path | None, root: Path | None) -> Path | None:
    """Return the root `path` is held to: `root` if named, else its default; a text has none."""
    if root is not None:
        return root
    return None if path is None else default_root(path)


def loaded_libraries(program: Program) -> tuple[Path, ...]:
    """Return the libraries clingo is given with `program`: those not already loaded before them."""
    return tuple(Path(loaded.name) for loaded in _loaded(program) if loaded.library)


def included_sources(program: Program) -> frozenset[Path]:
    """Return this program's path and every file it loads, by `#include` or as a library."""
    own = () if program.path is None else (program.path.resolve(),)
    return frozenset((*own, *(loaded.path for loaded in _loaded(program))))


def containment(program: Program, root: Path | None) -> Fault | None:
    """Refuse a program that loads a file outside the root it is held to, or a root too wide.

    The root is `shared_root`'s for the program's path and libraries. The library reads no home
    directory, so only the file system's root is too wide here. The diagnostic names escaping
    paths only — never their contents — so a refused include cannot publish another file through
    elenctic's own report.
    """
    paths = () if program.path is None else (program.path,)
    shared = shared_root(paths, program.libraries, root, None)
    if isinstance(shared, Fault):
        return shared
    if (held := held_root(program.path, shared)) is None:
        return None
    root = held.resolve()
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
    """Refuse program text (and the files it loads) that would abort pyclingo's logger."""
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
