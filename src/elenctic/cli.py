"""The command line: a thin client over the library, one subcommand per kind of inquiry."""

import argparse
import os
import re
import signal
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum, auto
from functools import partial
from importlib import import_module
from math import inf
from pathlib import Path
from typing import Final

from elenctic.about import VersionExit, package
from elenctic.check import check
from elenctic.determination import Range, Refutation, Truncation, option
from elenctic.engine import common_root, held_root, loaded_libraries, shared_root
from elenctic.explanation import Explanation
from elenctic.human import (
    Format,
    Rendered,
    deprecated,
    internal_error,
    refused,
    render_ask,
    render_run,
    render_why,
    reserved,
    source_lines,
    version,
)
from elenctic.inquiry import Ask, AskExit, WhyExit, ask, why
from elenctic.json_view import inquiry_json, to_json
from elenctic.legend import Question, conjoined, signed
from elenctic.literals import Literal, Scenario, Symbol
from elenctic.patterns import Pattern
from elenctic.presentation import (
    Environment,
    Presentation,
    Stream,
    Style,
    When,
    interactive,
    resolve,
)
from elenctic.program import Fault, Locus, Program, regular_text
from elenctic.queries import read_query
from elenctic.query import All, Answered, AnswerMode, Warrant, instance_of, variables_of
from elenctic.reader import suggestion
from elenctic.report import Entry, Exit, Internal, Run
from elenctic.search import Interrupt, Limit, Limits
from elenctic.session import ONE_BINDING, Session, evidenced, session
from elenctic.spans import Diagnostic, Parsed, Span, failure, first_unlexable, note, unreadable
from elenctic.syntax import binding_shape, read_asked, read_binding, read_scenario
from elenctic.tags import is_case, near_misses
from elenctic.theory import loaded_solvers
from elenctic.verdicts import Ended, Finding, Report
from elenctic.writer import queried

DEFAULT_MAX_SECONDS: Final = 30.0
DEFAULT_MAX_ANSWER_SETS: Final = 100_000


DEFAULT_MAX_DEPTH: Final = 3


DECIDED: Final = frozenset({"test", "explain", "why", "ask", "version"})
"""The subcommands that are built: a first argument that names one is a command, not a path."""
VERSION_FLAGS: Final = ("-V", "--version")
"""The option of the main parser that asks for `version`: valid before the command, never after."""
BARE: Final = frozenset({*VERSION_FLAGS, "-h", "--help"})
"""The options of the main parser that take no value."""

RESERVED = {"repl": "start an interactive session over a live program"}
"""The subcommands kept for later; each exits as a fault, with a note, until it is built."""


def _parsed_or_none[N: (int, float)](read: Callable[[str], N], text: str) -> N | None:
    try:
        return read(text)
    except ValueError:
        return None


def _limit_reader[N: (int, float)](
    read: Callable[[str], N], expected: str
) -> Callable[[str], N | Limit]:
    """Make the reader of a limit: `all`, or what is `expected` when positive."""

    def parse(text: str) -> N | Limit:
        if text == Limit.UNBOUNDED.value:
            return Limit.UNBOUNDED
        number = _parsed_or_none(read, text)
        if number is None or not 0 < number < inf:
            message = f"{text!r} is not {expected} or `all`"
            raise argparse.ArgumentTypeError(message)
        return number

    return parse


def _path_reader(*, directory: bool, otherwise: str) -> Callable[[str], Path]:
    """Make the reader of a path that is a `directory`, or is not one; else it is `otherwise`."""

    def parse(text: str) -> Path:
        path = Path(text)
        if path.is_dir() is not directory:
            message = f"`{text}` {otherwise}"
            raise argparse.ArgumentTypeError(message)
        return path

    return parse


_file = _path_reader(directory=False, otherwise="is a directory, not a `.lp` file")
"""Read the `PATH` of `why` and `ask`: one program, so not a directory."""
_directory = _path_reader(directory=True, otherwise="is not a directory")
"""Read the value of `--root`: a directory that exists."""


_seconds_limit = _limit_reader(float, "a positive number of seconds")
_answer_sets_limit = _limit_reader(int, "a positive integer")
_depth_limit = _limit_reader(int, "a positive integer")


def _index(text: str) -> int:
    """Read an index of an answer set: a positive integer."""
    number = _parsed_or_none(int, text)
    if number is None or number < 1:
        message = f"{text!r} is not a positive integer"
        raise argparse.ArgumentTypeError(message)
    return number


def _output_options(*, defaults: bool) -> argparse.ArgumentParser:
    """Make the parser of the options that decide how output looks.

    The main parser and every command take them. Only the main parser holds the defaults: a
    command that sets nothing leaves what stands before it, and one that does override it.
    """
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument(
        "--color",
        choices=list(When),
        default=When.AUTO if defaults else argparse.SUPPRESS,
        metavar="WHEN",
        help="color output: auto (on a terminal), always or never (default: auto)",
    )
    options.add_argument(
        "--icons",
        nargs="?",
        choices=list(When),
        const=When.AUTO,
        default=When.NEVER if defaults else argparse.SUPPRESS,
        metavar="WHEN",
        help="show Nerd Font glyphs: auto (on a terminal), always or never; "
        "`--icons` alone is `--icons=auto`, a value is given as `--icons=WHEN` "
        "(default: never)",
    )
    return options


class View(StrEnum):
    """How a command writes what it found: `--format`."""

    TEXT = auto()
    JSON = auto()
    TUI = auto()
    """The interactive view, from the optional `elenctic[tui]` extra."""


DEPRECATED: Final = {"full": "--format text", "short": "--format text --short"}
"""The values of `--format` that 1.0 took, which 1.x still accepts with a note and 2.0 removes."""
INTERACTIVE: Final = "tui on a terminal when elenctic[tui] is installed, else text"
"""The default of `--format` for the commands that show evidence."""
CASE_OR_LIBRARY_HELP: Final = "name a case as a path, and a library with `--with`"
"""The help of a refusal that mixes up a case and a library."""


def _view(text: str) -> str:
    """Read the value of `--format`: a view, or a value 1.x still accepts."""
    if text in set(View) or text in DEPRECATED:
        return text
    message = f"{text!r} is not text, json or tui"
    raise argparse.ArgumentTypeError(message)


