"""The command line: read paths, check each, print the run."""

import argparse
import signal
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from aspnext.check import check
from aspnext.engine import Fault, Interrupt, Limits, Locus, Program
from aspnext.report import Entry, Run, to_json, to_text
from aspnext.spans import Diagnostic, Position, Severity, Span

DEFAULT_BUDGET = 30.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aspnext", description="Check ASP programs against their contracts."
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, help=".lp files, or directories searched for them"
    )
    parser.add_argument("--json", action="store_true", help="write the run as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="list the claims that passed")
    parser.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BUDGET,
        metavar="SECONDS",
        help="time allowed per search; 0 is none (default: %(default)s)",
    )
    parser.add_argument("--models", type=int, metavar="N", help="most answer sets read per search")
    return parser


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
            Span(str(path), Position(1, 1), Position(1, 1)), Severity.ERROR, error.strerror
        )
        return Entry(str(path), Fault(Locus.REQUEST, (problem,)))
    result = check(program, limits=limits, interrupt=interrupt)
    return None if result is None else Entry(program.source, result)


def main(argv: Sequence[str] | None = None) -> int:
    """Check the named sources; exit 0 if every claim passes, 1 if not, 2 on a fault."""
    arguments = _parser().parse_args(argv)
    limits = Limits(seconds=arguments.budget or None, models=arguments.models)
    interrupt = Interrupt()
    signal.signal(signal.SIGINT, lambda *_: interrupt.pull())
    entries = [_entry(path, limits, interrupt) for path in _sources(arguments.paths)]
    run = Run(tuple(entry for entry in entries if entry is not None))
    print(to_json(run) if arguments.json else to_text(run, verbose=arguments.verbose))
    return run.exit_code


if __name__ == "__main__":
    sys.exit(main())
