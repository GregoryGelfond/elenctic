"""The command line: a thin client over the library, one subcommand per kind of inquiry."""

import argparse
import os
import signal
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import IntEnum
from math import inf
from pathlib import Path
from typing import Final

from elenctic.about import VersionExit, package
from elenctic.check import check
from elenctic.determination import Range, Truncation, option
from elenctic.human import (
    Format,
    Rendered,
    internal_error,
    refused,
    render_ask,
    render_run,
    render_why,
    reserved,
    version,
)
from elenctic.inquiry import Ask, AskExit, Why, WhyExit, ask, why
from elenctic.json_view import inquiry_json, to_json
from elenctic.literals import Scenario
from elenctic.presentation import Environment, Presentation, Stream, When, resolve
from elenctic.program import Fault, Locus, Program
from elenctic.queries import read_query
from elenctic.reader import suggestion
from elenctic.report import Entry, Exit, Internal, Run
from elenctic.search import Interrupt, Limit, Limits
from elenctic.session import evidenced
from elenctic.spans import Diagnostic, Parsed, failure, first_unlexable, note
from elenctic.syntax import read_atom, read_scenario
from elenctic.tags import is_case, near_misses
from elenctic.theory import loaded_solvers
from elenctic.verdicts import Report

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


def _directory(text: str) -> Path:
    """Read the value of `--root`: a directory that exists."""
    path = Path(text)
    if not path.is_dir():
        message = f"`{text}` is not a directory"
        raise argparse.ArgumentTypeError(message)
    return path


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