def _written(command: argparse.ArgumentParser, written: str, default: str) -> None:
    """Give a command the options that choose how what it found is written."""
    command.add_argument(
        "--format",
        type=_view,
        metavar="text|json|tui",
        help=f"how to write {written}: text, JSON, or tui, the interactive view "
        f"(default: {default})",
    )
    command.add_argument(
        "--short",
        action="store_true",
        help="write each diagnostic on one line, `path:line:col: level: message` (text only)",
    )
    command.add_argument(
        "--json", action="store_true", help=f"write {written} as JSON (same as --format json)"
    )


def _limited(command: argparse.ArgumentParser) -> None:
    """Give a command that searches the limits of each search."""
    command.add_argument(
        option(Truncation.MAX_SECONDS),
        type=_seconds_limit,
        default=DEFAULT_MAX_SECONDS,
        metavar="SECONDS|all",
        help="time allowed per search, or `all` for no limit (default: %(default)s)",
    )
    command.add_argument(
        option(Truncation.MAX_ANSWER_SETS),
        type=_answer_sets_limit,
        default=DEFAULT_MAX_ANSWER_SETS,
        metavar="N|all",
        help="most answer sets read per search, or `all` for no limit (default: %(default)s)",
    )


def _checking(command: argparse.ArgumentParser, written: str, default: str) -> None:
    """Give a command that checks programs the options of `test`."""
    command.add_argument(
        "paths", nargs="+", type=Path, help=".lp files, or directories searched for them"
    )
    _written(command, written, default)
    command.add_argument("--verbose", "-v", action="store_true", help="list the claims that passed")
    _program_options(command, held=_CHECKED_ROOT, loaded="every case")
    _limited(command)


_CHECKED_ROOT: Final = (
    "with `--with`, the directory that holds every path and library; else each directory "
    "searched, or a named file's own directory"
)
_ASKED_ROOT: Final = (
    "with `--with`, the directory that holds PATH and every library; else PATH's own directory"
)


def _program_options(command: argparse.ArgumentParser, *, held: str, loaded: str) -> None:
    """Give a command that loads programs its root, the default `held`, and libraries.

    Each library is loaded with `loaded`: every case `test` checks, or the program asked.
    """
    command.add_argument(
        "--root",
        type=_directory,
        metavar="DIR",
        help="the directory every path, `--with` file and `#include` must lie under "
        f"(default: {held})",
    )
    command.add_argument(
        "--with",
        action="append",
        type=Path,
        default=[],
        dest="libraries",
        metavar="FILE",
        help=f"a library loaded with {loaded}, such as a base encoding; may be repeated",
    )


def _depth(command: argparse.ArgumentParser) -> None:
    """Give a command that explains the options of how deep and how fully it shows the tree."""
    command.add_argument(
        "--max-depth",
        type=_depth_limit,
        default=DEFAULT_MAX_DEPTH,
        metavar="N|all",
        help=(
            "how many absent atoms deep an explanation goes, or `all` for no limit "
            f"(default: {DEFAULT_MAX_DEPTH})"
        ),
    )
    command.add_argument(
        "--spans",
        action="store_true",
        help="show each rule as written, its place and its substitution, beneath its instance",
    )


def _asking(command: argparse.ArgumentParser, written: str) -> None:
    """Give a command that asks about one program its path and the options of its search."""
    command.add_argument("path", type=_file, metavar="PATH", help="the .lp file asked about")
    _written(command, written, INTERACTIVE)
    _program_options(command, held=_ASKED_ROOT, loaded="the program")
    command.add_argument(
        "--over",
        choices=list(Range),
        type=Range,
        default=Range.ALL,
        help="all the answer sets, or only the optimal ones (default: all)",
    )
    _limited(command)


QUERY_HELP: Final = (
    "literals, `not` before any, `{ a, not -b }`, with variables `{ p(X), not q(X) }`, as "
    "`@query`; a full stop may end it"
)
"""The help of the `QUERY` that `ask` and `why` take."""


def _mode(command: argparse.ArgumentParser, default: AnswerMode | None) -> None:
    """Give a command that answers a query the `--mode` it answers in.

    A `default` of `None` lets the command tell the option given from one left out.
    """
    command.add_argument(
        "--mode",
        choices=list(AnswerMode),
        type=AnswerMode,
        default=default,
        help="default: the Gelfond\N{EN DASH}Kahl three-valued semantics, yes if true in every "
        "answer set, no if false in every one, else unknown; cautious: yes if true in every one, "
        "else not entailed; brave: yes if true in some, else none holds (default: default)",
    )


def _parser() -> argparse.ArgumentParser:
    """Make the parser; its help and usage are colored as `argparse` does by default."""
    parser = argparse.ArgumentParser(
        prog="elenctic",
        parents=[_output_options(defaults=True)],
        description="Test, debug and analyze answer set programs. "
        "With no command, the paths are tested: `elenctic PATH...` is `elenctic test PATH...`. "
        "`elenctic --version` and `elenctic -V` are `elenctic version`; they stand before "
        "the command, which does not take them.",
    )
    parser.add_argument(
        *VERSION_FLAGS,
        dest="show_version",
        action="store_true",
        help="print the version, as `version` does, and exit",
    )
    options = [_output_options(defaults=False)]
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    test = commands.add_parser(
        "test", parents=options, help="check programs against their contracts"
    )
    _checking(test, "the run", View.TEXT)
    explain = commands.add_parser(
        "explain", parents=options, help="check programs, and show why each failed claim fails"
    )
    _checking(explain, "the run, with the evidence", INTERACTIVE)
    _depth(explain)
    why = commands.add_parser(
        "why",
        parents=options,
        help="show what warrants a query's answer, or why an atom holds, or not, in an answer set",
    )
    _asking(why, "the warrant or the explanation")
    why.add_argument(
        "query",
        type=_literal,
        metavar="QUERY",
        help=f"{QUERY_HELP}; with --answer-set, one ground literal, `p(a)`, `not -p`",
    )
    why.add_argument(
        "--answer-set",
        type=_index,
        metavar="K",
        help="explain QUERY in the K-th answer set, counted from 1 among those --over reads, "
        "rather than warrant its answer",
    )
    _mode(why, None)
    why.add_argument(
        "--binding",
        metavar="X = V,...",
        help="the binding of a query with variables whose answer is warranted, as `ask` writes "
        "it: `X = a, Y = 1`",
    )
    why.add_argument(
        "--assuming",
        type=_literal,
        metavar="L,...",
        help="literals assumed, `p` or `not p`, as `assuming { ... }` writes them",
    )
    _depth(why)
    ask = commands.add_parser("ask", parents=options, help="answer one query over the answer sets")
    _asking(ask, "the answer")
    ask.add_argument("query", type=_literal, metavar="QUERY", help=QUERY_HELP)
    _mode(ask, AnswerMode.DEFAULT)
    ask.add_argument(
        "--unknown",
        action="store_true",
        help="show the bindings whose answer is unknown too, not only their count",
    )
    commands.add_parser(
        "version",
        parents=options,
        help="print the version, the license and the versions of clingo and clingcon",
    )
    for name, what in RESERVED.items():
        commands.add_parser(name, parents=options, help=f"{what} (reserved)").add_argument(
            "rest", nargs=argparse.REMAINDER
        )
    return parser


