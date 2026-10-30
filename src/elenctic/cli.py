"""The command line: a thin client over the library, one subcommand per kind of inquiry."""

import argparse
import signal
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from elenctic.check import check
from elenctic.program import Fault, Locus, Program
from elenctic.report import Entry, Run, to_json, to_text
from elenctic.search import Interrupt, Limits
from elenctic.spans import Diagnostic, Position, Severity, Span

DEFAULT_BUDGET = 30.0


RESERVED = {
    "repl": "an interactive session over a live program",
    "why": "the support of an atom, or why it is absent",
    "ask": "one query, answered over the answer sets",
    "explain": "the evidence behind a verdict",
}
"""The subcommands the design reserves; each exits 2 with a note until it is built."""


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
        type=float,
        default=DEFAULT_BUDGET,
        metavar="SECONDS",
        help="time allowed per search; 0 is none (default: %(default)s)",
    )
    test.add_argument("--models", type=int, metavar="N", help="most answer sets read per search")
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


def _entry(path: Path, limits: Limits, interrupt: Interrupt) -> Entry | None:
    try:
        program = Program.read(path)
    except OSError as error:
        problem = Diagnostic(
            Span(str(path), Position(1, 1), Position(1, 1)),
            Severity.ERROR,
            str(error),
        )
        return Entry(str(path), Fault(Locus.REQUEST, (problem,)))
    result = check(program, limits=limits, interrupt=interrupt)
    return None if result is None else Entry(program.source, result)


def _test(arguments: argparse.Namespace) -> int:
    limits = Limits(seconds=arguments.budget or None, models=arguments.models)
    interrupt = Interrupt()
    signal.signal(signal.SIGINT, lambda _signal, _frame: interrupt.pull())
    entries = [_entry(path, limits, interrupt) for path in _sources(arguments.paths)]
    run = Run(tuple(entry for entry in entries if entry is not None))
    print(to_json(run) if arguments.json else to_text(run, verbose=arguments.verbose))
    return run.exit_code


def _reserved(arguments: argparse.Namespace) -> int:
    print(f"elenctic: `{arguments.command}` is reserved and not yet built", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command; exit 0 if every claim passes, 1 if not, 2 on a fault."""
    arguments = _parser().parse_args(_normalized(sys.argv[1:] if argv is None else argv))
    return (_test if arguments.command == "test" else _reserved)(arguments)


if __name__ == "__main__":
    sys.exit(main())
