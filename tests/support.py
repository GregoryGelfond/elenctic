"""Shared test scaffolding.

Importable from any test module because ``pythonpath`` puts this directory on the path; ``conftest``
itself is not importable under pytest's importlib mode, so shared helpers live here instead.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

import elenctic.cli
from elenctic.result import Conclusion, Determination, SolveOutcome

__all__ = ["Streams", "decided", "document_of", "run_cli"]


def decided(determination: Determination) -> SolveOutcome:
    """A determination as a *finished* search reported it.

    The frame a check test is written in unless the test is about a search that stopped early —
    those state the conclusion they mean, in ``test_partial_search_verdicts.py``. It applies to the
    undecided arm too: a search can close the space and still leave the mode nothing to build from,
    and that pairing is the one whose diagnostic has no remedy to offer.
    """
    return SolveOutcome(determination, Conclusion.EXHAUSTED)


# The child: elenctic's own console entry, given the arguments the parent passes after the program
# text, and made to prove first that it is the same copy of the package the parent is testing. A
# prelude may stand a fault in front of it, which is how a register only a fault can reach gets
# exercised without one being contrived inside a corpus.
_CHILD = """
import sys
{prelude}
import elenctic.cli
from elenctic.cli import main

if elenctic.cli.__file__ != {loaded!r}:
    raise SystemExit("the child loaded " + str(elenctic.cli.__file__) + ", not the tree under test")
sys.exit(main(sys.argv[1:]))
"""


class Streams(NamedTuple):
    """What one run of the command line put on each stream, and the status it left with."""

    out: str
    err: str
    status: int


def run_cli(
    target: Path, *flags: str, prelude: str = "", env: dict[str, str] | None = None
) -> Streams:
    """One invocation of elenctic, **as a process**, with its two streams kept apart.

    A process and not a call, wherever what is being tested is which stream something landed on.
    Standard output carries the machine-readable report because the descriptor it *is* has been
    moved; a test runner capturing output replaces this language's standard output with an object of
    its own writing to a file of its own, which no longer travels through that descriptor. An
    in-process test therefore watches a stream the guarantee never touches, and reports a clean
    standard output whether or not the guarantee holds. Both capture fixtures share that blind spot.

    The hash seed is cleared rather than inherited, so that two runs really are two seeds: anything
    hash-ordered would otherwise be compared against itself. Both streams are
    decoded as UTF-8 here whatever the child was asked to encode in, because what the child encodes
    in is itself under test in places.
    """
    environment = {**os.environ, **(env or {})}
    environment.pop("PYTHONHASHSEED", None)
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD.format(prelude=prelude, loaded=elenctic.cli.__file__),
            str(target),
            *flags,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
        env=environment,
    )
    return Streams(finished.stdout, finished.stderr, finished.returncode)


def document_of(streams: Streams) -> dict[str, Any]:
    """What standard output carried, parsed — with the run's own account of itself if it carried no
    document, since a child that died for an unrelated reason otherwise reports only that something
    was not JSON."""
    try:
        parsed: dict[str, Any] = json.loads(streams.out)
    except json.JSONDecodeError as broken:
        raise AssertionError(
            f"standard output carried no document ({broken}). The run exited "
            f"{streams.status} and said:\n{streams.err}"
        ) from broken
    return parsed