_LITERAL: Final = re.compile(r"-[a-z_(]")
"""How a classical literal starts, `-p(X)`, or a term in parentheses, `-(p)`: argparse would take
either for an option."""


def _literals(arguments: list[str]) -> list[str]:
    """Keep a literal given to `why` or `ask`, such as `-p(X)`, from being read as an option.

    argparse reads an argument with a space in it as positional, so each one after the command
    that starts as a classical literal does, and is not an option, gets a trailing space; the
    `_literal` type drops it again.
    """
    at = next((i for i, a in enumerate(arguments) if a in DECIDED), len(arguments))
    if at == len(arguments) or arguments[at] not in {"why", "ask"}:
        return arguments
    ended = arguments.index("--") if "--" in arguments else len(arguments)
    return [
        f"{argument} "
        if at < index < ended and _LITERAL.match(argument) and argument not in BARE | {"-v"}
        else argument
        for index, argument in enumerate(arguments)
    ]


def _literal(text: str) -> str:
    """Take a literal as it was written, without the space `_literals` gave it."""
    return text.removesuffix(" ")


def _explicit_icons(argv: Iterable[str]) -> list[str]:
    """Name the value of a bare `--icons` (or its abbreviation), so it cannot take the next path."""
    arguments = list(argv)
    ended = arguments.index("--") if "--" in arguments else len(arguments)
    return [
        "--icons=auto"
        if index < ended and argument.startswith("--i") and "--icons".startswith(argument)
        else argument
        for index, argument in enumerate(arguments)
    ]


def _normalized(argv: Sequence[str]) -> list[str]:
    """Name the command: `test` unless one stands after the main parser's options."""
    arguments = _explicit_icons(argv)
    at = 0
    while at < len(arguments):
        argument = arguments[at]
        if argument in BARE or argument.startswith(("--color=", "--icons=")):
            at += 1
        elif argument == "--color":
            at += 2
        else:
            break
    if at >= len(arguments) or arguments[at] in {*DECIDED, *RESERVED}:
        return arguments
    return [*arguments[:at], "test", *arguments[at:]]


type _Source = tuple[Path, bool, Path]
"""A `.lp` path to check, whether the user named it, and its root."""


def _plan(
    paths: Sequence[Path], boundary: Path | None, libraries: Sequence[Path] = ()
) -> list[_Source | Entry]:
    """Return each path's sources in the order given; a path outside `boundary` is refused instead.

    So is a file named both as a path and as a library.
    """
    shared = {library.resolve() for library in libraries}
    return [item for path in paths for item in _placed(path, boundary, shared)]


def _placed(path: Path, boundary: Path | None, shared: set[Path]) -> list[_Source | Entry]:
    refusal = _misplaced(path, boundary, shared)
    return [*_sources(path, boundary)] if refusal is None else [refusal]


def _misplaced(path: Path, boundary: Path | None, shared: set[Path]) -> Entry | None:
    """Refuse a path outside `boundary`, or a file named with `--with` as well."""
    if boundary is not None and not path.resolve().is_relative_to(boundary):
        return _outside(path, boundary)
    if path.resolve() in shared:
        return _twice(path)
    return None


def _twice(path: Path) -> Entry:
    problem = failure(
        None,
        f"`{path}` is named both as a path and with `--with`",
        help=(CASE_OR_LIBRARY_HELP,),
    )
    return Entry(str(path), Fault(Locus.REQUEST, (problem,)))


def _boundary(
    paths: Sequence[Path], libraries: Sequence[Path], root: Path | None, home: Path | None
) -> Path | Entry | None:
    """Return the root every source is held to (`shared_root`), or its refusal as an entry."""
    held = shared_root(paths, libraries, root, home)
    if isinstance(held, Fault):
        return Entry(str(common_root(paths, libraries)), held)
    return held


def _refused_library(library: Path, boundary: Path | None) -> Entry | None:
    """Refuse a `--with` file outside the root, unreadable, or carrying a contract tag."""
    if boundary is not None and not library.resolve().is_relative_to(boundary):
        return _outside(library, boundary)
    program = _read(library)
    if isinstance(program, Fault):
        return Entry(str(library), program)
    if not is_case(program.text):
        return None
    problem = failure(
        None,
        f"`{library}` carries a contract tag",
        notes=("a `--with` file is a library: its claims would not be checked",),
        help=(CASE_OR_LIBRARY_HELP,),
    )
    return Entry(str(library), Fault(Locus.REQUEST, (problem,)), program.text)


def _planned(
    paths: Sequence[Path], libraries: Sequence[Path], root: Path | None, home: Path | None
) -> tuple[list[Entry], list[_Source | Entry]]:
    """Return the refusals of the root and the `--with` files, which stop the run, else its plan."""
    boundary = _boundary(paths, libraries, root, home)
    if isinstance(boundary, Entry):
        return [boundary], []
    refusals = [
        refusal
        for library in libraries
        if (refusal := _refused_library(library, boundary)) is not None
    ]
    return refusals, ([] if refusals else _plan(paths, boundary, libraries))


