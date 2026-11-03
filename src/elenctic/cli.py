"""The command line: a thin client over the library, one subcommand per kind of inquiry."""

import argparse
import os
import signal
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from math import inf
from pathlib import Path
from typing import Final

from elenctic.check import check
from elenctic.human import internal_error, render, reserved
from elenctic.json_view import to_json
from elenctic.paint import Color
from elenctic.presentation import Environment, Presentation, Stream, When, resolve
from elenctic.program import Fault, Locus, Program
from elenctic.report import Entry, Exit, Run
from elenctic.search import Interrupt, Limit, Limits
from elenctic.spans import Diagnostic, Position, Severity, Span

DEFAULT_BUDGET: Final = 30.0
DEFAULT_MODEL_CAP: Final = 100_000


RESERVED = {
    "repl": "an interactive session over a live program",
    "why": "the support of an atom, or why it is absent",
    "ask": "one query, answered over the answer sets",
    "explain": "the evidence behind a verdict",
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
_models_limit = _limit_reader(int, "a positive integer")


def _output_options() -> argparse.ArgumentParser:
    """Make the parser of the options that decide how output looks; every command takes them."""
    options = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    options.add_argument(
        "--color",
        choices=list(When),
        default=When.AUTO,
        metavar="WHEN",
        help="colour output: auto (on a terminal), always or never (default: %(default)s)",
    )
    options.add_argument(
        "--icons",
        nargs="?",
        choices=list(When),
        const=When.AUTO,
        default=When.NEVER,
        metavar="WHEN",
        help="show Nerd Font glyphs: auto (on a terminal), always or never; "
        "`--icons` alone is `--icons=auto`, a value is given as `--icons=WHEN` "
        "(default: %(default)s)",
    )
    return options


def _parser(presentation: Presentation) -> argparse.ArgumentParser:
    """Colour the parser's own help and errors only on streams the presentation colours.

    The parser decides for itself too, from `FORCE_COLOR` and the terminal, so it never colours
    a stream the presentation leaves plain, but it cannot be made to colour a redirected one.
    """
    colored = presentation.stdout.color is Color.ON and presentation.stderr.color is Color.ON
    parser = argparse.ArgumentParser(
        prog="elenctic",
        description="Test, debug and analyse ASP programs. "
        "With no command, the paths are tested: `elenctic PATH...` is `elenctic test PATH...`.",
        color=colored,
    )
    options = [_output_options()]
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    test = commands.add_parser(
        "test", parents=options, help="check programs against their contracts"
    )
    test.add_argument(
        "paths", nargs="+", type=Path, help=".lp files, or directories searched for them"
    )
    test.add_argument("--json", action="store_true", help="write the run as JSON")
    test.add_argument("--verbose", "-v", action="store_true", help="list the claims that passed")
    test.add_argument(
        "--budget",
        type=_seconds_limit,
        default=DEFAULT_BUDGET,
        metavar="SECONDS|all",
        help="time allowed per search, or `all` for no limit (default: %(default)s)",
    )
    test.add_argument(
        "--models",
        type=_models_limit,
        default=DEFAULT_MODEL_CAP,
        metavar="N|all",
        help="most answer sets read per search, or `all` for no limit (default: %(default)s)",
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
    """Name the default command when the arguments begin with neither a command nor `--help`."""
    named = bool(argv) and argv[0] in {"test", *RESERVED, "-h", "--help"}
    return _explicit_icons(argv if named or not argv else ["test", *argv])


def _sources(paths: Iterable[Path]) -> list[Path]:
    return [
        found
        for path in paths
        for found in (sorted(path.rglob("*.lp")) if path.is_dir() else [path])
    ]


def _unreadable_reason(error: OSError | UnicodeDecodeError) -> str:
    match error:
        case UnicodeDecodeError():
            return f"not valid UTF-8: {error.reason} at byte {error.start}"
        case _:
            return str(error)


def _entry(path: Path, limits: Limits, interrupt: Interrupt) -> Entry | None:
    try:
        program = Program.read(path)
    except (OSError, UnicodeDecodeError) as error:
        problem = Diagnostic(
            Span(str(path), Position(1, 1), Position(1, 1)),
            Severity.ERROR,
            _unreadable_reason(error),
        )
        return Entry(str(path), Fault(Locus.REQUEST, (problem,)))
    result = check(program, limits=limits, interrupt=interrupt)
    return None if result is None else Entry(program.source, result)


def _presentation(argv: Sequence[str], environment: Mapping[str, str]) -> Presentation:
    """Decide once how each stream is written: the one place that asks the environment and streams.

    The choices are read from `argv` before it is parsed, so that even a usage error is written
    as decided. A bad choice leaves the defaults; the parser then refuses it.
    """
    try:
        chosen = _output_options().parse_known_args(argv)[0]
    except argparse.ArgumentError:
        chosen = _output_options().parse_args([])
    return resolve(
        When(chosen.color),
        When(chosen.icons),
        Environment.of(environment),
        stdout=Stream.of(sys.stdout),
        stderr=Stream.of(sys.stderr),
    )


def _test(arguments: argparse.Namespace, presentation: Presentation) -> Exit:
    limits = Limits(seconds=arguments.budget, models=arguments.models)
    interrupt = Interrupt()
    signal.signal(signal.SIGINT, lambda _signal, _frame: interrupt.pull())
    entries = [_entry(path, limits, interrupt) for path in _sources(arguments.paths)]
    run = Run(tuple(entry for entry in entries if entry is not None))
    if arguments.json:
        print(to_json(run))
    else:
        rendered = render(run, presentation, verbose=arguments.verbose)
        sys.stderr.write(rendered.stderr)
        sys.stdout.write(rendered.stdout)
    return run.exit_code


def _reserved(arguments: argparse.Namespace, presentation: Presentation) -> Exit:
    print(reserved(arguments.command, presentation.stderr), file=sys.stderr)
    return Exit.FAULT


def _exit_for_internal_error(error: Exception, presentation: Presentation) -> Exit:
    print(internal_error(error, presentation.stderr), file=sys.stderr)
    return Exit.INTERNAL_ERROR


def main(argv: Sequence[str] | None = None) -> Exit:
    """Run a command and return the status to exit with."""
    normalized = _normalized(sys.argv[1:] if argv is None else argv)
    presentation = _presentation(normalized, os.environ)
    arguments = _parser(presentation).parse_args(normalized)
    try:
        return (_test if arguments.command == "test" else _reserved)(arguments, presentation)
    except Exception as error:  # noqa: BLE001
        return _exit_for_internal_error(error, presentation)


if __name__ == "__main__":
    sys.exit(main())