def _written(command: argparse.ArgumentParser, written: str) -> None:
    """Give a command the options that choose how what it found is written."""
    command.add_argument(
        "--format",
        choices=("full", "short", "json"),
        default="full",
        help=f"how to write {written}: rustc form (default), one-line short, or JSON",
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


def _checking(command: argparse.ArgumentParser, written: str) -> None:
    """Give a command that checks programs the options of `test`."""
    command.add_argument(
        "paths", nargs="+", type=Path, help=".lp files, or directories searched for them"
    )
    _written(command, written)
    command.add_argument("--verbose", "-v", action="store_true", help="list the claims that passed")
    command.add_argument(
        "--root",
        type=_directory,
        metavar="DIR",
        help="the directory every path and every `#include` must lie under (default: each "
        "directory searched, or a named file's own directory)",
    )
    _limited(command)


def _depth(command: argparse.ArgumentParser) -> None:
    """Give a command that explains the options of how deep and how fully it shows the tree."""
    command.add_argument(
        "--max-depth",
        type=_depth_limit,
        default=DEFAULT_MAX_DEPTH,
        metavar="N|all",
        help=(
            "how many absent atoms deep an explanation goes, or `all` for no limit "
            "(default: %(default)s)"
        ),
    )
    command.add_argument(
        "--spans",
        action="store_true",
        help="show each rule as written, its place and its substitution, beneath its instance",
    )


def _asking(command: argparse.ArgumentParser, written: str) -> None:
    """Give a command that asks about one program its path and the options of its search."""
    command.add_argument("path", type=Path, metavar="PATH", help="the .lp file asked about")
    _written(command, written)
    command.add_argument(
        "--over",
        choices=list(Range),
        type=Range,
        default=Range.ALL,
        help="all the answer sets, or only the optimal ones (default: all)",
    )
    _limited(command)


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
    _checking(test, "the run")
    explain = commands.add_parser(
        "explain", parents=options, help="check programs, and show why each failed claim fails"
    )
    _checking(explain, "the run, with the evidence")
    _depth(explain)
    why = commands.add_parser(
        "why", parents=options, help="show why an atom holds, or not, in an answer set"
    )
    _asking(why, "the explanation")
    why.add_argument("atom", metavar="ATOM", help="the ground literal asked about: `p(a)`, `-p`")
    why.add_argument(
        "--answer-set",
        type=_index,
        default=1,
        metavar="K",
        help="the answer set explained, counted from 1 among those --over reads (default: 1)",
    )
    why.add_argument(
        "--assuming",
        metavar="L,...",
        help="literals assumed, `p` or `not p`, as `assuming { ... }` writes them",
    )
    _depth(why)
    ask = commands.add_parser("ask", parents=options, help="answer one query over the answer sets")
    _asking(ask, "the answer")
    ask.add_argument(
        "query",
        metavar="QUERY",
        help="literals `{ a, -b }`, or one pattern `{ p(X) }`, as `@query`",
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


def _plan(paths: Sequence[Path], root: Path | None) -> list[_Source | Entry]:
    """Return each path's sources in the order given; a path outside `root` is refused instead."""
    boundary = None if root is None else root.resolve()
    return [item for path in paths for item in _placed(path, boundary)]


def _placed(path: Path, boundary: Path | None) -> list[_Source | Entry]:
    if boundary is not None and not path.resolve().is_relative_to(boundary):
        return [_outside(path, boundary)]
    return [*_sources(path, boundary)]


def _sources(path: Path, boundary: Path | None) -> list[_Source]:
    """Return the `.lp` files of `path` with their root: `boundary`, else the path's own."""
    if not path.is_dir():
        return [(path, True, path.parent.resolve() if boundary is None else boundary)]
    root = path.resolve() if boundary is None else boundary
    return [(found, False, root) for found in sorted(path.rglob("*.lp"))]


def _outside(path: Path, root: Path) -> Entry:
    problem = failure(
        None,
        f"`{path}` is outside the root {root}",
        help=("name paths under the root, or choose a root that holds them",),
    )
    return Entry(str(path), Fault(Locus.REQUEST, (problem,)))


def _unreadable_note(error: OSError | UnicodeDecodeError) -> str:
    match error:
        case UnicodeDecodeError():
            return f"not valid UTF-8 at byte {error.start}: {error.reason}"
        case _:
            return str(error)


def _read(path: Path) -> Program | Fault:
    """Read the program at `path`, or refuse it as unreadable."""
    try:
        return Program.read(path)
    except (OSError, UnicodeDecodeError) as error:
        problem = failure(None, f"cannot read `{path}`", notes=(_unreadable_note(error),))
        return Fault(Locus.REQUEST, (problem,))


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
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        if is_case(text):
            continue
        if (mistaken := _mistaken(text)) is None:
            continue
        shown, helps = mistaken
        found.append(note(None, f"`{path}` carries no contract tag; {shown}", help=helps))
    return tuple(found)


def _entry(  # noqa: PLR0913
    path: Path,
    limits: Limits,
    interrupt: Interrupt,
    *,
    named: bool,
    root: Path,
    max_depth: int | Limit | None = None,
) -> Entry | None:
    program = _read(path)
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
        return Entry(program.source, Internal.of(error), program.text)
    return None if result is None else Entry(program.source, result, program.text)


def _checked(
    item: _Source | Entry,
    limits: Limits,
    interrupt: Interrupt,
    max_depth: int | Limit | None = None,
) -> Entry | None:
    """Check a planned source, and explain it if `max_depth` is given; a refusal stands as it is."""
    if isinstance(item, Entry):
        return item
    path, named, root = item
    return _entry(path, limits, interrupt, named=named, root=root, max_depth=max_depth)


def _presentation(arguments: argparse.Namespace, environment: Mapping[str, str]) -> Presentation:
    """Decide once how each stream is written: the one place that reads the environment.

    `Stream.of` asks each stream. It governs elenctic's own report and diagnostics; the
    parser's help and usage are its own.
    """
    return resolve(
        When(arguments.color),
        When(arguments.icons),
        Environment.of(environment),
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
    """Take the limits of each search, and the interrupt the first SIGINT pulls."""
    limits = Limits(max_seconds=arguments.max_seconds, max_answer_sets=arguments.max_answer_sets)
    interrupt = Interrupt()
    signal.signal(signal.SIGINT, _sigint(interrupt))
    return limits, interrupt


def _test(arguments: argparse.Namespace, presentation: Presentation) -> Exit:
    """Check the paths; for `explain`, give each failed claim its evidence."""
    limits, interrupt = _searching(arguments)
    plan = _plan(arguments.paths, arguments.root)
    max_depth = arguments.max_depth if arguments.command == "explain" else None
    entries = [_checked(item, limits, interrupt, max_depth) for item in plan]
    run = Run(
        tuple(entry for entry in entries if entry is not None),
        notes=_walked_notes([item for item in plan if not isinstance(item, Entry)]),
    )
    fmt = "json" if arguments.json else arguments.format
    if fmt == "json":
        sys.stdout.write(to_json(run))
    else:
        rendered = render_run(
            run,
            presentation,
            verbose=arguments.verbose,
            form=Format.SHORT if fmt == "short" else Format.FULL,
            spans=getattr(arguments, "spans", False),
        )
        sys.stderr.write(rendered.stderr)
        sys.stdout.write(rendered.stdout)
    return run.exit_code


def _format(arguments: argparse.Namespace) -> str:
    return "json" if arguments.json else arguments.format


def _form(arguments: argparse.Namespace) -> Format:
    return Format.SHORT if _format(arguments) == "short" else Format.FULL


def _write(rendered: Rendered) -> None:
    sys.stderr.write(rendered.stderr)
    sys.stdout.write(rendered.stdout)


def _refuse[Outcome: IntEnum](  # noqa: PLR0913
    command: str,
    refusal: Fault | Diagnostic,
    arguments: argparse.Namespace,
    presentation: Presentation,
    *,
    text: str | None,
    outcome: Outcome,
) -> Outcome:
    """Write a refusal of the program or an argument, whose `text` it shows, and exit `outcome`."""
    fault = refusal if isinstance(refusal, Fault) else Fault(Locus.REQUEST, (refusal,))
    if _format(arguments) == "json":
        sys.stdout.write(inquiry_json(command, fault, outcome))
    else:
        source = str(arguments.path)
        _write(refused(fault, presentation, form=_form(arguments), source=source, text=text))
    return outcome


def _why(arguments: argparse.Namespace, presentation: Presentation) -> WhyExit:
    """Explain an atom in the answer set asked for; the CLI only reads and writes."""
    program = _read(arguments.path)
    if isinstance(program, Fault):
        return _refuse("why", program, arguments, presentation, text=None, outcome=WhyExit.FAULT)
    atom = read_atom(arguments.atom, "ATOM")
    if isinstance(atom, Diagnostic):
        return _refuse(
            "why", atom, arguments, presentation, text=arguments.atom, outcome=WhyExit.FAULT
        )
    assumed = arguments.assuming
    scenario: Parsed[Scenario] = (
        frozenset() if assumed is None else read_scenario(assumed, "--assuming")
    )
    if isinstance(scenario, Diagnostic):
        return _refuse(
            "why", scenario, arguments, presentation, text=assumed, outcome=WhyExit.FAULT
        )
    limits, interrupt = _searching(arguments)
    try:
        result: Why | Internal = why(
            program,
            atom,
            index=arguments.answer_set,
            scenario=scenario,
            over=arguments.over,
            limits=limits,
            interrupt=interrupt,
            max_depth=arguments.max_depth,
        )
    except Exception as error:  # noqa: BLE001
        result = Internal.of(error)
    outcome = WhyExit.of(result)
    if _format(arguments) == "json":
        sys.stdout.write(inquiry_json("why", result, outcome))
        return outcome
    source = str(arguments.path)
    _write(
        render_why(
            source,
            atom,
            result,
            presentation,
            form=_form(arguments),
            spans=arguments.spans,
            over=arguments.over,
            text=program.text,
        )
    )
    return outcome


def _ask(arguments: argparse.Namespace, presentation: Presentation) -> AskExit:
    """Answer a query over the answer sets; the CLI only reads and writes."""
    program = _read(arguments.path)
    if isinstance(program, Fault):
        return _refuse("ask", program, arguments, presentation, text=None, outcome=AskExit.FAULT)
    query = read_query(arguments.query, "QUERY")
    if isinstance(query, Diagnostic):
        return _refuse(
            "ask", query, arguments, presentation, text=arguments.query, outcome=AskExit.FAULT
        )
    limits, interrupt = _searching(arguments)
    try:
        result: Ask | Internal = ask(
            program, query, over=arguments.over, limits=limits, interrupt=interrupt
        )
    except Exception as error:  # noqa: BLE001
        result = Internal.of(error)
    outcome = AskExit.of(result)
    if _format(arguments) == "json":
        sys.stdout.write(inquiry_json("ask", result, outcome))
        return outcome
    source = str(arguments.path)
    form = _form(arguments)
    _write(render_ask(source, query, result, presentation, form=form, text=program.text))
    return outcome


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


def _runner(
    command: str, arguments: argparse.Namespace, presentation: Presentation
) -> tuple[Callable[[], Outcome], Outcome]:
    """Name what runs a command, and the outcome of a failure no check anticipated."""
    match command:
        case "test" | "explain":
            return (lambda: _test(arguments, presentation)), Exit.INTERNAL_ERROR
        case "why":
            return (lambda: _why(arguments, presentation)), WhyExit.INTERNAL_ERROR
        case "ask":
            return (lambda: _ask(arguments, presentation)), AskExit.INTERNAL_ERROR
        case "version":
            return (lambda: _version(presentation)), VersionExit.INTERNAL_ERROR
        case _:
            return (lambda: _reserved(arguments, presentation)), Exit.INTERNAL_ERROR


def main(argv: Sequence[str] | None = None) -> Outcome:
    """Run a command and return its outcome, which is the status to exit with."""
    parser = _parser()
    arguments = parser.parse_args(_normalized(sys.argv[1:] if argv is None else argv))
    if arguments.command is None and not arguments.show_version:
        parser.error("the following arguments are required: COMMAND")
    presentation = _presentation(arguments, os.environ)
    command = "version" if arguments.show_version else str(arguments.command)
    run, failed = _runner(command, arguments, presentation)
    return _guarded(run, failed, presentation)


if __name__ == "__main__":
    sys.exit(main())