def _sources(path: Path, boundary: Path | None) -> list[_Source]:
    """Return the `.lp` files of `path` with their root: `boundary`, else the path's own."""
    root = held_root(path, boundary)
    if not path.is_dir():
        return [(path, True, root)]
    return [(found, False, root) for found in sorted(path.rglob("*.lp"))]


def _outside(path: Path, root: Path) -> Entry:
    problem = failure(
        None,
        f"`{path}` is outside the root {root}",
        help=("name paths under the root, or choose a root that holds them",),
    )
    return Entry(str(path), Fault(Locus.REQUEST, (problem,)))


def _read(path: Path, libraries: Sequence[Path] = ()) -> Program | Fault:
    """Read the program at `path`, loaded with `libraries`, or refuse it as unreadable."""
    try:
        return Program.read(path, libraries)
    except (OSError, UnicodeDecodeError) as error:
        return Fault(Locus.REQUEST, (unreadable(str(path), error),))


def _mistaken(text: str) -> tuple[str, tuple[str, ...]] | None:
    """Say which `@tag`s of `text` are not tags, with what each likely means; `None` if none."""
    missed = tuple(dict.fromkeys(near_misses(text)))
    if not missed:
        return None
    shown = ", ".join(f"`@{name}`" for name in missed)
    verb = "is not a tag" if len(missed) == 1 else "are not tags"
    return f"{shown} {verb}", tuple(tip for name in missed for tip in suggestion(name))


def _not_a_case(path: Path, text: str) -> Fault:
    """Refuse a named path that carries no contract tag."""
    if (refused := first_unlexable(text, str(path))) is not None:
        return Fault(Locus.PROGRAM, (refused,))
    mistaken = _mistaken(text)
    notes, helps = (
        ((), ("a contract-free `.lp` is a library; name a case, or walk a directory",))
        if mistaken is None
        else ((mistaken[0],), mistaken[1])
    )
    problem = failure(None, f"`{path}` carries no contract tag", notes=notes, help=helps)
    return Fault(Locus.REQUEST, (problem,))


def _walked_notes(sources: list[_Source]) -> tuple[Diagnostic, ...]:
    """Return notes for walked libraries whose `@tag` looks misspelled (forgotten cases)."""
    found: list[Diagnostic] = []
    for path, named, _root in sources:
        if named:
            continue
        try:
            text = regular_text(path)
        except OSError, UnicodeDecodeError:
            continue
        if is_case(text):
            continue
        if (mistaken := _mistaken(text)) is None:
            continue
        shown, helps = mistaken
        found.append(note(None, f"`{path}` carries no contract tag; {shown}", help=helps))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class _Checking:
    """How each case of a run is checked: its search, its libraries, and the depth to explain to."""

    limits: Limits
    interrupt: Interrupt
    libraries: tuple[Path, ...]
    max_depth: int | Limit | None


def _entry(path: Path, checking: _Checking, *, named: bool, root: Path) -> Entry | None:
    limits, interrupt, max_depth = checking.limits, checking.interrupt, checking.max_depth
    program = _read(path, checking.libraries)
    if isinstance(program, Fault):
        return Entry(str(path), program)
    if not is_case(program.text):
        if named:
            return Entry(program.source, _not_a_case(path, program.text), program.text)
        return None
    try:
        result = check(program, limits=limits, interrupt=interrupt, root=root)
        if isinstance(result, Report) and max_depth is not None:
            result = evidenced(
                result, program, limits=limits, interrupt=interrupt, max_depth=max_depth
            )
    except Exception as error:  # noqa: BLE001
        return _recorded(program, Internal.of(error))
    return None if result is None else _recorded(program, result)


def _recorded(program: Program, result: Report | Fault | Internal) -> Entry:
    """Record what checking `program` came to, with what `_program` needs to read it again."""
    loaded = tuple(str(library) for library in loaded_libraries(program))
    return Entry(program.source, result, program.text, loaded)


def _program(entry: Entry) -> Program:
    """Return the program an entry was checked as: its text, loaded with its libraries."""
    path = Path(entry.source)
    return Program(entry.text or "", entry.source, path, tuple(map(Path, entry.libraries)))


def _checked(item: _Source | Entry, checking: _Checking) -> Entry | None:
    """Check a planned source, and explain it if a depth is given; a refusal stands as it is."""
    if isinstance(item, Entry):
        return item
    path, named, root = item
    return _entry(path, checking, named=named, root=root)


def _presentation(arguments: argparse.Namespace, environment: Environment) -> Presentation:
    """Decide once how each stream is written.

    `Stream.of` asks each stream. It governs elenctic's own report and diagnostics; the
    parser's help and usage are its own.
    """
    return resolve(
        When(arguments.color),
        When(arguments.icons),
        environment,
        stdout=Stream.of(sys.stdout),
        stderr=Stream.of(sys.stderr),
    )


def _sigint(interrupt: Interrupt) -> Callable[[int, object], None]:
    """First SIGINT asks the search to stop; a second restores the default handler and re-raises."""

    def handle(_signum: int, _frame: object) -> None:
        if interrupt.pulled:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.raise_signal(signal.SIGINT)
            return
        interrupt.pull()

    return handle


def _searching(arguments: argparse.Namespace) -> tuple[Limits, Interrupt]:
    """Take the limits of each search, and the interrupt the first SIGINT pulls.

    The interactive view's interrupt also stops the one call it cancels.
    """
    limits = Limits(max_seconds=arguments.max_seconds, max_answer_sets=arguments.max_answer_sets)
    interrupt = _calls() if arguments.view is View.TUI else Interrupt()
    signal.signal(signal.SIGINT, _sigint(interrupt))
    return limits, interrupt


def _calls() -> Interrupt:
    from elenctic.tui.calls import Calls  # noqa: PLC0415

    return Calls()


def _diagnosed(style: Style) -> Callable[[Fault | Internal, str | None, str], str]:
    """Write a refusal for the interactive view as the text view writes it, in its style."""
    shown = Presentation(style, style)

    def write(refusal: Fault | Internal, text: str | None, source: str) -> str:
        return refused(refusal, shown, source=source, text=text).stderr

    return write


