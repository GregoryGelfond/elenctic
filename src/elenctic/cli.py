"""The command line: a thin client over the library, one subcommand per kind of inquiry."""

import argparse
import signal
import sys
from collections.abc import Callable, Iterable, Sequence
from math import inf
from pathlib import Path
from typing import Final

from elenctic.check import check
from elenctic.display import legible
from elenctic.program import Fault, Locus, Program
from elenctic.report import Entry, Exit, Run, to_json, to_text
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elenctic",
        description="Test, debug and analyse ASP programs. "
        "With no command, the paths are tested: `elenctic PATH...` is `elenctic test PATH...`.",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    test = commands.add_parser("test", help="check programs against their contracts")
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
        commands.add_parser(name, help=f"{what} (reserved)").add_argument(
            "rest", nargs=argparse.REMAINDER
        )
    return parser


def _normalized(argv: Sequence[str]) -> list[str]:
    """Name the default command when the arguments begin with neither a command nor `--help`."""
    named = bool(argv) and argv[0] in {"test", *RESERVED, "-h", "--help"}
    return list(argv) if named or not argv else ["test", *argv]


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


def _test(arguments: argparse.Namespace) -> Exit:
    limits = Limits(seconds=arguments.budget, models=arguments.models)
    interrupt = Interrupt()
    signal.signal(signal.SIGINT, lambda _signal, _frame: interrupt.pull())
    entries = [_entry(path, limits, interrupt) for path in _sources(arguments.paths)]
    run = Run(tuple(entry for entry in entries if entry is not None))
    print(to_json(run) if arguments.json else to_text(run, verbose=arguments.verbose))
    return run.exit_code


def _reserved(arguments: argparse.Namespace) -> Exit:
    print(f"elenctic: `{arguments.command}` is reserved and not yet built", file=sys.stderr)
    return Exit.FAULT


def _exit_for_internal_error(error: Exception) -> Exit:
    message = legible(f"{type(error).__name__}: {error}")
    print(f"elenctic: internal error: {message}", file=sys.stderr)
    return Exit.INTERNAL_ERROR


def main(argv: Sequence[str] | None = None) -> Exit:
    """Run a command and return the status to exit with."""
    arguments = _parser().parse_args(_normalized(sys.argv[1:] if argv is None else argv))
    try:
        return (_test if arguments.command == "test" else _reserved)(arguments)
    except Exception as error:  # noqa: BLE001
        return _exit_for_internal_error(error)


if __name__ == "__main__":
    sys.exit(main())
