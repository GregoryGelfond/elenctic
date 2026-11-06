"""The command line: a thin client over the library, one subcommand per kind of inquiry."""

import argparse
import os
import signal
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from math import inf
from pathlib import Path
from typing import Final

from elenctic.about import VersionExit, package
from elenctic.check import check
from elenctic.determination import Truncation, option
from elenctic.human import Format, internal_error, render_run, reserved, version
from elenctic.json_view import to_json
from elenctic.presentation import Environment, Presentation, Stream, When, resolve
from elenctic.program import Fault, Locus, Program
from elenctic.report import Entry, Exit, Internal, Run
from elenctic.search import Interrupt, Limit, Limits
from elenctic.spans import Diagnostic, failure, first_unlexable, note
from elenctic.tags import is_case, near_misses
from elenctic.theory import loaded_solvers

DEFAULT_MAX_SECONDS: Final = 30.0
DEFAULT_MAX_ANSWER_SETS: Final = 100_000


DECIDED: Final = frozenset({"test", "version"})
"""The subcommands that are built: a first argument that names one is a command, not a path."""
VERSION_FLAGS: Final = ("-V", "--version")
"""The option of the main parser that asks for `version`: valid before the command, never after."""
BARE: Final = frozenset({*VERSION_FLAGS, "-h", "--help"})
"""The options of the main parser that take no value."""

RESERVED = {
    "repl": "start an interactive session over a live program",
    "why": "show the support of an atom, or why it is absent",
    "ask": "answer one query over the answer sets",
    "explain": "show the evidence behind a verdict",
}
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


_seconds_limit = _limit_reader(float, "a positive number of seconds")
_answer_sets_limit = _limit_reader(int, "a positive integer")


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
    test.add_argument(
        "paths", nargs="+", type=Path, help=".lp files, or directories searched for them"
    )
    test.add_argument(
        "--format",
        choices=("full", "short", "json"),
        default="full",
        help="how to write the run: rustc form (default), one-line short, or JSON",
    )
    test.add_argument(
        "--json", action="store_true", help="write the run as JSON (same as --format json)"
    )
    test.add_argument("--verbose", "-v", action="store_true", help="list the claims that passed")
    test.add_argument(
        option(Truncation.MAX_SECONDS),
        type=_seconds_limit,
        default=DEFAULT_MAX_SECONDS,
        metavar="SECONDS|all",
        help="time allowed per search, or `all` for no limit (default: %(default)s)",
    )
    test.add_argument(
        option(Truncation.MAX_ANSWER_SETS),
        type=_answer_sets_limit,
        default=DEFAULT_MAX_ANSWER_SETS,
        metavar="N|all",
        help="most answer sets read per search, or `all` for no limit (default: %(default)s)",
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


def _sources(paths: Iterable[Path]) -> list[tuple[Path, bool, Path]]:
    """Yield each `.lp` path, whether the user named it, and the corpus root that contains it.

    A walked directory is the root. A named file's own directory is the root.
    """
    return [
        (
            found,
            not path.is_dir(),
            path.resolve() if path.is_dir() else found.parent.resolve(),
        )
        for path in paths
        for found in (sorted(path.rglob("*.lp")) if path.is_dir() else [path])
    ]


def _unreadable_note(error: OSError | UnicodeDecodeError) -> str:
    match error:
        case UnicodeDecodeError():
            return f"not valid UTF-8 at byte {error.start}: {error.reason}"
        case _:
            return str(error)


def _not_a_case(path: Path, text: str) -> Fault:
    """Refuse a named path that carries no contract tag."""
    if (refused := first_unlexable(text, str(path))) is not None:
        return Fault(Locus.PROGRAM, (refused,))
    return Fault(
        Locus.REQUEST,
        (
            failure(
                None,
                f"`{path}` carries no contract tag",
                help=("a contract-free `.lp` is a library; name a case, or walk a directory",),
            ),
        ),
    )


def _walked_notes(sources: list[tuple[Path, bool, Path]]) -> tuple[Diagnostic, ...]:
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
        missed = near_misses(text)
        if not missed:
            continue
        shown = ", ".join(f"`@{name}`" for name in missed)
        found.append(
            note(
                None,
                f"`{path}` carries no contract tag; did you mean a claim rather than {shown}?",
            )
        )
    return tuple(found)


def _entry(
    path: Path, limits: Limits, interrupt: Interrupt, *, named: bool, root: Path
) -> Entry | None:
    try:
        program = Program.read(path)
    except (OSError, UnicodeDecodeError) as error:
        problem = failure(
            None,
            f"cannot read `{path}`",
            notes=(_unreadable_note(error),),
        )
        return Entry(str(path), Fault(Locus.REQUEST, (problem,)))
    if not is_case(program.text):
        if named:
            return Entry(program.source, _not_a_case(path, program.text), program.text)
        return None
    try:
        result = check(program, limits=limits, interrupt=interrupt, root=root)
    except Exception as error:  # noqa: BLE001
        return Entry(program.source, Internal.of(error), program.text)
    return None if result is None else Entry(program.source, result, program.text)


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


def _test(arguments: argparse.Namespace, presentation: Presentation) -> Exit:
    limits = Limits(max_seconds=arguments.max_seconds, max_answer_sets=arguments.max_answer_sets)
    interrupt = Interrupt()
    signal.signal(signal.SIGINT, _sigint(interrupt))
    sources = _sources(arguments.paths)
    entries = [
        _entry(path, limits, interrupt, named=named, root=root) for path, named, root in sources
    ]
    run = Run(
        tuple(entry for entry in entries if entry is not None),
        notes=_walked_notes(sources),
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
        )
        sys.stderr.write(rendered.stderr)
        sys.stdout.write(rendered.stdout)
    return run.exit_code


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


def main(argv: Sequence[str] | None = None) -> Exit | VersionExit:
    """Run a command and return its outcome, which is the status to exit with."""
    parser = _parser()
    arguments = parser.parse_args(_normalized(sys.argv[1:] if argv is None else argv))
    if arguments.command is None and not arguments.show_version:
        parser.error("the following arguments are required: COMMAND")
    presentation = _presentation(arguments, os.environ)
    match "version" if arguments.show_version else arguments.command:
        case "test":
            return _guarded(
                lambda: _test(arguments, presentation), Exit.INTERNAL_ERROR, presentation
            )
        case "version":
            return _guarded(
                lambda: _version(presentation), VersionExit.INTERNAL_ERROR, presentation
            )
        case _:
            return _guarded(
                lambda: _reserved(arguments, presentation), Exit.INTERNAL_ERROR, presentation
            )


if __name__ == "__main__":
    sys.exit(main())