type _Evidenced = Callable[[Entry, Finding, int | Limit], Finding | Fault | Internal]
"""Find a failed claim's evidence at a depth, the callable the interactive view is given."""


def _evidence_of(limits: Limits, interrupt: Interrupt) -> _Evidenced:
    """Find a failed claim's evidence for the interactive view, one session for each source."""
    opened: dict[str, Session | Fault] = {}

    def found(entry: Entry, finding: Finding, depth: int | Limit) -> Finding | Fault | Internal:
        try:
            if entry.source not in opened:
                program = _program(entry)
                solver = entry.result.solver if isinstance(entry.result, Report) else None
                opened[entry.source] = session(
                    program,
                    *(() if solver is None else (solver,)),
                    limits=limits,
                    interrupt=interrupt,
                )
            each = opened[entry.source]
            if isinstance(each, Fault):
                return each
            return replace(finding, evidence=each.evidence(finding, max_depth=depth))
        except Exception as error:  # noqa: BLE001
            return Internal.of(error)

    return found


def _test(arguments: argparse.Namespace, presentation: Presentation, home: Path | None) -> Exit:
    """Check the paths; for `explain`, give each failed claim its evidence."""
    limits, interrupt = _searching(arguments)
    libraries = tuple(arguments.libraries)
    refusals, plan = _planned(arguments.paths, libraries, arguments.root, home)
    explaining = arguments.command == "explain"
    max_depth = arguments.max_depth if explaining and arguments.view is not View.TUI else None
    checking = _Checking(limits, interrupt, libraries, max_depth)
    entries = [*refusals, *(_checked(item, checking) for item in plan)]
    run = Run(
        tuple(entry for entry in entries if entry is not None),
        notes=_walked_notes([item for item in plan if not isinstance(item, Entry)]),
    )
    if arguments.view is View.JSON:
        sys.stdout.write(to_json(run))
        return run.exit_code
    rendered = render_run(
        run,
        presentation,
        verbose=arguments.verbose,
        form=arguments.form,
        spans=getattr(arguments, "spans", False),
    )
    if arguments.view is View.TUI:
        _show_run(run, arguments, presentation, _evidence_of(limits, interrupt))
        sys.stderr.write(rendered.stderr)
        return run.exit_code
    _write(rendered)
    return run.exit_code


def _show_run(
    run: Run, arguments: argparse.Namespace, presentation: Presentation, evidence: _Evidenced
) -> None:
    """Show a run in the interactive view, which finds a claim's evidence when it is opened.

    `explain` opens each failed claim at the start.
    """
    from elenctic import tui  # noqa: PLC0415

    explaining = arguments.command == "explain"
    style = presentation.stdout
    shown = tui.run_view(
        run,
        style,
        command=arguments.command,
        subject=" ".join(map(str, arguments.paths)),
        lines_of=source_lines(None),
        diagnosed=_diagnosed(style),
        evidence=evidence,
        max_depth=arguments.max_depth if explaining else DEFAULT_MAX_DEPTH,
        every=not explaining or arguments.verbose,
        opened=explaining,
    )
    tui.show(shown, style)


def _write(rendered: Rendered) -> None:
    sys.stderr.write(rendered.stderr)
    sys.stdout.write(rendered.stdout)


def _refuse[Outcome: IntEnum](
    command: str,
    refusal: Fault | Diagnostic,
    arguments: argparse.Namespace,
    presentation: Presentation,
    *,
    outcome: Outcome,
) -> Outcome:
    """Write the refusal of an argument, showing it as it was given, and exit `outcome`."""
    fault = refusal if isinstance(refusal, Fault) else Fault(Locus.REQUEST, (refusal,))
    if arguments.view is View.JSON:
        sys.stdout.write(inquiry_json(command, fault, outcome))
        return outcome
    fault, text = _at_argument(arguments, fault, None)
    source = str(arguments.path)
    _write(refused(fault, presentation, form=arguments.form, source=source, text=text))
    return outcome


_GIVEN: Final = {
    "QUERY": "query",
    "--binding": "binding",
    "--assuming": "assuming",
    "--answer-set": "answer_set",
    "--over": "over",
    "--mode": "mode",
}
"""The arguments a fault can be placed at, by their names in the arguments."""


def _at_argument[Text: str | None](
    arguments: argparse.Namespace, fault: Fault, text: Text
) -> tuple[Fault, str | Text]:
    """Show a fault placed at an argument with the argument's text, else with `text`.

    A span that covers nothing names the argument a fault is about, by one who did not know the
    text it was given as: it is widened to all of it.
    """
    sources = {each.span.source for each in fault.diagnostics if each.span is not None}
    name = _GIVEN.get(sources.pop()) if len(sources) == 1 else None
    value = None if name is None else getattr(arguments, name, None)
    if value is None:
        return fault, text
    given = str(value)
    diagnostics = tuple(
        replace(each, span=Span.whole(each.span.source, given))
        if each.span is not None and each.span.start == each.span.end
        else each
        for each in fault.diagnostics
    )
    return Fault(fault.locus, diagnostics), given


def _inquired(
    arguments: argparse.Namespace, home: Path | None
) -> tuple[Program, Path] | list[Entry]:
    """Read the program a question is about, planned as `test` plans a path; else the refusals."""
    path, libraries = arguments.path, arguments.libraries
    refusals, plan = _planned([path], libraries, arguments.root, home)
    refusals += [item for item in plan if isinstance(item, Entry)]
    if refusals:
        return refusals
    program = _read(path, libraries)
    if isinstance(program, Fault):
        return [Entry(str(path), program)]
    _, _, root = next(item for item in plan if not isinstance(item, Entry))  # the file, read
    return program, root


def _refused_all[Outcome: IntEnum](
    command: str,
    refusals: list[Entry],
    arguments: argparse.Namespace,
    presentation: Presentation,
    outcome: Outcome,
) -> Outcome:
    """Write the refusals of what a question was asked about, each of its own file."""
    faults = [(entry, entry.result) for entry in refusals if isinstance(entry.result, Fault)]
    if arguments.view is View.JSON:
        fault = Fault(Locus.REQUEST, tuple(d for _, each in faults for d in each.diagnostics))
        sys.stdout.write(inquiry_json(command, fault, outcome))
        return outcome
    for entry, fault in faults:
        form, text = arguments.form, entry.text
        _write(refused(fault, presentation, form=form, source=entry.source, text=text))
    return outcome


_WARRANTING: Final = {"mode": "--mode", "binding": "--binding"}
"""The options only a query's warrant takes, by their names in the arguments."""


def _unused(arguments: argparse.Namespace) -> Diagnostic | None:
    """Refuse an option of a query's warrant given with `--answer-set`, where it does nothing."""
    if arguments.answer_set is None:
        return None
    found = next((f for k, f in _WARRANTING.items() if getattr(arguments, k) is not None), None)
    if found is None:
        return None
    message, where = f"`{found}` has no effect with `--answer-set`", Span.whole(found, "")
    return failure(
        where,
        message,
        label="no effect",
        help=(f"drop `{found}`, which only a query's warrant takes",),
    )


def _why(arguments: argparse.Namespace, presentation: Presentation, home: Path | None) -> WhyExit:
    """Warrant a query's answer, or explain an atom in the answer set asked for.

    The CLI only reads and writes.
    """
    inquired = _inquired(arguments, home)
    if isinstance(inquired, list):
        return _refused_all("why", inquired, arguments, presentation, WhyExit.FAULT)
    assumed = arguments.assuming
    scenario: Parsed[Scenario] = (
        frozenset() if assumed is None else read_scenario(assumed, "--assuming")
    )
    if isinstance(scenario, Diagnostic):
        return _refuse("why", scenario, arguments, presentation, outcome=WhyExit.FAULT)
    unused = _unused(arguments)
    if unused is not None:
        return _refuse("why", unused, arguments, presentation, outcome=WhyExit.FAULT)
    if arguments.answer_set is None:
        return _warrant(arguments, presentation, inquired, scenario)
    return _explain(arguments, presentation, inquired, scenario)


def _explain(
    arguments: argparse.Namespace,
    presentation: Presentation,
    inquired: tuple[Program, Path],
    scenario: Scenario,
) -> WhyExit:
    """Explain an atom in the answer set asked for."""
    program, root = inquired
    read = read_asked(arguments.query, "QUERY")
    if isinstance(read, Diagnostic):
        return _refuse("why", read, arguments, presentation, outcome=WhyExit.FAULT)
    atom, negated = read
    explained = _Explaining(program, root, scenario, arguments.over, _searching(arguments))
    result = explained(atom, arguments.answer_set, arguments.max_depth)
    outcome = WhyExit.of(result)
    if arguments.view is View.JSON:
        sys.stdout.write(inquiry_json("why", result, outcome))
        return outcome
    source, asked = str(arguments.path), signed(atom, negated=negated)
    if arguments.view is View.TUI and not isinstance(result, Fault | Internal):
        deeper = partial(explained, atom, arguments.answer_set)
        _why_view(arguments, presentation, explained, _Found(asked, result, deeper))
        return outcome
    form, spans, over, text = arguments.form, arguments.spans, arguments.over, program.text
    if isinstance(result, Fault):
        result, text = _at_argument(arguments, result, text)
    written = render_why(
        source, asked, result, presentation, form=form, spans=spans, over=over, text=text
    )
    _write(written)
    return outcome


@dataclass(frozen=True, slots=True)
class _Explaining:
    """What explains a literal of `program` in one answer set, as `why --answer-set` does."""

    program: Program
    root: Path
    scenario: Scenario
    over: Range
    searching: tuple[Limits, Interrupt]

    def __call__(
        self, literal: Literal, index: int, depth: int | Limit
    ) -> Explanation | Refutation | Ended | Fault | Internal:
        """Explain `literal` in the `index`-th answer set, `depth` absences deep."""
        limits, interrupt = self.searching
        try:
            return why(
                self.program,
                literal,
                index=index,
                scenario=self.scenario,
                over=self.over,
                limits=limits,
                interrupt=interrupt,
                max_depth=depth,
                root=self.root,
            )
        except Exception as error:  # noqa: BLE001
            return Internal.of(error)


def _answer_view(
    arguments: argparse.Namespace,
    presentation: Presentation,
    query: All | Pattern,
    result: Answered | Warrant | Refutation | Ended,
    explaining: _Explaining,
) -> None:
    """Show what `ask` found, or `why`'s warrant, in the interactive view."""
    from elenctic import tui  # noqa: PLC0415

    style, text = presentation.stdout, explaining.program.text
    shown = tui.ask_view(
        _question(arguments),
        query,
        result,
        style,
        over=arguments.over,
        lines_of=source_lines(text),
        diagnosed=_diagnosed(style),
        why_of=explaining,
        max_depth=arguments.max_depth if arguments.command == "why" else DEFAULT_MAX_DEPTH,
        text=text,
        unknown=arguments.command == "ask" and arguments.unknown,
    )
    tui.show(shown, style)


def _warrant(
    arguments: argparse.Namespace,
    presentation: Presentation,
    inquired: tuple[Program, Path],
    scenario: Scenario,
) -> WhyExit:
    """Show what warrants a query's answer, or that of one binding, as `ask` answers it."""
    program, root = inquired
    query = read_query(arguments.query, "QUERY")
    if isinstance(query, Diagnostic):
        return _refuse("why", query, arguments, presentation, outcome=WhyExit.FAULT)
    values = _binding(arguments, query)
    if isinstance(values, Diagnostic):
        return _refuse("why", values, arguments, presentation, outcome=WhyExit.FAULT)
    explaining = _Explaining(program, root, scenario, arguments.over, _searching(arguments))
    limits, interrupt = explaining.searching
    mode = AnswerMode.DEFAULT if arguments.mode is None else arguments.mode
    try:
        result: Warrant | Refutation | Ended | Fault | Internal = why(
            program,
            query,
            values=values,
            mode=mode,
            scenario=scenario,
            over=arguments.over,
            limits=limits,
            interrupt=interrupt,
            max_depth=arguments.max_depth,
            root=root,
        )
    except Exception as error:  # noqa: BLE001
        result = Internal.of(error)
    outcome = WhyExit.of(result)
    if arguments.view is View.JSON:
        sys.stdout.write(inquiry_json("why", result, outcome))
    else:
        asked = conjoined(instance_of(query, values)) if values else query
        _show_warrant(arguments, presentation, asked, result, explaining)
    return outcome


def _binding(arguments: argparse.Namespace, query: All | Pattern) -> Parsed[tuple[Symbol, ...]]:
    """Read the values of the binding `--binding` names, in the order of the query's variables."""
    variables = tuple(each.name for each in variables_of(query))
    text = arguments.binding
    if text is None and variables:
        name = f"name one with `--binding '{binding_shape(variables)}'`, as `ask` writes it"
        where = Span.whole("QUERY", "")
        return failure(where, ONE_BINDING, label="has variables", help=(name,))
    if text is None:
        return ()
    return read_binding(text, variables, "--binding")


def _show_warrant(
    arguments: argparse.Namespace,
    presentation: Presentation,
    query: All | Pattern,
    result: Warrant | Refutation | Ended | Fault | Internal,
    explaining: _Explaining,
) -> None:
    """Show `why`'s warrant as `ask`'s answer is shown, or why there is none as `why` shows it."""
    source, text, form = str(arguments.path), explaining.program.text, arguments.form
    interactive = arguments.view is View.TUI
    match result:
        case Warrant() if interactive:
            _answer_view(arguments, presentation, query, result, explaining)
        case Warrant():
            spans = arguments.spans
            shown = Question(source)
            _write(
                render_ask(shown, query, result, presentation, form=form, text=text, spans=spans)
            )
        case Fault():
            fault, given = _at_argument(arguments, result, text)
            _write(refused(fault, presentation, form=form, source=source, text=given))
        case Internal():
            _write(refused(result, presentation, form=form, source=source, text=text))
        case _ if interactive:
            unfound = _Found(queried(query), result, lambda _depth: result)
            _why_view(arguments, presentation, explaining, unfound)
        case _:
            asked = queried(query)
            _write(render_why(source, asked, result, presentation, form=form, spans=False))


@dataclass(frozen=True, slots=True)
class _Found:
    """What `why` found for what was `asked`, and how to explain it `deeper`."""

    asked: str
    result: Explanation | Refutation | Ended
    deeper: Callable[[int | Limit], Explanation | Refutation | Ended | Fault | Internal]


def _why_view(
    arguments: argparse.Namespace,
    presentation: Presentation,
    explaining: _Explaining,
    found: _Found,
) -> None:
    """Show what `why` found in the interactive view: an explanation, or why there is none."""
    from elenctic import tui  # noqa: PLC0415

    style, text = presentation.stdout, explaining.program.text
    shown = tui.why_view(
        str(arguments.path),
        found.asked,
        found.result,
        style,
        over=explaining.over,
        lines_of=source_lines(text),
        diagnosed=_diagnosed(style),
        explained=found.deeper,
        max_depth=arguments.max_depth,
        text=text,
    )
    tui.show(shown, style)


def _asked_query(arguments: argparse.Namespace) -> Parsed[All | Pattern]:
    """Read the query `ask` was given; `--unknown` needs one with variables, in the default mode.

    Only the default mode answers `unknown`.
    """
    query = read_query(arguments.query, "QUERY")
    if isinstance(query, Diagnostic) or not arguments.unknown:
        return query
    if arguments.mode is not AnswerMode.DEFAULT:
        return failure(
            Span.whole("--mode", ""),
            f"the {arguments.mode} mode answers no binding `unknown`",
            label="not the default mode",
            help=("drop `--unknown`, which shows the unknown bindings of the default mode",),
        )
    if variables_of(query):
        return query
    return failure(
        Span.whole("QUERY", ""),
        "a query without variables has no unknown bindings to show",
        label="has no variables",
        help=("drop `--unknown`, which shows the unknown bindings of a query with variables",),
    )


def _ask(arguments: argparse.Namespace, presentation: Presentation, home: Path | None) -> AskExit:
    """Answer a query over the answer sets; the CLI only reads and writes."""
    inquired = _inquired(arguments, home)
    if isinstance(inquired, list):
        return _refused_all("ask", inquired, arguments, presentation, AskExit.FAULT)
    program, root = inquired
    query = _asked_query(arguments)
    if isinstance(query, Diagnostic):
        return _refuse("ask", query, arguments, presentation, outcome=AskExit.FAULT)
    limits, interrupt = _searching(arguments)
    try:
        result: Ask | Internal = ask(
            program,
            query,
            mode=arguments.mode,
            over=arguments.over,
            limits=limits,
            interrupt=interrupt,
            root=root,
        )
    except Exception as error:  # noqa: BLE001
        result = Internal.of(error)
    outcome = AskExit.of(result)
    if arguments.view is View.JSON:
        sys.stdout.write(inquiry_json("ask", result, outcome))
        return outcome
    if arguments.view is View.TUI and not isinstance(result, Fault | Internal):
        explaining = _Explaining(program, root, frozenset(), arguments.over, (limits, interrupt))
        _answer_view(arguments, presentation, query, result, explaining)
        return outcome
    form, question, text = arguments.form, _question(arguments), program.text
    if isinstance(result, Fault):
        result, text = _at_argument(arguments, result, text)
    rendered = render_ask(
        question, query, result, presentation, form=form, text=text, unknown=arguments.unknown
    )
    _write(rendered)
    return outcome


def _question(arguments: argparse.Namespace) -> Question:
    """Name the file a question was put to, and the options, as given, that read its program."""
    libraries = [("--with", str(each)) for each in arguments.libraries]
    root = [] if arguments.root is None else [("--root", str(arguments.root))]
    return Question(str(arguments.path), tuple(word for pair in libraries + root for word in pair))


def _version(presentation: Presentation) -> VersionExit:
    sys.stdout.write(version(package(), loaded_solvers(), presentation.stdout))
    return VersionExit.REPORTED


def _reserved(arguments: argparse.Namespace, presentation: Presentation) -> Exit:
    sys.stderr.write(reserved(arguments.command, presentation.stderr))
    return Exit.FAULT


def _guarded[Outcome](
    run: Callable[[], Outcome], failed: Outcome, presentation: Presentation
) -> Outcome:
    """Run a command; a failure that no check anticipated is one line on stderr and `failed`."""
    try:
        return run()
    except Exception as error:  # noqa: BLE001
        sys.stderr.write(internal_error(error, presentation.stderr))
        return failed


type Outcome = Exit | VersionExit | WhyExit | AskExit
"""The outcome of a command: each has its own type, and its value is the status to exit with."""

FAULTS: Final[Mapping[str, Outcome]] = {
    "test": Exit.FAULT,
    "explain": Exit.FAULT,
    "why": WhyExit.FAULT,
    "ask": AskExit.FAULT,
}
"""The commands that write what they found, each with the outcome of a refused request."""


def _installed() -> bool:
    """Say whether the interactive view's extra is installed: whether its package imports."""
    try:
        import_module("elenctic.tui")
    except ModuleNotFoundError as error:
        if (error.name or "").partition(".")[0] in {"textual", "rich"}:
            return False
        raise
    return True


def _tui_refused(message: str, tip: str) -> Fault:
    return Fault(Locus.REQUEST, (failure(None, message, help=(tip,)),))


def _chosen(
    arguments: argparse.Namespace, presentation: Presentation, environment: Environment
) -> tuple[View, Format] | Fault:
    """Decide how a command writes what it found, from `--format`, `--json` and `--short`.

    With no `--format`, the commands that show evidence take the interactive view when its extra
    is installed and stdin and stdout are terminals; `test`, and every other case, takes text. A
    value 1.0 took is read as its new spelling, with a note.
    """
    form = Format.SHORT if arguments.short or arguments.format == "short" else Format.FULL
    named = _named(arguments, presentation)
    terminal = interactive(environment, stdin=Stream.of(sys.stdin), stdout=Stream.of(sys.stdout))
    if named is None:
        tui = arguments.command != "test" and terminal and _installed()
        return (View.TUI if tui else View.TEXT), form
    refusal = _refusal(arguments, named, terminal=terminal)
    return (View(named), form) if refusal is None else refusal


def _refusal(arguments: argparse.Namespace, named: str, *, terminal: bool) -> Fault | None:
    """Refuse a view the options ask for twice over, or the interactive view off a terminal."""
    if (conflict := _conflicting(arguments)) is not None:
        return Fault(Locus.REQUEST, (conflict,))
    return _tui_refusal(terminal=terminal) if named == View.TUI else None


def _conflicting(arguments: argparse.Namespace) -> Diagnostic | None:
    """Refuse `--short` of JSON, which has no short form, and `--json` with another view.

    1.0 took `--json` with `--format full`, `short` or `json`, and still does.
    """
    if arguments.short and (arguments.json or arguments.format == View.JSON):
        return failure(None, "a JSON document has no short form", help=("drop `--short`",))
    if arguments.json and arguments.format in {View.TEXT, View.TUI}:
        message = f"`--json` and `--format {arguments.format}` ask for two views"
        return failure(None, message, help=("drop one of them",))
    return None


def _named(arguments: argparse.Namespace, presentation: Presentation) -> str | None:
    """Name the view `--json` or `--format` asks for; a value 1.0 took is read anew, with a note."""
    named: str | None = "json" if arguments.json else arguments.format
    if named in DEPRECATED:
        sys.stderr.write(deprecated(f"--format {named}", DEPRECATED[named], presentation.stderr))
        return View.TEXT
    return named


def _tui_refusal(*, terminal: bool) -> Fault | None:
    """Why `--format tui` cannot be shown: the extra is missing, or there is no terminal."""
    if not _installed():
        return _tui_refused(
            "`--format tui` needs the optional `elenctic[tui]` extra",
            "pip install 'elenctic[tui]'",
        )
    if not terminal:
        return _tui_refused(
            "`--format tui` needs a terminal on stdin and stdout",
            "write `--format text` to a pipe or a file",
        )
    return None


def _runner(
    command: str, arguments: argparse.Namespace, presentation: Presentation, home: Path | None
) -> tuple[Callable[[], Outcome], Outcome]:
    """Name what runs a command, and the outcome of a failure no check anticipated."""
    match command:
        case "test" | "explain":
            return (lambda: _test(arguments, presentation, home)), Exit.INTERNAL_ERROR
        case "why":
            return (lambda: _why(arguments, presentation, home)), WhyExit.INTERNAL_ERROR
        case "ask":
            return (lambda: _ask(arguments, presentation, home)), AskExit.INTERNAL_ERROR
        case "version":
            return (lambda: _version(presentation)), VersionExit.INTERNAL_ERROR
        case _:
            return (lambda: _reserved(arguments, presentation)), Exit.INTERNAL_ERROR


def _home(variables: Mapping[str, str]) -> Path | None:
    """Read the home directory a default root must not hold: `HOME`, resolved; none if unset."""
    home = variables.get("HOME")
    return Path(home).resolve() if home else None


def main(argv: Sequence[str] | None = None) -> Outcome:
    """Run a command and return its outcome, which is the status to exit with.

    Run on the process's own command line (`argv` none), a closed stdout ends the process as it
    ends `ls` or `git`: by `SIGPIPE`, quietly, rather than as an error of elenctic's.
    """
    if argv is None and hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    parser = _parser()
    arguments = parser.parse_args(_literals(_normalized(sys.argv[1:] if argv is None else argv)))
    if arguments.command is None and not arguments.show_version:
        parser.error("the following arguments are required: COMMAND")
    variables = os.environ  # the one place that reads the environment
    environment = Environment.of(variables)
    presentation = _presentation(arguments, environment)
    command = "version" if arguments.show_version else str(arguments.command)
    if command in FAULTS:
        chosen = _chosen(arguments, presentation, environment)
        if isinstance(chosen, Fault):
            _write(refused(chosen, presentation))
            return FAULTS[command]
        arguments.view, arguments.form = chosen
    run, failed = _runner(command, arguments, presentation, _home(variables))
    return _guarded(run, failed, presentation)


if __name__ == "__main__":
    sys.exit(main())
